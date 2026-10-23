"""Синтетический поток задачи: Markdown-вызов -> настоящий инструмент -> finish."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.mkdtemp())
os.environ.update(DEWIAR_WORKSPACE=str(TEMP / "workspace"), DEWIAR_STATE_DIR=str(TEMP / "state"),
                  DEWIAR_CONFIG_DIR=str(TEMP / "config"))
sys.path.insert(0, str(ROOT / "core"))

from tasks import TaskManager  # noqa: E402
from tools import Toolbox  # noqa: E402
from workspace import Workspace  # noqa: E402


class Server(BaseHTTPRequestHandler):
    requests = 0

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests += 1
        has_tool_result = any(m.get("role") == "tool" for m in body.get("messages", []))
        if has_tool_result:
            text = '**Функция:** finish\n**Аргументы:** {"summary":"Markdown-вызовы выполнены"}'
        else:
            text = ('Сначала посмотрю файлы.\n\n### Функция: code_list\n\n'
                    '**Функция:** code_list\n**Аргументы:** {"pattern":""}\n\n'
                    '**Ответ от функции:** {"files":["выдумка.txt"]}\n\n'
                    '**Функция:** code_delete\n**Аргументы:** {"path":"project"}')
        event = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
        raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(raw)


class Settings:
    def get(self, *keys):
        return {} if keys and keys[0] == "tools" else None


class Host:
    def __init__(self, port):
        self.workspace = Workspace(None)
        self.toolbox = Toolbox(Settings(), None)
        self.port = port

    def persona_name(self): return "Агент"
    def memory(self): return ""
    def llm_profile(self):
        return {"name": "synthetic", "kind": "openai", "base_url": f"http://127.0.0.1:{self.port}/v1", "model": "mock"}
    def max_steps(self): return 4
    def code_auto_run(self): return False
    def announce(self, _text): pass
    def emit(self, *_args, **_kwargs): pass


class FlowTest(unittest.TestCase):
    def test_markdown_call_is_executed_but_fiction_is_not(self):
        Server.requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            project = TEMP / "project"
            project.mkdir(exist_ok=True)
            (project / "real.txt").write_text("ok", encoding="utf-8")
            manager = TaskManager(Host(server.server_port))
            task = manager.create("Изучи", "Изучи проект", str(project), start=False)
            task.data["force_finish"] = True
            manager.start(task.id)
            for _ in range(120):
                if task.status in ("done", "failed"):
                    break
                time.sleep(0.05)
            self.assertEqual(task.status, "done", task.data.get("error"))
            self.assertEqual(task.result, "Markdown-вызовы выполнены")
            self.assertTrue((project / "real.txt").exists())
            journal = (task.dir / "журнал.md").read_text(encoding="utf-8")
            self.assertIn("строгий Markdown-вызов", journal)
            self.assertIn("`code_list`", journal)
            self.assertNotIn("`code_delete`", journal)
            self.assertEqual(Server.requests, 2)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
