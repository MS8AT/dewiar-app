"""Автономный клиент подписки, не запускающий ядро Dewiar.

Требует явный путь к локальному runtime и отдельные флаги передачи данных.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("op", choices=["health", "profiles", "login", "models", "generate", "disconnect"])
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--model")
    parser.add_argument("--transport", choices=["siwc", "codex"], default="codex")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--export-current-text", action="store_true")
    parser.add_argument("--usage-reviewed", action="store_true")
    args = parser.parse_args()
    # IPC-клиент входит в runtime: запуск Dewiar не требуется.
    spec = importlib.util.spec_from_file_location("ipc_client", args.runtime / "ipc_client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.invoke(args.op, profile=args.profile, model=args.model,
                               text=sys.stdin.read(32769) if args.op == "generate" else None,
                               export=args.export_current_text, usage=args.usage_reviewed,
                               network=args.allow_network, policy=lambda: not args.allow_network,
                               runtime=args.runtime, transport=args.transport)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
        return 0
    except module.SubscriptionError as exc:
        print(json.dumps({"ok": False, "code": exc.code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
