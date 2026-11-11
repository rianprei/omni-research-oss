"""OAuth RFC9207 compliance tests; no model, cloud, or MCP SDK required."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from oauth_issuer_identification import OAuthIssuerIdentification, _with_issuer

ISSUER = "https://omni-host-sampling-mcp.onrender.com/"
STABLE = "https://chatgpt.com/connector_platform_oauth_redirect"
LEGACY = "https://chatgpt.com/connector/oauth/sampleCallback"


class IssuerIdentificationTests(unittest.IsolatedAsyncioTestCase):
    async def ask(self, path, status, body, headers=(), method="GET"):
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": status, "headers": list(headers)})
            await send({"type": "http.response.body", "body": body})
        wrapped = OAuthIssuerIdentification(mock_app, ISSUER)
        emitted = []
        async def send(message):
            emitted.append(message)
        await wrapped(
            {"type": "http", "path": path, "method": method, "headers": []},
            lambda: None, send,
        )
        return emitted

    async def test_metadata_advertises_exact_issuer(self):
        body=json.dumps({
            "issuer":ISSUER,
            "authorization_endpoint":ISSUER+"/authorize",
            "token_endpoint":ISSUER+"/token",
            "code_challenge_methods_supported":["S256"],
        }).encode()
        for path in ("/.well-known/oauth-authorization-server",
                     "/.well-known/oauth-authorization-server/mcp"):
            with self.subTest(path=path):
                messages = await self.ask(path, 200, body, [
                    (b"content-type",b"application/json"),
                    (b"content-length",str(len(body)).encode()),
                ])
                self.assertEqual(len(messages),2)
                self.assertTrue(json.loads(messages[1]["body"])["authorization_response_iss_parameter_supported"])
                self.assertEqual(json.loads(messages[1]["body"])["issuer"],ISSUER)
                headers = dict(messages[0]["headers"])
                self.assertEqual(int(headers[b"content-length"]),len(messages[1]["body"]))

    async def test_success_callback_preserves_state_and_code(self):
        for url in (STABLE,LEGACY):
            with self.subTest(url=url):
                src=url+"?code=one-time-secret&state=state%2Fsession"
                result=_with_issuer(src,ISSUER)
                params=parse_qs(urlsplit(result).query)
                self.assertEqual(params["code"],["one-time-secret"])
                self.assertEqual(params["state"],["state/session"])
                self.assertEqual(params["iss"],[ISSUER])
                self.assertEqual(result.count("iss="),1)

    async def test_error_callback_must_identify_issuer(self):
        output = _with_issuer(STABLE+"?error=access_denied&state=abc",ISSUER)
        params = parse_qs(urlsplit(output).query)
        self.assertEqual(params["error"],["access_denied"])
        self.assertEqual(params["iss"],[ISSUER])

    async def test_duplicate_issuer_is_overwritten(self):
        url=LEGACY+"?code=xyz&state=abc&iss=https%3A%2F%2Fattacker.test"
        output=_with_issuer(url,ISSUER)
        self.assertEqual(parse_qs(urlsplit(output).query)["iss"],[ISSUER])

    async def test_non_chatgpt_or_unrelated_redirect_unchanged(self):
        for url in (
            "https://evil.example/connector/oauth/x?code=123&state=abc",
            "https://chatgpt.com/connector/oauth/?code=123&state=abc",
            "https://chatgpt.com/connector/oauth/cb?prompt=123",
            ISSUER+"owner/approve?ticket=123",
            "http://chatgpt.com/connector_platform_oauth_redirect?code=123",
        ):
            self.assertEqual(_with_issuer(url,ISSUER),url)

    async def test_asgi_location_redirect_is_augmented(self):
        location=(LEGACY+"?code=xyz&state=abc").encode()
        result=await self.ask("/owner/approve",303,b"",headers=[(b"location",location)],method="POST")
        self.assertEqual(result[0]["status"],303)
        updated=dict(result[0]["headers"])[b"location"].decode()
        self.assertEqual(parse_qs(urlsplit(updated).query)["iss"],[ISSUER])

    async def test_non_metadata_streaming_is_not_buffered(self):
        seen = []
        async def streaming(scope,receive,send):
            await send({"type":"http.response.start","status":200,"headers":[]})
            await send({"type":"http.response.body","body":b"chunk1","more_body":True})
            await send({"type":"http.response.body","body":b"chunk2","more_body":False})
        async def collect(event):
            seen.append(event)
        await OAuthIssuerIdentification(streaming,ISSUER)(
            {"type":"http","path":"/mcp","method":"POST"},lambda:None,collect)
        self.assertEqual([x.get("body") for x in seen[1:]],[b"chunk1",b"chunk2"])

    async def test_metadata_issuer_mismatch_is_not_advertised(self):
        body=json.dumps({"issuer":"https://other.example"}).encode()
        result=await self.ask("/.well-known/oauth-authorization-server",200,body)
        self.assertEqual(result[1]["body"],body)

    async def test_invalid_issuer_refused(self):
        with self.assertRaises(ValueError):
            OAuthIssuerIdentification(None,"http://evil.example")


if __name__=="__main__":
    unittest.main()
