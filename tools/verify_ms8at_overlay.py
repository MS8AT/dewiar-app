"""Детерминированно проверяет отдельный overlay MS8AT; сеть и модели не используются."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "integrations" / "ms8at" / "overlay.json"
TOP_KEYS = {"schema", "product", "overlay_id", "upstream", "fork", "payload_manifest",
            "integration_prompt", "runtime_roots", "source_only_paths", "features",
            "required_tests", "update_policy"}
UPDATE_KEYS = {"release_source", "apply", "auto_download_requested", "effective", "blocked_until"}
SHA = re.compile(r"[a-f0-9]{64}")
SAFE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


def fail(message):
    raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(value):
    if not isinstance(value, str) or not SAFE.fullmatch(value) or any(
            part in {"", ".", ".."} for part in value.split("/")):
        fail("небезопасный путь overlay")
    return value


def git(root, *args, text=False, check=True):
    run = subprocess.run(["git", "-C", str(root), *args], check=check,
                         capture_output=True, text=text, timeout=60)
    return run.stdout


def descriptor(path=OVERLAY):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != TOP_KEYS or data.get("schema") != 1 or data.get("product") != "MS8AT8DWiar":
        fail("неверная схема overlay")
    if data.get("overlay_id") != "ms8at-dewiar-integrations":
        fail("неверный идентификатор overlay")
    upstream = data.get("upstream")
    fork = data.get("fork")
    if (not isinstance(upstream, dict) or set(upstream) != {"version", "commit"}
            or not re.fullmatch(r"0[.]\d+[.]\d+", upstream.get("version", ""))
            or not re.fullmatch(r"[a-f0-9]{40}", upstream.get("commit", ""))
            or not isinstance(fork, dict) or set(fork) != {"build"}
            or type(fork.get("build")) is not int or fork["build"] < 1):
        fail("неверная база или build overlay")
    for key in ("payload_manifest", "integration_prompt"):
        safe_path(data.get(key))
    for key in ("runtime_roots", "source_only_paths", "required_tests"):
        values = data.get(key)
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            fail("пустой или повторный список overlay")
        for value in values:
            safe_path(value)
    features = data.get("features")
    if (not isinstance(features, list) or not features or len(features) != len(set(features))
            or any(not re.fullmatch(r"[a-z0-9_]+", item) for item in features)):
        fail("неверные features overlay")
    policy = data.get("update_policy")
    if (not isinstance(policy, dict) or set(policy) != UPDATE_KEYS
            or policy.get("apply") != "verified_release_on_normal_exit"
            or type(policy.get("auto_download_requested")) is not bool
            or policy.get("effective") is not False
            or not isinstance(policy.get("blocked_until"), list)
            or len(policy["blocked_until"]) < 4):
        fail("неверная политика обновления overlay")
    return data


def verify(root=ROOT, overlay=OVERLAY):
    root = root.resolve()
    data = descriptor(overlay)
    base = data["upstream"]["commit"]
    git(root, "cat-file", "-e", base + "^{commit}")
    version_text = (root / "core" / "version.py").read_text(encoding="utf-8")
    if not re.search(r'^VERSION\s*=\s*[\'\"]' + re.escape(data["upstream"]["version"])
                     + r'[\'\"]', version_text, re.MULTILINE):
        fail("версия исходников не совпадает с overlay")
    policy_text = (root / "core" / "fork_update_policy.py").read_text(encoding="utf-8")
    if not re.search(r"^BUILD\s*=\s*" + str(data["fork"]["build"]) + r"\s*$",
                     policy_text, re.MULTILINE):
        fail("build исходников не совпадает с overlay")

    manifest_path = root / data["payload_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("version") != 1 or manifest.get("upstream") != base or not isinstance(files, list):
        fail("манифест payload относится к другой базе")
    seen = set()
    paths = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "before", "after"}:
            fail("неверная запись payload")
        name = safe_path(item["path"])
        folded = name.casefold()
        if folded in seen or not name.startswith(("core/", "ui/")):
            fail("повторный или чужой runtime-путь")
        seen.add(folded)
        paths.add(name)
        current = root / name
        if not current.is_file() or not SHA.fullmatch(item.get("after") or ""):
            fail("нет runtime-файла или after SHA")
        if digest(current.read_bytes()) != item["after"]:
            fail("after SHA не совпадает: " + name)
        probe = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{base}:{name}"],
                               capture_output=True, timeout=60)
        before = digest(git(root, "show", f"{base}:{name}")) if probe.returncode == 0 else None
        if item.get("before") != before:
            fail("before SHA не совпадает: " + name)

    changed = set(filter(None, git(root, "diff", "--name-only", base, "--",
                                   *data["runtime_roots"], text=True).splitlines()))
    allowed = paths | set(data["source_only_paths"])
    if changed != allowed:
        fail("runtime diff не совпадает с декларацией: " + ", ".join(sorted(changed ^ allowed)))
    required = [data["integration_prompt"], *data["required_tests"]]
    if any(not (root / safe_path(path)).is_file() for path in required):
        fail("не найден промпт или обязательный тест")
    prompt = (root / data["integration_prompt"]).read_text(encoding="utf-8")
    if "Текст модели не является полномочием" not in prompt or "effective=false" not in prompt:
        fail("промпт не фиксирует границу полномочий")
    return {"ok": True, "product": data["product"], "upstream": data["upstream"],
            "build": data["fork"]["build"], "runtime_files": len(paths),
            "auto_update_effective": data["update_policy"]["effective"], "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--overlay", type=Path, default=OVERLAY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.root, args.overlay)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
              if args.json else "REFUSED: " + str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)
          if args.json else f"PASS: overlay; upstream={result['upstream']['version']}; "
          f"build={result['build']}; runtime_files={result['runtime_files']}; model_calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
