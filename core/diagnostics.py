"""Пассивное диагностическое API поверх brain_watch и существующих настроек.

Только status/brains/journal/sli; команды не запускают модели, тесты сервера или вход.
Настройки и записи проецируются по белым спискам: имена, адреса, ключи и тексты не выходят.
SLI описывает ограниченную выборку журнала, не доступность сервиса и не выполнение SLA.
"""
import math
import re

import brain_watch
from version import VERSION

SCHEMA = 1
FORK = "MS8AT8DWiar"
LIMIT = 100
MAX_LATENCY_S = 7 * 86400
COVERAGE = "instrumented_text_calls_and_task_events"
ACTIONS = {"status", "brains", "journal", "sli"}
ROLES = ("chat", "tasks", "auxiliary", "meeting", "diary")
KINDS = {"openai", "ollama", "anthropic", "chatgpt_subscription"}
TASK_STATES = {"queued", "running", "waiting", "paused", "sleeping", "done", "failed", "stopped"}
EVENT_KINDS = {"call_start", "call_signal", "call_completed", "call_failed", "call_interrupted",
               "task_state", "task_quota_granted"}
TERMINAL = {"completed", "failed", "interrupted"}
PERMISSIONS = ("export", "usage_reviewed", "history", "memory_read", "memory_write", "tasks",
               "project_read", "task_review", "task_learning", "auxiliary", "meeting", "diary")


def _enum(value, allowed, default="unknown"):
    return value if isinstance(value, str) and value in allowed else default


def _number(value, maximum=253402300799):
    return value if type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value) else None


def _ref(value):
    # Уже хешированные ID и случайные ID вызовов; произвольную строку не отражаем.
    return value if isinstance(value, str) and re.fullmatch(r"(?:[a-f0-9]{16}|[a-f0-9]{32})", value) else None


def _rows(snapshot, key):
    rows = snapshot.get(key)
    if not isinstance(rows, list):
        return [], 1
    return rows[:LIMIT], 0


def _snapshot(host):
    try:
        snapshot = brain_watch.status(host)
        return snapshot if isinstance(snapshot, dict) else {}
    except Exception:  # noqa: BLE001 — диагностический ответ не раскрывает текст внутренней ошибки
        return {}


def _observer(snapshot):
    storage_error = snapshot.get("storage_error") is not False
    enabled = snapshot.get("journal") if type(snapshot.get("journal")) is bool else None
    coverage = COVERAGE if snapshot.get("coverage") == COVERAGE else "unknown"
    at = _number(snapshot.get("observed_at"))
    state = ("unavailable" if storage_error else "paused" if enabled is False else
             "partial" if enabled is None or coverage == "unknown" or at is None else "observing")
    return {"state": state, "observed_at": at, "journal_enabled": enabled,
            "storage_error": storage_error, "coverage": coverage}


def _tasks(snapshot):
    rows, invalid = _rows(snapshot, "tasks")
    counts = dict.fromkeys(sorted(TASK_STATES) + ["unknown"], 0)
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        state = _enum(row.get("state"), TASK_STATES)
        counts[state] += 1
        invalid += state == "unknown"
    return {"sample_limit": LIMIT, "sampled": sum(counts.values()), "invalid_records": invalid, "counts": counts}


def _brains(host):
    try:
        profiles = host.s.get("llm", "profiles")
        active = host.s.get("llm", "active")
        routes = host.s.get("llm", "routes")
        tasks = host.s.get("tasks", "llm")
    except Exception:  # noqa: BLE001 — никаких содержимых настроек/ошибок в ответе
        return {"state": "unavailable", "profiles": [], "bindings": {}, "sample_limit": LIMIT}
    if not isinstance(profiles, dict):
        return {"state": "unavailable", "profiles": [], "bindings": {}, "sample_limit": LIMIT}
    invalid = 0
    if not isinstance(routes, dict):
        invalid += routes is not None
        routes = {}
    bindings = {}
    for role in ROLES:
        choice = active if role == "chat" else tasks if role == "tasks" else routes.get(role)
        explicit = role == "chat" or choice not in (None, "")
        selected = choice if explicit else active
        if selected in (None, ""):
            state, ref = "unassigned", None
        elif not isinstance(selected, str):
            state, ref = "invalid", None
            invalid += 1
        else:
            state = "configured" if isinstance(profiles.get(selected), dict) else "missing"
            ref = brain_watch.tag(selected)
        bindings[role] = {"ref": ref, "selection": "explicit" if explicit else "inherited", "state": state}
    result = []
    for pid, profile in list(profiles.items())[:LIMIT]:
        if not isinstance(pid, str) or not pid or not isinstance(profile, dict):
            invalid += 1
            continue
        kind = _enum(profile.get("kind"), KINDS)
        ref = brain_watch.tag(pid)
        result.append({"ref": ref, "kind": kind, "active": pid == active,
                       "roles": [role for role, binding in bindings.items() if binding["ref"] == ref and binding["state"] == "configured"],
                       "configured_model": isinstance(profile.get("model"), str) and bool(profile["model"].strip()),
                       "subscription_permissions": {key: profile.get("subscription_" + key) is True for key in PERMISSIONS}
                       if kind == "chatgpt_subscription" else None})
    return {"state": "partial" if invalid else "configured", "profiles": result, "bindings": bindings,
            "sample_limit": LIMIT, "profiles_total": len(profiles), "truncated": len(profiles) > LIMIT,
            "invalid_records": invalid}


def _journal(snapshot):
    rows, invalid = _rows(snapshot, "events")
    events = []
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        kind = _enum(row.get("kind"), EVENT_KINDS)
        seq, at, ref = row.get("seq"), _number(row.get("at")), _ref(row.get("ref"))
        if kind == "unknown" or type(seq) is not int or not 1 <= seq <= 2 ** 63 - 1 or at is None or ref is None:
            invalid += 1
            continue
        event = {"seq": seq, "at": at, "kind": kind, "ref": ref}
        if kind == "call_start":
            event.update(profile=_ref(row.get("profile")), role=_enum(row.get("role"), brain_watch.ROLES))
        elif kind == "task_state":
            steps = row.get("steps")
            event.update(state=_enum(row.get("state"), TASK_STATES),
                         steps=steps if type(steps) is int and 0 <= steps <= 1000000 else None)
        elif kind == "task_quota_granted":
            amount, limit = row.get("amount"), row.get("limit")
            event.update(amount=amount if type(amount) is int and 1 <= amount <= 20 else None,
                         limit=limit if type(limit) is int and 1 <= limit <= 100 else None)
        events.append(event)
    return {"events": events, "sample_limit": LIMIT, "invalid_records": invalid,
            "window": "latest_retained_events_not_full_history"}


def _sli(snapshot):
    rows, invalid = _rows(snapshot, "runs")
    counts = dict.fromkeys(("completed", "failed", "interrupted", "unknown", "running"), 0)
    durations, starts = [], []
    invalid_durations = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        state = _enum(row.get("state"), TERMINAL | {"running"})
        start, end = _number(row.get("started")), _number(row.get("ended"))
        if start is not None:
            starts.append(start)
        if state in TERMINAL and (start is None or end is None or end < start):
            state = "unknown"
            invalid += 1
        if state == "running" and (start is None or row.get("ended") is not None):
            state = "unknown"
            invalid += 1
        counts[state] += 1
        if state in TERMINAL:
            elapsed = _number(row.get("elapsed_s"), MAX_LATENCY_S)
            if elapsed is not None and abs(elapsed - (end - start)) <= 0.01:
                durations.append(elapsed)
            else:
                invalid_durations += 1
    durations.sort()
    observer = _observer(snapshot)
    trustworthy = not observer["storage_error"]
    denominator = counts["completed"] + counts["failed"]
    def percentile(part):
        return durations[max(0, math.ceil(len(durations) * part) - 1)] if durations and trustworthy else None
    state = ("unknown" if not trustworthy else "partial" if observer["state"] != "observing" or invalid or counts["unknown"] or invalid_durations
             else "observed_sample" if sum(counts.values()) else "no_data")
    return {"state": state,
            "sample_limit": LIMIT, "sampled": sum(counts.values()), "counts": counts,
            "window": "latest_retained_runs_not_time_window", "started_from": min(starts) if starts else None,
            "started_to": max(starts) if starts else None, "invalid_records": invalid,
            "success_ratio": counts["completed"] / denominator if trustworthy and denominator else None,
            "success_denominator": denominator, "success_definition": "completed/(completed+failed)",
            "latency_s": {"sampled": len(durations), "p50": percentile(0.5), "p95": percentile(0.95),
                          "method": "nearest_rank", "scope": "completed_failed_interrupted", "invalid_records": invalid_durations},
            "availability": "not_measured", "sla": "not_evaluated", "acceptance": "unknown"}


def dispatch(host, action, args=None):
    """JSON-совместимый ответ без побочных вызовов; параметры пока не принимаются.

    Новые действия добавляются явно, не пробрасываются в Engine.command. Даже
    исключение чтения превращается в неизвестное состояние, а не зелёный ноль.
    """
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("Неизвестное действие диагностики")
    if args is not None and (not isinstance(args, dict) or args):
        raise ValueError("Диагностика не принимает параметры")
    out = {"schema": SCHEMA, "fork": FORK, "version": VERSION, "action": action}
    if action == "brains":
        return dict(out, **_brains(host))
    snapshot = _snapshot(host)
    out["observer"] = _observer(snapshot)
    if action == "status":
        from fork_update_policy import status as update_status
        out.update(tasks=_tasks(snapshot), model_access="not_checked", acceptance="unknown")
        out["updates"] = update_status()
    elif action == "journal":
        out.update(_journal(snapshot))
    else:
        out.update(_sli(snapshot))
    return out
