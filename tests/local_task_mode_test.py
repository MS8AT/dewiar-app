"""Продолжение той же задачи на LAN: синтетический сервер, закрытые пути и запрет облачного fallback."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.mkdtemp(prefix="dewiar-local-tasks-"))
os.environ.update(DEWIAR_WORKSPACE=str(TEMP / "workspace"), DEWIAR_STATE_DIR=str(TEMP / "state"),
                  DEWIAR_CONFIG_DIR=str(TEMP / "config"))
sys.path.insert(0, str(ROOT / "core"))
import brain_routes
import local_task_mode as local
from tasks import TaskManager
from tools import Toolbox
from workspace import Workspace


class Settings:
    def __init__(self, port=1234):
        self.data = {"llm": {"active": "cloud", "profiles": {
            "cloud": {"kind": "chatgpt_subscription", "subscription_transport": "codex"},
            "lan": {"kind": "openai", "base_url": f"http://127.0.0.1:{port}/v1", "model": "test-local"}}},
            "tasks": {"local_only": True, "self_check": False, "learn": False}}

    def get(self, *keys):
        value = self.data
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        return copy.deepcopy(value)


class Server(BaseHTTPRequestHandler):
    seen = []
    actions = [("update_plan", {"plan": "- [ ] Изучить проект"}), ("code_list", {"pattern": "."}),
               ("code_read", {"path": "README.md"}), ("update_plan", {"plan": "- [x] Изучить проект"}),
               ("finish", {"summary": "Проект изучен по README.md; источник проверен чтением. Модель и команды проекта не запускались."})]

    def log_message(self, *_args): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        n = len(self.seen)
        self.seen.append(body)
        name, args = self.actions[min(n, len(self.actions) - 1)]
        call = {"index": 0, "id": f"c{n}", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        event = {"choices": [{"delta": {"tool_calls": [call]}}]}
        raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(raw)


class Host:
    def __init__(self, port):
        self.s = Settings(port)
        self.workspace = Workspace(None)
        self.toolbox = Toolbox(self.s, None)
    def persona_name(self): return "Агент"
    def llm_profile(self): return self.s.get("llm", "profiles")["cloud"]
    def max_steps(self): return 8
    def code_auto_run(self): return True  # даже эта настройка не даёт read-only задаче запускать команды
    def announce(self, _text): pass
    def emit(self, *_args, **_kwargs): pass


class LocalTaskTests(unittest.TestCase):
    def test_only_explicit_local_addresses_are_accepted(self):
        for address in ("http://192.168.88.8:1234/v1", "http://127.0.0.1/v1", "http://localhost/v1", "http://[::1]/v1"):
            self.assertTrue(local.is_local({"kind": "openai", "base_url": address}))
        for address in ("https://api.openai.com/v1", "http://192.168.1.2.evil.invalid/v1", "http://u:p@192.168.1.2/v1"):
            self.assertFalse(local.is_local({"kind": "openai", "base_url": address}))
        self.assertFalse(local.is_local({"kind": "chatgpt_subscription", "base_url": "http://localhost/v1"}))

    def test_local_only_route_blocks_codex_before_dispatch(self):
        settings = Settings()
        self.assertEqual(brain_routes.profile(settings, "tasks")["kind"], "unavailable")
        settings.data["tasks"]["llm"] = "lan"
        self.assertTrue(local.is_local(brain_routes.profile(settings, "tasks")))

    def test_missing_bound_profile_never_uses_active_cloud(self):
        host = types.SimpleNamespace(s=Settings(), llm_profile=Mock())
        task = types.SimpleNamespace(data={"local_profile_id": "missing"})
        with self.assertRaises(ValueError):
            local.task_profile(host, task)
        host.llm_profile.assert_not_called()

    def test_live_task_cannot_change_executor(self):
        task = types.SimpleNamespace(data={"status": "running"}, thread=None, control_lock=threading.RLock())
        with self.assertRaises(ValueError):
            local.select(types.SimpleNamespace(host=types.SimpleNamespace(s=Settings())), task, "lan")

    def test_same_task_completes_locally_and_preserves_codex_audit(self):
        Server.seen = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            project = TEMP / "project"
            project.mkdir(exist_ok=True)
            (project / "README.md").write_text("Synthetic project source", encoding="utf-8")
            (project / "Pass").mkdir(exist_ok=True)
            (project / "Pass" / "local.txt").write_text("SYNTHETIC-SECRET", encoding="utf-8")
            manager = TaskManager(Host(server.server_port))
            task = manager.create("Изучи", "Изучи проект", str(project), start=False)
            task.data.update(subscription_binding={"id": "old-codex"}, subscription_attempts=5)
            (task.dir / "история.json").write_text('[{"role":"user","content":"STALE-WRONG-PATH"}]', encoding="utf-8")
            tid = task.id
            local.select(manager, task, "lan")
            self.assertEqual(task.id, tid)
            self.assertEqual(task.data["previous_codex"]["subscription_attempts"], 5)
            self.assertNotIn("subscription_binding", task.data)
            self.assertEqual(Server.seen, [])
            self.assertTrue(manager._tool_raw(task, "code_write", {"path": "x", "content": "x"}).startswith("Защита"))
            self.assertTrue(manager._tool_raw(task, "finish", {"summary": "Нет доступа, всё готово"}).startswith("Итог не принят"))
            self.assertTrue(local.read_project(task, "code_read", {"path": "C:\\wrong\\README.md"}).startswith("Ошибка пути"))
            self.assertTrue(local.read_project(task, "code_read", {"path": "Pass/local.txt"}).startswith("Ошибка"))
            manager.start(task.id)
            task.thread.join(timeout=8)
            self.assertFalse(task.thread.is_alive())
            self.assertEqual(task.status, "done", task.data.get("error"))
            self.assertEqual(task.data["progress"], [1, 1])
            self.assertTrue((task.dir / "итог.md").is_file())
            self.assertFalse((task.dir / "рабочая копия").exists())
            self.assertEqual(len(list((task.dir / "_history").glob("*.json"))), 1)
            self.assertEqual(len(Server.seen), 5)
            for request in Server.seen:
                self.assertEqual(request["model"], "test-local")
                self.assertLessEqual({x["function"]["name"] for x in request["tools"]}, local.READ_TOOLS)
                self.assertNotIn("SYNTHETIC-SECRET", json.dumps(request))
                self.assertNotIn("STALE-WRONG-PATH", json.dumps(request))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
