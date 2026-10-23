"""Граница Human Memory: только точный scope, read-only MCP и безопасный пакет."""
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import human_memory_contour as memory
sys.modules.setdefault("engine_base", types.ModuleType("engine_base"))
from engine_commands import CommandsMixin

SECRET = "SYNTHETIC-SECRET-MUST-NOT-LEAK"


class MCP:
    def __init__(self, payload=None, available=True, cancel=None):
        self.payload, self.available, self.cancel, self.calls = payload, available, cancel, []

    def has(self, name):
        self.calls.append(("has", name))
        return self.available and name == memory.TOOL

    def status(self):
        return {"human_memory": {"status": "ok", "error": SECRET}}

    def call(self, name, args):
        self.calls.append(("call", name, args))
        if self.cancel is not None:
            self.cancel.set()
        return json.dumps(self.payload, ensure_ascii=False)


class HumanMemoryTests(unittest.TestCase):
    def scope(self):
        return {"session_id": "session-42", "object_key": "person/main", "keys": ["criteria", "decision"],
                "since": "2026-10-01T00:00:00+03:00", "as_of": "2026-10-23T14:00:00+03:00"}

    def task(self):
        return types.SimpleNamespace(id="task-42", data={})

    def packet(self, status="ready", missing=None):
        return {"packet": {"status": status, "covered": ["criteria", "decision"], "missing": missing or [],
                           "items": [{"id": "phrase:42", "quote": "Synthetic quoted evidence",
                                      "quote_sha256": "a" * 64, "source": "source:42",
                                      "source_at": "2026-10-20T10:00:00+03:00", "kind": "reported_fact",
                                      "message_provenance": {"metadata": {"secret": SECRET}}}]}}

    def test_configure_requires_exact_bounded_scope_and_hides_identifiers(self):
        task = self.task()
        memory.configure(task, self.scope())
        self.assertRegex(task.data["human_memory_revision"], r"^[a-f0-9]{32}$")
        public = memory.public_scope(task)
        self.assertTrue(public["enabled"])
        self.assertEqual(public["keys"], 2)
        self.assertNotIn("session-42", json.dumps(public))
        self.assertNotIn("person/main", json.dumps(public))
        for bad in (self.scope() | {"extra": "x"}, self.scope() | {"keys": []},
                    self.scope() | {"keys": ["same", "same"]},
                    self.scope() | {"since": "2026-10-01"},
                    self.scope() | {"since": self.scope()["as_of"]}):
            with self.subTest(bad=bad), self.assertRaises(memory.HumanMemoryError):
                memory.configure(self.task(), bad)

    def test_recall_uses_only_named_readonly_tool_and_returns_citable_allowlist(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        mcp = MCP(self.packet())
        result = memory.recall(types.SimpleNamespace(mcp=mcp), task, cancel)
        self.assertEqual(result["items"][0]["id"], "phrase:42")
        self.assertEqual(result["items"][0]["quote_sha256"], "a" * 64)
        self.assertFalse(result["items"][0]["authority"])
        self.assertNotIn(SECRET, json.dumps(result))
        call = next(row for row in mcp.calls if row[0] == "call")
        self.assertEqual(call[1], memory.TOOL)
        request = call[2]["request"]
        self.assertEqual(request["task_id"], task.id)
        self.assertEqual(request["revision"], task.data["human_memory_revision"])
        self.assertEqual(request["budget_bytes"], 4500)
        self.assertFalse(request["include_unknown_dates"])

    def test_missing_connector_or_partial_packet_stops_without_fallback(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        unavailable = MCP(self.packet(), available=False)
        with self.assertRaisesRegex(memory.HumanMemoryError, "fallback"):
            memory.recall(types.SimpleNamespace(mcp=unavailable), task, cancel)
        self.assertFalse(any(row[0] == "call" for row in unavailable.calls))
        with self.assertRaisesRegex(memory.HumanMemoryError, "недостаточно"):
            memory.recall(types.SimpleNamespace(mcp=MCP(self.packet("partial", ["decision"]))), task, cancel)

    def test_cancel_after_mcp_discards_packet(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        with self.assertRaisesRegex(memory.HumanMemoryError, "остановлена после чтения"):
            memory.recall(types.SimpleNamespace(mcp=MCP(self.packet(), cancel=cancel)), task, cancel)

    def test_status_never_exposes_connector_error(self):
        out = memory.status(types.SimpleNamespace(mcp=MCP(self.packet())))
        self.assertEqual(out["state"], "ready")
        self.assertNotIn(SECRET, json.dumps(out))

    def test_task_create_requires_profile_grant_before_creating_anything(self):
        tasks = types.SimpleNamespace(create=Mock())
        host = types.SimpleNamespace(tasks=tasks)
        with patch("subscription_context.task_profile", return_value={"kind": "chatgpt_subscription"}), \
             self.assertRaisesRegex(ValueError, "не разрешена"):
            CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope()})
        tasks.create.assert_not_called()

    def test_task_create_configures_before_start(self):
        task = self.task()
        task.save, task.public = Mock(), Mock(return_value={"id": task.id})
        calls = []
        tasks = types.SimpleNamespace(
            create=Mock(side_effect=lambda *a, **kw: calls.append(("create", kw.get("start"))) or task),
            start=Mock(side_effect=lambda tid: calls.append(("start", tid))),
            delete=Mock(), _emit=Mock())
        host = types.SimpleNamespace(tasks=tasks)
        profile = {"kind": "chatgpt_subscription", "subscription_transport": "codex",
                   "subscription_human_memory": True}
        with patch("subscription_context.task_profile", return_value=profile):
            out = CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope()})
        self.assertEqual(out, {"id": task.id})
        self.assertEqual(calls, [("create", False), ("start", task.id)])
        self.assertIn("human_memory_scope", task.data)
        tasks.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
