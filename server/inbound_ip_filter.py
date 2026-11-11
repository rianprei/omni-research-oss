"""Application-level inbound IP allowlist for the private Host Sampling MCP.

The two user-provided Render CIDRs are retained. Optionally extend the
allowlist with the *official, changing* ChatGPT integrations egress feed:
https://openai.com/chatgpt-connectors.json

Bearer authentication is still required; IP identity alone never authorizes.
This is NOT a Render firewall or a guarantee of IP authenticity.
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
import time
from collections.abc import Iterable
from urllib.request import Request, urlopen

HOST_SAMPLING_ALLOWED_CIDRS = ("74.220.49.0/24", "74.220.57.0/24")
OPENAI_CONNECTORS_URL = "https://openai.com/chatgpt-connectors.json"


def _parse_openai_prefixes(raw: bytes) -> tuple:
    """Validate the public OpenAI JSON feed; reject empty/unrecognized payloads."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid egress feed")
    entries = data.get("prefixes")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4096:
        raise ValueError("Invalid OpenAI egress prefixes")
    result = []
    for entry in entries:
        values = [entry] if isinstance(entry, str) else [
            entry.get(k) for k in ("ipv4Prefix", "ipv6Prefix") if isinstance(entry, dict)
        ]
        for value in values:
            if value:
                result.append(ipaddress.ip_network(value, strict=True))
    if not result:
        raise ValueError("No valid OpenAI networks")
    return tuple(set(result))


def _fetch_openai_prefixes() -> tuple:
    request = Request(OPENAI_CONNECTORS_URL, headers={
        "Accept": "application/json", "User-Agent": "OmniHostSampling/0.2",
    })
    with urlopen(request, timeout=5) as response:
        # Bound memory even if upstream sends oversized JSON.
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("OpenAI prefix feed too large")
    return _parse_openai_prefixes(raw)


class IngressAllowlist:
    def __init__(
        self, app, allowed: Iterable[str] | None = None,
        include_openai: bool | None = None,
        fetcher=None, refresh_seconds: int = 3600,
    ):
        self.app = app
        if allowed is None:
            configured = os.environ.get(
                "OMNI_HOST_SAMPLING_ALLOWED_CIDRS",
                ",".join(HOST_SAMPLING_ALLOWED_CIDRS),
            )
            allowed = tuple(item.strip() for item in configured.split(","))
        self.networks = tuple(ipaddress.ip_network(cidr, strict=True) for cidr in allowed)
        if not self.networks:
            raise ValueError("Ingress allowlist must not be empty")
        if include_openai is None:
            include_openai = os.getenv("OMNI_HOST_SAMPLING_INCLUDE_OPENAI_EGRESS", "0") == "1"
        self.include_openai = include_openai
        self.fetcher = fetcher or _fetch_openai_prefixes
        self.refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._openai_networks: tuple = ()
        self._next_refresh = 0.0
        self._feed_status = "not_enabled" if not include_openai else "pending"

    @property
    def feed_status(self) -> str:
        return self._feed_status

    def _networks(self):
        if not self.include_openai:
            return self.networks
        now = time.monotonic()
        if now >= self._next_refresh:
            with self._lock:
                if now >= self._next_refresh:
                    try:
                        loaded = self.fetcher()
                        if not loaded:
                            raise ValueError("Empty ChatGPT egress feed")
                        self._openai_networks = loaded
                        self._feed_status = "loaded"
                        self._next_refresh = now + self.refresh_seconds
                    except Exception:
                        # Fail closed: never treat feed errors as permission.
                        # Keep last verified networks if already available.
                        self._feed_status = "error" if not self._openai_networks else "stale"
                        self._next_refresh = now + min(120, self.refresh_seconds)
        return self.networks + self._openai_networks

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") == "/healthz" and scope.get("method") in ("GET", "HEAD"):
            return await self.app(scope, receive, send)

        headers = {}
        for name, value in scope.get("headers", []):
            name = name.lower()
            if name == b"cf-connecting-ip":
                if name in headers:  # ambiguous: reject
                    return await self._reject(send)
                headers[name] = value
        address = headers.get(b"cf-connecting-ip", b"")
        try:
            parsed = ipaddress.ip_address(address.decode("ascii"))
            allowed = any(parsed in network for network in self._networks())
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
