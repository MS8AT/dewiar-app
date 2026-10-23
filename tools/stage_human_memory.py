"""Stage the exact Python import closure of an existing Human Memory facade locally.

Copies source only. Credentials, configurations and the existing database stay
at their original paths. Does not register MCP or run the staged code.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_closure(package):
    """Resolve only relative imports inside ai_new_memory, without executing source."""
    pending, found = ["", "config", "human_memory"], {}
    while pending:
        module = pending.pop()
        if module in found:
            continue
        relative = Path(*module.split(".")) if module else Path()
        source = package / relative.with_suffix(".py") if module else package / "__init__.py"
        is_package = False
        if not source.is_file():
            source = package / relative / "__init__.py"
            is_package = True
        if not source.is_file():
            raise ValueError("relative source import unavailable")
        found[module] = source
        prefix = module.split(".") if is_package else module.split(".")[:-1]
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = prefix[:len(prefix) - node.level + 1]
                if node.module:
                    pending.append(".".join(base + node.module.split(".")))
                else:
                    pending.extend(".".join(base + [item.name]) for item in node.names)
    return sorted(set(found.values()))


def stage(workspace, destination, adapter):
    workspace, destination = Path(workspace).resolve(), Path(destination).absolute()
    if os.name == "nt":
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(destination.anchor) != 3:
            raise ValueError("destination must be local")
    service = workspace / "Source/c_HUMAN_MEMORY/service.py"
    package = workspace / "Source/c_AI_SEMANTIC_MEMORY/09_runtime/src/ai_new_memory"
    sources = [service, *python_closure(package)]
    rows = [{"path": p.relative_to(workspace).as_posix(), "sha256": sha(p)} for p in sources]
    rows.append({"path": "human_memory_stdio.py", "sha256": sha(adapter)})
    identity = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
    target = destination / ("source-" + identity)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-worckbook-stage-") as temporary:
        staging = Path(temporary)
        for source, row in zip([*sources, adapter], rows):
            copied = staging / row["path"]
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
            if sha(source) != row["sha256"] or sha(copied) != row["sha256"]:
                raise ValueError("source changed while staging")
        if target.exists():
            if not all((target / row["path"]).is_file() and sha(target / row["path"]) == row["sha256"] for row in rows):
                raise ValueError("existing local bundle differs")
        else:
            shutil.copytree(staging, target)
        receipt = {"schema": 1, "source": str(workspace), "target": str(target), "files": rows,
                   "hashes_verified": True, "key_copied": False, "database_copied": False,
                   "network_code_executed": False}
    receipt["temporary_stage_removed"] = not staging.exists()
    (target / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, default=Path(__file__).resolve().parents[1] / "core/human_memory_stdio.py")
    args = parser.parse_args()
    result = stage(args.workspace, args.destination, args.adapter)
    print(json.dumps(result, ensure_ascii=False))
