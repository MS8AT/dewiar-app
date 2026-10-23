"""Квота задач Codex: только синтетические профили, без модели, сети и секретов."""
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

CORE = Path(__file__).resolve().parents[1] / "core"
sys.path.insert(0, str(CORE))
import subscription_context as context
import subscription_quota as quota


PROFILE = {"kind": "chatgpt_subscription", "subscription_transport": "codex",
           "model": "synthetic-model", "subscription_profile_id": "codex-" + "a" * 32,
           "subscription_export": True, "subscription_usage_reviewed": True,
           "subscription_tasks": True, "subscription_task_limit": 5}


class Task:
    def __init__(self, used=5, status="paused"):
        self.data = {"id": "synthetic-task", "status": status,
                     "subscription_binding": context.snapshot(dict(PROFILE, id="p")),
                     "subscription_attempts": used, "error": "исчерпан"}
        self.thread = None
        self.control_lock = threading.RLock()
        self.save = Mock()
        self.journal = Mock()


def fixture(task=None):
    profile = dict(PROFILE)
    settings = types.SimpleNamespace(get=lambda *keys: "p" if keys in (("tasks", "llm"), ("llm", "active")) else "")
    host = types.SimpleNamespace(llm_profile=lambda: profile, s=settings)
    manager = types.SimpleNamespace(host=host, _emit=Mock())
    return manager, task or Task(), profile


class QuotaTests(unittest.TestCase):
    def test_confirmed_grant_preserves_attempts_and_does_not_start_task(self):
        manager, task, _ = fixture()
        with patch.object(context, "confirm_local", return_value=True) as confirm, \
             patch("brain_watch.safe") as watch:
            result = quota.grant(manager, task, 5)
        confirm.assert_called_once()
        self.assertEqual(task.data["subscription_attempts"], 5)
        self.assertEqual(task.data["subscription_request_limit"], 10)
        self.assertEqual(task.data["subscription_quota_grants"], 5)
        self.assertEqual(task.data["status"], "paused")
        self.assertEqual(result["remaining"], 5)
        task.save.assert_called_once(); manager._emit.assert_called_once_with(task)
        watch.assert_called_once_with("quota", task.data, 5, 10)

    def test_refusal_and_invalid_states_never_mutate(self):
        manager, task, _ = fixture()
        before = dict(task.data)
        with patch.object(context, "confirm_local", return_value=False), self.assertRaises(context.ContextError):
            quota.grant(manager, task, 5)
        self.assertEqual(task.data, before); task.save.assert_not_called()
        for bad in (0, 21, True, "5"):
            with self.subTest(amount=bad), self.assertRaises(context.ContextError):
                quota.grant(manager, task, bad)

    def test_requires_exhausted_stopped_task_and_same_profile(self):
        for task in (Task(used=4), Task(status="running")):
            manager, task, _ = fixture(task)
            with self.subTest(task=task.data), self.assertRaises(context.ContextError), \
                 patch.object(context, "confirm_local", side_effect=AssertionError("must not confirm")):
                quota.grant(manager, task)
        manager, task, profile = fixture()
        profile["model"] = "changed"
        with self.assertRaises(context.ContextError), \
             patch.object(context, "confirm_local", side_effect=AssertionError("must not confirm")):
            quota.grant(manager, task)

    def test_confirmation_race_and_total_cap_are_closed(self):
        manager, task, _ = fixture()
        def changed(*_):
            task.data["status"] = "running"
            return True
        with patch.object(context, "confirm_local", side_effect=changed), self.assertRaises(context.ContextError):
            quota.grant(manager, task)
        self.assertNotIn("subscription_request_limit", task.data)

        manager, task, _ = fixture()
        manager.tasks = {task.data["id"]: task}
        def deleted(*_):
            manager.tasks.pop(task.data["id"])
            return True
        with patch.object(context, "confirm_local", side_effect=deleted), self.assertRaises(context.ContextError):
            quota.grant(manager, task)
        self.assertNotIn("subscription_request_limit", task.data)

        manager, task, _ = fixture(Task(used=100))
        task.data["subscription_request_limit"] = 100
        self.assertEqual(quota.status(task)["can_grant"], False)
        with self.assertRaises(context.ContextError):
            quota.grant(manager, task, 1)

    def test_commit_holds_task_lock_and_save_failure_rolls_back_memory(self):
        manager, task, _ = fixture()
        contender_entered = threading.Event()
        contender_done = threading.Event()
        def save_inside_lock():
            def contender():
                contender_entered.set()
                with task.control_lock:
                    contender_done.set()
            thread = threading.Thread(target=contender)
            thread.start(); self.assertTrue(contender_entered.wait(1))
            self.assertFalse(contender_done.wait(.05))
        task.save.side_effect = save_inside_lock
        with patch.object(context, "confirm_local", return_value=True):
            quota.grant(manager, task, 5)
        self.assertTrue(contender_done.wait(1))

        manager, task, _ = fixture()
        before = dict(task.data)
        def failed_with_message():
            task.data.setdefault("inbox", []).append({"text": "concurrent message"})
            raise OSError("synthetic disk failure")
        task.save.side_effect = failed_with_message
        with patch.object(context, "confirm_local", return_value=True), self.assertRaises(context.ContextError):
            quota.grant(manager, task, 5)
        self.assertEqual({key: task.data[key] for key in before}, before)
        self.assertEqual(task.data["inbox"], [{"text": "concurrent message"}])
        task.journal.assert_not_called()

    def test_text_journal_failure_keeps_saved_grant_without_second_json_write(self):
        manager, task, _ = fixture()
        task.journal.side_effect = OSError("synthetic journal failure")
        with patch.object(context, "confirm_local", return_value=True):
            result = quota.grant(manager, task, 5)
        self.assertEqual(result["limit"], 10)
        self.assertEqual(task.save.call_count, 1)

    def test_public_status_is_bounded_and_rejects_corruption(self):
        _, task, _ = fixture()
        self.assertEqual(quota.status(task)["grant_default"], 5)
        task.data["subscription_attempts"] = "private-corruption"
        self.assertEqual(quota.status(task), {"valid": False, "used": None, "limit": None,
                                             "remaining": None, "exhausted": False,
                                             "can_grant": False, "grant_default": None,
                                             "max_limit": 100})

    def test_historical_default_limit_works_but_invalid_current_profile_does_not(self):
        manager, task, profile = fixture()
        task.data["subscription_binding"]["subscription_task_limit"] = None
        profile.pop("subscription_task_limit")
        with patch.object(context, "confirm_local", return_value=True):
            self.assertEqual(quota.grant(manager, task, 5)["limit"], 10)

        manager, task, profile = fixture()
        task.data["subscription_binding"]["subscription_task_limit"] = None
        profile["subscription_task_limit"] = None
        with patch.object(context, "confirm_local", side_effect=AssertionError("must not confirm")), \
             self.assertRaises(context.ContextError):
            quota.grant(manager, task, 5)


if __name__ == "__main__":
    unittest.main()
