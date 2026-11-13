"""Offline lifecycle tests: no model or API requests are made."""
import unittest
from test_host_sampling_core import FakeClient
import host_agent_lifecycle as life


class HostAgentLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with life._lock:
            life._agents.clear()
            life._limit = 3
            life._active = 0

    async def test_spawn_followup_and_list(self):
        client = FakeClient()
        initial = await life.spawn_agents(
            client, 11, "Analyze independent evidence", ["researcher", "critic"]
        )
        self.assertTrue(initial["spawned"])
        self.assertEqual(initial["agents_completed"], 2)
        self.assertEqual(len(initial["agent_ids"]), 2)
        self.assertEqual(client.peak, 2)
        agent_id = initial["agent_ids"][0]
        reply = await life.send_message(client, 12, agent_id, "Find a counterexample")
        self.assertTrue(reply["sent"])
        self.assertEqual(reply["messages"], 4)
        self.assertIn("Analyze independent evidence", client.calls[-1]["messages"][0].content.text)
        waited = await life.wait_agent(agent_id)
        self.assertEqual(waited["result"], "Response from the mocked host model")
        self.assertEqual(life.list_agents()["count"], 2)
        self.assertNotIn("result", life.list_agents()["agents"][0])
        self.assertIn("result", life.list_agents(include_results=True)["agents"][0])

    async def test_concurrency_limit_runs_batches(self):
        life.configuration(1)
        client = FakeClient()
        result = await life.spawn_agents(client, 13, "Independent question")
        self.assertEqual(result["agents_completed"], 3)
        self.assertEqual(client.peak, 1)
        self.assertEqual(len(result["task_ids"]), 3)
        self.assertEqual(life.configuration()["max_concurrent_subagents"], 1)

    async def test_no_client_sampling_creates_no_agents(self):
        client = FakeClient(False)
        result = await life.spawn_agents(client, 14, "Independent question")
        self.assertEqual(result["error"], "HOST_SAMPLING_UNSUPPORTED")
        self.assertEqual(client.calls, [])
        self.assertEqual(life.list_agents()["count"], 0)

    async def test_invalid_arguments_and_missing_id(self):
        with self.assertRaises(ValueError):
            life.configuration(True)
        with self.assertRaises(ValueError):
            life.configuration(4)
        with self.assertRaises(ValueError):
            await life.wait_agent("invalid")
        with self.assertRaises(ValueError):
            await life.send_message(FakeClient(), 15, "0" * 32, "no")
        self.assertEqual(
            (await life.wait_agent("0" * 32))["error"],
            "AGENT_NOT_FOUND_OR_RESTARTED"
        )


if __name__ == "__main__":
    unittest.main()
