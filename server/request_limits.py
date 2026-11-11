"""Cheap process-local resource limits for the unauthenticated public MCP endpoint.

Not a replacement for authenticated, provider-backed quotas or WAF protection.
"""
from __future__ import annotations

import asyncio
from collections import deque
import time


class RateLimitedApp:
    def __init__(self, app, *, requests_per_minute=120, concurrency=6, max_bytes=32768):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.max_bytes = max_bytes
        self.lock = asyncio.Lock()
        self.timestamps = deque()
        self.slots = asyncio.Semaphore(concurrency)

    async def _reply(self, send, code, message, extra_headers=()):
        body = message.encode("utf-8")
        headers = [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]
        headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": code, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/mcp":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if scope.get("method") == "POST":
            size = headers.get(b"content-length")
            if size is None:
                return await self._reply(send, 411, "Content-Length required for MCP POST")
            try:
                body_size = int(size)
            except (ValueError, TypeError):
                return await self._reply(send, 400, "Invalid Content-Length")
            if body_size < 0 or body_size > self.max_bytes:
                return await self._reply(send, 413, "MCP request exceeds maximum input size")

        now = time.monotonic()
        async with self.lock:
            while self.timestamps and self.timestamps[0] <= now-60:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.requests_per_minute:
                return await self._reply(send, 429, "Public MCP rate limit exceeded", [(b"retry-after", b"60")])
            self.timestamps.append(now)

        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=0.08)
        except asyncio.TimeoutError:
            return await self._reply(send, 503, "MCP concurrent request capacity reached", [(b"retry-after", b"1")])
        try:
            return await self.app(scope, receive, send)
        finally:
            self.slots.release()
