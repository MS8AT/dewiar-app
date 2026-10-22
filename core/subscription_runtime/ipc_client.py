"""Локальный stdio-клиент транспорта подписки для Dewiar и автономного запуска.

OAuth, история и токены здесь не обрабатываются. Ошибки наружу — только фиксированные.
"""
import json
import os
from pathlib import Path
import queue
import sys
import subprocess
import threading
import time
import uuid

KIND = "chatgpt_subscription"
MESSAGES = {
    "network_denied": "Включён local_only: передача в OpenAI запрещена.",
    "consent_required": "Подтвердите отправку текущего текста и проверьте лимиты/кредиты в ChatGPT Usage.",
    "profile_required": "Выберите отдельный аккаунт ChatGPT в настройках подписки.",
    "sharing_required": "Аккаунт не подключён или не дал доступ к плану. Повторите явный вход.",
    "busy": "С этим хранилищем аккаунтов уже работает другой локальный клиент. Дождитесь его завершения.",
    "storage_unavailable": "Защищённое хранилище Windows недоступно. Не переносите токены вручную.",
    "dependency_unavailable": "Локальная среда подписки не установлена или повреждена.",
    "cancelled": "Запрос отменён. Автоматического повтора не было.",
    "outcome_unknown": "Исход запроса не подтверждён. Не повторяйте автоматически; проверьте Usage и состояние аккаунта.",
    "unsupported_context": "Этот вход подписки принимает локальные текстовые сообщения без вложений и удалённых каналов. Память и задачи Codex включаются отдельными галочками в настройках.",
    "invalid_request": "Некорректный запрос к модулю подписки.",
    "subscription_failed": "Запрос по подписке не завершён. Проверьте аккаунт и ChatGPT Usage; автоматического повтора нет.",
    "codex_policy_unavailable": "Codex не подтвердил изоляцию текстового режима. Запрос заблокирован; настройки организации не обходятся.",
    "codex_tools_denied": "Codex запросил инструмент или дополнительное разрешение. В текстовом режиме это запрещено; запрос остановлен.",
    "codex_model_unavailable": "Выбранная модель отсутствует в каталоге Codex этого аккаунта. Обновите список моделей.",
}


class SubscriptionError(Exception):
    def __init__(self, code):
        self.code = code if code in MESSAGES else "subscription_failed"
        super().__init__(MESSAGES[self.code])


def is_subscription(profile):
    return isinstance(profile, dict) and profile.get("kind") == KIND


def local_only():
    import egress
    return egress.local_only()


def invoke(op, *, profile=None, model=None, text=None, export=False, usage=False,
           network=False, cancel=None, policy=local_only, runtime=None, transport="siwc", response_schema=None):
    """Сеть разрешается явной операцией интерфейса; процесс никогда не перезапускается."""
    root = Path(runtime) if runtime else Path(__file__).resolve().parent.parent / "subscription_runtime"
    node = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"
    if transport not in {"siwc", "codex"}:
        raise SubscriptionError("invalid_request")
    if response_schema is not None and (transport != "codex" or op != "generate" or response_schema != "dewiar-actions-v1"):
        raise SubscriptionError("invalid_request")
    if transport == "codex":
        command = [sys.executable, "-I", "-B", str(root / "codex_sidecar.py")]
        ready = (root / "codex_sidecar.py").is_file()
    else:
        command = [str(node), str(root / "sidecar.mjs")]
        ready = node.is_file() and (root / "sidecar.mjs").is_file()
    rid = uuid.uuid4().hex
    blocked = bool(policy())
    if op in {"login", "models", "generate", "disconnect"} and (blocked or not network):
        raise SubscriptionError("network_denied")
    if cancel is not None and cancel.is_set():
        raise SubscriptionError("cancelled")
    if not ready:
        raise SubscriptionError("dependency_unavailable")
    request = {"v": 1, "id": rid, "op": op, "local_only": blocked, "network": network}
    if profile:
        request["profile"] = profile
    if op == "generate":
        request.update(model=model, text=text, export_current_text=export is True, usage_reviewed=usage is True)
        if response_schema is not None:
            request["response_schema"] = response_schema
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("OPENAI_") and k.upper() not in {"NODE_OPTIONS", "NODE_PATH"}
           and not k.upper().endswith("_PROXY")}
    env["WORKBOOK_SIWC_PYTHON"] = sys.executable
    proc = subprocess.Popen(command, cwd=str(root),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env)
    events = queue.Queue(maxsize=2)

    def read_output():
        try:
            line = proc.stdout.readline(8 * 1024 * 1024 + 1)
            events.put_nowait(line)
        except Exception:
            try:
                events.put_nowait(b"")
            except queue.Full:
                pass

    threading.Thread(target=read_output, name="subscription-result", daemon=True).start()
    deadline = time.monotonic() + (660 if op == "login" else 300)
    cancelling = None
    try:
        # После создания процесса проверяем снова: запрос ещё не был отправлен.
        if network and policy():
            raise SubscriptionError("network_denied")
        proc.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        proc.stdin.flush()
        while True:
            now = time.monotonic()
            stop = (cancel is not None and cancel.is_set()) or (network and policy()) or now > deadline
            if stop and cancelling is None:
                cancelling = now
                proc.stdin.write((json.dumps({"v": 1, "id": rid, "op": "cancel"}) + "\n").encode())
                proc.stdin.flush()
            # Даём уже начатому обновлению сохранить заменённые учётные данные.
            if cancelling is not None and now - cancelling > 120:
                raise SubscriptionError("outcome_unknown")
            try:
                line = events.get(timeout=0.05)
            except queue.Empty:
                continue
            if not line or len(line) > 8 * 1024 * 1024:
                raise SubscriptionError("outcome_unknown")
            try:
                result = json.loads(line)
                if result.get("v") != 1 or result.get("id") != rid or result.get("type") != "result":
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise SubscriptionError("outcome_unknown") from None
            if cancelling is not None or (cancel is not None and cancel.is_set()):
                raise SubscriptionError("cancelled")
            if result.get("ok") is not True:
                raise SubscriptionError(result.get("code"))
            return result["data"]
    except (OSError, KeyError):
        raise SubscriptionError("outcome_unknown") from None
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Завершение только после результата IPC или сбоя, без автоповтора.
            proc.terminate()
            proc.wait(timeout=5)
        proc.stdout.close()
