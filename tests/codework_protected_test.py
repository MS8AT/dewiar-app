"""Закрытые корни и один недоступный файл не ломают подготовку задачи по коду."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

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

with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    project, work = base / "project", base / "work"
    project.mkdir()
    (project / "README.md").write_text("visible", encoding="utf-8")
    (project / "locked.txt").write_text("unreadable", encoding="utf-8")
    for name in ("Pass", "Private", "Runtime"):
        (project / name).mkdir()
        (project / name / "hidden.txt").write_text("must-not-copy", encoding="utf-8")

    copytree, copy2 = shutil.copytree, shutil.copy2

    def copy_file(src, dst, **kwargs):
        if Path(src).name == "locked.txt":
            raise PermissionError("test: access denied")
        return copy2(src, dst, **kwargs)

    def copy_project(*args, **kwargs):
        return copytree(*args, **dict(kwargs, copy_function=copy_file))

    with patch("codework.shutil.copytree", side_effect=copy_project):
        code = CodeWork(project, work)
        code.prepare()
    ok((work / "README.md").read_text(encoding="utf-8") == "visible",
       "copy mode keeps readable files after access denial")
    ok(not (work / "locked.txt").exists(), "unreadable file is skipped")
    ok(not any((work / name).exists() for name in ("Pass", "Private", "Runtime")),
       "partial copy still excludes protected roots")
    ok(code.mode.get("mode") == "copy", "partial copy has a completed baseline")
    ok("README.md" in code.list(""), "task can list the remaining project")

print("ALL OK")
