"""Граница Human Memory: только точный scope, read-only MCP и безопасный пакет."""
import json
import hashlib
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

    def packet(self, task, status="ready", missing=None):
        quote = "Synthetic quoted evidence"
        request = {"task_id": str(task.id), "revision": task.data["human_memory_revision"],
                   **task.data["human_memory_scope"], "budget_bytes": 4500, "recent_days": 7,
                   "max_rounds": 2, "page_size": 16, "include_unknown_dates": False, "cursors": {}}
        return {"packet": {"schema": memory.MEMORY_SCHEMA, "task_id": request["task_id"],
                           "revision": request["revision"], "scope": memory._scope_hash(request),
                           "object": request["object_key"], "as_of": memory._utc(request["as_of"]),
                           "status": status, "covered": ["criteria", "decision"], "missing": missing or [],
                           "items": [{"id": "phrase:42", "quote": quote,
                                      "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(), "source": "source:42",
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
                    self.scope() | {"keys": ["same", "same"]}, self.scope() | {"keys": [{}]},
                    self.scope() | {"keys": ["SAME", "same"]},
                    self.scope() | {"since": "2026-10-01"},
                    self.scope() | {"since": self.scope()["as_of"]}):
            with self.subTest(bad=bad), self.assertRaises(memory.HumanMemoryError):
                memory.configure(self.task(), bad)

    def test_recall_uses_only_named_readonly_tool_and_returns_citable_allowlist(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        mcp = MCP(self.packet(task))
        result = memory.recall(types.SimpleNamespace(mcp=mcp), task, cancel)
        self.assertEqual(result["items"][0]["id"], "phrase:42")
        self.assertEqual(result["items"][0]["quote_sha256"], hashlib.sha256(b"Synthetic quoted evidence").hexdigest())
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
        unavailable = MCP(self.packet(task), available=False)
        with self.assertRaisesRegex(memory.HumanMemoryError, "fallback"):
            memory.recall(types.SimpleNamespace(mcp=unavailable), task, cancel)
        self.assertFalse(any(row[0] == "call" for row in unavailable.calls))
        with self.assertRaisesRegex(memory.HumanMemoryError, "недостаточно"):
            memory.recall(types.SimpleNamespace(mcp=MCP(self.packet(task, "partial", ["decision"]))), task, cancel)

    def test_foreign_scope_bad_quote_hash_and_empty_ready_packet_are_refused(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        packets = []
        foreign = self.packet(task); foreign["packet"]["revision"] = "foreign"
        packets.append(foreign)
        bad_hash = self.packet(task); bad_hash["packet"]["items"][0]["quote_sha256"] = "b" * 64
        packets.append(bad_hash)
        empty = self.packet(task); empty["packet"]["items"] = []; empty["packet"]["covered"] = []
        packets.append(empty)
        for packet in packets:
            with self.subTest(packet=packet["packet"].get("revision")), self.assertRaises(memory.HumanMemoryError):
                memory.recall(types.SimpleNamespace(mcp=MCP(packet)), task, cancel)

    def test_cancel_after_mcp_discards_packet(self):
        task, cancel = self.task(), threading.Event()
        memory.configure(task, self.scope())
        with self.assertRaisesRegex(memory.HumanMemoryError, "остановлена после чтения"):
            memory.recall(types.SimpleNamespace(mcp=MCP(self.packet(task), cancel=cancel)), task, cancel)

    def test_status_never_exposes_connector_error(self):
        out = memory.status(types.SimpleNamespace(mcp=MCP({})))
        self.assertEqual(out["state"], "ready")
        self.assertNotIn(SECRET, json.dumps(out))

    def test_task_create_requires_profile_grant_before_creating_anything(self):
        tasks = types.SimpleNamespace(create=Mock())
        host = types.SimpleNamespace(tasks=tasks)
        with patch("subscription_context.task_profile", return_value={"kind": "chatgpt_subscription"}), \
             self.assertRaisesRegex(ValueError, "не разрешена"):
            CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope()})
        tasks.create.assert_not_called()

    def test_task_create_validates_scope_before_creating_anything(self):
        tasks = types.SimpleNamespace(create=Mock())
        host = types.SimpleNamespace(tasks=tasks)
        profile = {"kind": "chatgpt_subscription", "subscription_transport": "codex",
                   "subscription_human_memory": True}
        with patch("subscription_context.task_profile", return_value=profile), self.assertRaises(ValueError):
            CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope() | {"keys": [{}]}})
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
        self.assertTrue(task.data["human_memory_enabled"])
        tasks.delete.assert_not_called()

    def test_task_create_rolls_back_save_or_emit_failure_without_secret(self):
        for failing in ("save", "emit"):
            with self.subTest(failing=failing):
                task = self.task()
                task.public = Mock(return_value={"id": task.id})
                task.save = Mock(side_effect=RuntimeError(SECRET) if failing == "save" else None)
                tasks = types.SimpleNamespace(create=Mock(return_value=task), start=Mock(), delete=Mock(),
                                              _emit=Mock(side_effect=RuntimeError(SECRET) if failing == "emit" else None))
                host = types.SimpleNamespace(tasks=tasks)
                profile = {"kind": "chatgpt_subscription", "subscription_transport": "codex",
                           "subscription_human_memory": True}
                with patch("subscription_context.task_profile", return_value=profile), self.assertRaises(ValueError) as caught:
                    CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope()})
                self.assertNotIn(SECRET, str(caught.exception))
                tasks.delete.assert_called_once_with(task.id)
                tasks.start.assert_not_called()

    def test_task_create_reports_incomplete_rollback_without_secret(self):
        task = self.task(); task.public = Mock(); task.save = Mock(side_effect=RuntimeError(SECRET))
        tasks = types.SimpleNamespace(create=Mock(return_value=task), start=Mock(), _emit=Mock(),
                                      discard_created=Mock(return_value=False))
        host = types.SimpleNamespace(tasks=tasks)
        profile = {"kind": "chatgpt_subscription", "subscription_transport": "codex",
                   "subscription_human_memory": True}
        with patch("subscription_context.task_profile", return_value=profile), self.assertRaises(ValueError) as caught:
            CommandsMixin.command(host, "task_create", {"goal": "g", "human_memory": self.scope()})
        self.assertIn("не завершён", str(caught.exception)); self.assertNotIn(SECRET, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
