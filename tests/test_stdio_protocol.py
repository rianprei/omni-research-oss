"""Contract tests for the local stdio MCP and its JSON-RPC boundary."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "server"))
import main as mcp_main


class StdioProtocolTests(unittest.TestCase):
    def test_initialize_and_tool_inventory(self):
        initialized = mcp_main.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        })
        self.assertEqual(initialized["protocolVersion"], "2025-11-25")
        listed = mcp_main.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {item["name"] for item in listed["tools"]}
        self.assertEqual(len(names), 9)
        self.assertIn("omni_research-deep", names)
        self.assertIn("read_document", names)
        self.assertIn("memory_save", names)

    def test_tool_call_rejects_missing_wrong_and_extra_arguments(self):
        cases = [
            {"name": "fetch_source", "arguments": {}},
            {"name": "fetch_source", "arguments": {"url": 7}},
            {"name": "fetch_source", "arguments": {"url": "https://example.org", "extra": True}},
            {"name": "omni_research-deep", "arguments": {"query": "test", "limit": True}},
            {"name": "omni_research-deep", "arguments": {"query": "test", "mode": "bad"}},
        ]
        for params in cases:
            with self.subTest(params=params):
                result = mcp_main.handle({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": params,
                })
                self.assertTrue(result["isError"])

    def test_unknown_tool_is_a_tool_error(self):
        result = mcp_main.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "missing", "arguments": {}},
        })
        self.assertTrue(result["isError"])
        self.assertIn("Tool not found", result["content"][0]["text"])

    def test_unknown_rpc_method_returns_method_not_found(self):
        with self.assertRaises(mcp_main.JsonRpcError) as raised:
            mcp_main.handle({"jsonrpc": "2.0", "id": 5, "method": "missing/method"})
        self.assertEqual(raised.exception.code, -32601)

    def test_stdio_returns_parse_and_request_errors_without_leaking_tracebacks(self):
        payload = (
            b"{not-json\n"
            b"[]\n"
            b'{"jsonrpc":"2.0","id":9,"method":"missing/method"}\n'
            b'{"jsonrpc":"2.0","id":10,"method":"tools/list"}\n'
        )
        result = subprocess.run(
            [sys.executable, str(REPOSITORY_ROOT / "server" / "main.py")],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([item["error"]["code"] for item in responses[:3]],
                         [-32700, -32600, -32601])
        self.assertEqual(responses[2]["id"], 9)
        self.assertEqual(responses[3]["id"], 10)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
