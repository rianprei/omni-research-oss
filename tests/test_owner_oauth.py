"""Owner-approved OAuth server tests; no ChatGPT subscription or API needed."""
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, RegistrationError
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from owner_oauth import OwnerOAuthProvider, MCP_RESOURCE, _is_chatgpt_callback

PASSWORD = "test-only-no-real-owner-password-with-48-chars"
CALLBACK = "https://chatgpt.com/connector/oauth/testing-callback"

def fake_request(method: str, path: str, body: bytes = b""):
    scope = {
        "type": "http", "method": method, "path": path,
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request(scope, receive)

class OwnerOAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = OwnerOAuthProvider(PASSWORD)
        self.client = SimpleNamespace(
            client_id="chatgpt-testing-client", redirect_uris=[CALLBACK],
        )
        await self.provider.register_client(self.client)
        self.params = AuthorizationParams(
            state="opaque-state",
            scopes=["mcp"],
            code_challenge="A"*43,
            redirect_uri=CALLBACK,
            redirect_uri_provided_explicitly=True,
            resource=MCP_RESOURCE,
        )

    async def test_callback_is_strictly_limited_to_chatgpt(self):
        for uri in [
            CALLBACK,
            "https://chatgpt.com/connector_platform_oauth_redirect",
        ]:
            self.assertTrue(_is_chatgpt_callback(uri))
        for uri in [
            "https://attacker.example/callback",
            "https://chatgpt.com.evil.org/connector/oauth/abc",
            "http://chatgpt.com/connector/oauth/abc",
            "https://chatgpt.com/connector/oauth/",
            "https://chatgpt.com/connector/oauth/a#fragment",
        ]:
            self.assertFalse(_is_chatgpt_callback(uri), uri)

    async def test_register_blocks_untrusted_redirects(self):
        with self.assertRaises(RegistrationError):
            await self.provider.register_client(
                SimpleNamespace(client_id="bad", redirect_uris=["https://evil.example/callback"])
            )

    async def test_authorization_requires_correct_resource(self):
        p = self.params.model_copy(update={"resource": "https://evil.example/mcp"})
        with self.assertRaises(AuthorizeError):
            await self.provider.authorize(self.client, p)

    async def test_no_automatic_login_and_one_time_code(self):
        uri = await self.provider.authorize(self.client, self.params)
        ticket = parse_qs(urlsplit(uri).query)["ticket"][0]
        self.assertIsNotNone(self.provider._pending_ticket(ticket))
        before = len(self.provider.codes)
        wrong = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password=bad".encode()
        ))
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(len(self.provider.codes), before)
        correct = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(correct.status_code, 303)
        redir = correct.headers["location"]
        self.assertTrue(redir.startswith(CALLBACK))
        code_value = parse_qs(urlsplit(redir).query)["code"][0]
        code = await self.provider.load_authorization_code(self.client, code_value)
        self.assertIsNotNone(code)
        oauth_token = await self.provider.exchange_authorization_code(self.client, code)
        access = await self.provider.load_access_token(oauth_token.access_token)
        self.assertEqual(access.resource, MCP_RESOURCE)
        self.assertEqual(access.scopes, ["mcp"])
        self.assertEqual(access.subject, "omni-owner")
        with self.assertRaises(Exception):
            await self.provider.exchange_authorization_code(self.client, code)
        replay = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(replay.status_code, 400)

    async def test_access_token_expiry(self):
        access = self.provider._issue_token(self.client.client_id, MCP_RESOURCE)
        record = await self.provider.load_access_token(access.access_token)
        self.assertIsNotNone(record)
        record.expires_at = int(time.time()) - 1
        self.assertIsNone(await self.provider.load_access_token(access.access_token))

    async def test_expired_ticket(self):
        uri = await self.provider.authorize(self.client, self.params)
        ticket = parse_qs(urlsplit(uri).query)["ticket"][0]
        self.provider.pending[ticket].expires_at = time.time() - 1
        self.assertIsNone(self.provider._pending_ticket(ticket))
        refused = await self.provider.approve(fake_request(
            "POST", "/owner/approve", f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(refused.status_code, 400)

if __name__ == "__main__":
    unittest.main()
