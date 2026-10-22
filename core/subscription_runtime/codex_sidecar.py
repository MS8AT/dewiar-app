"""Явный транспорт Codex по подписке с собственным входом и профилями Windows.

Чужие учётные данные не импортируются; перехода на API-ключ или другую модель нет.
"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlparse
import uuid

# Режим -I исключает каталог скрипта; добавляем только наш локальный runtime.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import windows_store as win
from codex_policy import SafeError, fail, validate, profile_id, safe_auth, final_text, thread_params
from codex_rpc import Rpc


def executable():
    pin = json.loads((ROOT / "codex-dependency.json").read_text(encoding="utf-8"))
    # Ищем только исполняемый файл: не читаем чужие профили и не доверяем PATH.
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    if not base.is_absolute() or str(base).startswith("\\\\"):
        fail("dependency_unavailable")
    for candidate in sorted(base.glob("*/codex.exe")):
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in [candidate, *candidate.parents]):
            continue
        with candidate.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest == pin["sha256"]:
            return candidate
    fail("dependency_unavailable")


class Profiles:
    """Мьютекс по Windows SID и закрытые каталоги; токенами в keyring управляет Codex."""
    def __enter__(self):
        self.k, self.a = win.api()
        self.sid = win.current_sid(self.k, self.a)
        self.sd, self.sa = win.descriptor(self.a, self.sid)
        self.mutex, self.acquired = None, False
        try:
            self.k.CreateMutexW.argtypes = [c.POINTER(win.SecurityAttributes), win.w.BOOL, win.w.LPCWSTR]
            self.k.CreateMutexW.restype = win.w.HANDLE
            self.k.WaitForSingleObject.argtypes = [win.w.HANDLE, win.w.DWORD]
            self.k.ReleaseMutex.argtypes = [win.w.HANDLE]
            self.mutex = self.k.CreateMutexW(c.byref(self.sa), False, "Global\\AI_WorkBook_Codex_v1_" + self.sid)
            if not self.mutex:
                fail("storage_unavailable")
            result = self.k.WaitForSingleObject(self.mutex, 0)
            self.acquired = result in (0, 0x80)
            if result != 0:
                fail("busy" if result == 0x102 else "storage_unavailable")
            self.root = win.storage(self.k, self.a, self.sid, self.sa, parts=["AI_WorckBook_Codex", "profiles-v1"])
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.acquired:
            self.k.ReleaseMutex(self.mutex)
        if self.mutex:
            self.k.CloseHandle(self.mutex)
        self.k.LocalFree(self.sd)

    def folder(self, pid, create=False):
        if not profile_id(pid):
            fail("profile_required")
        path = self.root / pid
        if not create and not path.is_dir():
            fail("profile_required")
        return win.secure_subdirectories(self.root, self.k, self.a, self.sid, self.sa, parts=[pid])

    def read(self, pid):
        path = self.folder(pid) / "profile.json"
        if not path.exists():
            return {"id": pid, "label": "Codex " + pid[6:14], "status": "disconnected", "sharing": False}
        if path.is_symlink() or path.stat().st_size > 4096:
            fail("storage_unavailable")
        saved = json.loads(path.read_text(encoding="utf-8"))
        return {"id": pid, "label": "Codex " + pid[6:14],
                "status": "connected" if saved.get("connected") is True else "disconnected",
                "sharing": saved.get("connected") is True, "cached": True}

    def save(self, pid, connected):
        path = self.folder(pid) / "profile.json"
        if path.is_symlink():
            fail("storage_unavailable")
        # Не копируем из Codex почту, идентификатор аккаунта, разрешения и токены.
        path.write_text(json.dumps({"connected": connected is True}), encoding="utf-8")

    def list(self):
        return [self.read(p.name) for p in sorted(self.root.iterdir()) if profile_id(p.name)]

    def paths(self, pid, create=False):
        parent = self.folder(pid, create)
        home = win.secure_subdirectories(parent, self.k, self.a, self.sid, self.sa, parts=["home"])
        cwd = win.secure_subdirectories(parent, self.k, self.a, self.sid, self.sa, parts=["empty-workspace"])
        # В пустой рабочий каталог не импортируем чужие настройки или файлы.
        if any(cwd.iterdir()) or any((home / name).exists() for name in ("auth.json", "config.toml", "AGENTS.md", "hooks.json", "skills", "plugins")):
            fail("codex_policy_unavailable")
        return home, cwd


def model_catalog(rpc):
    result, cursor, seen = [], None, set()
    for _ in range(10):
        page = rpc.request("model/list", {"cursor": cursor, "limit": 100, "includeHidden": False})
        for item in page.get("data", []):
            slug = item.get("model", item.get("id"))
            if isinstance(slug, str) and re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", slug):
                result.append({"id": slug, "label": str(item.get("displayName") or slug)[:200]})
        cursor = page.get("nextCursor")
        if not cursor:
            return result
        if not isinstance(cursor, str) or cursor in seen:
            fail("outcome_unknown")
        seen.add(cursor)
    fail("outcome_unknown")


def login(rpc, opener):
    attempt = rpc.request("account/login/start", {"type": "chatgpt"})
    rpc.login_id = attempt.get("loginId")
    url = attempt.get("authUrl", "")
    parsed = urlparse(url)
    if attempt.get("type") != "chatgpt" or not rpc.login_id or parsed.scheme != "https" or parsed.hostname not in {"auth.openai.com", "chatgpt.com"} or parsed.username or parsed.password or parsed.port not in (None, 443):
        fail("subscription_failed")
    opener(url)
    while True:
        event = rpc.event()
        if event.get("method") == "account/login/completed":
            data = event.get("params", {})
            if data.get("loginId") != rpc.login_id:
                continue
            rpc.login_id = None
            if data.get("success") is not True:
                fail("subscription_failed")
            return safe_auth(rpc.request("account/read", {"refreshToken": False}))


def generate(rpc, request, cwd):
    if request["model"] not in {model["id"] for model in model_catalog(rpc)}:
        fail("codex_model_unavailable")
    structured = request.get("response_schema") == "dewiar-actions-v1"
    started = rpc.request("thread/start", thread_params(request["model"], cwd, structured))
    rpc.thread_id = started.get("thread", {}).get("id")
    if not rpc.thread_id or started.get("model") != request["model"] or started.get("modelProvider") != "openai":
        fail("codex_policy_unavailable")
    from codex_policy import ACTION_SCHEMA
    turn = rpc.request("turn/start", {"threadId": rpc.thread_id,
                                     "input": [{"type": "text", "text": request["text"]}],
                                     **({"outputSchema": ACTION_SCHEMA} if structured else {}),
                                     "environments": []})
    rpc.turn_id = turn.get("turn", {}).get("id")
    if not rpc.turn_id:
        fail("outcome_unknown")
    items, seen = [], set()
    while True:
        event = rpc.event()
        method, data = event.get("method"), event.get("params", {})
        if data.get("threadId") != rpc.thread_id or data.get("turnId", rpc.turn_id) != rpc.turn_id:
            continue
        if method in {"item/started", "item/completed"}:
            item = data.get("item", {})
            if item.get("type") not in {"userMessage", "agentMessage", "reasoning"}:
                fail("codex_tools_denied")
            if method == "item/completed" and item.get("type") == "agentMessage":
                key = item.get("id")
                if key in seen or len(items) >= 128:
                    fail("outcome_unknown")
                seen.add(key)
                items.append(item)
        if method == "turn/completed":
            completed = data.get("turn", {})
            if completed.get("id") != rpc.turn_id or completed.get("error"):
                fail("outcome_unknown")
            answer = final_text(items, completed.get("status"))
            rpc.turn_id = None
            return {"text": answer, "completed": True, "profile": request["profile"], "transport": "codex"}


def execute(request, cancel, profiles_factory=Profiles, rpc_factory=Rpc, opener=os.startfile if os.name == "nt" else None):
    validate(request)
    if cancel.is_set():
        fail("cancelled")
    op = request["op"]
    if op == "health":
        try:
            executable()
            ready = True
        except Exception:
            ready = False
        return {"dependency_ready": ready, "transport": "codex", "network_called": False,
                "effective_upstream": "openai", "data_leaves_device": True, "protocol": 1,
                "auth_store": "OS keyring, separate profile", "live_verified": False}
    with profiles_factory() as profiles:
        if op == "profiles":
            return {"profiles": profiles.list(), "transport": "codex", "network_called": False}
        pid = request.get("profile") or "codex-" + uuid.uuid4().hex
        home, cwd = profiles.paths(pid, create=op == "login")
        rpc = rpc_factory(executable(), home, cwd, cancel, timeout=660 if op == "login" else 300)
        try:
            rpc.initialize()
            if op == "login":
                profiles.save(pid, False)
                data = login(rpc, opener)
                profiles.save(pid, True)
                return {**data, "profile": pid, "transport": "codex"}
            if op == "disconnect":
                rpc.request("account/logout")
                profiles.save(pid, False)
                return {"disconnected": True, "transport": "codex"}
            safe_auth(rpc.request("account/read", {"refreshToken": False}))
            if op == "models":
                return {"models": model_catalog(rpc), "transport": "codex"}
            return generate(rpc, request, cwd)
        finally:
            rpc.close()


def main():
    cancel = threading.Event()
    request = {}
    try:
        raw = sys.stdin.buffer.readline(256 * 1024 + 1)
        if len(raw) > 256 * 1024 or not raw.endswith(b"\n"):
            fail("invalid_request")
        request = json.loads(raw)
        validate(request)

        def control():
            while True:
                line = sys.stdin.buffer.readline(1024)
                if not line:
                    cancel.set()
                    return
                try:
                    message = json.loads(line)
                    if message.get("id") == request["id"] and message.get("op") == "cancel":
                        cancel.set()
                        return
                except Exception:
                    cancel.set()
                    return

        threading.Thread(target=control, name="codex-cancel", daemon=True).start()
        data = execute(request, cancel)
        if cancel.is_set():
            fail("cancelled")
        result = {"v": 1, "id": request["id"], "type": "result", "ok": True, "data": data}
    except Exception as exc:
        rid = request.get("id", "invalid") if isinstance(request, dict) else "invalid"
        result = {"v": 1, "id": rid, "type": "result", "ok": False,
                  "code": exc.code if isinstance(exc, SafeError) else "subscription_failed"}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    # Родитель управляет процессом; не завершаем Python с заблокированным stdin-потоком.
    os._exit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
