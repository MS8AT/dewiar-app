"""Полный синтетический поток: context overflow -> один компактный повтор -> finish."""
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
    requests = []
    reject_compact = False

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = next((m.get("content", "") for m in body.get("messages", []) if m.get("role") == "system"), "")
        tools = body.get("tools") or []
        self.requests.append({"system_chars": len(system), "tools": len(tools)})
        if len(tools) > 25 or self.reject_compact:
            raw = json.dumps({"error": {"code": 400, "message": "request exceeds the available context size"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        call = {"index": 0, "id": "doctor-ok", "type": "function",
                "function": {"name": "finish", "arguments": json.dumps({"summary": "Готово после лечения"}, ensure_ascii=False)}}
        event = {"choices": [{"delta": {"tool_calls": [call]}}]}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode())


class Settings:
    def get(self, *keys):
        return {} if keys and keys[0] == "tools" else None


class Host:
    def __init__(self, port):
        self.workspace = Workspace(None)
        self.toolbox = Toolbox(Settings(), None)
        self.events = []
        self.port = port

    def persona_name(self):
        return "Агент"

    def memory(self):
        return "M" * 8000

    def llm_profile(self):
        return {"name": "synthetic", "kind": "openai", "base_url": f"http://127.0.0.1:{self.port}/v1", "model": "mock"}

    def max_steps(self):
        return 3

    def code_auto_run(self):
        return False

    def announce(self, _text):
        pass

    def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))


class FlowTest(unittest.TestCase):
    def test_one_bounded_repair_continues_task(self):
        Server.requests = []
        Server.reject_compact = False
        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            project = TEMP / "project"
            project.mkdir(exist_ok=True)
            manager = TaskManager(Host(server.server_port))
            task = manager.create("Изучи", "Изучи проект", str(project), start=False)
            task.data["force_finish"] = True
            manager.start(task.id)
            for _ in range(100):
                if task.status in ("done", "failed"):
                    break
                time.sleep(0.05)
            self.assertEqual(task.status, "done", task.data.get("error"))
            self.assertEqual(task.data["doctor"]["last_result"], "recovered")
            # llm.py делает свой штатный повтор с короткой историей, затем доктор — ровно один компактный.
            self.assertEqual(len(Server.requests), 3, Server.requests)
            self.assertEqual(Server.requests[0], Server.requests[1])
            self.assertGreater(Server.requests[0]["tools"], 25)
            self.assertLessEqual(Server.requests[2]["tools"], 25)
            self.assertEqual(task.data["doctor"]["context_repairs"], 1)
            journal = (task.dir / "журнал.md").read_text(encoding="utf-8")
            self.assertIn("AI-доктор", journal)
            self.assertIn("компактный запрос принят", journal)
        finally:
            server.shutdown()
            server.server_close()

    def test_second_context_failure_stops_without_loop(self):
        Server.requests = []
        Server.reject_compact = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            project = TEMP / "project-fail"
            project.mkdir(exist_ok=True)
            manager = TaskManager(Host(server.server_port))
            task = manager.create("Изучи", "Изучи проект", str(project), start=False)
            manager.start(task.id)
            for _ in range(100):
                if task.status in ("done", "failed"):
                    break
                time.sleep(0.05)
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.data["doctor"]["last_result"], "failed")
            self.assertEqual(task.data["doctor"]["context_repairs"], 1)
            self.assertIn("AI-доктор сократил", task.data["error"])
            self.assertLessEqual(len(Server.requests), 4)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
