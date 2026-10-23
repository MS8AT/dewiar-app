"""Диагностическое API на синтетических снимках: без сети, моделей и пользовательских файлов."""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import diagnostics as diag

SECRET = "SYNTHETIC-private-token-not-to-be-returned"
CALL = "a" * 32
PROFILE = "b" * 16


class Settings:
    def __init__(self):
        self.data = {"llm": {"active": "main-secret-id", "routes": {"diary": "codex-secret-id"}, "profiles": {
            "main-secret-id": {"name": SECRET, "api_key": SECRET, "model": SECRET, "base_url": SECRET, "kind": "openai"},
            "codex-secret-id": {"kind": "chatgpt_subscription", "name": SECRET, "model": SECRET,
                                "subscription_profile_id": SECRET, "subscription_tasks": True, "subscription_diary": True}}},
                     "tasks": {"llm": "codex-secret-id"}}
    def get(self, *keys):
        result = self.data
        for key in keys:
            result = result.get(key) if isinstance(result, dict) else None
        return copy.deepcopy(result)


def snapshot():
    return {"observed_at": 1000, "storage_error": False, "journal": True, "coverage": diag.COVERAGE,
            "runs": [], "events": [], "tasks": [], "profiles": {PROFILE: SECRET}, "token": SECRET}


def run(state, elapsed=2, **extra):
    terminal = state in diag.TERMINAL
    return dict({"state": state, "started": 100, "ended": 100 + elapsed if terminal else None,
                 "elapsed_s": elapsed, "prompt": SECRET, "api_key": SECRET}, **extra)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings()
        self.host = types.SimpleNamespace(s=self.s, probe=Mock(side_effect=AssertionError("must not probe")))
        self.data = snapshot()
        self.mock = patch.object(diag.brain_watch, "status", side_effect=lambda host: copy.deepcopy(self.data))
        self.status = self.mock.start(); self.addCleanup(self.mock.stop)

    def call(self, action):
        result = diag.dispatch(self.host, action, {})
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("main-secret-id", text)
        self.assertNotIn("codex-secret-id", text)
        return result

    def test_unknown_action_and_args_refuse_before_observation(self):
        for action in (SECRET, None, [], {}, 1):
            with self.assertRaisesRegex(ValueError, "Неизвестное действие"):
                diag.dispatch(self.host, action, {})
        for args in ({"token": SECRET}, [], "", 0, False):
            with self.assertRaisesRegex(ValueError, "не принимает параметры"):
                diag.dispatch(self.host, "status", args)
        self.status.assert_not_called()

    def test_status_reports_counts_not_tasks_or_profiles(self):
        self.data["tasks"] = [{"state": "running", "ref": SECRET, "goal": SECRET}, {"state": "done", "text": SECRET}]
        result = self.call("status")
        self.assertEqual(result["schema"], 1)
        self.assertEqual(result["fork"], "MS8AT8DWiar")
        self.assertEqual(result["observer"]["state"], "observing")
        self.assertEqual(result["tasks"]["counts"]["running"], 1)
        self.assertEqual(result["tasks"]["sampled"], 2)
        self.assertEqual(result["model_access"], "not_checked")
        self.assertNotIn("profiles", result)

    def test_brains_hash_ids_and_only_boolean_permissions(self):
        result = self.call("brains")
        self.status.assert_not_called()
        a, b = result["profiles"]
        self.assertEqual(a["ref"], diag.brain_watch.tag("main-secret-id"))
        self.assertTrue(a["active"])
        self.assertTrue(a["configured_model"])
        self.assertIn("chat", a["roles"])
        self.assertIsNone(a["subscription_permissions"])
        self.assertEqual(b["roles"], ["tasks", "diary"])
        self.assertTrue(b["subscription_permissions"]["tasks"])
        self.assertFalse(b["subscription_permissions"]["export"])

    def test_non_boolean_permission_does_not_grant(self):
        p = self.s.data["llm"]["profiles"]["codex-secret-id"]
        p["subscription_export"] = SECRET
        p["subscription_memory_write"] = 1
        result = self.call("brains")["profiles"][1]["subscription_permissions"]
        self.assertFalse(result["export"])
        self.assertFalse(result["memory_write"])

    def test_deleted_binding_is_missing_not_active_fallback(self):
        self.s.data["llm"]["routes"]["meeting"] = SECRET
        result = self.call("brains")["bindings"]["meeting"]
        self.assertEqual(result["state"], "missing")
        self.assertEqual(result["ref"], diag.brain_watch.tag(SECRET))
        self.assertEqual(result["selection"], "explicit")

    def test_invalid_settings_do_not_escape_or_raise_raw_errors(self):
        self.s.data["llm"]["active"] = {"key": SECRET}
        self.s.data["llm"]["routes"] = SECRET
        self.s.data["llm"]["profiles"]["bad"] = SECRET
        result = self.call("brains")
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["bindings"]["chat"]["state"], "invalid")
        self.assertGreater(result["invalid_records"], 0)

    def test_unknown_provider_kind_is_not_echoed(self):
        self.s.data["llm"]["profiles"]["main-secret-id"]["kind"] = SECRET
        self.assertEqual(self.call("brains")["profiles"][0]["kind"], "unknown")

    def test_settings_failure_is_unknown_and_does_not_echo_error(self):
        self.host.s = types.SimpleNamespace(get=Mock(side_effect=RuntimeError(SECRET)))
        result = self.call("brains")
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["profiles"], [])

    def test_journal_projects_fields_and_rejects_arbitrary_strings(self):
        self.data["events"] = [
            {"seq": 1, "at": 900, "kind": "call_start", "ref": CALL, "profile": PROFILE, "role": "chat", "text": SECRET},
            {"seq": 2, "at": 901, "kind": "task_state", "ref": PROFILE, "state": "running", "steps": 5, "error": SECRET},
            {"seq": 3, "at": 902, "kind": SECRET, "ref": SECRET},
            {"seq": 4, "at": 903, "kind": "call_completed", "ref": SECRET},
        ]
        result = self.call("journal")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["invalid_records"], 2)
        self.assertEqual(result["events"][1]["steps"], 5)
        self.assertNotIn("profiles", result)

    def test_journal_nested_allowlist_values(self):
        self.data["events"] = [{"seq": 1, "at": 1, "kind": "call_start", "ref": CALL,
                                "profile": SECRET, "role": {"secret": SECRET}},
                               {"seq": 2, "at": 2, "kind": "task_state", "ref": PROFILE, "state": SECRET, "steps": SECRET}]
        events = self.call("journal")["events"]
        self.assertIsNone(events[0]["profile"])
        self.assertEqual(events[0]["role"], "unknown")
        self.assertEqual(events[1]["state"], "unknown")
        self.assertIsNone(events[1]["steps"])

    def test_journal_projects_quota_event_without_task_content(self):
        self.data["events"] = [{"seq": 1, "at": 1, "kind": "task_quota_granted", "ref": PROFILE,
                                "amount": 5, "limit": 10, "goal": SECRET}]
        event = self.call("journal")["events"][0]
        self.assertEqual(event["kind"], "task_quota_granted")
        self.assertEqual((event["amount"], event["limit"]), (5, 10))
        self.assertNotIn("goal", event)

    def test_journal_projects_task_action_without_arguments_or_response(self):
        self.data["events"] = [{"seq": 1, "at": 1, "kind": "task_action", "ref": PROFILE,
                                "action": "project_read", "attempt": 3, "state": "accepted",
                                "arguments": SECRET, "response": SECRET}]
        event = self.call("journal")["events"][0]
        self.assertEqual((event["action"], event["attempt"], event["state"]),
                         ("project_read", 3, "accepted"))
        self.assertNotIn("arguments", event)
        self.assertNotIn("response", event)

    def test_zero_calls_is_not_hundred_percent_success(self):
        result = self.call("sli")
        self.assertEqual(result["state"], "no_data")
        self.assertIsNone(result["success_ratio"])
        self.assertEqual(result["success_denominator"], 0)
        self.assertIsNone(result["latency_s"]["p95"])
        self.assertEqual(result["availability"], "not_measured")
        self.assertEqual(result["sla"], "not_evaluated")

    def test_success_ratio_excludes_cancelled_unknown_and_running(self):
        self.data["runs"] = [run("completed"), run("failed"), run("interrupted"),
                             run("outcome_unknown"), run("no_fresh_signal"), run("running")]
        result = self.call("sli")
        self.assertEqual(result["success_ratio"], 0.5)
        self.assertEqual(result["success_denominator"], 2)
        self.assertEqual(result["counts"]["unknown"], 2)
        self.assertEqual(result["counts"]["interrupted"], 1)
        self.assertEqual(result["counts"]["running"], 1)
        self.assertEqual(result["state"], "partial")

    def test_nearest_rank_p50_p95_only_terminal_durations(self):
        self.data["runs"] = [run("completed", n) for n in range(1, 21)] + [run("running", 999)]
        result = self.call("sli")
        self.assertEqual(result["latency_s"]["sampled"], 20)
        self.assertEqual(result["latency_s"]["p50"], 10)
        self.assertEqual(result["latency_s"]["p95"], 19)

    def test_invalid_duration_cannot_poison_quantiles(self):
        self.data["runs"] = [run("completed", 2), run("completed", elapsed_s=float("nan")),
                             run("failed", elapsed_s=-1), run("failed", elapsed_s=True),
                             run("interrupted", elapsed_s=diag.MAX_LATENCY_S + 1), run("failed", elapsed_s=10)]
        result = self.call("sli")
        self.assertEqual(result["latency_s"]["sampled"], 1)
        self.assertEqual(result["latency_s"]["invalid_records"], 5)
        self.assertEqual(result["latency_s"]["p95"], 2)

    def test_invalid_terminal_times_are_unknown_not_success(self):
        self.data["runs"] = [run("completed", ended=None), run("completed", started=101, ended=100), run("failed", ended=True)]
        result = self.call("sli")
        self.assertEqual(result["counts"]["unknown"], 3)
        self.assertIsNone(result["success_ratio"])

    def test_storage_failure_never_reports_success_or_latency(self):
        self.data["runs"] = [run("completed")]
        self.data["storage_error"] = True
        result = self.call("sli")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["observer"]["state"], "unavailable")
        self.assertIsNone(result["success_ratio"])
        self.assertIsNone(result["latency_s"]["p50"])

    def test_observer_error_is_redacted_and_unknown(self):
        self.status.side_effect = RuntimeError(SECRET)
        result = self.call("status")
        self.assertEqual(result["observer"]["state"], "unavailable")
        self.assertTrue(result["observer"]["storage_error"])

    def test_disabled_journal_is_paused_not_healthy(self):
        self.data["journal"] = False
        result = self.call("status")
        self.assertEqual(result["observer"]["state"], "paused")
        self.assertEqual(self.call("sli")["state"], "partial")

    def test_malformed_snapshot_fields_are_bounded_and_json_safe(self):
        self.data.update(observed_at=float("inf"), journal=SECRET, coverage=SECRET,
                         runs=[None, {"state": [SECRET]}], tasks=[None, {"state": [SECRET]}], events=[None])
        for action in ("status", "journal", "sli"):
            result = self.call(action)
            self.assertEqual(result["observer"]["state"], "partial")

    def test_samples_are_limited_and_not_claimed_as_full_history(self):
        self.data["runs"] = [run("completed")] * 101
        self.data["tasks"] = [{"state": "running"}] * 101
        self.data["events"] = [{"seq": 1, "at": 1, "kind": "call_signal", "ref": CALL}] * 101
        self.assertEqual(self.call("sli")["sampled"], 100)
        self.assertEqual(self.call("status")["tasks"]["sampled"], 100)
        self.assertEqual(len(self.call("journal")["events"]), 100)
        self.assertIn("not_full_history", self.call("journal")["window"])

    def test_all_actions_are_read_only_and_never_probe_network(self):
        before = copy.deepcopy(self.s.data)
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")) as network:
            for action in sorted(diag.ACTIONS):
                self.call(action)
        network.assert_not_called()
        self.host.probe.assert_not_called()
        self.assertEqual(self.s.data, before)

    def test_brains_sample_is_bounded(self):
        self.s.data["llm"]["profiles"] = {str(i): {"kind": "openai"} for i in range(103)}
        result = self.call("brains")
        self.assertEqual(len(result["profiles"]), 100)
        self.assertEqual(result["profiles_total"], 103)
        self.assertTrue(result["truncated"])

    def test_huge_numbers_do_not_overflow_or_leak_non_json_numbers(self):
        self.data["observed_at"] = 10 ** 1000
        self.data["runs"] = [run("completed", elapsed_s=10 ** 1000), run("failed", ended=10 ** 1000)]
        result = self.call("sli")
        self.assertIsNone(result["observer"]["observed_at"])
        self.assertIsNone(result["latency_s"]["p95"])
        self.assertEqual(result["counts"]["unknown"], 1)


if __name__ == "__main__":
    unittest.main()
