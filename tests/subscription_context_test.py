"""Автономные проверки контекста и задач с синтетическими данными.

Настоящая память и модель не используются; побочные действия подменены.
"""
import ast
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

CORE = Path(__file__).resolve().parents[1] / "core"
sys.path.insert(0, str(CORE))
import subscription_context as context
import subscription_adapter as adapter
import subscription_quota as quota

PROFILE = {"kind": "chatgpt_subscription", "subscription_transport": "codex", "model": "test-model",
           "subscription_profile_id": "codex-" + "a" * 32, "subscription_export": True, "subscription_usage_reviewed": True}


def reply(name=None, **args):
    return json.dumps({"text": "synthetic reply", "actions": [] if not name else [{"name": name, "arguments": json.dumps(args)}]})


class Host:
    def __init__(self, **flags):
        self.profile = dict(PROFILE, **flags)
        self.s = types.SimpleNamespace(active_llm=lambda: self.profile,
                                       get=lambda *keys: "p" if keys == ("llm", "active") else "")
        self.workspace = types.SimpleNamespace(memory_text=Mock(return_value="synthetic memory"), remember=Mock(return_value="secret old value"))
        self.pending_confirm = None
        self.emit = Mock()
        self.llm_profile = lambda: self.profile
        self.tasks = Mock()


class Task:
    def __init__(self, root):
        self.dir, self.cancel = root, threading.Event()
        self.goal = "synthetic goal"
        self.data = {"status": "running", "steps": 0, "project": ""}
        self.save = Mock()
        self.journal = Mock()


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.egress = patch.dict(sys.modules, {"egress": types.SimpleNamespace(local_only=lambda: False)})
        self.egress.start()
        self.cancel = threading.Event()

    def tearDown(self):
        self.egress.stop()

    def test_default_chat_is_unchanged_and_reads_no_memory(self):
        host = Host(); generate = Mock(return_value="raw answer")
        self.assertEqual(context.chat_answer(host, host.profile, "current", self.cancel, generate), "raw answer")
        generate.assert_called_once_with(host.profile, "current", self.cancel)
        host.workspace.memory_text.assert_not_called()

    def test_memory_read_is_independent(self):
        host = Host(subscription_memory_read=True); generate = Mock(return_value=reply())
        context.chat_answer(host, host.profile, "current", self.cancel, generate)
        sent = json.loads(generate.call_args.args[1])
        self.assertEqual(sent["memory_about_me"], "synthetic memory")
        self.assertEqual(sent["allowed_actions"], {})
        host.workspace.remember.assert_not_called()

    def test_write_only_does_not_export_old_memory(self):
        host = Host(subscription_memory_write=True); generate = Mock(return_value=reply("memory_save", fact="new fact"))
        with patch.object(context, "confirm_local", return_value=True):
            result = context.chat_answer(host, host.profile, "remember", self.cancel, generate)
        host.workspace.memory_text.assert_not_called()
        host.workspace.remember.assert_called_once_with("new fact")
        self.assertNotIn("secret old value", result)

    def test_memory_write_refusal_has_no_effect(self):
        host = Host(subscription_memory_write=True)
        with patch.object(context, "confirm_local", return_value=False):
            result = context.save_memory(host, host.profile, self.cancel, "fact")
        self.assertIn("не подтверждена", result)
        host.workspace.remember.assert_not_called()

    def test_grant_revocation_during_confirmation_blocks_write(self):
        host = Host(subscription_memory_write=True)
        def confirm(*args):
            self.cancel.set()
            return True
        with patch.object(context, "confirm_local", side_effect=confirm), self.assertRaises(context.ContextError):
            context.save_memory(host, host.profile, self.cancel, "fact")
        host.workspace.remember.assert_not_called()

    def test_local_only_blocks_before_memory_and_generation(self):
        host = Host(subscription_memory_read=True); generate = Mock()
        with patch.dict(sys.modules, {"egress": types.SimpleNamespace(local_only=lambda: True)}), self.assertRaises(context.ContextError):
            context.chat_answer(host, host.profile, "current", self.cancel, generate)
        host.workspace.memory_text.assert_not_called(); generate.assert_not_called()

    def test_history_is_bounded_and_isolated_from_shared_history(self):
        host = Host(subscription_history=True); host.history = ["private foreign history"]
        generate = Mock(return_value=reply())
        for _ in range(8):
            context.chat_answer(host, host.profile, "x" * 15000, self.cancel, generate)
        sent = json.loads(generate.call_args.args[1])
        self.assertEqual(len(sent["session_history"]), 3)
        self.assertNotIn("private foreign history", generate.call_args.args[1])
        self.assertLess(len(generate.call_args.args[1]), 30000)

    def test_history_cleared_on_scope_revision_or_account_change(self):
        for field, value in (("subscription_scope_revision", "new"), ("subscription_profile_id", "B"), ("id", "other")):
            host = Host(subscription_history=True); generate = Mock(return_value=reply())
            context.chat_answer(host, host.profile, "old private text", self.cancel, generate)
            host.profile[field] = value
            context.chat_answer(host, host.profile, "new", self.cancel, generate)
            self.assertEqual(json.loads(generate.call_args.args[1])["session_history"], [])

    def test_disable_history_drops_retained_text(self):
        host = Host(subscription_history=True); generate = Mock(return_value=reply())
        context.chat_answer(host, host.profile, "old", self.cancel, generate)
        host.profile["subscription_history"] = False
        context.chat_answer(host, host.profile, "new", self.cancel, generate)
        self.assertNotIn("_subscription_history", host.__dict__)

    def test_payload_too_large_stops_before_generation(self):
        host = Host(subscription_history=True); generate = Mock()
        with self.assertRaises(context.ContextError):
            context.chat_answer(host, host.profile, "x" * 16001, self.cancel, generate)
        generate.assert_not_called()
        with self.assertRaises(context.ContextError):
            context.pack({"text": "\\" * 30000})

    def test_malformed_multiple_unknown_and_duplicate_actions_rejected(self):
        for text in ('{}', '[]', 'not JSON', '{"text":"a","text":"b","actions":[]}',
                     reply("run_command", command="bad"),
                     json.dumps({"text": "", "actions": [{"name": "finish", "arguments": "{}"}] * 2}),
                     json.dumps({"text": "", "actions": [{"name": "finish", "arguments": '{"summary":"a","summary":"b"}'}]})):
            with self.assertRaises(context.ContextError):
                context.decode(text, {"finish": ["summary"]})

    def test_action_error_has_fixed_reason_and_no_payload(self):
        marker = "PRIVATE-SYNTHETIC"
        def envelope(actions):
            return json.dumps({"text": marker, "actions": actions})
        cases = {
            "response_size": marker * 20000,
            "response_json": marker,
            "response_fields": json.dumps({"text": marker}),
            "action_count": envelope([{}, {}]),
            "action_fields": envelope([{"name": marker}]),
            "action_name": reply(marker, summary=marker),
            "arguments_type": envelope([{"name": "finish", "arguments": {"summary": marker}}]),
            "arguments_json": envelope([{"name": "finish", "arguments": marker}]),
            "arguments_fields": reply("finish", unexpected=marker),
            "arguments_values": reply("finish", summary=123),
        }
        self.assertEqual(set(cases), set(context.ActionError.REASONS))
        for code, raw in cases.items():
            with self.subTest(code=code), self.assertRaises(context.ActionError) as caught:
                context.decode(raw, {"finish": ["summary"]})
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn(marker, str(caught.exception))

    def test_unhashable_names_and_deep_json_are_safe(self):
        for name in ([], {}, None, 1):
            raw = json.dumps({"text": "", "actions": [{"name": name, "arguments": "{}"}]})
            with self.assertRaises(context.ActionError) as caught:
                context.decode(raw, {"finish": ["summary"]})
            self.assertEqual(caught.exception.code, "action_name")
        with self.assertRaises(context.ActionError):
            context.decode("[" * 2000 + "]" * 2000, {})

    def test_project_line_number_is_a_string_not_an_implicit_conversion(self):
        allowed = {"project_read": ["path", "start_line"]}
        _, actions = context.decode(reply("project_read", path="app.py", start_line="1"), allowed)
        self.assertEqual(actions[0][1]["start_line"], "1")
        with self.assertRaises(context.ActionError) as caught:
            context.decode(reply("project_read", path="app.py", start_line=1), allowed)
        self.assertEqual(caught.exception.code, "arguments_values")

    def test_invalid_task_action_is_counted_paused_and_never_retried(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root)
            generate = Mock(return_value=reply("run_command", command="PRIVATE-SYNTHETIC"))
            context.run_task(manager, task, generate)
            generate.assert_called_once()
            self.assertEqual(task.data["subscription_attempts"], 1)
            self.assertEqual(task.data["status"], "paused")
            self.assertFalse(task.data["auto_resume"])
            self.assertIn("[action_name]", task.data["error"])
            self.assertNotIn("PRIVATE-SYNTHETIC", task.data["error"])
            host.workspace.remember.assert_not_called()
            self.assertEqual(list(task.dir.iterdir()), [])
            self.assertIn("response_format", json.loads(generate.call_args.args[1]))

    def test_chat_format_is_explicit_without_granting_actions(self):
        host = Host(subscription_history=True)
        generate = Mock(return_value=reply())
        context.chat_answer(host, host.profile, "current", self.cancel, generate)
        sent = json.loads(generate.call_args.args[1])
        self.assertEqual(sent["allowed_actions"], {})
        self.assertEqual(sent["response_format"]["envelope"]["actions"], [])

    def test_chat_task_creation_is_confirmed_paused_and_bound(self):
        host = Host(subscription_tasks=True)
        task = types.SimpleNamespace(data={}, save=Mock())
        host.tasks.create.return_value = task
        with patch.object(context, "confirm_local", return_value=True):
            context.chat_answer(host, host.profile, "task", self.cancel, Mock(return_value=reply("create_task", title="title", goal="goal")))
        host.tasks.create.assert_called_once_with("title", "goal", start=False)
        self.assertEqual(task.data["subscription_binding"], context.snapshot(host.profile))
        host.tasks.start.assert_not_called()

    def test_task_is_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as root:
            host = Host(); task = Task(Path(root)); generate = Mock()
            self.assertTrue(context.run_task(types.SimpleNamespace(host=host, _emit=Mock()), task, generate))
            generate.assert_not_called(); self.assertEqual(task.data["status"], "paused")

    def test_other_provider_not_intercepted(self):
        host = Host(); host.profile = {"kind": "openai"}
        self.assertFalse(context.run_task(types.SimpleNamespace(host=host), types.SimpleNamespace(data={})))

    def test_legacy_host_needs_no_subscription_settings(self):
        host = types.SimpleNamespace(llm_profile=lambda: {"kind": "openai", "model": "mock"})
        self.assertFalse(context.run_task(types.SimpleNamespace(host=host), types.SimpleNamespace(data={})))

    def task_fixture(self, root, **flags):
        host = Host(subscription_tasks=True, **flags)
        manager = types.SimpleNamespace(host=host, _beat=Mock(), _emit=Mock())
        return host, manager, Task(Path(root))

    def test_task_finish_does_not_call_legacy_system_tools_or_memory(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root)
            (task.dir / "история.json").write_text("PRIVATE LEGACY HISTORY", encoding="utf-8")
            (task.dir / "блокнот.md").write_text("PRIVATE LEGACY NOTES", encoding="utf-8")
            generate = Mock(return_value=reply("finish", summary="Synthetic done"))
            context.run_task(manager, task, generate)
            self.assertEqual(task.data["status"], "done")
            self.assertEqual(task.data["subscription_attempts"], 1)
            self.assertEqual((task.dir / "итог.md").read_text(encoding="utf-8"), "Synthetic done")
            self.assertNotIn("PRIVATE LEGACY", generate.call_args.args[1])
            host.workspace.memory_text.assert_not_called()
            self.assertFalse(task.data["verified"])

    def test_task_attempt_budget_persists_across_resume(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root, subscription_task_limit=2)
            generate = Mock(return_value=reply("notebook", text="synthetic note"))
            context.run_task(manager, task, generate)
            self.assertEqual(generate.call_count, 2); self.assertEqual(task.data["status"], "paused")
            context.run_task(manager, task, generate)
            self.assertEqual(generate.call_count, 2)
            self.assertFalse(task.data["auto_resume"])

    def test_imported_profile_cannot_bypass_base_limit_with_21_to_100(self):
        for amount in (21, 100):
            with self.subTest(amount=amount), tempfile.TemporaryDirectory() as root:
                host, manager, task = self.task_fixture(root, subscription_task_limit=amount)
                generate = Mock()
                with patch.object(context, "confirm_local", side_effect=AssertionError("must not confirm")):
                    context.run_task(manager, task, generate)
                generate.assert_not_called()
                self.assertEqual(task.data["status"], "paused")
                self.assertNotIn("subscription_attempts", task.data)

    def test_confirmed_quota_extension_allows_separate_manual_resume(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root, subscription_task_limit=2)
            generate = Mock(return_value=reply("notebook", text="synthetic note"))
            context.run_task(manager, task, generate)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(task.data["subscription_attempts"], 2)
            self.assertEqual(task.data["status"], "paused")
            quota.grant(manager, task, 2)
            self.assertEqual(generate.call_count, 2)  # выдача квоты не вызывает модель
            self.assertEqual(task.data["status"], "paused")
            generate.return_value = reply("finish", summary="Synthetic done")
            context.run_task(manager, task, generate)
            self.assertEqual(generate.call_count, 3)
            self.assertEqual(task.data["subscription_attempts"], 3)
            self.assertEqual(task.data["subscription_request_limit"], 4)
            self.assertEqual(task.data["status"], "done")

    def test_unknown_outcome_is_counted_and_not_retried(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root)
            generate = Mock(side_effect=adapter.SubscriptionError("outcome_unknown"))
            context.run_task(manager, task, generate)
            generate.assert_called_once(); self.assertEqual(task.data["subscription_attempts"], 1)
            self.assertEqual(task.data["status"], "paused")

    def test_task_binding_prevents_account_change_and_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            host, manager, task = self.task_fixture(root)
            task.data["subscription_binding"] = context.snapshot(context.task_profile(host))
            for profile in (dict(host.profile, subscription_profile_id="B"), {"kind": "openai"}):
                host.profile = profile; generate = Mock()
                self.assertTrue(context.run_task(manager, task, generate)); generate.assert_not_called()

    def test_task_profile_change_during_generation_blocks_action(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=True):
            host, manager, task = self.task_fixture(root)
            def generate(*args, **kwargs):
                host.profile["subscription_tasks"] = False
                return reply("finish", summary="must not save")
            context.run_task(manager, task, generate)
            self.assertFalse((task.dir / "итог.md").exists()); self.assertEqual(task.data["status"], "paused")

    def test_task_launch_refusal_never_dispatches(self):
        with tempfile.TemporaryDirectory() as root, patch.object(context, "confirm_local", return_value=False):
            host, manager, task = self.task_fixture(root); generate = Mock()
            context.run_task(manager, task, generate)
            generate.assert_not_called(); self.assertNotIn("subscription_attempts", task.data)

    def test_task_has_only_explicit_small_allowlist(self):
        for flags in ({}, {"subscription_project_read": True, "subscription_memory_write": True}):
            allowed = context.task_actions(dict(PROFILE, **flags))
            self.assertFalse(set(allowed) & {"run_python", "run_command", "spawn_parts", "notify", "web_search", "write_file"})

    def test_project_reads_nested_source_but_blocks_sensitive_paths(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root); (folder / "src").mkdir(); (folder / "src" / "app.py").write_text("print('synthetic')")
            task = types.SimpleNamespace(data={"project": root})
            self.assertIn("src/", context.project_action(task, "project_list", "."))
            self.assertIn("synthetic", context.project_action(task, "project_read", "src/app.py"))
            for rel in ("../escape.py", "C:/outside.py", ".env", "Pass.txt", "Pass/key.txt", "src/password.txt"):
                with self.assertRaises(context.ContextError):
                    context.project_action(task, "project_read", rel)

    def test_project_secret_content_refused_and_no_arbitrary_root(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root); (folder / "app.py").write_text('api_key = "synthetic-secret-value"')
            with self.assertRaises(context.ContextError):
                context.project_action(types.SimpleNamespace(data={"project": root}), "project_read", "app.py")
            with self.assertRaises(context.ContextError):
                context.project_action(types.SimpleNamespace(data={}), "project_list", ".")

    def test_task_hook_precedes_all_legacy_reads(self):
        tree = ast.parse((CORE / "tasks.py").read_text(encoding="utf-8"))
        run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run")
        self.assertIsInstance(run.body[1], ast.ImportFrom)
        self.assertEqual(run.body[1].module, "subscription_context")
        self.assertIsInstance(run.body[2], ast.If)
        self.assertIsInstance(run.body[2].body[0], ast.Return)

    def test_chat_and_explicit_task_selection_use_same_identity(self):
        host = Host()
        self.assertEqual(context.snapshot(context.chat_profile(host)), context.snapshot(context.task_profile(host)))

    def test_structured_mode_not_allowed_in_siwc(self):
        with patch.object(adapter._ipc.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
            with self.assertRaises(adapter.SubscriptionError):
                adapter._ipc.invoke("generate", transport="siwc", response_schema="dewiar-actions-v1")

    def test_local_confirmation_no_voice_or_external_push(self):
        host = Host(); host.announce = Mock()
        def emit(event, **data):
            if event == "confirm":
                host.pending_confirm["answer"] = True
                host.pending_confirm["event"].set()
        host.emit = emit
        self.assertTrue(context.confirm_local(host, "synthetic", self.cancel))
        self.assertIsNone(host.pending_confirm); host.announce.assert_not_called()

    def test_concurrent_confirmation_does_not_replace_existing_prompt(self):
        host = Host(); existing = {"event": threading.Event(), "answer": False}; host.pending_confirm = existing
        self.assertFalse(context.confirm_local(host, "synthetic", self.cancel))
        self.assertIs(host.pending_confirm, existing); host.emit.assert_not_called()
        self.assertTrue(context._CONFIRM_LOCK.acquire(blocking=False)); context._CONFIRM_LOCK.release()

    def test_project_read_pagination_and_bounds(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root); (folder / "app.py").write_text("\n".join(str(i) for i in range(200)))
            task = types.SimpleNamespace(data={"project": root})
            self.assertTrue(context.project_action(task, "project_read", "app.py", "150").startswith("150: 149"))
            with self.assertRaises(context.ContextError):
                context.project_action(task, "project_read", "app.py", "-1")


if __name__ == "__main__":
    unittest.main()
