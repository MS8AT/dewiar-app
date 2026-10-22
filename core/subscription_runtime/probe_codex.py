"""Офлайн-проверка протокола CLI в новом пустом временном профиле.

Вход, обновление токенов, model/list, thread/start и inference не вызываются.
Вывод содержит только признаки совместимости, без сырых журналов и настроек.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_rpc import Rpc, child_environment, nested, verify_config
from codex_policy import CONFIG, SafeError
from codex_sidecar import executable


def main():
    with tempfile.TemporaryDirectory(prefix="dewiar-codex-probe-") as directory:
        root = Path(directory)
        home, cwd = root / "home", root / "empty"
        home.mkdir(); cwd.mkdir()
        # Дополнительная защита этой проверки: HTTP через закрытый loopback.
        # В новом профиле нет учётных данных; account RPC не отправляется.
        env = child_environment(home)
        env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9", NO_PROXY="")
        real_popen = subprocess.Popen
        initialized, compatible, failure, config = False, False, None, {}
        with tempfile.TemporaryFile() as diagnostics:
            def spawn(*args, **kwargs):
                kwargs["stderr"] = diagnostics
                return real_popen(*args, **kwargs)
            with patch("codex_rpc.child_environment", return_value=env), patch("codex_rpc.subprocess.Popen", side_effect=spawn):
                rpc = Rpc(executable(), home, cwd, threading.Event(), timeout=20)
                try:
                    rpc.request("initialize", {"clientInfo": {"name": "ai_worckbook_offline_probe", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}})
                    initialized = True
                    rpc.send({"method": "initialized", "params": {}})
                    config = rpc.request("config/read", {"includeLayers": False}).get("config", {})
                    verify_config({"config": config})
                    compatible = True
                except SafeError as error:
                    failure = error.code
                finally:
                    rpc.close()
            diagnostics.seek(0)
            error_lines = diagnostics.read(8192).decode("utf-8", errors="replace").splitlines()[:20]
        differences = [key for key, value in CONFIG.items() if nested(config, key) != value]
        # Показываем имена несовпавших полей, но не значения системной конфигурации.
        print(json.dumps({"exit": rpc.proc.returncode, "initialize": initialized, "policy_verified": compatible, "failure": failure,
                          "config_read": bool(config), "differences": differences,
                          "extra_config": {key: bool(config.get(key)) for key in ("mcp_servers", "plugins", "hooks", "model_providers", "openai_base_url", "chatgpt_base_url")},
                          "schema_error_count": len(error_lines), "home_entries": sorted(p.name for p in home.iterdir()), "live_login": False, "model_calls": 0,
                          "remote_http_proxy": "blocked-loopback", "key_copied": False}, ensure_ascii=False))
        return 0 if compatible else 2


if __name__ == "__main__":
    sys.exit(main())
