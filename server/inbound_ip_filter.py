"""Application-layer ingress allowlist for the Omni Host Sampling MCP only.

Render's native inbound IP rules for web services require a Scale or
Enterprise workspace; this is a narrower application-level fallback, not
an edge/network ACL. No X-Forwarded-For trust (it can be spoofed).
Cloudflare overwrites CF-Connecting-IP on its origin connections.
"""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterable

HOST_SAMPLING_ALLOWED_CIDRS = ("74.220.49.0/24", "74.220.57.0/24")


class IngressAllowlist:
    def __init__(self, app, allowed: Iterable[str] | None = None):
        self.app = app
        if allowed is None:
            configured = os.environ.get(
                "OMNI_HOST_SAMPLING_ALLOWED_CIDRS", ",".join(HOST_SAMPLING_ALLOWED_CIDRS)
            )
            allowed = tuple(item.strip() for item in configured.split(","))
        self.networks = tuple(ipaddress.IPv4Network(cidr, strict=True) for cidr in allowed)
        if not self.networks:
            raise ValueError("Ingress allowlist must not be empty")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        # Leave Render's HTTP liveness check usable. MCP routes remain restricted.
        if scope.get("path") == "/healthz" and scope.get("method") in ("GET", "HEAD"):
            return await self.app(scope, receive, send)

        headers = {}
        for name, value in scope.get("headers", []):
            name = name.lower()
            if name == b"cf-connecting-ip":
                if name in headers:  # multiple copies are ambiguous: fail closed
                    return await self._reject(send)
                headers[name] = value
        address = headers.get(b"cf-connecting-ip", b"")
        try:
            parsed = ipaddress.ip_address(address.decode("ascii"))
            allowed = isinstance(parsed, ipaddress.IPv4Address) and any(
                parsed in network for network in self.networks
            )
        except (ValueError, UnicodeError):
            allowed = False
        if not allowed:
            return await self._reject(send)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send):
        payload = b"Forbidden: source IP not on Omni Host Sampling allowlist"
        await send({
            "type": "http.response.start", "status": 403,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(payload)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
