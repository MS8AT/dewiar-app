"""Установка локального дополнения Codex поверх точной базы Dewiar.

По умолчанию только проверка. Меняются лишь файлы манифеста; настройки и входы
не затрагиваются. Частично завершённая установка допускает проверяемый откат.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
MANIFEST = SOURCE / "tools" / "local_codex_manifest.json"


def digest(path):
    if path.exists() and not path.is_file():
        raise ValueError("Вместо файла обнаружен каталог")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def plain(path):
    """Запрещаем ссылки в любом компоненте пути и файлы с несколькими hardlink."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Ссылки и junction запрещены")
        if part.is_file() and part.stat().st_nlink > 1:
            raise ValueError("Файл имеет несколько hardlink")
    return path


def local(path):
    path = plain(path)
    if os.name != "nt" or str(path).startswith("\\\\"):
        raise ValueError("Установщик поддерживает только локальные диски Windows")
    import ctypes
    if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) != 3:
        raise ValueError("Требуется фиксированный локальный диск")
    return path


def entries(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not 1 <= len(data.get("files", [])) <= 100:
        raise ValueError("Неверный манифест")
    seen = set()
    for item in data["files"]:
        name = item.get("path", "")
        if (not re.fullmatch(r"(core|ui)/[A-Za-z0-9_./-]+", name)
                or any(p in {"", ".", ".."} for p in name.split("/")) or name in seen):
            raise ValueError("Неверный или повторный путь манифеста")
        seen.add(name)
        for key in ("before", "after"):
            if not (key == "before" and item.get(key) is None) and not re.fullmatch(r"[a-f0-9]{64}", item.get(key, "")):
                raise ValueError("Неверный SHA-256")
    return data["files"]


def stopped():
    """Не завершаем процессы: при запущенном или непроверяемом Dewiar отказываем."""
    command = ("$ErrorActionPreference='Stop'; "
               "$p=@(Get-CimInstance Win32_Process | Where-Object {"
               f"$_.ProcessId -ne {os.getpid()} -and ("
               "$_.Name -match '^Dewiar.*[.]exe$' -or "
               r"($_.Name -match '^python(w)?[.]exe$' -and $_.CommandLine -match 'Dewiar[\\/]'))}); "
               "if($p.Count){exit 2}")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("Закройте Dewiar, включая трей; проверка процессов должна завершиться успешно")


def replace(source, target):
    """Заменяем один проверенный файл, без промежуточного усечённого содержимого."""
    plain(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".codex-install-", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def transfer(mode, app, backup, source=SOURCE, manifest=MANIFEST, *, files=None):
    """Все проверки комплекта выполняются до первой записи; пути проверяет CLI."""
    files = entries(manifest) if files is None else files
    if not app.is_dir() or not source.is_dir():
        raise ValueError("Каталог приложения или исходников отсутствует")
    if app == source or app in source.parents or source in app.parents:
        raise ValueError("Исходники и приложение должны быть отдельными каталогами")
    if backup is not None and any(backup == p or backup in p.parents or p in backup.parents for p in (app, source)):
        raise ValueError("Резервная копия должна быть вне приложения и исходников")
    if mode == "rollback":
        if backup is None or not backup.is_dir():
            raise ValueError("Укажите каталог резервной копии")
        receipt = plain(backup / "receipt.json")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if saved != {"app": str(app), "files": files}:
            raise ValueError("Резервная копия относится к другой установке или версии")
        for item in files:
            current = digest(plain(app / item["path"]))
            if current not in (item["before"], item["after"]):
                raise ValueError("Файлы изменены после установки; автоматический откат запрещён")
            if item["before"] is not None and digest(plain(backup / item["path"])) != item["before"]:
                raise ValueError("Повреждена резервная копия")
        for item in files:
            target = app / item["path"]
            if item["before"] is None:
                if target.exists():
                    target.unlink()
            else:
                replace(backup / item["path"], target)
        return "base"
    for item in files:
        if digest(plain(source / item["path"])) != item["after"]:
            raise ValueError("Комплект исходников не соответствует манифесту")
    current = [digest(plain(app / item["path"])) for item in files]
    is_base = all(value == item["before"] for value, item in zip(current, files))
    is_installed = all(value == item["after"] for value, item in zip(current, files))
    if mode == "check":
        if is_base:
            return "base"
        if is_installed:
            return "installed"
        raise ValueError("Смешанная, неизвестная или локально изменённая версия")
    if not is_base:
        raise ValueError("Неизвестная версия или локальные правки; установка запрещена")
    if mode != "install" or backup is None or backup.exists():
        raise ValueError("Для установки нужен новый каталог резервной копии")
    backup.mkdir(parents=True)
    for item in files:
        if item["before"] is not None:
            target = backup / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(app / item["path"], target)
            if digest(target) != item["before"]:
                raise ValueError("Не удалось проверить резервную копию")
    with (backup / "receipt.json").open("x", encoding="utf-8") as stream:
        json.dump({"app": str(app), "files": files}, stream, ensure_ascii=False, indent=2)
    for item in files:
        # Повторная сверка защищает от изменившейся базы; при сбое нужен ручной откат.
        if digest(plain(app / item["path"])) != item["before"]:
            raise ValueError("База изменилась во время установки; используйте проверяемый откат")
        replace(source / item["path"], app / item["path"])
        if digest(app / item["path"]) != item["after"]:
            raise ValueError("Проверка установленного файла не прошла")
    return "installed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check", "install", "rollback"), default="check")
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--closed", action="store_true", help="Подтверждение штатного закрытия Dewiar")
    args = parser.parse_args()
    try:
        local(SOURCE)
        app = local(args.app)
        backup = local(args.backup) if args.backup else None
        if args.mode != "check":
            if not args.closed:
                raise ValueError("Сначала закройте Dewiar и передайте --closed")
            stopped()
        state = transfer(args.mode, app, backup)
        print("PASS: " + args.mode + "; state=" + state + "; настройки, аккаунты и сеть не затронуты")
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("REFUSED: проверка не пройдена. Требуется чистая база 0.40.0, локальные пути, "
              "неизменённый комплект и закрытый Dewiar; детали см. docs/LOCAL_CODEX_RU.md. "
              "После прерванной записи используйте --mode rollback с той же копией.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
