"""Application-layer allowlist tests without MCP/Render dependencies."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from inbound_ip_filter import IngressAllowlist, HOST_SAMPLING_ALLOWED_CIDRS


class IngressIPTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, headers=(), path="/mcp", method="POST"):
        calls = []

        async def inner(scope, receive, send):
            calls.append("invoked")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(event):
            calls.append(event)

        scope = {"type": "http", "path": path, "method": method, "headers": list(headers)}
        await IngressAllowlist(inner)(scope, receive, send)
        return next(x["status"] for x in calls if isinstance(x, dict) and x.get("type") == "http.response.start"), "invoked" in calls

    async def test_exact_two_cidrs(self):
        self.assertEqual(HOST_SAMPLING_ALLOWED_CIDRS, ("74.220.49.0/24", "74.220.57.0/24"))
        for addr in ("74.220.49.0", "74.220.49.1", "74.220.49.254", "74.220.49.255",
                     "74.220.57.0", "74.220.57.128", "74.220.57.255"):
            with self.subTest(addr=addr):
                code, called = await self.request([(b"cf-connecting-ip", addr.encode())])
                self.assertEqual((code, called), (200, True))

    async def test_other_sources_rejected(self):
        for addr in ("74.220.48.255", "74.220.50.0", "74.220.56.255",
                     "74.220.58.0", "127.0.0.1", "::1", "8.8.8.8",
                     "74.220.49.10, 1.1.1.1", "garbage"):
            with self.subTest(addr=addr):
                code, called = await self.request([(b"cf-connecting-ip", addr.encode())])
                self.assertEqual((code, called), (403, False))

    async def test_no_header_and_spoofed_xff_rejected(self):
        self.assertEqual(await self.request(), (403, False))
        self.assertEqual(await self.request([
            (b"x-forwarded-for", b"74.220.49.15")]), (403, False))

    async def test_duplicate_cf_connecting_ip_is_rejected(self):
        self.assertEqual(await self.request([
            (b"cf-connecting-ip", b"74.220.49.15"),
            (b"CF-Connecting-IP", b"74.220.57.15"),
        ]), (403, False))

    async def test_health_check_unchanged(self):
        self.assertEqual(await self.request(path="/healthz", method="GET"), (200, True))
        self.assertEqual(await self.request(path="/healthz", method="HEAD"), (200, True))
        self.assertEqual(await self.request(path="/healthz", method="POST"), (403, False))

    async def test_empty_allowlist_is_not_allowed(self):
        with self.assertRaises(ValueError):
            IngressAllowlist(lambda *_: None, allowed=())


if __name__ == "__main__":
    unittest.main()
