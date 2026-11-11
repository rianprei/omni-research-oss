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
import hashlib
import hmac
import html
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

BASE_URL = "https://omni-host-sampling-mcp.onrender.com"
MCP_RESOURCE = BASE_URL + "/mcp"
SCOPE = "mcp"
PENDING_LIFETIME = 300
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


class OwnerOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, owner_password: str):
        if len(owner_password) < 32:
            raise RuntimeError("OMNI_AGENT_ACCESS_TOKEN must contain at least 32 characters")
        self.owner_password = owner_password
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, Pending] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.failed_logins: list[float] = []

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError(error="invalid_client_metadata", error_description="Missing client id")
        # Restrict the DCR client to the official ChatGPT OAuth callback URLs.
        redirects = client_info.redirect_uris or []
        if not redirects or len(redirects) > 5 or not all(_is_chatgpt_callback(str(x)) for x in redirects):
            raise RegistrationError(error="invalid_redirect_uri", error_description="ChatGPT redirect required")
        if len(self.clients) >= 24:
            raise RegistrationError(error="invalid_client_metadata", error_description="Registration capacity exhausted")
        self.clients[client_info.client_id] = client_info

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
        value = secrets.token_urlsafe(48)
        self.access_tokens[value] = AccessToken(
            token=value, client_id=client_id, scopes=[SCOPE],
            expires_at=int(time.time()) + TOKEN_LIFETIME,
            resource=resource or MCP_RESOURCE,
            subject="omni-owner",
            claims={"iss": BASE_URL},
        )
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
        record = self.access_tokens.get(token)
        if record and record.expires_at and record.expires_at > time.time():
            return record
        self.access_tokens.pop(token, None)
        return None

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        raise TokenError(error="invalid_grant", error_description="Refresh not supported; reconnect")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.access_tokens.pop(token.token, None)

    def _pending_ticket(self, ticket: str) -> Pending | None:
        pending = self.pending.get(ticket)
        if not pending or pending.expires_at < time.time():
            self.pending.pop(ticket, None)
            return None
        return pending

    async def approval_page(self, request: Request) -> Response:
        ticket = request.query_params.get("ticket", "")
        pending = self._pending_ticket(ticket)
        if not pending:
            return HTMLResponse("Authorization request expired; start connecting again.", status_code=400)
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
        if not pending:
            return HTMLResponse("Solicitação expirada ou inválida.", status_code=400)
        if not hmac.compare_digest(password.encode(), self.owner_password.encode()):
            self.failed_logins.append(now)
            return HTMLResponse("Chave incorreta. Volte e tente novamente.", status_code=403)
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
        return RedirectResponse(redirect, status_code=303, headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        })
