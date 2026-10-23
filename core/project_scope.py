"""Закрытые корни и ограниченный список исходников; записи и сети нет."""
import os
from pathlib import Path, PurePosixPath

PROTECTED_ROOTS = {"pass", "private", "runtime"}


def protected(relative):
    parts = PurePosixPath(str(relative).replace("\\", "/")).parts
    return bool(parts) and parts[0].casefold() in PROTECTED_ROOTS


def walk(root, limit=5000, ignored=()):
    """Недоступная ветка не прерывает весь обзор; закрытые корни не перечисляются."""
    root = Path(root)
    out = []
    for directory, dirs, files in os.walk(root):
        top = Path(directory) == root
        dirs[:] = sorted(name for name in dirs if name not in ignored and not name.startswith(".dewiar")
                         and not (top and name.casefold() in PROTECTED_ROOTS))
        for name in sorted(files):
            out.append(PurePosixPath(Path(directory, name).relative_to(root).as_posix()))
            if len(out) >= limit:
                return out
    return out
