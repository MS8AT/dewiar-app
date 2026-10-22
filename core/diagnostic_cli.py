"""Локальная CLI диагностики поверх существующего WebSocket API ядра.

Тесты и описание API работают без запущенного Dewiar. Чтение состояния требует
локального токена, но не выдаёт настройки, события разговора или команды модели.
Удалённый адрес, произвольная команда и передача токена в аргументах не поддержаны.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ACTIONS = ("status", "brains", "journal", "sli")


def schema():
    return {"schema": 1, "transport": "ws://127.0.0.1:<port>", "authentication": "local token file; never print",
            "hello": {"cmd": "hello", "scope": "diagnostics", "token": "<read from protected file>"},
            "request": {"id": 1, "cmd": "diagnostics_read", "args": {"action": "status", "args": {}}},
            "actions": list(ACTIONS), "side_effects": "read-only metadata; no model/probe/download"}


def read_token(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("token_unavailable")
    if not path.is_file() or path.stat().st_size > 1024 or path.stat().st_nlink != 1:
        raise ValueError("token_unavailable")
    token = path.read_text(encoding="ascii").strip()
    if not 24 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("token_unavailable")
    return token


def request(action, token_file, port=8765, timeout=10, connect=None):
    if action not in ACTIONS or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_request")
    token = read_token(token_file)
    if connect is None:
        from websockets.sync.client import connect
    deadline = time.monotonic() + timeout
    with connect(f"ws://127.0.0.1:{port}", open_timeout=timeout, close_timeout=1,
                 max_size=512 * 1024, proxy=None) as ws:
        ws.send(json.dumps({"cmd": "hello", "scope": "diagnostics", "token": token}))
        hello = json.loads(ws.recv(timeout=max(.01, deadline - time.monotonic())))
        # Старое ядро присылает полный hello. Не показываем его и не продолжаем.
        if hello.get("type") != "hello" or hello.get("data") != {"limited": True, "scope": "diagnostics"}:
            raise ValueError("diagnostic_scope_unavailable")
        ws.send(json.dumps({"id": 1, "cmd": "diagnostics_read", "args": {"action": action, "args": {}}}))
        reply = json.loads(ws.recv(timeout=max(.01, deadline - time.monotonic())))
        if reply.get("type") != "reply" or reply.get("id") != 1 or reply.get("ok") is not True:
            raise ValueError("diagnostic_request_failed")
        data = reply.get("data")
        if not isinstance(data, dict) or data.get("schema") != 1 or data.get("action") != action:
            raise ValueError("invalid_diagnostic_reply")
        return data


def selftest():
    """Малый installed smoke: свои временные данные, без Settings/token/HTTP/моделей."""
    import tempfile
    from brain_watch import Ledger
    from brain_routes import needs_probe
    def require(condition):
        if not condition:
            raise RuntimeError("offline_check_failed")
    checks = []
    with tempfile.TemporaryDirectory(prefix="dewiar-diagnostics-") as temp:
        ledger = Ledger(Path(temp) / "watch.sqlite3", clock=lambda: 1000)
        require(ledger.snapshot()["runs"] == [])
        require(not ledger.path.exists())
        checks.append("empty_observer_has_no_write")
        rid = ledger.start({"id": "synthetic"}, "chat")
        ledger.finish(rid, "completed")
        require(ledger.snapshot()["runs"][0]["state"] == "completed")
        require(ledger.snapshot()["acceptance"] == "unknown")
        checks.append("completed_is_not_acceptance")
        ledger.finish(rid, "failed")
        require(ledger.snapshot()["runs"][0]["state"] == "completed")
        checks.append("terminal_absorbs_late_finish")
        other = ledger.start({"id": "synthetic"}, "tasks")
        require(other)
        restarted = Ledger(ledger.path)
        require(any(r["state"] == "outcome_unknown" for r in restarted.snapshot()["runs"]))
        checks.append("restart_outcome_unknown")
    before = {"active": "a", "profiles": {"a": {"kind": "openai", "name": "A"}}}
    after = {"active": "a", "profiles": {"a": {"kind": "openai", "name": "B"}, "b": {"kind": "openai"}}}
    require(not needs_probe(before, after))
    checks.append("rename_and_add_do_not_probe")
    return {"schema": 1, "action": "test", "status": "PASS", "checks": checks, "model_calls": 0,
            "network_calls": 0, "coverage": "installed_offline_smoke_not_full_suite_or_live_acceptance"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(*ACTIONS, "api", "test"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", type=Path, help="Файл локального токена; значение не выводится")
    args = parser.parse_args(argv)
    try:
        if args.action == "api":
            data = schema()
        elif args.action == "test":
            data = selftest()
        else:
            if args.token_file is None:
                from settings import TOKEN_PATH
                args.token_file = TOKEN_PATH
            data = request(args.action, args.token_file, args.port)
        print(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (Exception, KeyboardInterrupt):
        # Исключения транспорта могут включать данные сервера/путь/token. Не печатаем.
        print(json.dumps({"schema": 1, "status": "UNAVAILABLE", "error": "diagnostics_failed",
                          "hint": "Проверьте локальное ядро новой версии, token-file и порт; API/test работают offline."}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
