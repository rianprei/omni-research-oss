"""Offline tests for the external-agent runtime (no API key or model charges)."""
import os
import sys
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import agent_runtime as a

READY={"OMNI_AGENT_MODEL_KEY":"fake-test-key","OMNI_AGENT_MODEL":"mock-model",
       "OMNI_AGENT_BASE_URL":"https://api.example.org/v1"}

class RemoteAgentsTests(unittest.TestCase):
    def wait_result(self, task_id, timeout=4):
        start=time.monotonic()
        while time.monotonic()-start<timeout:
            result=a.task("get",task_id)
            if result.get("status") in ("completed","failed","cancelled"):
                return result
            time.sleep(0.01)
        self.fail("Task did not complete")

    def test_provider_unconfigured_starts_nothing(self):
        with patch.dict(os.environ, {"OMNI_AGENT_MODEL_KEY":"","OMNI_AGENT_MODEL":""}):
            answer=a.spawn_agent("Do a real task")
            self.assertFalse(answer["started"])
            self.assertEqual(answer["error"],"MODEL_PROVIDER_NOT_CONFIGURED")
            self.assertFalse(a.provider_status()["configured"])

    def test_model_secret_is_never_returned(self):
        with patch.dict(os.environ, READY):
            info=a.agent()
            self.assertTrue(info["backend"]["configured"])
            self.assertNotIn("fake-test-key",str(info))
            self.assertIn("researcher",info["roles"])

    def test_three_calls_really_run_concurrently(self):
        barrier=threading.Barrier(3,timeout=4)
        seen=[]
        def invoke(role,prompt,tokens):
            seen.append(threading.get_ident())
            barrier.wait()
            return "independent model response"
        with patch.dict(os.environ, READY),patch.object(a,"_invoke_provider",side_effect=invoke):
            resp=a.spawn_agent("Analyze independent evidence",role="critic",count=3)
            self.assertTrue(resp["started"])
            results=[self.wait_result(x) for x in resp["task_ids"]]
            self.assertTrue(all(x["status"]=="completed" for x in results))
            self.assertEqual(len(set(seen)),3)
            self.assertTrue(all(x["result"]=="independent model response" for x in results))

    def test_idempotency_and_key_mismatch(self):
        with patch.dict(os.environ, READY),patch.object(a,"_invoke_provider",return_value="ok"):
            key="dedup-"+str(time.monotonic())
            first=a.spawn_agent("Write one test",idempotency_key=key)
            second=a.spawn_agent("Write one test",idempotency_key=key)
            self.assertTrue(second["replayed"])
            self.assertEqual(first["task_ids"],second["task_ids"])
            with self.assertRaises(ValueError):
                a.spawn_agent("Different task now",idempotency_key=key)
            self.wait_result(first["task_ids"][0])

    def test_cancel_cannot_leak_output(self):
        entered=threading.Event()
        release=threading.Event()
        def slow(role,prompt,tokens):
            entered.set()
            release.wait(timeout=3)
            return "should not be exposed after cancellation"
        with patch.dict(os.environ, READY),patch.object(a,"_invoke_provider",side_effect=slow):
            resp=a.spawn_agent("Review some code")
            taskid=resp["task_ids"][0]
            self.assertTrue(entered.wait(timeout=3))
            pending=a.task("cancel",taskid)
            self.assertTrue(pending["cancellation_pending"])
            release.set()
            final=self.wait_result(taskid)
            self.assertEqual(final["status"],"cancelled")
            self.assertIsNone(final["result"])

    def test_input_validation(self):
        with patch.dict(os.environ, READY):
            for kw in [
                {"prompt":"hi"},{"prompt":"Research some topic","count":True},
                {"prompt":"Research some topic","count":5},
                {"prompt":"Research some topic","role":"unknown"},
                {"prompt":"Research some topic","max_output_tokens":0},
                {"prompt":"Research some topic","idempotency_key":"x"*101},
            ]:
                with self.subTest(kw=kw), self.assertRaises(ValueError):
                    a.spawn_agent(**kw)
            self.assertEqual(a.task("get","missing")["error"],"TASK_NOT_FOUND_OR_RESTARTED")
            with self.assertRaises(ValueError):
                a.task("delete","x")

    def test_api_configuration_validation(self):
        with patch.dict(os.environ,{**READY,"OMNI_AGENT_BASE_URL":"http://127.0.0.1:3000/v1"}):
            self.assertFalse(a.provider_status()["configured"])
        with patch.dict(os.environ,{**READY,"OMNI_AGENT_BASE_URL":"https://user:pass@api.example.org/v1"}):
            self.assertFalse(a.provider_status()["configured"])

if __name__=="__main__":
    unittest.main()
