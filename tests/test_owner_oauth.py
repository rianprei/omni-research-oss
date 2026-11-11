"""Owner-approved OAuth server tests; no ChatGPT subscription or API needed."""
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
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
        self.client = OAuthClientInformationFull.model_validate({
            "client_id": "temporary-client-id",
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": "mcp",
            "client_name": "ChatGPT test",
        })
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
        # A repeated form submission before code exchange must return the
        # EXACT same OAuth redirect without minting another authorization code.
        repeated = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(repeated.status_code, 303)
        self.assertEqual(repeated.headers["location"], redir)
        self.assertEqual(len(self.provider.codes), before + 1)
        self.assertEqual((await self.provider.approval_page(
            fake_request("GET", "/owner/approve")
        )).status_code, 400)
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
        self.assertEqual(replay.status_code, 200)
        self.assertIn("Autorização concluída", replay.body.decode())

    async def test_wrong_password_after_approval_is_still_denied(self):
        uri = await self.provider.authorize(self.client, self.params)
        ticket = parse_qs(urlsplit(uri).query)["ticket"][0]
        good = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(good.status_code, 303)
        rejected = await self.provider.approve(fake_request(
            "POST", "/owner/approve", f"ticket={ticket}&password=wrong".encode()
        ))
        self.assertEqual(rejected.status_code, 403)
        still = await self.provider.approve(fake_request(
            "POST", "/owner/approve",
            f"ticket={ticket}&password={PASSWORD}".encode()
        ))
        self.assertEqual(still.headers["location"], good.headers["location"])

    async def test_access_token_expiry(self):
        access = self.provider._issue_token(self.client.client_id, MCP_RESOURCE)
        record = await self.provider.load_access_token(access.access_token)
        self.assertIsNotNone(record)
        expired = self.provider._seal("oa1", {
            "client_id": self.client.client_id, "scopes": ["mcp"],
            "iat": int(time.time()) - 1000, "exp": int(time.time()) - 1,
            "resource": MCP_RESOURCE, "subject": "omni-owner",
        })
        self.assertIsNone(await self.provider.load_access_token(expired))

    async def test_signed_dcr_client_and_access_survive_restart(self):
        cid = self.client.client_id
        self.assertTrue(cid.startswith("oc1."))
        access = self.provider._issue_token(cid, MCP_RESOURCE)
        self.provider.clients.clear()
        self.provider.access_tokens.clear()
        recovered = await self.provider.get_client(cid)
        self.assertEqual(recovered.client_id, cid)
        self.assertEqual(recovered.client_secret, self.provider._client_secret(cid))
        self.assertIsNotNone(await self.provider.load_access_token(access.access_token))
        self.assertIsNone(await self.provider.get_client(cid + "corrupt"))
        self.assertIsNone(await self.provider.load_access_token(access.access_token + "corrupt"))

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
