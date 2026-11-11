"""Unit tests: the MCP client (not this server) chooses and runs a model."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import host_sampling_core as core
from mcp.types import TextContent

class FakeClient:
    def __init__(self, supported=True):
        self.client_capabilities = types.SimpleNamespace(sampling=object() if supported else None)
        self.calls = []
        self.active = 0
        self.peak = 0
    async def create_message(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.peak = max(self.active, self.peak)
        await asyncio.sleep(0.012)
        self.active -= 1
        return types.SimpleNamespace(
            content=TextContent(type="text", text="Response from the mocked host model"),
            model="mock-host-model"
        )

class HostSamplingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_sampling_is_explicit_failure(self):
        client = FakeClient(False)
        result = await core.spawn(client, 12, "Study African history")
        self.assertFalse(result["spawned"])
        self.assertEqual(result["error"], "HOST_SAMPLING_UNSUPPORTED")
        self.assertEqual(client.calls, [])

    async def test_three_concurrent_client_requests(self):
        client = FakeClient()
        result = await core.spawn(client, 100, "Study African history")
        self.assertTrue(result["spawned"])
        self.assertEqual(result["agents_completed"], 3)
        self.assertEqual(client.peak, 3)
        self.assertEqual(len(client.calls), 3)
        self.assertTrue(all(x["related_request_id"] == 100 for x in client.calls))
        self.assertTrue(all(x["model_preferences"].hints[0].name == "gpt-6" for x in client.calls))
        self.assertEqual({x["reported_model"] for x in result["results"]}, {"mock-host-model"})
        self.assertEqual(core.lookup(result["task_id"])["agents_completed"], 3)

    async def test_unsupported_request_does_not_invent_model_output(self):
        class RejectingClient(FakeClient):
            async def create_message(self, **kwargs):
                raise NotImplementedError("Host does not implement sampling")
        result = await core.spawn(RejectingClient(), 101, "Study African history", roles=["critic"])
        self.assertFalse(result["spawned"])
        self.assertEqual(result["results"][0]["error"], "CLIENT_SAMPLING_REQUEST_REJECTED")

    async def test_input_restrictions(self):
        client = FakeClient()
        for bad in ({"prompt": "x"}, {"prompt": "valid prompt", "roles": []},
                    {"prompt": "valid prompt", "roles": ["invalid"]},
                    {"prompt": "valid prompt", "roles": ["coder"] * 4},
                    {"prompt": "valid prompt", "max_tokens": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await core.spawn(client, 100, **bad)
        self.assertEqual(client.calls, [])

if __name__ == "__main__":
    unittest.main()
