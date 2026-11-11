"""RFC 9207 issuer identification for the official MCP OAuth AS.

ChatGPT can use a stable OAuth callback when the authorization server
advertises issuer identification and echoes the exact issuer as iss in
authorization responses. Wrap only metadata and redirects.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ISSUER_METADATA_PATHS = frozenset((
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-authorization-server/mcp",
))


def _with_issuer(location: str, issuer: str) -> str:
    parts = urlsplit(location)
    if parts.scheme != "https" or parts.netloc != "chatgpt.com":
        return location
    callback = (
        parts.path == "/connector_platform_oauth_redirect"
        or (
            parts.path.startswith("/connector/oauth/")
            and bool(parts.path.removeprefix("/connector/oauth/"))
        )
    )
    if not callback:
        return location
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(k in ("code", "error") for k, _ in pairs):
        return location
    pairs = [(k, v) for k, v in pairs if k != "iss"]
    pairs.append(("iss", issuer))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(pairs), parts.fragment))


class OAuthIssuerIdentification:
    def __init__(self, app, issuer: str):
        if not issuer.startswith("https://") and not issuer.startswith("http://localhost:"):
            raise ValueError("OAuth issuer must be HTTPS (or localhost for CI)")
        self.app = app
        # Match the MCP SDK\u0027s canonical AnyHttpUrl issuer, which ends with a slash.
        self.issuer = issuer.rstrip("/") + "/"

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        is_metadata = scope.get("method") == "GET" and path in ISSUER_METADATA_PATHS
        if is_metadata:
            return await self._metadata(scope, receive, send)
        # Redirect headers can be changed in-flight without buffering.
        async def redirect_send(event):
            if event["type"] == "http.response.start" and 300 <= event.get("status", 0) < 400:
                headers = []
                for name, value in event.get("headers", []):
                    if name.lower() == b"location":
                        loc = value.decode("utf-8")
                        loc = _with_issuer(loc, self.issuer)
                        headers.append((name, loc.encode("utf-8")))
                    else:
                        headers.append((name, value))
                event = dict(event, headers=headers)
            await send(event)
        return await self.app(scope, receive, redirect_send)

    async def _metadata(self, scope, receive, send):
        events = []
        async def collect(event):
            events.append(event)
        await self.app(scope, receive, collect)
        start = next((e for e in events if e["type"] == "http.response.start"), None)
        if not start or start.get("status") != 200:
            for e in events:
                await send(e)
            return
        raw = b"".join(e.get("body", b"") for e in events
                       if e["type"] == "http.response.body")
        if len(raw) > 131072:
            for e in events:
                await send(e)
            return
        try:
            metadata = json.loads(raw)
            if not isinstance(metadata, dict) or metadata.get("issuer") != self.issuer:
                raise ValueError("Invalid OAuth AS metadata issuer")
            metadata["authorization_response_iss_parameter_supported"] = True
            payload = json.dumps(metadata, separators=(",", ":")).encode()
        except (ValueError, UnicodeError):
            # Never advertise support if discovery JSON was unrecognizable.
            for e in events:
                await send(e)
            return
        hdrs = [(n, v) for n, v in start.get("headers", [])
                if n.lower() not in (b"content-length", b"etag")]
        hdrs.append((b"content-length", str(len(payload)).encode()))
        await send(dict(start, headers=hdrs))
        await send({"type": "http.response.body", "body": payload})
