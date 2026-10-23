"""Полный исходный выпуск Dewiar с дополнением, без замены Python и пользовательских данных.

План привязан к SHA каждого файла закрытого приложения и точной базе Git.
Запись и проверяемый откат используют те же правила, что install_local_codex.
Неизвестные файлы, колёса и скачанные модели не удаляются; приложение не запускается.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

import install_local_codex as installer

SOURCE = Path(__file__).resolve().parents[1]
BASE = "24a3d6c22142b623081478a121d396d7e42741c1"
RELEASE = "0.39.7"
ROOTS = ("core", "ui", "data", "icons", "requirements-win.lock")
REQUIRED = {"core/version.py", "core/main.py", "ui/app.py", "ui/settings.html", "requirements-win.lock"}
TESTS = {"core/subscription_runtime/policy.test.mjs", "core/subscription_runtime/test_codex.py",
         "core/subscription_runtime/test_windows_store.py"}


def git(source, *args):
    return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True,
                          encoding="utf-8", timeout=60).stdout


def payload(source):
    """Выпуск целиком плюс только файлы проверенного дополнения, не весь checkout."""
    addon = installer.entries(source / "tools/local_codex_manifest.json")
    allowed = {item["path"] for item in addon}
    changed = set(git(source, "diff", "--name-only", BASE, "--", *ROOTS).splitlines())
    untracked = set(git(source, "ls-files", "--others", "--exclude-standard", "--", *ROOTS).splitlines())
    if not ((changed | untracked) - TESTS) <= allowed:
        raise ValueError("Правки вне проверенного дополнения")
    for item in addon:
        if installer.digest(installer.plain(source / item["path"])) != item["after"]:
            raise ValueError("Дополнение не соответствует манифесту")
    names = set(git(source, "ls-tree", "-r", "--name-only", BASE, "--", *ROOTS).splitlines()) | allowed
    if not REQUIRED <= names:
        raise ValueError("Неполный выпуск")
    version = (source / "core/version.py").read_text(encoding="utf-8")
    if not re.search(rf'^VERSION\s*=\s*[\'"]{re.escape(RELEASE)}[\'"]', version, re.MULTILINE):
        raise ValueError("Неверная версия")
    # Маркер версии меняется последним: незавершённая запись не выдаётся за новый выпуск.
    return sorted(names - {"core/version.py"}) + ["core/version.py"]


def read_plan(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("kind") != "dewiar-full-source-release" or data.get("base") != BASE
            or data.get("release") != RELEASE or not 5 <= len(data.get("files", [])) <= 1000):
        raise ValueError("Неверный план выпуска")
    seen = set()
    for item in data["files"]:
        name = item.get("path", "")
        parts = name.split("/")
        if (not re.fullmatch(r"(?:core|ui|data|icons)/[A-Za-z0-9_./-]+|requirements-win[.]lock", name)
                or any(p in {"", ".", ".."} or p.endswith(".") for p in parts)
                or name.lower() in seen):
            raise ValueError("Неверный или повторный путь")
        seen.add(name.lower())
        for key in ("before", "after"):
            value = item.get(key)
            if not (key == "before" and value is None) and not re.fullmatch(r"[a-f0-9]{64}", value or ""):
                raise ValueError("Неверный SHA-256")
    if not REQUIRED <= seen or data["files"][-1]["path"] != "core/version.py":
        raise ValueError("Неполный комплект или неверный порядок")
    return data


def prepare(app, plan, source=SOURCE):
    if not app.is_dir() or plan.exists():
        raise ValueError("Нужно приложение и новый файл плана")
    names = payload(source)
    lock = "requirements-win.lock"
    if installer.digest(app / lock) != installer.digest(source / lock):
        raise ValueError("Зависимости различаются: требуется отдельное обновление Python")
    files = [{"path": name, "before": installer.digest(installer.plain(app / name)),
              "after": installer.digest(installer.plain(source / name))} for name in names]
    data = {"kind": "dewiar-full-source-release", "base": BASE, "release": RELEASE,
            "app": str(app), "files": files}
    # Проверка общим переносчиком до сохранения плана; неизвестные extras не затрагиваются.
    installer.transfer("check", app, None, source, files=files)
    with plan.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    return len(files)


def execute(mode, app, backup, plan, source=SOURCE):
    data = read_plan(plan)
    if data["app"] != str(app) or [item["path"] for item in data["files"]] != payload(source):
        raise ValueError("План относится к другому приложению или комплекту")
    installer.transfer(mode, app, backup, source, files=data["files"])
    return len(data["files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "check", "install", "rollback"), default="check")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--closed", action="store_true")
    args = parser.parse_args()
    try:
        source, app, plan = (installer.local(p) for p in (SOURCE, args.app, args.plan))
        backup = installer.local(args.backup) if args.backup else None
        if any(plan == p or p in plan.parents for p in (app, source)):
            raise ValueError("План должен быть вне приложения и checkout")
        if args.mode in {"install", "rollback"}:
            if not args.closed:
                raise ValueError("Закройте Dewiar и передайте --closed")
            installer.stopped()
        count = prepare(app, plan, source) if args.mode == "plan" else execute(args.mode, app, backup, plan, source)
        print(f"PASS: {args.mode}; release={RELEASE}; files={count}; model_calls=0")
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("REFUSED: план/комплект/зависимости/пути или процессы не прошли проверку. "
              "При прерванной установке не запускайте приложение; используйте тот же план и backup для rollback.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
