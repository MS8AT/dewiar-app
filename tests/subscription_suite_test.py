"""Автономные проверки подписки без входа, пользовательской памяти и запросов модели.

Запускаются отдельными процессами: подмены модулей в одном наборе не влияют
на другой. Windows-проверки явно пропускаются на других ОС, а не считаются пройденными.
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "core" / "subscription_runtime"


def main():
    tests = [ROOT / "tests" / "subscription_adapter_test.py",
             ROOT / "tests" / "subscription_routing_test.py",
             ROOT / "tests" / "subscription_context_test.py",
             ROOT / "tests" / "subscription_install_test.py",
             ROOT / "tests" / "subscription_upgrade_test.py",
             ROOT / "tests" / "brain_watch_test.py",
             ROOT / "tests" / "diagnostics_test.py",
             ROOT / "tests" / "diagnostic_cli_test.py",
             ROOT / "tests" / "fork_update_policy_test.py",
             RUNTIME / "test_codex.py", RUNTIME / "test_windows_store.py"]
    for test in tests:
        subprocess.run([sys.executable, "-B", str(test)], check=True, cwd=ROOT)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Для проверок интерфейса требуется Node.js")
    subprocess.run([node, "--test", str(ROOT / "tests" / "subscription.test.mjs"),
                    str(ROOT / "tests" / "brains.test.mjs"),
                    str(ROOT / "tests" / "fork_update_ui.test.mjs"),
                    str(ROOT / "tests" / "subscription_confirm.test.mjs"),
                    str(RUNTIME / "policy.test.mjs")], check=True, cwd=ROOT)
    print("ALL OK")


if __name__ == "__main__":
    main()
