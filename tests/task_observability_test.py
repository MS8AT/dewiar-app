"""Read-only API задачи: синтетика, без файлов пользователя, сети и модели."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import brain_watch
import task_observability as api

SECRET = "SYNTHETIC-SECRET-DO-NOT-RETURN"


class Task:
    def __init__(self, tid, state="running", parent=None, binding=True):
        self.id, self.status = tid, state
        self.data = {"id": tid, "status": state, "steps": 2, "subscription_attempts": 3}
        if parent:
            self.data["parent"] = parent
        if binding:
            self.data["subscription_binding"] = {"id": SECRET, "subscription_task_limit": 5,
                                                  "api_key": SECRET, "model": SECRET}


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.parent = Task("parent-private")
        self.child = Task("child-private", "paused", self.parent.id)
        self.host = types.SimpleNamespace(tasks=types.SimpleNamespace(
            tasks={self.parent.id: self.parent, self.child.id: self.child}))
        self.snapshot = {"observed_at": 10, "journal": True, "storage_error": False,
                         "events": [
                             {"seq": 1, "at": 8, "kind": "task_state", "ref": brain_watch.tag(self.parent.id),
                              "state": "running", "steps": 2, "goal": SECRET},
                             {"seq": 2, "at": 9, "kind": "task_action", "ref": brain_watch.tag(self.parent.id),
                              "action": "plan", "attempt": 3, "state": "accepted", "response": SECRET},
                             {"seq": 3, "at": 9, "kind": "task_action", "ref": brain_watch.tag(self.child.id),
                              "action": "finish", "attempt": 1, "state": "done"}]}

    def test_safe_projection_filters_task_and_hashes_ids(self):
        with patch.object(brain_watch, "status", return_value=self.snapshot), \
             patch("subscription_quota.status", return_value={"valid": True, "used": 3, "limit": 5,
                                                               "remaining": 2, "exhausted": False,
                                                               "can_grant": False, "grant_default": 5,
                                                               "max_limit": 100}):
            out = api.view(self.host, self.parent)
        text = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(self.parent.id, text)
        self.assertNotIn(self.child.id, text)
        self.assertEqual(out["api"], "task_observe")
        self.assertTrue(out["read_only"])
        self.assertEqual(len(out["events"]), 2)
        self.assertEqual(out["events"][1]["action"], "plan")
        self.assertEqual(out["children"][0]["state"], "paused")
        self.assertEqual(out["codex"]["quota"]["remaining"], 2)
        self.assertEqual(out["observer"]["state"], "observing")

    def test_bad_observer_data_is_unknown_not_green(self):
        bad = {"observed_at": float("inf"), "journal": SECRET, "storage_error": SECRET,
               "events": [{"seq": SECRET, "at": SECRET, "kind": "task_action",
                            "ref": brain_watch.tag(self.parent.id), "action": SECRET}]}
        with patch.object(brain_watch, "status", return_value=bad), \
             patch("subscription_quota.status", side_effect=RuntimeError(SECRET)):
            out = api.view(self.host, self.parent)
        self.assertIsNone(out["observer"]["observed_at"])
        self.assertIsNone(out["observer"]["journal_enabled"])
        self.assertTrue(out["observer"]["storage_error"])
        self.assertEqual(out["observer"]["state"], "unavailable")
        self.assertEqual(out["codex"]["quota"]["state"], "unavailable")
        self.assertEqual(out["events"], [])
        self.assertEqual(out["invalid_records"], 1)

    def test_children_and_events_are_filtered_before_limit(self):
        tasks = {f"noise-{i}": Task(f"noise-{i}", binding=False) for i in range(120)}
        late_child = Task("late-child", "paused", self.parent.id, binding=False)
        tasks.update({self.parent.id: self.parent, late_child.id: late_child})
        self.host.tasks.tasks = tasks
        events = [{"seq": i + 1, "at": i + 1, "kind": "task_state", "ref": brain_watch.tag(f"noise-{i}"),
                   "state": "running", "steps": 0} for i in range(120)]
        events.append({"seq": 121, "at": 121, "kind": "task_state", "ref": brain_watch.tag(self.parent.id),
                       "state": "running", "steps": 2})
        snapshot = {"observed_at": 122, "journal": True, "storage_error": False, "events": events}
        with patch.object(brain_watch, "status", return_value=snapshot), \
             patch("subscription_quota.status", return_value={"valid": True}):
            out = api.view(self.host, self.parent)
        self.assertEqual(1, len(out["children"]))
        self.assertEqual(brain_watch.tag(late_child.id), out["children"][0]["ref"])
        self.assertEqual(1, len(out["events"]))
        self.assertEqual(121, out["events"][0]["seq"])


if __name__ == "__main__":
    unittest.main()
