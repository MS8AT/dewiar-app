"""Явный выбор мозга для текстовых контуров, поверх существующего реестра llm.profiles.

Пустое назначение наследует основной мозг. Удалённый назначенный профиль даёт
отказ, а не скрытый переход на другой аккаунт. Здесь нет сети и запуска моделей.
"""
import copy

ROLES = {"tasks": "Задачи", "auxiliary": "Черновики навыков", "meeting": "Встречи и суфлёр", "diary": "Дневник"}
CAPS = {"tasks": "tasks", "auxiliary": "auxiliary", "meeting": "meeting", "diary": "diary"}


def needs_probe(before, after):
    """Добавление второго мозга и переименование не проверяют активную модель за счёт пользователя."""
    def chosen(llm):
        p = (llm.get("profiles") or {}).get(llm.get("active")) or {}
        return {k: v for k, v in p.items() if k != "name"}
    return before.get("active") != after.get("active") or chosen(before) != chosen(after)


def profile(settings, role):
    if role not in ROLES:
        raise ValueError("Неизвестный контур мозга")
    routes = settings.get("llm", "routes") or {}
    selected = (settings.get("tasks", "llm") if role == "tasks" else routes.get(role)) or ""
    pid = selected or settings.get("llm", "active") or ""
    profiles = settings.get("llm", "profiles") or {}
    if pid and pid not in profiles:
        return {"kind": "unavailable", "_route_missing": True, "_brain_id": pid, "_brain_role": role}
    if not pid:
        return None
    result = copy.deepcopy(profiles[pid])
    result.update(id=pid, _brain_id=pid, _brain_role=role)
    result["_subscription_current"] = lambda: profile(settings, role) or {}
    return result


def update(settings, routes):
    """Назначение не включает разрешения профиля и не запускает сохранённые задачи."""
    if not isinstance(routes, dict) or not set(routes) <= set(ROLES):
        raise ValueError("Неизвестные назначения мозгов")
    profiles = settings.get("llm", "profiles") or {}
    for role, pid in routes.items():
        if not isinstance(pid, str) or (pid and pid not in profiles):
            raise ValueError("Выбранный профиль отсутствует")
        p = profiles.get(pid, {})
        if p.get("kind") == "chatgpt_subscription":
            if (p.get("subscription_transport") != "codex" or not p.get("model") or not p.get("subscription_profile_id")
                    or p.get("subscription_export") is not True or p.get("subscription_usage_reviewed") is not True
                    or p.get("subscription_" + CAPS[role]) is not True):
                raise ValueError("Сначала выберите аккаунт/модель Codex и разрешите этот контур, отправку текста и Usage в профиле")
    patch = {"llm": {"routes": {k: v for k, v in routes.items() if k != "tasks"}}}
    if "tasks" in routes:
        patch["tasks"] = {"llm": routes["tasks"]}
    settings.update(patch)
    return settings.snapshot()
