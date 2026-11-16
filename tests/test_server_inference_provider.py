"""Offline tests for independent agents using an OpenAI-compatible server provider."""
import json
import os
import unittest
from unittest.mock import patch

import inference_provider as provider
import host_agent_lifecycle as life
from test_host_sampling_core import FakeClient


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class _HTTP:
    def __init__(self):
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        assert timeout <= 45
        body = json.loads(request.data)
        assert body["messages"][0]["role"] == "system"
        return _Response({
            "model": "mock-model",
            "choices": [{"message": {"content": "Independent model response"}}],
        })


class ServerProviderAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with life._lock:
            life._agents.clear()
            life._limit = 3
            life._active = 0

    async def test_three_agents_and_followup_without_host_sampling(self):
        http = _HTTP()
        env = {
            "OMNI_INFERENCE_BASE_URL": "https://provider.example/v1",
            "OMNI_INFERENCE_MODEL": "mock-model",
            "OMNI_INFERENCE_API_KEY": "test-private-secret",
        }
        with patch.dict(os.environ, env), patch.object(provider, "build_opener", return_value=http):
            client = FakeClient(False)
            result = await life.spawn_agents(client, 9, "Independent model question")
            self.assertTrue(result["spawned"])
            self.assertEqual(result["agents_completed"], 3)
            self.assertEqual(len(http.calls), 3)
            self.assertEqual(client.calls, [])
            self.assertTrue(all(a["reported_model"] == "mock-model" for g in result["groups"] for a in g["agents"]))
            followup = await life.send_message(client, 10, result["agent_ids"][0], "Analyze another case")
            self.assertTrue(followup["sent"])
            self.assertEqual(len(http.calls), 4)
            self.assertIn("Bearer test-private-secret", http.calls[0].get_header("Authorization"))
            self.assertEqual(http.calls[0].full_url, "https://provider.example/v1/chat/completions")

    async def test_no_model_and_no_client_sampling(self):
        with patch.dict(os.environ, {"OMNI_INFERENCE_BASE_URL": "", "OMNI_INFERENCE_MODEL": ""}):
            result = await life.spawn_agents(FakeClient(False), 9, "Independent model question")
            self.assertFalse(result["spawned"])
            self.assertEqual(result["error"], "HOST_SAMPLING_UNSUPPORTED")

    def test_url_requires_https_except_loopback(self):
        with patch.dict(os.environ, {"OMNI_INFERENCE_BASE_URL": "http://external.example/v1",
                                    "OMNI_INFERENCE_MODEL": "m"}):
            self.assertEqual(provider._call_provider("p", "instructions", 100)["error"], "PROVIDER_RESPONSE_INVALID")


if __name__ == "__main__":
    unittest.main()
