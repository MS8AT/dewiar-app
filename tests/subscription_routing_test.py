"""Служебные маршруты, согласие и завершение задач на синтетических данных.

Не читаем аккаунты/память пользователя, не запускаем сервер и не вызываем модель.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from subscription_context_test import Host, Task, PROFILE, reply
import subscription_context as context
import subscription_adapter as adapter


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.egress = patch.dict(sys.modules, {"egress": types.SimpleNamespace(local_only=lambda: False)})
        self.egress.start(); self.addCleanup(self.egress.stop)

    def test_text_consumers_require_their_own_permission(self):
        purposes = {"skill_draft": "auxiliary", "exam": "auxiliary", "meeting": "meeting", "diary": "diary"}
        for purpose, cap in purposes.items():
            with self.subTest(purpose=purpose), patch.object(adapter, "generate", return_value="answer") as gen:
                with self.assertRaises(context.ContextError):
                    list(adapter.text_events(PROFILE, "system", [], purpose=purpose))
                gen.assert_not_called()
                profile = dict(PROFILE, **{"subscription_" + cap: True})
                self.assertEqual(list(adapter.text_events(profile, "system", [{"role": "user", "content": "sample"}], purpose=purpose)), [("text", "answer")])
                self.assertEqual(gen.call_count, 1)
                self.assertEqual(json.loads(gen.call_args.args[1])["purpose"], purpose)

    def test_unknown_consumers_tools_and_attachments_fail_closed(self):
        p = dict(PROFILE, subscription_auxiliary=True)
        with patch.object(adapter, "generate") as gen:
            for kwargs in ({}, {"purpose": "unknown"}, {"purpose": "exam", "tools": [{"name": "shell"}]}):
                with self.assertRaises(context.ContextError):
                    list(adapter.text_events(p, "s", [], **kwargs))
            for message in ({"role": "tool", "content": "secret"}, {"role": "user", "content": [{"type": "image"}]}):
                with self.assertRaises(context.ContextError):
                    list(adapter.text_events(p, "s", [message], purpose="exam"))
            gen.assert_not_called()

    def test_oversize_and_local_only_do_not_dispatch(self):
        p = dict(PROFILE, subscription_auxiliary=True)
        with patch.object(adapter, "generate") as gen:
            with self.assertRaises(context.ContextError):
                list(adapter.text_events(p, "x" * 31000, [], purpose="exam"))
            with patch.dict(sys.modules, {"egress": types.SimpleNamespace(local_only=lambda: True)}), self.assertRaises(context.ContextError):
                list(adapter.text_events(p, "s", [], purpose="exam"))
            gen.assert_not_called()

    def test_failure_has_one_attempt_and_no_fallback(self):
        p = dict(PROFILE, subscription_auxiliary=True)
        with patch.object(adapter, "generate", side_effect=adapter.SubscriptionError("outcome_unknown")) as gen:
            with self.assertRaises(adapter.SubscriptionError):
                list(adapter.text_events(p, "s", [], purpose="exam"))
            self.assertEqual(gen.call_count, 1)

    def test_revoked_scope_suppresses_completed_answer(self):
        current = dict(PROFILE, subscription_meeting=True)
        p = dict(current, _subscription_current=lambda: current)
        def generate(*a):
            current["subscription_meeting"] = False
            return "stale"
        with patch.object(adapter, "generate", side_effect=generate), self.assertRaises(context.ContextError):
            list(adapter.text_events(p, "s", [], purpose="meeting"))

    def test_llm_bridge_is_used_before_generic_http(self):
        with patch.dict(sys.modules, {"settings": types.SimpleNamespace(LLM_PRESETS={}), "httpx": types.SimpleNamespace()}):
            import llm
        p = dict(PROFILE, subscription_auxiliary=True)
        with patch.object(adapter, "generate", return_value="routed"), patch.object(llm, "_base", side_effect=AssertionError("generic HTTP")):
            self.assertEqual(list(llm.stream_chat(p, "s", [], purpose="exam")), ["routed"])
            with self.assertRaises(llm.LLMError):
                list(llm.stream_events(p, "s", []))

    def test_confirmation_nonce_and_replay(self):
        host = Host()
        host.pending_confirm = {"source": "subscription", "id": "nonce", "text": "synthetic", "answer": False, "event": threading.Event()}
        with patch.object(adapter, "invoke", side_effect=AssertionError("transport forbidden")):
            self.assertEqual(adapter.ui_command("confirm_get", {}, host)["data"], {"id": "nonce", "text": "synthetic"})
            self.assertFalse(adapter.ui_command("confirm_answer", {"id": "old", "ok": True}, host)["ok"])
            self.assertFalse(host.pending_confirm["event"].is_set())
            self.assertTrue(adapter.ui_command("confirm_answer", {"id": "nonce", "ok": False}, host)["ok"])
            adapter.ui_command("confirm_answer", {"id": "nonce", "ok": True}, host)
            self.assertFalse(host.pending_confirm["answer"])
            self.assertIsNone(adapter.ui_command("confirm_get", {}, host)["data"])

    def run_task(self, root, responses, **flags):
        host = Host(subscription_tasks=True, **flags)
        task = Task(Path(root)); manager = types.SimpleNamespace(host=host, _beat=Mock(), _emit=Mock())
        gen = Mock(side_effect=responses)
        with patch.object(context, "confirm_local", return_value=True):
            context.run_task(manager, task, gen)
        return task, gen, manager

    def test_task_review_and_lesson_share_persisted_budget(self):
        with tempfile.TemporaryDirectory() as root:
            task, gen, manager = self.run_task(root, [reply("finish", summary="result"), reply("finish", summary="no concerns"), "draft lesson"],
                                             subscription_task_review=True, subscription_task_learning=True, subscription_task_limit=3)
            self.assertEqual(task.data["status"], "done")
            self.assertEqual(task.data["subscription_attempts"], 3)
            self.assertEqual(gen.call_count, 3)
            self.assertFalse(task.data["verified"])
            self.assertEqual((task.dir / "урок Codex.md").read_text(encoding="utf-8"), "draft lesson")
            manager.host.workspace.remember.assert_not_called()

    def test_review_rejection_never_marks_done(self):
        with tempfile.TemporaryDirectory() as root:
            task, gen, _ = self.run_task(root, [reply("finish", summary="candidate"), reply("pause", question="missing evidence")], subscription_task_review=True)
            self.assertEqual(task.data["status"], "paused")
            self.assertFalse((task.dir / "итог.md").exists())
            self.assertEqual(task.data["subscription_attempts"], 2)

    def test_review_failure_is_counted_and_not_retried(self):
        with tempfile.TemporaryDirectory() as root:
            task, gen, _ = self.run_task(root, [reply("finish", summary="candidate"), adapter.SubscriptionError("outcome_unknown")], subscription_task_review=True)
            self.assertEqual(task.data["status"], "paused")
            self.assertEqual(task.data["subscription_attempts"], 2)
            self.assertEqual(gen.call_count, 2)

    def test_insufficient_budget_keeps_draft_without_more_requests(self):
        with tempfile.TemporaryDirectory() as root:
            task, gen, _ = self.run_task(root, [reply("finish", summary="candidate")], subscription_task_review=True, subscription_task_limit=1)
            self.assertEqual(task.data["status"], "paused")
            self.assertEqual(task.data["subscription_context"]["draft_summary"], "candidate")
            self.assertEqual(gen.call_count, 1)

    def test_task_waits_visibly_before_any_model_request(self):
        with tempfile.TemporaryDirectory() as root:
            host = Host(subscription_tasks=True); task = Task(Path(root))
            manager = types.SimpleNamespace(host=host, _beat=Mock(), _emit=Mock())
            gen = Mock()
            def confirm(*args):
                self.assertIn("Ожидаю подтверждения", task.data["activity"])
                gen.assert_not_called()
                return False
            with patch.object(context, "confirm_local", side_effect=confirm):
                context.run_task(manager, task, gen)
            self.assertEqual(task.data["status"], "paused")


if __name__ == "__main__":
    unittest.main()
