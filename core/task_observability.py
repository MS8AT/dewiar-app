"""Read-only API карточки задачи: квота, дерево и безопасный журнал heartbeat.

Никаких целей, промптов, ответов, путей, имён аккаунтов и аргументов действий.
Этот модуль не запускает модель, не продолжает задачу и не проверяет сеть.
"""
import math

import brain_watch

SCHEMA = 1
LIMIT = 100
STATES = brain_watch.STATES | {"unknown"}
EVENTS = {"task_state", "task_quota_granted", "task_action"}


def _number(value, maximum=253402300799):
    return value if type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value) else None


def _integer(value, maximum=1000000):
    return value if type(value) is int and 0 <= value <= maximum else None


def _quota(task):
    if not task.data.get("subscription_binding"):
        return None
    try:
        from subscription_quota import status
        item = status(task)
    except Exception:  # noqa: BLE001 - диагностика не отражает внутреннюю ошибку
        return {"state": "unavailable"}
    if not isinstance(item, dict):
        return {"state": "unavailable"}
    allowed = {"valid", "limit", "used", "remaining", "exhausted", "can_grant", "grant_default", "max_limit"}
    result = {key: item.get(key) for key in allowed if key in item}
    if any(type(result.get(key)) is not int or not 0 <= result[key] <= 100
           for key in ("limit", "used", "remaining", "grant_default", "max_limit") if key in result and result[key] is not None):
        return {"state": "unavailable"}
    for key in ("valid", "exhausted", "can_grant"):
        if key in result and type(result[key]) is not bool:
            return {"state": "unavailable"}
    return {"state": "available" if result.get("valid") is True else "invalid", **result}


def _child(task):
    return {"ref": brain_watch.tag(task.id),
            "state": task.status if task.status in STATES else "unknown",
            "steps": _integer(task.data.get("steps")),
            "quota": _quota(task)}


def _event(row):
    if not isinstance(row, dict) or row.get("kind") not in EVENTS:
        return None
    seq, at = row.get("seq"), _number(row.get("at"))
    if type(seq) is not int or not 1 <= seq <= 2 ** 63 - 1 or at is None:
        return None
    out = {"seq": seq, "at": at, "kind": row["kind"]}
    if row["kind"] == "task_state":
        out.update(state=row.get("state") if row.get("state") in STATES else "unknown",
                   steps=_integer(row.get("steps")))
    elif row["kind"] == "task_quota_granted":
        amount, limit = row.get("amount"), row.get("limit")
        out.update(amount=amount if type(amount) is int and 1 <= amount <= 20 else None,
                   limit=limit if type(limit) is int and 1 <= limit <= 100 else None)
    else:
        out.update(action=row.get("action") if row.get("action") in brain_watch.TASK_ACTIONS else "unknown",
                   attempt=row.get("attempt") if type(row.get("attempt")) is int and 1 <= row["attempt"] <= 100 else None,
                   state=row.get("state") if row.get("state") in brain_watch.ACTION_STATES else "unknown")
    return out


def view(host, task):
    """JSON-совместимая проекция одной задачи. Все ID хешируются."""
    try:
        snapshot = brain_watch.status(host)
    except Exception:  # noqa: BLE001
        snapshot = {}
    ref = brain_watch.tag(task.id)
    rows = snapshot.get("events") if isinstance(snapshot, dict) else None
    events = []
    invalid = 0
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("ref") == ref:
                item = _event(row)
                if item is None:
                    invalid += 1
                else:
                    events.append(item)
                if len(events) + invalid >= LIMIT:
                    break
    else:
        invalid = 1
    children = [_child(child) for child in getattr(host.tasks, "tasks", {}).values()
                if child.data.get("parent") == task.id][:LIMIT]
    binding = task.data.get("subscription_binding")
    profile_ref = None
    if isinstance(binding, dict):
        pid = binding.get("id") or binding.get("subscription_profile_id")
        profile_ref = brain_watch.tag(pid) if isinstance(pid, str) and pid else None
    state = task.status if task.status in STATES else "unknown"
    observed_at = _number(snapshot.get("observed_at")) if isinstance(snapshot, dict) else None
    journal_enabled = snapshot.get("journal") if isinstance(snapshot, dict) and type(snapshot.get("journal")) is bool else None
    storage_error = snapshot.get("storage_error") is not False if isinstance(snapshot, dict) else True
    observer_state = ("unavailable" if storage_error else "paused" if journal_enabled is False else
                      "observing" if journal_enabled is True and observed_at is not None else "unknown")
    try:
        from human_memory_contour import public_scope, status as memory_status
        memory = {"scope": public_scope(task), "connector": memory_status(host)}
    except Exception:  # noqa: BLE001
        memory = {"scope": {"enabled": False}, "connector": {"state": "unavailable", "read_only": True}}
    return {"schema": SCHEMA, "api": "task_observe", "read_only": True,
            "coverage": "task_state_quota_and_codex_actions", "task_ref": ref,
            "parent_ref": brain_watch.tag(task.data["parent"]) if isinstance(task.data.get("parent"), str) and task.data["parent"] else None,
            "state": state, "steps": _integer(task.data.get("steps")), "human_memory": memory,
            "codex": {"enabled": isinstance(binding, dict), "profile_ref": profile_ref,
                      "attempts": _integer(task.data.get("subscription_attempts"), 100), "quota": _quota(task)},
            "children": children, "events": events, "invalid_records": invalid,
            "observer": {"state": observer_state, "observed_at": observed_at, "journal_enabled": journal_enabled,
                         "storage_error": storage_error},
            "privacy": "no_prompts_responses_arguments_paths_account_names_or_secrets"}
