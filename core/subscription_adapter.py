"""Отдельный локальный маршрут подписки: команды интерфейса и жизненный цикл ответа.

Проверки выполняются до общего маршрута Dewiar. Контекстом управляет
subscription_context; транспорт и закрытое хранилище находятся в subscription_runtime.
"""
import importlib.util
from pathlib import Path
import threading

_RUNTIME = Path(__file__).resolve().parent / "subscription_runtime"
_spec = importlib.util.spec_from_file_location("workbook_subscription_ipc", _RUNTIME / "ipc_client.py")
_ipc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ipc)
MESSAGES, SubscriptionError = _ipc.MESSAGES, _ipc.SubscriptionError
invoke, is_subscription = _ipc.invoke, _ipc.is_subscription

def ui_command(action, args, host=None):
    """Чтение статуса не обновляет токены и не вызывает модель."""
    try:
        if action in {"confirm_get", "confirm_answer"}:
            box = getattr(host, "pending_confirm", None)
            if not box or box.get("source") != "subscription" or box["event"].is_set():
                return {"ok": True, "data": None}
            if action == "confirm_get":
                return {"ok": True, "data": {"id": box["id"], "text": box["text"]}}
            if args.get("id") != box["id"] or type(args.get("ok")) is not bool:
                raise SubscriptionError("invalid_request")
            box["answer"] = args["ok"]
            box["event"].set()
            return {"ok": True, "data": None}
        if action not in {"health", "profiles", "login", "models", "disconnect"}:
            raise SubscriptionError("invalid_request")
        transport = args.get("transport", "siwc")
        if transport not in {"siwc", "codex"}:
            raise SubscriptionError("invalid_request")
        data = invoke(action, profile=args.get("profile"), transport=transport,
                      network=action in {"login", "models", "disconnect"})
        return {"ok": True, "data": data}
    except SubscriptionError as exc:
        return {"ok": False, "code": exc.code, "error": str(exc)}
    except Exception:
        return {"ok": False, "code": "subscription_failed", "error": MESSAGES["subscription_failed"]}


def generate(profile, text, cancel, caller=invoke, response_schema=None):
    extra = {"response_schema": response_schema} if response_schema else {}
    result = caller("generate", profile=profile.get("subscription_profile_id"), model=profile.get("model"),
                    text=text, export=profile.get("subscription_export") is True,
                    usage=profile.get("subscription_usage_reviewed") is True, network=True, cancel=cancel,
                    transport=profile.get("subscription_transport", "siwc"), **extra)
    if result.get("completed") is not True or result.get("profile") != profile.get("subscription_profile_id"):
        raise SubscriptionError("outcome_unknown")
    if profile.get("subscription_transport") == "codex" and result.get("transport") != "codex":
        raise SubscriptionError("outcome_unknown")
    return result["text"]


def text_events(profile, system, messages, cancel=None, *, purpose=None, tools=None):
    """Явные текстовые потребители используют один транспорт, без наследования tools/fallback."""
    from subscription_context import ContextError, enabled, pack, ready, snapshot
    permissions = {"skill_draft": "auxiliary", "exam": "auxiliary", "meeting": "meeting",
                   "diary": "diary", "task_review": "task_review", "task_learning": "task_learning",
                   "history": "history"}
    labels = {"auxiliary": "служебные текстовые функции", "meeting": "встречи и суфлёр",
              "diary": "дневник", "task_review": "самопроверка задач",
              "task_learning": "уроки задач", "history": "история"}
    cancel = cancel if cancel is not None else threading.Event()
    parent_cancel = cancel
    current = profile.get("_subscription_current")
    signature = snapshot(profile)

    class ScopeCancel:
        def is_set(self):
            return parent_cancel.is_set() or (callable(current) and snapshot(current() or {}) != signature)

    cancel = ScopeCancel()
    ready(profile, cancel)
    capability = permissions.get(purpose)
    if not capability or not enabled(profile, capability):
        raise ContextError("Codex: включите разрешение «" + labels.get(capability, "отдельный поддерживаемый маршрут") +
                           "» в профиле. Неявный вызов модели не отправлен.")
    if tools:
        raise ContextError("Этот маршрут Codex принимает только текст. Инструменты вызываются отдельным контуром задач.")
    if not isinstance(system, str) or not isinstance(messages, list):
        raise ContextError("Codex: неподдерживаемый формат контекста.")
    for item in messages:
        if (not isinstance(item, dict) or set(item) - {"role", "content"}
                or item.get("role") not in {"user", "assistant", "system"} or not isinstance(item.get("content"), str)):
            raise ContextError("Codex: вложения и вызовы инструментов в текстовом маршруте запрещены.")
    prompt = pack({"purpose": purpose, "instructions": system, "messages": messages})
    answer = generate(profile, prompt, cancel)
    ready(profile, cancel)
    yield "text", answer


def start_turn(engine, text, images=None, quiet=False, via=None, raw=False, shown=None, report=None):
    """Ранний перехват до инструментов и истории; True означает обработанный запрос."""
    from subscription_context import chat_profile
    profile = chat_profile(engine)
    if not is_subscription(profile):
        return False
    if images or quiet or via is not None or raw or report is not None or shown is not None or "\n\nВложения:" in text:
        message = MESSAGES["unsupported_context"]
        engine.emit("error", text=message)
        if report:
            report(False, message)
        if via and callable(via.get("done")):
            via["done"](message)
        return True
    from engine_base import Turn
    with engine._turn_lock:
        engine._cancel_locked()
        engine.turn_n += 1
        turn = Turn(engine.turn_n)
        turn.asked, turn.persona, turn.back_to = text, engine.s.get("persona"), None
        engine.turn = turn
    engine.emit("heard", text=text)

    class ScopeCancel:
        def is_set(self):
            current = chat_profile(engine)
            from subscription_context import PROFILE_FIELDS
            fields = PROFILE_FIELDS
            return turn.cancel.is_set() or any(current.get(key) != profile.get(key) for key in fields)

    scope_cancel = ScopeCancel()

    def work():
        with engine._turn_lock:
            if engine.turn is not turn or turn.cancel.is_set():
                return
            engine.set_state("thinking")
        try:
            from subscription_context import chat_answer, ContextError
            answer = chat_answer(engine, profile, text, scope_cancel, generate)
            with engine._turn_lock:
                if engine.turn is not turn or scope_cancel.is_set():
                    return
                # Ответ показываем только после подтверждённого завершения транспорта.
                turn.full = answer
                engine.emit("answer", text=answer, done=True, model=True, sources=[])
        except (SubscriptionError, ContextError) as exc:
            if not turn.cancel.is_set():
                engine.emit("error", text=str(exc))
        except Exception:
            if not turn.cancel.is_set():
                engine.emit("error", text=MESSAGES["subscription_failed"])
        finally:
            with engine._turn_lock:
                if engine.turn is turn:
                    engine.turn = None
                    engine.follow_up_until = 0
                    engine.set_state("idle")
            # Общая история, обучение, инструменты, TTS и резервный провайдер не вызываются.

    threading.Thread(target=work, name=f"subscription-{turn.n}", daemon=True).start()
    return True
