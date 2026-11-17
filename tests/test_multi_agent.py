"""Offline contract tests for the public multi_agent orchestration tool."""
import os
import unittest
from unittest.mock import patch

import host_agent_lifecycle as life
from test_host_sampling_core import FakeClient


class MultiAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with life._lock:
            life._agents.clear()
            life._limit = 3
            life._active = 0

    async def test_two_independent_agents(self):
        client = FakeClient()
        report = await life.multi_agent(
            client, 101, "Examine technical tradeoffs",
            ["researcher", "critic"], 400, "gpt-6",
        )
        self.assertEqual(report["orchestration"], "multi_agent")
        self.assertTrue(report["executed"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["backend"], "client_sampling")
        self.assertFalse(report["native_chatgpt_agents"])
        self.assertEqual(report["agents_requested"], 2)
        self.assertEqual(report["agents_completed"], 2)
        self.assertEqual(len(report["agents"]), 2)
        self.assertEqual(len(set(report["agent_ids"])), 2)
        self.assertEqual({a["role"] for a in report["agents"]}, {"researcher", "critic"})
        self.assertEqual(life.list_agents()["count"], 2)

    async def test_backend_missing_fails_without_fake_agent(self):
        with patch.dict(os.environ, {
            "OMNI_INFERENCE_BASE_URL": "", "OMNI_INFERENCE_MODEL": "",
        }):
            report = await life.multi_agent(FakeClient(False), 102, "Analyze issue")
        self.assertFalse(report["executed"])
        self.assertEqual(report["status"], "not_executed")
        self.assertEqual(report["error"], "HOST_SAMPLING_UNSUPPORTED")
        self.assertEqual(report["backend"], "none")
        self.assertEqual(report["agents_completed"], 0)
        self.assertEqual(report["agent_ids"], [])
        self.assertEqual(report["agents"], [])
        self.assertEqual(life.list_agents()["count"], 0)

    async def test_concurrency_one_batches_requested_three(self):
        life.configuration(1)
        client = FakeClient()
        report = await life.multi_agent(client, 103, "Analyze issue")
        self.assertTrue(report["executed"])
        self.assertEqual(report["agents_completed"], 3)
        self.assertEqual(client.peak, 1)
        self.assertEqual(len(report["task_ids"]), 3)

    async def test_validation_reuses_original_guardrails(self):
        with self.assertRaises(ValueError):
            await life.multi_agent(FakeClient(), 104, "Analyze issue", roles=["unknown"])
        with self.assertRaises(ValueError):
            await life.multi_agent(FakeClient(), 105, "Analyze issue", max_tokens=2000)


if __name__ == "__main__":
    unittest.main()
