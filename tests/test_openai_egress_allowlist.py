"""Offline tests for the official ChatGPT egress feed allowlist integration."""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from inbound_ip_filter import IngressAllowlist, _parse_openai_prefixes, OPENAI_CONNECTORS_URL


class ChatGPTEgressTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, middleware, ip):
        events = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(event):
            events.append(event)

        headers = [(b"cf-connecting-ip", ip.encode("ascii"))]
        await middleware({
            "type": "http", "path": "/mcp", "method": "POST", "headers": headers,
        }, receive, send)
        return next(e["status"] for e in events if e["type"] == "http.response.start")

    @staticmethod
    def inner():
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})
        return app

    async def test_parse_official_json_shape_and_ipv6(self):
        payload = b'{"creationTime": "2026-11-11", "prefixes": [{"ipv4Prefix": "203.0.113.0/24"}, {"ipv6Prefix": "2001:db8::/32"}]}'
        networks = _parse_openai_prefixes(payload)
        self.assertEqual({str(n) for n in networks}, {"203.0.113.0/24", "2001:db8::/32"})

    async def test_empty_feed_is_rejected(self):
        for raw in [b"{}", b'{"prefixes": []}', b'{"prefixes": [{"unexpected": "a"}]}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _parse_openai_prefixes(raw)

    async def test_correct_feed_url(self):
        self.assertEqual(OPENAI_CONNECTORS_URL, "https://openai.com/chatgpt-connectors.json")

    async def test_openai_ranges_augment_user_ranges(self):
        calls = []
        def fetcher():
            calls.append(True)
            return _parse_openai_prefixes(
                b'{"prefixes": [{"ipv4Prefix": "203.0.113.0/24"}]}'
            )
        m = IngressAllowlist(self.inner(), include_openai=True, fetcher=fetcher)
        self.assertEqual(await self.request(m, "203.0.113.23"), 200)
        self.assertEqual(await self.request(m, "74.220.49.15"), 200)
        self.assertEqual(await self.request(m, "74.220.57.200"), 200)
        self.assertEqual(await self.request(m, "198.51.100.8"), 403)
        self.assertEqual(len(calls), 1)
        self.assertEqual(m.feed_status, "loaded")

    async def test_fail_closed_on_initial_feed_error(self):
        def broken():
            raise ConnectionError("Feed temporarily unreachable")
        m = IngressAllowlist(self.inner(), include_openai=True, fetcher=broken)
        self.assertEqual(await self.request(m, "203.0.113.9"), 403)
        self.assertEqual(await self.request(m, "74.220.49.9"), 200)
        self.assertEqual(m.feed_status, "error")

    async def test_last_verified_feed_survives_refresh_error(self):
        seen = [0]
        def fetcher():
            seen[0] += 1
            if seen[0] == 1:
                return _parse_openai_prefixes(
                    b'{"prefixes": [{"ipv4Prefix": "203.0.113.0/24"}]}'
                )
            raise ConnectionError("Network unavailable")
        m = IngressAllowlist(self.inner(), include_openai=True, fetcher=fetcher, refresh_seconds=1)
        self.assertEqual(await self.request(m, "203.0.113.9"), 200)
        m._next_refresh = 0  # deterministic elapsed-time injection
        self.assertEqual(await self.request(m, "203.0.113.9"), 200)
        self.assertEqual(m.feed_status, "stale")
        self.assertEqual(seen[0], 2)

    async def test_opt_in_env_flag(self):
        with patch.dict(os.environ, {"OMNI_HOST_SAMPLING_INCLUDE_OPENAI_EGRESS": "1"}):
            obj = IngressAllowlist(self.inner(), fetcher=lambda: ("does-not-matter",))
            self.assertTrue(obj.include_openai)


if __name__ == "__main__":
    unittest.main()
