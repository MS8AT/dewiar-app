"""Ограниченный stdio-клиент закреплённой версии Codex app-server.

Один процесс обслуживает одну операцию; запросы инструментов отклоняются.
"""
from collections import deque
import json
import os
import queue
import subprocess
import threading
import time

from codex_policy import CONFIG, SafeError, fail

MAX_FRAME = 4 * 1024 * 1024


def child_environment(home):
    # Не наследуем ключи провайдеров, настройки Codex, прокси и внешних агентов.
    names = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "LOCALAPPDATA",
             "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
             "PROGRAMDATA", "PATH", "PATHEXT", "COMSPEC"}
    env = {k: v for k, v in os.environ.items() if k.upper() in names}
    env["CODEX_HOME"] = str(home)
    return env


def command(executable):
    args = [str(executable), "app-server", "--listen", "stdio://", "--strict-config"]
    for key, value in CONFIG.items():
        args += ["-c", key + "=" + json.dumps(value, ensure_ascii=False)]
    return args


def nested(data, dotted):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def verify_config(data):
    config = data.get("config", {})
    for key, expected in CONFIG.items():
        # Некоторые возможности представлены булевым значением или таблицей enabled.
        actual = nested(config, key)
        if actual != expected:
            fail("codex_policy_unavailable")
    for key in ("mcp_servers", "plugins", "hooks"):
        if config.get(key):
            fail("codex_policy_unavailable")
    # Системная конфигурация не должна подменять адрес или провайдера.
    if config.get("openai_base_url") or config.get("model_providers"):
        fail("codex_policy_unavailable")


class Rpc:
    def __init__(self, executable, home, cwd, cancel, timeout=300):
        self.cancel, self.deadline = cancel, time.monotonic() + timeout
        self.frames, self.pending = queue.Queue(maxsize=512), deque()
        self.sequence, self.turn_id, self.thread_id, self.login_id = 0, None, None, None
        self.proc = subprocess.Popen(command(executable), cwd=str(cwd), env=child_environment(home),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.failed = threading.Event()
        threading.Thread(target=self._reader, name="codex-stdio-reader", daemon=True).start()

    def _reader(self):
        try:
            while True:
                raw = self.proc.stdout.readline(MAX_FRAME + 1)
                if not raw or len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                    break
                message = json.loads(raw)
                if not isinstance(message, dict):
                    break
                self.frames.put_nowait(message)
        except Exception:
            pass
        finally:
            self.failed.set()

    def send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            fail("outcome_unknown")

    def _next(self):
        while True:
            if self.cancel.is_set():
                fail("cancelled")
            if time.monotonic() >= self.deadline:
                fail("outcome_unknown")
            try:
                message = self.frames.get(timeout=0.05)
                if "method" in message and "id" in message:
                    # Не подтверждаем инструменты, не передаём токены и не выдаём себя
                    # за официальный клиент. Любой запрос сервера останавливает операцию.
                    self.send({"id": message["id"], "error": {"code": -32601, "message": "Disabled in text-only client"}})
                    fail("codex_tools_denied")
                if message.get("method") == "error":
                    fail("subscription_failed")
                return message
            except queue.Empty:
                if self.failed.is_set():
                    fail("outcome_unknown")

    def request(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params or {}})
        while True:
            message = self._next()
            if message.get("id") == request_id:
                if "error" in message:
                    fail("subscription_failed")
                result = message.get("result")
                if not isinstance(result, dict):
                    fail("outcome_unknown")
                return result
            if "id" in message or len(self.pending) >= 512:
                fail("outcome_unknown")
            self.pending.append(message)

    def event(self):
        if self.cancel.is_set():
            fail("cancelled")
        return self.pending.popleft() if self.pending else self._next()

    def initialize(self):
        self.request("initialize", {"clientInfo": {"name": "ai_worckbook_dewiar_local", "title": "Dewiar local Codex", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}})
        self.send({"method": "initialized", "params": {}})
        verify_config(self.request("config/read", {"includeLayers": False}))

    def close(self):
        # Отмена затрагивает только дочерний процесс, а не приложение Codex.
        try:
            if self.turn_id and self.thread_id:
                self.send({"id": -1, "method": "turn/interrupt", "params": {"threadId": self.thread_id, "turnId": self.turn_id}})
            if self.login_id:
                self.send({"id": -2, "method": "account/login/cancel", "params": {"loginId": self.login_id}})
            self.proc.stdin.close()
        except (OSError, SafeError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self.proc.stdout.close()
