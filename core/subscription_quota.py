"""Подтверждаемое продление локальной квоты ограниченной задачи Codex.

Продление не запускает модель и не сбрасывает число уже сделанных попыток. Оно
доступно только исчерпавшей лимит остановленной задаче с тем же профилем и набором
разрешений. Каждая выдача подтверждается человеком и остаётся в журналах.
"""
import threading


DEFAULT_LIMIT = 5
MAX_GRANT = 20
MAX_TOTAL = 100
STOPPED = {"paused", "stopped", "failed"}


def profile_limit(profile):
    """Исходный лимит профиля: только 1..20, даже если профиль импортирован вручную."""
    value = profile.get("subscription_task_limit", DEFAULT_LIMIT)
    return value if type(value) is int and 1 <= value <= MAX_GRANT else None


def _base_limit(data):
    binding = data.get("subscription_binding")
    if not isinstance(binding, dict):
        return None
    # Старые snapshot всегда содержат ключ со значением None, если пользователь
    # не менял штатный лимит. Для привязанной исторической задачи это default=5.
    value = binding.get("subscription_task_limit")
    if value is None:
        value = DEFAULT_LIMIT
    return value if type(value) is int and 1 <= value <= MAX_GRANT else None


def effective_limit(task, profile):
    """Полный лимит задачи: исходный профиль плюс подтверждённые продления."""
    stored = task.data.get("subscription_request_limit")
    if stored is not None:
        return stored
    return profile_limit(profile)


def status(task):
    """Безопасная проекция квоты для UI; не содержит аккаунт, цель или текст задачи."""
    data = task.data
    base = _base_limit(data)
    if base is None:
        return None
    used = data.get("subscription_attempts", 0)
    total = data.get("subscription_request_limit", base)
    if type(used) is not int or used < 0 or type(total) is not int or not 1 <= total <= MAX_TOTAL:
        return {"valid": False, "used": None, "limit": None, "remaining": None,
                "exhausted": False, "can_grant": False, "grant_default": None,
                "max_limit": MAX_TOTAL}
    grant = min(base, MAX_GRANT, MAX_TOTAL - total)
    thread = getattr(task, "thread", None)
    stopped = data.get("status") in STOPPED and not (thread is not None and thread.is_alive())
    return {"valid": True, "used": used, "limit": total, "remaining": max(0, total - used),
            "exhausted": used >= total, "can_grant": stopped and used >= total and grant > 0,
            "grant_default": grant if grant > 0 else None, "max_limit": MAX_TOTAL}


def grant(manager, task, amount=DEFAULT_LIMIT):
    """После локального подтверждения расширить бюджет; модель и задачу не запускать."""
    import brain_watch
    import subscription_context as context

    if type(amount) is not int or not 1 <= amount <= MAX_GRANT:
        raise context.ContextError("Можно выдать от 1 до 20 дополнительных запросов Codex.")
    thread = getattr(task, "thread", None)
    if task.data.get("status") not in STOPPED or (thread is not None and thread.is_alive()):
        raise context.ContextError("Продлевать лимит можно только у остановленной задачи.")
    current = context.task_profile(manager.host)
    current_base = profile_limit(current)
    if current_base is None:
        raise context.ContextError("Лимит Codex в текущем профиле должен быть целым числом от 1 до 20.")
    binding = task.data.get("subscription_binding")
    if not isinstance(binding, dict) or not context.codex(binding):
        raise context.ContextError("У задачи нет привязанного профиля Codex.")
    if context.snapshot(binding) != context.snapshot(current):
        raise context.ContextError("Профиль или разрешения изменились. Создайте новую задачу; квота не перенесена.")
    if not context.enabled(current, "tasks"):
        raise context.ContextError("В этом профиле выключены фоновые задачи Codex.")
    before = status(task)
    if not before or not before["valid"] or not before["exhausted"]:
        raise context.ContextError("Текущий лимит задачи ещё не исчерпан или повреждён.")
    if before["limit"] + amount > MAX_TOTAL:
        raise context.ContextError("Общий лимит одной задачи не может превышать 100 запросов Codex.")

    question = (f"Выдать этой задаче ещё {amount} запросов Codex?\n"
                f"Уже использовано: {before['used']} из {before['limit']}.\n"
                "Запросы могут расходовать лимит подписки или кредиты. "
                "Продление будет записано в локальный журнал, задача сама не запустится.")
    cancel = threading.Event()
    if not context.confirm_local(manager.host, question, cancel):
        raise context.ContextError("Продление лимита Codex не подтверждено.")

    # start() использует тот же per-task lock: состояние нельзя изменить между
    # повторной проверкой и сохранением. Старый Task без lock безопасно не бывает
    # в текущем процессе, но fallback сохраняет совместимость тестовых объектов.
    lock = getattr(task, "control_lock", threading.RLock())
    with lock:
        thread = getattr(task, "thread", None)
        current = context.task_profile(manager.host)
        fresh_binding = task.data.get("subscription_binding")
        fresh = status(task)
        registry = getattr(manager, "tasks", None)
        deleted = isinstance(registry, dict) and registry.get(task.data.get("id")) is not task
        if (deleted or task.data.get("status") not in STOPPED
                or (thread is not None and thread.is_alive())
                or not isinstance(fresh_binding, dict)
                or context.snapshot(fresh_binding) != context.snapshot(current)
                or not fresh or not fresh["valid"] or fresh["limit"] != before["limit"]
                or not fresh["exhausted"]):
            raise context.ContextError("Состояние задачи изменилось во время подтверждения; квота не выдана.")

        total = before["limit"] + amount
        missing = object()
        changed_keys = ("subscription_request_limit", "subscription_quota_grants", "error", "updated")
        old_values = {key: task.data.get(key, missing) for key in changed_keys}
        task.data["subscription_request_limit"] = total
        task.data["subscription_quota_grants"] = total - _base_limit(task.data)
        task.data["error"] = ""
        try:
            task.save()
        except (OSError, TypeError, ValueError) as exc:
            # Откатываем только поля этой операции: параллельно полученный inbox
            # или иной независимый прогресс задачи не должен исчезнуть.
            for key, value in old_values.items():
                if value is missing:
                    task.data.pop(key, None)
                else:
                    task.data[key] = value
            raise context.ContextError("Не удалось сохранить продление квоты Codex; изменение отменено.") from exc
        try:
            task.journal(f"Квота Codex продлена человеком: +{amount}; использовано {before['used']} из {total}.")
        except OSError:
            # Не переписываем основной receipt второй раз: событие останется в
            # обезличенном heartbeat ниже, без риска повредить сохранённый JSON.
            pass
    brain_watch.safe("quota", task.data, amount, total)
    manager._emit(task)
    return status(task)
