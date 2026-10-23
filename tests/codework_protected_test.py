"""Закрытые корни и один недоступный файл не ломают подготовку задачи по коду."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
from codework import CodeWork, _walk  # noqa: E402


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="u", GIT_AUTHOR_EMAIL="u@x",
               GIT_COMMITTER_NAME="u", GIT_COMMITTER_EMAIL="u@x")
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", env=env)


def ok(value, message):
    if not value:
        raise AssertionError(message)
    print("PASS:", message)


with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    project, work = base / "project", base / "work"
    project.mkdir()
    (project / "README.md").write_text("visible", encoding="utf-8")
    for name in ("Pass", "Private", "Runtime"):
        (project / name).mkdir()
        (project / name / "secret.env").write_text("must-not-copy", encoding="utf-8")

    files = {str(p) for p in _walk(project)}
    ok(files == {"README.md"}, "обзор исключает Pass, Private и Runtime")

    git(project, "init", "-q")
    git(project, "add", "README.md")
    git(project, "commit", "-qm", "initial")
    code = CodeWork(project, work)
    code.prepare()
    ok((work / "README.md").is_file(), "tracked source copied")
    ok(not any((work / name).exists() for name in ("Pass", "Private", "Runtime")),
       "protected untracked roots never copied")
    ok(code.mode.get("mode") == "git", "git baseline completed")

print("ALL OK")
