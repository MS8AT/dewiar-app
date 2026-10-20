"""Остановить Dewiar перед установкой обновления: все его python/pythonw из папки установки (кроме себя).
Запускает установщик (packaging/windows/dewiar.nsi, STOP_DEWIAR) своим же Python из папки Dewiar. Раньше это делал
PowerShell с -ExecutionPolicy Bypass — антивирусы (Kaspersky, PDM:Trojan.Win32.Generic) видели в этом поведение вируса
и убирали Dewiar (комментарии к ролику, 20.10). Только стандартная библиотека и psutil, если он есть."""
import os
import sys
import time


def targets(inst, procs, me):
    """[pid] процессов python из папки inst. procs — [(pid, путь к exe)]; me — свой номер (себя не трогаем)."""
    root = os.path.normcase(os.path.abspath(inst)).rstrip("\\/") + os.sep
    out = []
    for pid, exe in procs:
        if pid == me or not exe:
            continue
        e = os.path.normcase(os.path.abspath(exe))
        if e.startswith(root) and os.path.basename(e) in ("python.exe", "pythonw.exe", "python", "pythonw"):
            out.append(pid)
    return out


def main(argv):
    if len(argv) < 2:
        return 2
    try:
        import psutil
    except ImportError:
        return 0                                     # без psutil — хватит остановки по номерам из ui.pid / core.pid
    procs = []
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            procs.append((p.info["pid"], p.info["exe"] or ""))
        except (psutil.Error, OSError):
            continue
    pids = targets(argv[1], procs, os.getpid())
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except (psutil.Error, OSError):
            pass
    if pids:
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
