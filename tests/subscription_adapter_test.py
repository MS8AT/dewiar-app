"""Проверки адаптера с синтетическими данными.

Не запускают Engine, вход или модель; настоящие пользовательские настройки не читаются.
"""
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
RUNTIME = APP / "core" / "subscription_runtime"
CORE = APP / "core"
sys.path.insert(0, str(CORE))
import subscription_adapter as adapter
ipc = adapter._ipc


class Settings:
    def __init__(self, profile):
        self.profile = profile

    def active_llm(self):
        return self.profile

    def get(self, *args):
        return "synthetic-persona"


class Turn:
    def __init__(self, n):
        self.n, self.cancel = n, threading.Event()
        self.full = ""


class Engine:
    def __init__(self, profile):
        self.s, self.turn, self.turn_n = Settings(profile), None, 0
        self._turn_lock = threading.RLock()
        self.events, self.states, self.history = [], [], ["private-other-account-history"]
        self.finished = threading.Event()

    def _cancel_locked(self):
        if self.turn:
            self.turn.cancel.set()
        self.turn = None

    def emit(self, event, **data):
        self.events.append((event, data))

    def set_state(self, state):
        self.states.append(state)
        if state == "idle":
            self.finished.set()


PROFILE = {"kind": "chatgpt_subscription", "subscription_profile_id": "A", "model": "test-model",
           "subscription_export": True, "subscription_usage_reviewed": True}


class AdapterTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "SIWC использует Windows и локальный node.exe")
    def test_health_roundtrip_no_network(self):
        result = ipc.invoke("health", policy=lambda: True, runtime=RUNTIME)
        self.assertIsInstance(result["dependency_ready"], bool)
        self.assertFalse(result["network_called"])
        self.assertTrue(result["data_leaves_device"])

    def test_network_policy_blocks_before_child_creation(self):
        with patch.object(ipc.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
            for op in ("login", "models", "disconnect", "generate"):
                with self.assertRaises(ipc.SubscriptionError) as caught:
                    ipc.invoke(op, network=True, policy=lambda: True, runtime=RUNTIME)
                self.assertEqual(caught.exception.code, "network_denied")

    def test_cancelled_request_never_spawns(self):
        cancel = threading.Event(); cancel.set()
        with patch.object(ipc.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
            with self.assertRaises(ipc.SubscriptionError):
                ipc.invoke("health", cancel=cancel, policy=lambda: False, runtime=RUNTIME)

    def test_request_contract_and_terminal_validation(self):
        calls = []
        def caller(op, **args):
            calls.append((op, args))
            return {"completed": True, "profile": "A", "text": "mock answer"}
        self.assertEqual(adapter.generate(PROFILE, "only current text", threading.Event(), caller), "mock answer")
        self.assertEqual(calls[0][1]["text"], "only current text")
        self.assertNotIn("history", calls[0][1])
        self.assertEqual(calls[0][1]["profile"], "A")
        for bad in ({"profile": "A"}, {"completed": True, "profile": "B"}):
            with self.assertRaises(ipc.SubscriptionError):
                adapter.generate(PROFILE, "text", threading.Event(), lambda *a, **k: bad)

    def test_other_providers_are_untouched(self):
        self.assertFalse(adapter.start_turn(Engine({"kind": "openai"}), "hello"))

    def test_unsupported_channels_are_rejected_without_generation(self):
        with patch.object(adapter, "generate", side_effect=AssertionError("must not generate")):
            for kwargs in ({"images": ["private"]}, {"quiet": True}, {"raw": True}, {"via": {}}, {"shown": "attachment"}):
                engine = Engine(PROFILE)
                self.assertTrue(adapter.start_turn(engine, "hello", **kwargs))
                self.assertIsNone(engine.turn)
                self.assertEqual(engine.events[0][0], "error")
            self.assertTrue(adapter.start_turn(Engine(PROFILE), "hello\n\nВложения: private"))

    def test_completed_turn_does_not_touch_shared_history(self):
        engine = Engine(PROFILE)
        with patch.dict(sys.modules, {"engine_base": types.SimpleNamespace(Turn=Turn)}):
            with patch.object(adapter, "generate", return_value="mock completed answer"):
                adapter.start_turn(engine, "current text")
                self.assertTrue(engine.finished.wait(3))
        self.assertEqual(engine.history, ["private-other-account-history"])
        self.assertEqual(engine.events[-1], ("answer", {"text": "mock completed answer", "done": True, "model": True, "sources": []}))
        self.assertIsNone(engine.turn)

    def test_failure_emits_no_success_or_retry(self):
        engine = Engine(PROFILE)
        with patch.dict(sys.modules, {"engine_base": types.SimpleNamespace(Turn=Turn)}):
            with patch.object(adapter, "generate", side_effect=ipc.SubscriptionError("outcome_unknown")) as generate:
                adapter.start_turn(engine, "current text")
                self.assertTrue(engine.finished.wait(3))
                self.assertEqual(generate.call_count, 1)
        self.assertFalse(any(name == "answer" for name, _ in engine.events))

    def test_generic_llm_paths_fail_before_transport(self):
        # Compile just the existing functions: no imports/model/client startup.
        module = ast.parse((CORE / "llm.py").read_text(encoding="utf-8"))
        names = {"stream_events", "list_models", "test_profile"}
        selected = ast.Module(body=[n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        namespace = {"LLMError": RuntimeError, "observed_stream": __import__("brain_watch").observed_stream}
        exec(compile(selected, "llm-guard-fixture", "exec"), namespace)
        with self.assertRaises(RuntimeError):
            next(namespace["stream_events"](PROFILE, "private memory", []))
        with self.assertRaises(RuntimeError):
            namespace["list_models"](PROFILE)
        self.assertFalse(namespace["test_profile"](PROFILE)["ok"])

    def test_ui_command_allowlist(self):
        self.assertFalse(adapter.ui_command("generate", {})["ok"])

    def test_codex_health_roundtrip_no_login_or_model(self):
        # CI не обязан иметь desktop CLI: проверяем настоящий IPC и честный отказ.
        # Установленный CLI проверяется отдельно probe_codex.py без входа/модели.
        with tempfile.TemporaryDirectory() as empty, patch.dict(os.environ, {"LOCALAPPDATA": empty}):
            result = ipc.invoke("health", policy=lambda: True, runtime=RUNTIME, transport="codex")
        self.assertFalse(result["dependency_ready"])
        self.assertEqual(result["transport"], "codex")
        self.assertFalse(result["network_called"])
        self.assertFalse(result["live_verified"])

    def test_transport_is_explicit_and_wrong_result_is_rejected(self):
        profile = dict(PROFILE, subscription_transport="codex")
        calls = []
        def caller(op, **args):
            calls.append(args)
            return {"completed": True, "profile": "A", "text": "synthetic", "transport": "codex"}
        self.assertEqual(adapter.generate(profile, "text", threading.Event(), caller), "synthetic")
        self.assertEqual(calls[0]["transport"], "codex")
        with self.assertRaises(ipc.SubscriptionError):
            adapter.generate(profile, "text", threading.Event(), lambda *a, **k: {"completed": True, "profile": "A", "text": "wrong", "transport": "siwc"})
        with patch.object(adapter, "invoke", side_effect=AssertionError("must not invoke")):
            self.assertFalse(adapter.ui_command("health", {"transport": "unknown"})["ok"])

    def test_codex_network_gate_never_starts_child(self):
        with patch.object(ipc.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
            for op in ("login", "models", "generate", "disconnect"):
                with self.assertRaises(ipc.SubscriptionError) as caught:
                    ipc.invoke(op, network=True, policy=lambda: True, runtime=RUNTIME, transport="codex")
                self.assertEqual(caught.exception.code, "network_denied")

    def test_switching_transport_cancels_in_flight_result(self):
        engine = Engine(dict(PROFILE, subscription_transport="siwc"))
        def response(profile, text, cancel):
            engine.s.profile = dict(PROFILE, subscription_transport="codex")
            self.assertTrue(cancel.is_set())
            return "stale response"
        with patch.dict(sys.modules, {"engine_base": types.SimpleNamespace(Turn=Turn)}), patch.object(adapter, "generate", side_effect=response):
            adapter.start_turn(engine, "current text")
            self.assertTrue(engine.finished.wait(3))
        self.assertFalse(any(name == "answer" for name, _ in engine.events))

    def test_background_brain_does_not_replace_subscription(self):
        tree = ast.parse((CORE / "engine_brain.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_ensure_brain")
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "brain-guard-fixture", "exec"), namespace)
        settings = {("llm", "active"): "p", ("llm", "profiles"): {"p": PROFILE}}
        engine = types.SimpleNamespace(s=types.SimpleNamespace(get=lambda *keys: settings.get(keys)),
                                       account=types.SimpleNamespace(logged_in=lambda: True), _brain_lock=threading.Lock())
        # Reaching any network helper or the rest of the method is a failure.
        def forbidden(*args, **kwargs):
            raise AssertionError("background cloud access")
        cloud = types.SimpleNamespace(CloudError=RuntimeError, PROFILE_ID="cloud", fetch=forbidden)
        with patch.dict(sys.modules, {"cloud": cloud, "egress": types.SimpleNamespace(local_only=lambda: False)}):
            namespace["_ensure_brain"](engine)

    def test_no_subscription_as_legacy_fallback(self):
        tree = ast.parse((CORE / "engine_answer.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_cloud_fallback")
        namespace = {"is_cloud": lambda p: p.get("kind") == "cloud"}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "fallback-guard-fixture", "exec"), namespace)
        values = {("llm", "fallback"): "sub", ("llm", "profiles"): {"sub": PROFILE}}
        engine = types.SimpleNamespace(s=types.SimpleNamespace(get=lambda *keys: values.get(keys)))
        with patch.dict(sys.modules, {"cloud": types.SimpleNamespace(is_cloud=namespace["is_cloud"])}):
            self.assertIsNone(namespace["_cloud_fallback"](engine, {"kind": "cloud"}, RuntimeError("synthetic")))

    def test_switching_account_in_flight_discards_old_answer(self):
        engine = Engine(dict(PROFILE))
        def synthetic_response(profile, text, cancel):
            engine.s.profile = dict(PROFILE, subscription_profile_id="B")
            self.assertTrue(cancel.is_set())
            return "account A answer must not be delivered in B"
        with patch.dict(sys.modules, {"engine_base": types.SimpleNamespace(Turn=Turn)}):
            with patch.object(adapter, "generate", side_effect=synthetic_response):
                adapter.start_turn(engine, "current text")
                self.assertTrue(engine.finished.wait(3))
        self.assertFalse(any(name == "answer" for name, _ in engine.events))


if __name__ == "__main__":
    unittest.main()
