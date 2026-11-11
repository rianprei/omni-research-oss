"""Owner-approved OAuth 2.1 adapter for ChatGPT MCP.

The existing OMNI_AGENT_ACCESS_TOKEN is used ONLY as a password in the
owner's HTTPS consent page. ChatGPT never receives that password. All
MCP bearer tokens are newly minted, scoped, short-lived OAuth access tokens.

This is a single-owner, process-local authorization server. Registering
OAuth clients, pending approvals and tokens do not survive Render restarts.
Use durable identity/storage for multi-user production deployments.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
    OAuthAuthorizationServerProvider, RefreshToken, RegistrationError,
    TokenError, construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

BASE_URL = os.environ.get("OMNI_AGENT_PUBLIC_URL", "https://omni-host-sampling-mcp.onrender.com").rstrip("/")
MCP_RESOURCE = BASE_URL + "/mcp"
SCOPE = "mcp"
PENDING_LIFETIME = 900
TOKEN_LIFETIME = 43200


def _is_chatgpt_callback(url: str) -> bool:
    parts = urlparse(str(url))
    if parts.scheme != "https" or parts.netloc != "chatgpt.com" or parts.fragment:
        return False
    if parts.path == "/connector_platform_oauth_redirect":
        return True
    return (parts.path.startswith("/connector/oauth/") and
            len(parts.path) < 300 and
            all(c.isalnum() or c in "-_" for c in parts.path.removeprefix("/connector/oauth/")))


@dataclass
class Pending:
    client: OAuthClientInformationFull
    params: AuthorizationParams
    expires_at: float


@dataclass
class Approved:
    redirect_uri: str
    authorization_code: str
    expires_at: float


class OwnerOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, owner_password: str):
        if len(owner_password) < 32:
            raise RuntimeError("OMNI_AGENT_ACCESS_TOKEN must contain at least 32 characters")
        self.owner_password = owner_password
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, Pending] = {}
        self.approved: dict[str, Approved] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.failed_logins: list[float] = []

    def _seal(self, prefix: str, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        signature = hmac.new(
            self.owner_password.encode(), (prefix + "." + encoded).encode(), hashlib.sha256,
        ).hexdigest()
        return prefix + "." + encoded + "." + signature

    def _open(self, token: str, prefix: str) -> dict | None:
        if not token.startswith(prefix + ".") or len(token) > 4096:
            return None
        try:
            _, encoded, signature = token.split(".", 2)
            mac = hmac.new(
                self.owner_password.encode(), (prefix + "." + encoded).encode(), hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(mac, signature):
                return None
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            return data
        except (ValueError, UnicodeError, TypeError, binascii.Error):
            return None

    def _client_secret(self, client_id: str) -> str:
        return hmac.new(
            self.owner_password.encode(), ("client-secret:" + client_id).encode(), hashlib.sha256,
        ).hexdigest()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        known = self.clients.get(client_id)
        if known:
            return known
        metadata = self._open(client_id, "oc1")
        if metadata is None:
            return None
        try:
            if not all(_is_chatgpt_callback(x) for x in metadata["redirect_uris"]):
                return None
            method = metadata.get("token_endpoint_auth_method", "client_secret_post")
            return OAuthClientInformationFull.model_validate({
                **metadata,
                "client_id": client_id,
                "client_id_issued_at": metadata.get("registered_at", int(time.time())),
                "client_secret": self._client_secret(client_id) if method != "none" else None,
                "client_secret_expires_at": 0 if method != "none" else None,
            })
        except Exception:
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError(error="invalid_client_metadata", error_description="Missing client id")
        # Restrict the DCR client to the official ChatGPT OAuth callback URLs.
        redirects = client_info.redirect_uris or []
        if not redirects or len(redirects) > 5 or not all(_is_chatgpt_callback(str(x)) for x in redirects):
            raise RegistrationError(error="invalid_redirect_uri", error_description="ChatGPT redirect required")
        # A signed, public client identifier survives Render Free sleeps; the
        # confidential client secret is independently derived and NOT encoded
        # into the client identifier. The signing key is the owner's private key.
        metadata = client_info.model_dump(
            mode="json",
            exclude={"client_id", "client_secret", "client_secret_expires_at", "client_id_issued_at"},
            exclude_none=True,
        )
        if metadata.get("token_endpoint_auth_method") not in ("none", "client_secret_post", "client_secret_basic"):
            raise RegistrationError(error="invalid_client_metadata", error_description="Unsupported token method")
        metadata["registered_at"] = int(time.time())
        new_id = self._seal("oc1", metadata)
        client_info.client_id = new_id
        client_info.client_id_issued_at = metadata["registered_at"]
        if client_info.token_endpoint_auth_method == "none":
            client_info.client_secret = None
            client_info.client_secret_expires_at = None
        else:
            client_info.client_secret = self._client_secret(new_id)
            client_info.client_secret_expires_at = 0
        self.clients[new_id] = client_info
        if len(self.clients) > 24:
            self.clients.pop(next(iter(self.clients)))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not _is_chatgpt_callback(str(params.redirect_uri)):
            raise AuthorizeError(error="invalid_request", error_description="Unrecognized callback")
        if params.resource not in (None, MCP_RESOURCE):
            raise AuthorizeError(error="invalid_target", error_description="Unrecognized resource")
        if params.scopes and (set(params.scopes) - {SCOPE}):
            raise AuthorizeError(error="invalid_scope", error_description="Only mcp scope is permitted")
        if len(self.pending) > 100:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if v.expires_at >= now}
            if len(self.pending) > 100:
                raise AuthorizeError(error="temporarily_unavailable", error_description="Pending approval capacity")
        ticket = secrets.token_urlsafe(32)
        self.pending[ticket] = Pending(client, params, time.time() + PENDING_LIFETIME)
        return f"{BASE_URL}/owner/approve?ticket={ticket}"

    def _issue_token(self, client_id: str, resource: str | None) -> OAuthToken:
        now = int(time.time())
        value = self._seal("oa1", {
            "client_id": client_id, "scopes": [SCOPE], "iat": now,
            "exp": now + TOKEN_LIFETIME, "resource": resource or MCP_RESOURCE,
            "subject": "omni-owner",
        })
        return OAuthToken(
            access_token=value, token_type="Bearer",
            expires_in=TOKEN_LIFETIME, scope=SCOPE,
        )

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        code = self.codes.get(authorization_code)
        if not code or code.client_id != client.client_id or code.expires_at <= time.time():
            return None
        return code

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        original = self.codes.pop(authorization_code.code, None)
        if original is None or original.expires_at <= time.time() or original.client_id != client.client_id:
            raise TokenError(error="invalid_grant", error_description="Invalid/expired authorization code")
        return self._issue_token(original.client_id, original.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        payload = self._open(token, "oa1")
        if not payload or not isinstance(payload.get("exp"), int):
            return None
        if payload["exp"] <= int(time.time()) or payload.get("resource") != MCP_RESOURCE:
            return None
        if payload.get("scopes") != [SCOPE] or payload.get("subject") != "omni-owner":
            return None
        if not isinstance(payload.get("client_id"), str):
            return None
        try:
            return AccessToken(
                token=token, client_id=payload["client_id"], scopes=[SCOPE],
                expires_at=payload["exp"], resource=MCP_RESOURCE,
                subject="omni-owner", claims={"iss": BASE_URL},
            )
        except Exception:
            return None

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        raise TokenError(error="invalid_grant", error_description="Refresh not supported; reconnect")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Stateless owner tokens are revoked globally by rotating OMNI_AGENT_ACCESS_TOKEN.
        return None

    def _pending_ticket(self, ticket: str) -> Pending | None:
        pending = self.pending.get(ticket)
        if not pending or pending.expires_at < time.time():
            self.pending.pop(ticket, None)
            return None
        return pending

    def _approved_ticket(self, ticket: str) -> Approved | None:
        approved = self.approved.get(ticket)
        if approved and approved.expires_at > time.time():
            return approved
        self.approved.pop(ticket, None)
        return None

    @staticmethod
    def _already_approved_page() -> Response:
        return HTMLResponse(
            "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            "<title>Autorização concluída</title><h1>Autorização concluída</h1>"
            "<p>O pedido já foi aprovado. Retorne ao ChatGPT para continuar. "
            "Caso a conexão não tenha sido concluída, reinicie-a pelo ChatGPT.</p></html>",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def approval_page(self, request: Request) -> Response:
        ticket = request.query_params.get("ticket", "")
        pending = self._pending_ticket(ticket)
        if not pending:
            if self._approved_ticket(ticket):
                return self._already_approved_page()
            return HTMLResponse("Solicitação expirada. Inicie uma nova conexão pelo ChatGPT.", status_code=400)
        # Only self-generated ticket and fixed text appear in HTML.
        safe_ticket = html.escape(ticket, quote=True)
        doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'">
<title>Autorizar Omni Host Sampling</title>
<style>body{{font:16px system-ui;max-width:440px;margin:5rem auto;padding:1rem;color:#17222e}}
input,button{{width:100%;box-sizing:border-box;padding:12px;margin-top:12px}}
button{{cursor:pointer;background:#164b96;color:white;border:0}}
p{{line-height:1.5}}</style></head><body>
<h1>Autorizar Omni Host Sampling</h1><p>Este servidor MCP solicita acesso para o ChatGPT.
Insira sua chave privada de proprietário. Ela será enviada apenas para este servidor via HTTPS,
nunca ao ChatGPT. Não forneça a chave no chat.</p>
<form action="/owner/approve" method="post">
<input type="hidden" name="ticket" value="{safe_ticket}">
<input type="password" name="password" placeholder="Chave de proprietário" autocomplete="off" required>
<button type="submit">Autorizar conexão</button>
</form></body></html>"""
        return HTMLResponse(doc, headers={
            "Cache-Control": "no-store", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        })

    async def approve(self, request: Request) -> Response:
        now = time.time()
        self.failed_logins = [t for t in self.failed_logins if now - t <= 300]
        if len(self.failed_logins) >= 12:
            return HTMLResponse("Muitas tentativas. Tente novamente depois de cinco minutos.", status_code=429)
        body = await request.body()
        if len(body) > 8192:
            return HTMLResponse("Formulário muito grande", status_code=413)
        from urllib.parse import parse_qs
        params = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=False)
        ticket = params.get("ticket", [""])[0]
        password = params.get("password", [""])[0]
        pending = self._pending_ticket(ticket)
        approved = self._approved_ticket(ticket)
        if not pending and not approved:
            return HTMLResponse(
                "Solicitação expirada. Reinicie a conexão no ChatGPT para gerar um novo pedido.",
                status_code=400,
            )
        # Check the owner's password even when returning a prior approval result.
        if not hmac.compare_digest(password.encode(), self.owner_password.encode()):
            self.failed_logins.append(now)
            return HTMLResponse("Chave incorreta. Volte e tente novamente.", status_code=403)
        if approved:
            # The OAuth code itself remains one-time use. Reposting an already
            # approved form must not mislead the owner with an "expired" error.
            if approved.authorization_code in self.codes:
                return RedirectResponse(
                    approved.redirect_uri, status_code=303,
                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
                )
            return self._already_approved_page()
        self.pending.pop(ticket, None)
        client, auth = pending.client, pending.params
        code = AuthorizationCode(
            code=secrets.token_urlsafe(40),
            client_id=client.client_id,
            scopes=[SCOPE],
            expires_at=now + 180,
            code_challenge=auth.code_challenge,
            redirect_uri=auth.redirect_uri,
            redirect_uri_provided_explicitly=auth.redirect_uri_provided_explicitly,
            resource=auth.resource or MCP_RESOURCE,
            subject="omni-owner",
        )
        self.codes[code.code] = code
        redirect = construct_redirect_uri(str(auth.redirect_uri), code=code.code, state=auth.state)
        # The human browser may resend the same form after a successful 303.
        # Cache only the redirect; never mint a second authorization code.
        self.approved[ticket] = Approved(
            redirect_uri=redirect, authorization_code=code.code,
            expires_at=now + PENDING_LIFETIME,
        )
        if len(self.approved) > 100:
            self.approved = {
                k: v for k, v in self.approved.items() if v.expires_at > now
            }
        return RedirectResponse(redirect, status_code=303, headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        })
