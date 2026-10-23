"""Сердце и назначения на синтетических данных: ни профилей пользователя, ни сети."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import brain_watch as watch
import brain_routes as routes


class Settings:
    def __init__(self):
        self.data = {"llm": {"active": "a", "routes": {}, "profiles": {
            "a": {"name": "Основной", "kind": "openai", "model": "model-a"},
            "b": {"name": "Другой", "kind": "openai", "model": "model-b"}}}, "tasks": {}, "brain_watch": {}}
    def get(self, *keys):
        v = self.data
        for key in keys:
            if not isinstance(v, dict):
                return None
            v = v.get(key)
        return copy.deepcopy(v)
    def update(self, data):
        def merge(a, b):
            for k, v in b.items():
                if isinstance(v, dict) and isinstance(a.get(k), dict):
                    merge(a[k], v)
                else:
                    a[k] = copy.deepcopy(v)
        merge(self.data, data)
    def snapshot(self):
        return copy.deepcopy(self.data)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings()

    def test_roles_are_separate_and_default_inherits_main(self):
        self.assertEqual(routes.profile(self.s, "diary")["id"], "a")
        routes.update(self.s, {"diary": "b", "tasks": "b"})
        self.assertEqual(routes.profile(self.s, "diary")["id"], "b")
        self.assertEqual(routes.profile(self.s, "tasks")["id"], "b")
        self.assertEqual(routes.profile(self.s, "meeting")["id"], "a")
        self.assertEqual(self.s.get("llm", "active"), "a")

    def test_deleted_route_never_falls_back(self):
        routes.update(self.s, {"meeting": "b", "tasks": "b"})
        del self.s.data["llm"]["profiles"]["b"]
        for role in ("meeting", "tasks"):
            p = routes.profile(self.s, role)
            self.assertTrue(p["_route_missing"])
            self.assertEqual(p["kind"], "unavailable")

    def test_explicit_clear_restores_inheritance(self):
        routes.update(self.s, {"meeting": "b"})
        routes.update(self.s, {"meeting": ""})
        self.assertEqual(routes.profile(self.s, "meeting")["id"], "a")

    def test_bad_assignments_do_not_modify_settings(self):
        before = self.s.snapshot()
        for value in ({"unknown": "a"}, {"diary": "missing"}, {"tasks": 4}, None):
            with self.assertRaises(ValueError):
                routes.update(self.s, value)
        self.assertEqual(self.s.snapshot(), before)

    def test_codex_assignment_needs_own_permissions(self):
        p = {"kind": "chatgpt_subscription", "subscription_transport": "codex", "model": "test",
             "subscription_profile_id": "synthetic", "subscription_export": True, "subscription_usage_reviewed": True}
        self.s.data["llm"]["profiles"]["c"] = p
        for role in routes.ROLES:
            with self.assertRaises(ValueError):
                routes.update(self.s, {role: "c"})
            p["subscription_" + role] = True
            routes.update(self.s, {role: "c"})
            self.assertEqual(routes.profile(self.s, role)["id"], "c")
        self.assertEqual(self.s.get("llm", "active"), "a")

    def test_current_callback_follows_binding_not_old_copy(self):
        p = routes.profile(self.s, "diary")
        routes.update(self.s, {"diary": "b"})
        self.assertEqual(p["id"], "a")
        self.assertEqual(p["_subscription_current"]()["id"], "b")

    def test_inactive_add_and_rename_do_not_probe_active_brain(self):
        before = self.s.get("llm")
        after = copy.deepcopy(before)
        after["profiles"]["c"] = {"kind": "openai", "model": "another"}
        after["profiles"]["a"]["name"] = "New name"
        self.assertFalse(routes.needs_probe(before, after))
        after["profiles"]["a"]["model"] = "changed"
        self.assertTrue(routes.needs_probe(before, after))

    def test_ordinary_deleted_route_refuses_before_http(self):
        # HTTP заменён до импорта: тест работает и без сторонних пакетов, сеть невозможна.
        with patch.dict(sys.modules, {"httpx": Mock()}):
            import llm
        with patch.object(llm.httpx, "Client") as client, patch.object(llm, "_stream_retry") as stream:
            with self.assertRaisesRegex(llm.LLMError, "Назначенный мозг удалён"):
                list(llm.stream_events({"kind": "unavailable", "_route_missing": True,
                                        "base_url": "http://synthetic.invalid/v1", "model": "synthetic"}, "", []))
            client.assert_not_called()
            stream.assert_not_called()


class WatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.clock = [1000.0]
        self.s = Settings()
        self.path = Path(temp.name) / "watch.sqlite3"
        self.ledger = watch.Ledger(self.path, self.s, lambda: self.clock[0])
        self.patch = patch.object(watch, "_ledger", self.ledger)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_status_empty_does_not_create_storage(self):
        self.assertEqual(self.ledger.snapshot()["runs"], [])
        self.assertFalse(self.path.exists())

    def test_completed_is_not_acceptance_or_inferred_tokens(self):
        with watch.call({"id": "a"}, "chat"):
            self.clock[0] += 4
        snapshot = self.ledger.snapshot()
        self.assertEqual(snapshot["runs"][0]["state"], "completed")
        self.assertEqual(snapshot["acceptance"], "unknown")
        self.assertEqual(snapshot["runs"][0]["elapsed_s"], 4)
        self.assertNotIn("tokens", snapshot)

    def test_failure_does_not_log_secret_error(self):
        secret = "sk-SYNTHETIC-DO-NOT-LOG"
        with self.assertRaises(RuntimeError), watch.call({"id": secret, "api_key": secret, "model": secret, "base_url": secret}):
            raise RuntimeError(secret)
        self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.assertEqual(self.ledger.snapshot()["runs"][0]["state"], "failed")

    def test_poll_does_not_refresh_signal_and_stale_is_not_failed(self):
        rid = self.ledger.start({"id": "a"}, "chat")
        self.clock[0] += 91
        for _ in range(3):
            run = self.ledger.snapshot()["runs"][0]
            self.assertEqual(run["state"], "no_fresh_signal")
            self.assertEqual(run["last_signal"], 1000)
            self.assertIsNone(run["ended"])
        self.ledger.signal(rid)
        self.assertEqual(self.ledger.snapshot()["runs"][0]["state"], "running")

    def test_restart_preserves_unknown_outcome(self):
        self.ledger.start({"id": "a"}, "chat")
        other = watch.Ledger(self.path)
        self.assertEqual(other.snapshot()["runs"][0]["state"], "outcome_unknown")

    def test_terminal_absorbs_late_signal_and_second_finish(self):
        rid = self.ledger.start({}, "chat")
        self.ledger.finish(rid, "failed")
        self.clock[0] += 100
        self.ledger.signal(rid); self.ledger.finish(rid, "completed")
        out = self.ledger.snapshot()
        self.assertEqual(out["runs"][0]["state"], "failed")
        self.assertEqual(len(out["events"]), 2)

    def test_nested_transport_is_not_counted_twice(self):
        @watch.observed_call
        def transport(profile, text, cancel):
            return "not logged"
        @watch.observed_stream
        def stream(profile, system, messages, cancel=None):
            yield "text", transport(profile, "private", cancel)
        self.assertEqual(list(stream({"id": "a"}, "private", [])), [("text", "not logged")])
        self.assertEqual(len(self.ledger.snapshot()["runs"]), 1)

    def test_generator_close_is_interruption(self):
        @watch.observed_stream
        def stream(p, s, m, cancel=None):
            yield "text", "one"
            yield "text", "two"
        gen = stream({}, "", [])
        next(gen); gen.close()
        self.assertEqual(self.ledger.snapshot()["runs"][0]["state"], "interrupted")

    def test_disabled_does_not_create_journal(self):
        self.s.data["brain_watch"]["journal"] = False
        with watch.call({}):
            pass
        self.assertFalse(self.path.exists())

    def test_task_only_allowlist_and_deduplicated(self):
        t = {"id": "task-a", "status": "running", "steps": 1, "goal": "secret goal", "error": "secret error"}
        self.ledger.task(t); self.ledger.task(t)
        t["status"] = "paused"; self.ledger.task(t)
        self.assertEqual(len(self.ledger.snapshot()["events"]), 2)
        self.assertNotIn(b"secret", self.path.read_bytes())

    def test_quota_event_contains_only_bounded_numbers_and_hashed_task(self):
        secret = "PRIVATE-SYNTHETIC-TASK"
        self.ledger.quota({"id": secret, "goal": secret}, 5, 10)
        event = self.ledger.snapshot()["events"][0]
        self.assertEqual(event["kind"], "task_quota_granted")
        self.assertEqual((event["amount"], event["limit"]), (5, 10))
        self.assertEqual(event["ref"], watch.tag(secret))
        self.assertNotIn(secret.encode(), self.path.read_bytes())
        before = self.path.read_bytes()
        self.ledger.quota({"id": secret}, 21, 10)
        self.assertEqual(self.path.read_bytes(), before)

    def test_threads_have_distinct_runs(self):
        def worker(n):
            with watch.call({"id": str(n)}, "chat"):
                pass
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for t in threads: t.start()
        for t in threads: t.join()
        rows = self.ledger.snapshot()["runs"]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(x["state"] == "completed" for x in rows))

    def test_storage_failure_does_not_retry_model_or_raise_secret(self):
        self.path.mkdir()
        calls = []
        @watch.observed_call
        def generate(p, text, cancel):
            calls.append(1); return "answer"
        self.assertEqual(generate({}, "private", None), "answer")
        self.assertEqual(calls, [1]); self.assertTrue(self.ledger.storage_error)

    def test_retention_is_bounded(self):
        with self.ledger.db() as db:
            db.executemany("INSERT INTO events(at,kind,ref,data) VALUES(?,?,?,?)", [(1, "call_start", "a", "{}") for _ in range(5005)])
            self.ledger.event(db, "call_completed", "a", {})
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 5000)

    def test_old_unfinished_runs_are_bounded_but_current_run_is_kept(self):
        with self.ledger.db() as db:
            db.executemany("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                           [(str(i), "p", "chat", "old-session", i, i, None, "running") for i in range(510)])
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", ("active", "p", "chat", self.ledger.session, -1, -1, None, "running"))
            self.ledger.event(db, "call_signal", "active", {})
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0], 501)
            self.assertEqual(db.execute("SELECT ended FROM runs WHERE id='active'").fetchone(), (None,))


if __name__ == "__main__":
    unittest.main()
