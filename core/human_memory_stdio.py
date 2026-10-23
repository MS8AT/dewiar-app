"""Малый stdio-адаптер существующего Human Memory: health и ограниченный recall.

Использует локальную проверенную копию фасада; хранилище остаётся внешним.
Не требует пакета mcp, не создаёт БД и не вызывает модель.
"""
import argparse
import json
import os
from pathlib import Path
import sys

TOOLS = [
    {"name": "human_memory_health", "description": "Read-only Human Memory connection health.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "human_memory_recall", "description": "Read bounded memory for an explicit task/session/object/keys/time scope.",
     "inputSchema": {"type": "object", "properties": {"request": {"type": "object"}},
                     "required": ["request"], "additionalProperties": False}},
]
for _tool in TOOLS:
    _tool["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


def dispatch(message, service):
    """Один JSON-RPC запрос; ошибки не раскрывают paths, входные данные или цитаты."""
    if not isinstance(message, dict) or "id" not in message:
        return None
    result = {"jsonrpc": "2.0", "id": message["id"]}
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        result["result"] = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "dewiar-human-memory", "version": "1.0"}}
    elif method == "ping":
        result["result"] = {}
    elif method == "tools/list":
        result["result"] = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            if not isinstance(params, dict) or set(params) - {"name", "arguments", "_meta"}:
                raise ValueError()
            name, args = params.get("name"), params.get("arguments") or {}
            if name == "human_memory_health" and args == {}:
                data = service.health()
            elif name == "human_memory_recall" and isinstance(args, dict) and set(args) == {"request"} and isinstance(args["request"], dict):
                data = service.recall(args["request"])
            else:
                raise ValueError()
            text = json.dumps(data, ensure_ascii=False, allow_nan=False)
            if len(text.encode("utf-8")) > 128000:
                raise ValueError()
            result["result"] = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception:
            result["result"] = {"content": [{"type": "text", "text": "Human Memory: request or source unavailable"}], "isError": True}
    else:
        result["error"] = {"code": -32601, "message": "method not supported"}
    return result


def load_service(directory):
    directory = Path(directory).absolute()
    if os.name == "nt":
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(directory.anchor) != 3:
            raise ValueError("service must be staged on a local disk")
    for part in (directory, *directory.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("service path must be plain")
    if not (directory / "service.py").is_file():
        raise ValueError("service unavailable")
    sys.path.insert(0, str(directory))
    from service import MemoryService
    return MemoryService()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-dir", required=True)
    args = parser.parse_args()
    service = load_service(args.service_dir)
    for line in sys.stdin:
        if len(line.encode("utf-8")) > 128000:
            continue
        try:
            reply = dispatch(json.loads(line), service)
        except (ValueError, TypeError, RecursionError):
            reply = None
        if reply is not None:
            print(json.dumps(reply, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
