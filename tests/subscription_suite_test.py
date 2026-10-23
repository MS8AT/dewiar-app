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
             ROOT / "tests" / "subscription_quota_test.py",
             ROOT / "tests" / "subscription_install_test.py",
             ROOT / "tests" / "subscription_upgrade_test.py",
             ROOT / "tests" / "subscription_brain_probe_test.py",
             ROOT / "tests" / "brain_watch_test.py",
             ROOT / "tests" / "diagnostics_test.py",
             ROOT / "tests" / "task_observability_test.py",
             ROOT / "tests" / "human_memory_contour_test.py",
             ROOT / "tests" / "task_directory_safety_test.py",
             ROOT / "tests" / "task_doctor_test.py",
             ROOT / "tests" / "task_doctor_flow_test.py",
             ROOT / "tests" / "tool_call_recovery_test.py",
             ROOT / "tests" / "tool_call_recovery_flow_test.py",
             ROOT / "tests" / "model_purpose_test.py",
             ROOT / "tests" / "diagnostic_cli_test.py",
             ROOT / "tests" / "fork_update_policy_test.py",
             ROOT / "tests" / "ms8at_release_gate_test.py",
             RUNTIME / "test_codex.py", RUNTIME / "test_windows_store.py"]
    for test in tests:
        subprocess.run([sys.executable, "-B", str(test)], check=True, cwd=ROOT)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Для проверок интерфейса требуется Node.js")
    # Node на Windows объединяет несколько абсолютных UNC-путей в один шаблон.
    # Отдельные относительные запуски одинаково работают с локальной и сетевой копией.
    node_tests = ["tests/subscription.test.mjs", "tests/brains.test.mjs", "tests/task_observability_ui.test.mjs",
                  "tests/fork_update_ui.test.mjs", "tests/subscription_confirm.test.mjs",
                  "tests/task_quota_ui.test.mjs", "core/subscription_runtime/policy.test.mjs"]
    for test in node_tests:
        subprocess.run([node, "--test", test], check=True, cwd=ROOT)
    print("ALL OK")


if __name__ == "__main__":
    main()
