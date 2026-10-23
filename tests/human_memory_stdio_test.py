"""MCP transport contract with a synthetic service; no real memory or model."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from human_memory_stdio import dispatch


class StdioTest(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.health.return_value = {"db_exists": True, "read_only": True, "model_calls": 0}
        self.service.recall.return_value = {"status": "insufficient", "items": []}

    def call(self, method, **params):
        return dispatch({"jsonrpc": "2.0", "id": 3, "method": method, "params": params}, self.service)

    def test_handshake_and_readonly_tool_catalog_do_not_read_store(self):
        self.assertEqual(self.call("initialize")["result"]["protocolVersion"], "2025-06-18")
        tools = self.call("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"human_memory_health", "human_memory_recall"})
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
        self.service.health.assert_not_called()
        self.service.recall.assert_not_called()

    def test_health_and_exact_recall_envelope(self):
        health = self.call("tools/call", name="human_memory_health", arguments={})["result"]
        self.assertFalse(health["isError"])
        self.assertTrue(json.loads(health["content"][0]["text"])["read_only"])
        self.call("tools/call", name="human_memory_recall", arguments={"request": {"synthetic": True}})
        self.service.recall.assert_called_once_with({"synthetic": True})

    def test_unknown_action_and_raw_exception_are_not_exposed(self):
        self.service.recall.side_effect = ValueError("SYNTHETIC-SECRET")
        for name, args in (("write", {}), ("human_memory_health", {"extra": True}), ("human_memory_recall", {"request": {}})):
            reply = self.call("tools/call", name=name, arguments=args)
            self.assertTrue(reply["result"]["isError"])
            self.assertNotIn("SYNTHETIC-SECRET", json.dumps(reply))
        self.assertEqual(self.call("sampling/createMessage")["error"]["code"], -32601)
        self.assertIsNone(dispatch({"method": "notifications/initialized"}, self.service))


if __name__ == "__main__":
    unittest.main()
