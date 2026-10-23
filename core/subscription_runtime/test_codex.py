"""Синтетические проверки протокола и политики Codex.

Учётные данные пользователя и запросы модели не используются.
"""
import copy
import json
import os
import queue
from pathlib import Path
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_policy as policy
import codex_rpc as wire
import codex_sidecar as sidecar

PID = "codex-" + "a" * 32


def request(op="generate", **overrides):
    value = {"v": 1, "id": "test", "op": op, "network": True, "local_only": False, "profile": PID}
    if op == "generate":
        value.update(text="synthetic text", model="test-model", export_current_text=True, usage_reviewed=True)
    value.update(overrides)
    return value


def effective_config():
    result = {}
    for key, value in policy.CONFIG.items():
        parent = result
        parts = key.split(".")
        for part in parts[:-1]:
            parent = parent.setdefault(part, {})
        parent[parts[-1]] = value
    return {"config": result}


class MockRpc:
    def __init__(self, events=None, status="completed"):
        self.calls = []
        self.thread_id = self.turn_id = self.login_id = None
        self.events = events if events is not None else [
            {"method": "item/completed", "params": {"threadId": "t", "turnId": "u", "item": {"id": "a", "type": "agentMessage", "phase": "final_answer", "text": "synthetic answer"}}},
            {"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "u", "status": status, "error": None}}}]

    def request(self, method, params=None):
        self.calls.append((method, params))
        return {"model/list": {"data": [{"model": "test-model", "displayName": "Test"}], "nextCursor": None},
                "thread/start": {"thread": {"id": "t"}, "model": "test-model", "modelProvider": "openai"},
                "turn/start": {"turn": {"id": "u"}},
                "account/login/start": {"type": "chatgpt", "loginId": "login", "authUrl": "https://auth.openai.com/oauth/authorize?synthetic=true"},
                "account/read": {"account": {"type": "chatgpt", "planType": "business"}}}[method]

    def event(self):
        if not self.events:
            raise policy.SafeError("outcome_unknown")
        return self.events.pop(0)


class PolicyTests(unittest.TestCase):
    def test_fixed_structured_schema_only(self):
        policy.validate(request(response_schema="dewiar-actions-v1"))
        for req in (request(response_schema={}), request(response_schema="arbitrary"), request("health", response_schema="dewiar-actions-v1")):
            with self.assertRaises(policy.SafeError):
                policy.validate(req)

    def test_structured_reply_does_not_enable_native_tools(self):
        rpc = MockRpc()
        sidecar.generate(rpc, request(response_schema="dewiar-actions-v1"), Path("C:/synthetic-empty"))
        turn = next(p for m, p in rpc.calls if m == "turn/start")
        thread = next(p for m, p in rpc.calls if m == "thread/start")
        self.assertEqual(turn["outputSchema"], policy.ACTION_SCHEMA)
        self.assertEqual(turn["environments"], [])
        self.assertEqual(thread["dynamicTools"], [])
        self.assertEqual(thread["environments"], [])
        self.assertFalse(thread["config"]["features.shell_tool"])

    def test_valid_request(self):
        self.assertEqual(policy.validate(request())["profile"], PID)

    def test_action_schema_and_prompt_match_decoder_contract(self):
        actions = policy.ACTION_SCHEMA["properties"]["actions"]
        self.assertEqual(actions["maxItems"], 1)
        self.assertEqual(set(actions["items"]["properties"]["name"]["enum"]),
                         {"plan", "notebook", "finish", "pause", "memory_save",
                          "create_task", "project_list", "project_read", "spawn_parts", "wait_parts"})
        self.assertEqual(actions["items"]["properties"]["arguments"]["type"], "string")
        instructions = policy.thread_params("test-model", ".", structured=True)["baseInstructions"]
        for required in ("start_line", "8000", "10000", "20000", "actions=[]", "allowed_actions"):
            self.assertIn(required, instructions)

    def test_siwc_does_not_send_host_identifier(self):
        source = (Path(__file__).resolve().parent / "sidecar.mjs").read_text(encoding="utf-8")
        self.assertIn("sendHostId: false", source)
        self.assertNotIn("sendHostId: true", source)

    def test_no_memory_history_files_tools_or_unknown_fields(self):
        for key in ("history", "instructions", "tools", "files", "memory", "api_key", "endpoint", "transport"):
            with self.subTest(key=key), self.assertRaises(policy.SafeError):
                policy.validate(request(**{key: "synthetic"}))

    def test_network_and_local_only_gate(self):
        for op in policy.NETWORK:
            for change in ({"network": False}, {"local_only": True}):
                with self.assertRaises(policy.SafeError) as result:
                    policy.validate(request(op, **change))
                self.assertEqual(result.exception.code, "network_denied")

    def test_generate_requires_both_consents(self):
        for change in ({"export_current_text": False}, {"usage_reviewed": False}):
            with self.assertRaises(policy.SafeError):
                policy.validate(request(**change))

    def test_reject_foreign_profile_or_paths(self):
        for value in ("hermes", "siwc-profile", "../escape", "C:/home", PID + "/home", None):
            with self.assertRaises(policy.SafeError):
                policy.validate(request(profile=value))

    def test_payload_bounds_and_types(self):
        for change in ({"text": "x" * 32769}, {"text": ""}, {"model": "bad model"}, {"local_only": "false"}, {"v": 2}):
            with self.assertRaises(policy.SafeError):
                policy.validate(request(**change))

    def test_health_does_not_spawn_open_store_or_call_network(self):
        with patch.object(sidecar, "executable", return_value=Path("synthetic.exe")):
            result = sidecar.execute(request("health", local_only=True), threading.Event(),
                                     profiles_factory=lambda: self.fail("store opened"), rpc_factory=lambda *a: self.fail("spawned"))
        self.assertTrue(result["dependency_ready"])
        self.assertFalse(result["network_called"])

    def test_cancelled_before_any_side_effect(self):
        cancel = threading.Event(); cancel.set()
        with patch.object(sidecar, "executable", side_effect=AssertionError("must not run")):
            with self.assertRaises(policy.SafeError) as result:
                sidecar.execute(request(), cancel)
        self.assertEqual(result.exception.code, "cancelled")

    def test_isolation_uses_no_environments_tools_or_durable_threads(self):
        result = policy.thread_params("test-model", "C:/synthetic-empty")
        self.assertEqual(result["environments"], [])
        self.assertEqual(result["dynamicTools"], [])
        self.assertEqual(result["runtimeWorkspaceRoots"], [])
        self.assertEqual(result["selectedCapabilityRoots"], [])
        self.assertTrue(result["ephemeral"])
        self.assertFalse(result["allowProviderModelFallback"])
        self.assertEqual(result["approvalPolicy"], "never")
        self.assertEqual(result["sandbox"], "read-only")

    def test_config_readback_fails_closed(self):
        data = effective_config()
        wire.verify_config(data)
        for key, value in (("shell_tool", True), ("apps", True), ("memories", True)):
            bad = copy.deepcopy(data); bad["config"]["features"][key] = value
            with self.assertRaises(policy.SafeError):
                wire.verify_config(bad)
        for field in ("mcp_servers", "plugins", "hooks", "model_providers", "openai_base_url", "chatgpt_base_url"):
            bad = copy.deepcopy(data); bad["config"][field] = {"unknown": "blocked"}
            with self.assertRaises(policy.SafeError):
                wire.verify_config(bad)

    def test_environment_drops_foreign_tokens_and_overrides(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "CODEX_HOME": "foreign", "HERMES_TOKEN": "synthetic", "HTTPS_PROXY": "synthetic"}):
            env = wire.child_environment("C:/synthetic-owned-profile")
        self.assertEqual(env["CODEX_HOME"], "C:/synthetic-owned-profile")
        self.assertFalse(any(k in env for k in ("OPENAI_API_KEY", "HERMES_TOKEN", "HTTPS_PROXY")))
        args = wire.command("codex.exe")
        self.assertIn('cli_auth_credentials_store="keyring"', args)
        self.assertIn("--strict-config", args)

    def test_api_key_or_external_tokens_auth_are_rejected(self):
        for account in (None, {"type": "apiKey"}, {"type": "chatgptAuthTokens"}):
            with self.assertRaises(policy.SafeError):
                policy.safe_auth({"account": account})

    def test_only_completed_final_text(self):
        items = [{"type": "agentMessage", "phase": "commentary", "text": "working"},
                 {"type": "agentMessage", "phase": "final_answer", "text": "done"}]
        self.assertEqual(policy.final_text(items, "completed"), "done")
        for status in ("failed", "interrupted", "inProgress", None):
            with self.assertRaises(policy.SafeError):
                policy.final_text(items, status)

    def test_completed_protocol_sends_only_current_text(self):
        rpc = MockRpc()
        result = sidecar.generate(rpc, request(), Path("C:/synthetic-empty"))
        self.assertEqual(result["text"], "synthetic answer")
        self.assertEqual(result["transport"], "codex")
        sent = next(args for method, args in rpc.calls if method == "turn/start")
        self.assertEqual(sent["input"], [{"type": "text", "text": "synthetic text"}])
        self.assertEqual(len([m for m, _ in rpc.calls if m == "turn/start"]), 1)

    def test_failure_after_text_does_not_succeed_or_retry(self):
        rpc = MockRpc(status="failed")
        with self.assertRaises(policy.SafeError):
            sidecar.generate(rpc, request(), Path("C:/synthetic-empty"))
        self.assertEqual(sum(m == "turn/start" for m, _ in rpc.calls), 1)

    def test_tool_items_fail_closed(self):
        for kind in ("commandExecution", "fileChange", "mcpToolCall", "webSearch", "dynamicToolCall"):
            rpc = MockRpc(events=[{"method": "item/started", "params": {"threadId": "t", "turnId": "u", "item": {"type": kind}}}])
            with self.assertRaises(policy.SafeError) as result:
                sidecar.generate(rpc, request(), Path("C:/synthetic-empty"))
            self.assertEqual(result.exception.code, "codex_tools_denied")

    def test_unavailable_model_never_starts_turn(self):
        rpc = MockRpc()
        with self.assertRaises(policy.SafeError):
            sidecar.generate(rpc, request(model="not-in-catalog"), Path("C:/synthetic-empty"))
        self.assertEqual([m for m, _ in rpc.calls], ["model/list"])

    def test_browser_login_uses_own_managed_flow(self):
        rpc = MockRpc(events=[{"method": "account/login/completed", "params": {"loginId": "login", "success": True}}])
        urls = []
        auth = sidecar.login(rpc, urls.append)
        self.assertEqual(auth["status"], "connected")
        self.assertEqual(rpc.calls[0], ("account/login/start", {"type": "chatgpt"}))
        self.assertEqual(len(urls), 1)
        self.assertIsNone(rpc.login_id)

    def test_rpc_rejects_unsolicited_approval_request(self):
        rpc = wire.Rpc.__new__(wire.Rpc)
        rpc.cancel = threading.Event(); rpc.deadline = time.monotonic() + 5
        rpc.frames = queue.Queue(); rpc.failed = threading.Event()
        rpc.frames.put({"id": 77, "method": "item/commandExecution/requestApproval", "params": {}})
        sent = []; rpc.send = sent.append
        with self.assertRaises(policy.SafeError) as caught:
            rpc._next()
        self.assertEqual(caught.exception.code, "codex_tools_denied")
        self.assertEqual(sent[0]["error"]["code"], -32601)

    def test_rpc_cancel_or_timeout_never_retries(self):
        rpc = wire.Rpc.__new__(wire.Rpc)
        rpc.cancel = threading.Event(); rpc.deadline = time.monotonic() - 1
        rpc.frames = queue.Queue(); rpc.failed = threading.Event()
        with self.assertRaises(policy.SafeError) as caught:
            rpc._next()
        self.assertEqual(caught.exception.code, "outcome_unknown")
        rpc.cancel.set()
        with self.assertRaises(policy.SafeError) as caught:
            rpc._next()
        self.assertEqual(caught.exception.code, "cancelled")

    @unittest.skipUnless(os.name == "nt", "Проверка Windows ACL и SID")
    def test_private_profile_paths_are_distinct_and_do_not_adopt_config(self):
        with tempfile.TemporaryDirectory(prefix="codex-synthetic-profile-") as directory:
            # Только уникальный тестовый каталог; настоящий профиль не открывается.
            with patch.object(sidecar.win, "storage", return_value=Path(directory)):
                with sidecar.Profiles() as profiles:
                    first, cwd = profiles.paths(PID, create=True)
                    second, _ = profiles.paths("codex-" + "b" * 32, create=True)
                    self.assertNotEqual(first, second)
                    sidecar.win.check_acl(first, profiles.k, profiles.a, profiles.sid)
                    profiles.save(PID, True)
                    self.assertTrue(profiles.read(PID)["cached"])
                    self.assertEqual(json.loads((first.parent / "profile.json").read_text()), {"connected": True})
                    (first / "config.toml").write_text("# synthetic foreign config")
                    with self.assertRaises(policy.SafeError):
                        profiles.paths(PID)

    @unittest.skipUnless(os.name == "nt", "Проверка Windows ACL и SID")
    def test_private_folder_rejects_traversal_before_creating(self):
        k, a = sidecar.win.api(); sid = sidecar.win.current_sid(k, a)
        sd, sa = sidecar.win.descriptor(a, sid)
        try:
            with tempfile.TemporaryDirectory(prefix="codex-synthetic-path-") as directory:
                for part in ("..", "C:", "a/b", "a\\b", "."):
                    with self.assertRaises(RuntimeError):
                        sidecar.win.secure_subdirectories(Path(directory), k, a, sid, sa, parts=[part])
                self.assertEqual(list(Path(directory).iterdir()), [])
        finally:
            k.LocalFree(sd)


if __name__ == "__main__":
    unittest.main()
