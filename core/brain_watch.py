"""Локальное сердце мозгов: метаданные вызовов и задач, SQLite-журнал и свежесть сигналов.

Наблюдение не запускает модели, не проверяет сеть, не возобновляет задачи и не
считает успешный ответ приёмкой. Тексты, аргументы, ключи, адреса и ошибки не пишем.
Потеря сигнала означает неизвестный прогресс; после перезапуска исход не додумываем.
"""
from contextlib import contextmanager, closing
from contextvars import ContextVar
import functools
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

ROLES = {"chat", "tasks", "auxiliary", "meeting", "diary", "exam", "skill_draft", "task_review", "task_learning", "history"}
STATES = {"queued", "running", "waiting", "paused", "sleeping", "done", "failed", "stopped"}
TASK_ACTIONS = {"plan", "notebook", "memory_save", "project_list", "project_read",
                "human_memory_recall", "spawn_parts", "wait_parts", "pause", "finish"}
ACTION_STATES = {"accepted", "paused", "done", "blocked"}
_ledger = None
_current = ContextVar("dewiar_brain_call", default=None)


def tag(value):
    return hashlib.sha256(str(value or "unassigned").encode("utf-8")).hexdigest()[:16]


class Ledger:
    def __init__(self, path, settings=None, clock=time.time):
        self.path, self.settings, self.clock = Path(path), settings, clock
        self.session = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.last, self.tasks = {}, {}
        self.storage_error = False

    def enabled(self):
        return self.settings is None or self.settings.get("brain_watch", "journal") is not False

    @contextmanager
    def db(self):
        # Журнал принадлежит этому ПК; не открываем БД через подменённые ссылки.
        for p in (self.path, *self.path.parents):
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                raise OSError("journal path is not plain")
        if self.path.is_file() and self.path.stat().st_nlink > 1:
            raise OSError("journal has hardlinks")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=2)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at REAL, kind TEXT, ref TEXT, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, profile TEXT, role TEXT, session TEXT, started REAL, signal REAL, ended REAL, state TEXT)")
            with db:
                yield db

    def event(self, db, kind, ref, data):
        db.execute("INSERT INTO events(at,kind,ref,data) VALUES(?,?,?,?)", (self.clock(), kind, ref, json.dumps(data)))
        db.execute("DELETE FROM events WHERE seq NOT IN (SELECT seq FROM events ORDER BY seq DESC LIMIT 5000)")
        # Старые неизвестные исходы тоже ограничены; текущие незавершённые вызовы не удаляем.
        db.execute("DELETE FROM runs WHERE (ended IS NOT NULL OR session != ?) AND id NOT IN (SELECT id FROM runs ORDER BY started DESC LIMIT 500)", (self.session,))

    def start(self, profile, role):
        if not self.enabled():
            return None
        rid, at = uuid.uuid4().hex, self.clock()
        pid = tag(profile.get("_brain_id") or profile.get("id"))
        role = role if role in ROLES else "unknown"
        with self.lock, self.db() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", (rid, pid, role, self.session, at, at, None, "running"))
            self.event(db, "call_start", rid, {"profile": pid, "role": role})
        self.last[rid] = at
        return rid

    def signal(self, rid):
        if not rid or self.clock() - self.last.get(rid, 0) < 5:
            return
        with self.lock, self.db() as db:
            changed = db.execute("UPDATE runs SET signal=? WHERE id=? AND ended IS NULL", (self.clock(), rid)).rowcount
            if changed:
                self.event(db, "call_signal", rid, {})
        self.last[rid] = self.clock()

    def finish(self, rid, state):
        if not rid or state not in {"completed", "failed", "interrupted"}:
            return
        with self.lock, self.db() as db:
            changed = db.execute("UPDATE runs SET ended=?,state=? WHERE id=? AND ended IS NULL", (self.clock(), state, rid)).rowcount
            if changed:
                self.event(db, "call_" + state, rid, {})
        self.last.pop(rid, None)

    def task(self, task):
        if not self.enabled() or not isinstance(task, dict) or not task.get("id"):
            return
        state = task.get("status")
        if state not in STATES:
            return
        steps = task.get("steps", 0)
        steps = steps if type(steps) is int and 0 <= steps <= 1000000 else 0
        tid = tag(task["id"])
        fingerprint = (state, steps)
        with self.lock:
            if self.tasks.get(tid) == fingerprint:
                return
            with self.db() as db:
                self.event(db, "task_state", tid, {"state": state, "steps": steps})
            self.tasks[tid] = fingerprint
            if len(self.tasks) > 1000:
                self.tasks.pop(next(iter(self.tasks)))

    def quota(self, task, amount, limit):
        """Записать только факт продления, без имени, цели, профиля и текста задачи."""
        if (not self.enabled() or not isinstance(task, dict) or not task.get("id")
                or type(amount) is not int or not 1 <= amount <= 20
                or type(limit) is not int or not 1 <= limit <= 100):
            return
        with self.lock, self.db() as db:
            self.event(db, "task_quota_granted", tag(task["id"]), {"amount": amount, "limit": limit})

    def action(self, task, action, attempt, state):
        """Безопасный след шага Codex: только имя из закрытого списка и числа, без аргументов/ответа."""
        if (not self.enabled() or not isinstance(task, dict) or not task.get("id")
                or action not in TASK_ACTIONS or state not in ACTION_STATES
                or type(attempt) is not int or not 1 <= attempt <= 100):
            return
        with self.lock, self.db() as db:
            self.event(db, "task_action", tag(task["id"]),
                       {"action": action, "attempt": attempt, "state": state})

    def snapshot(self):
        now = self.clock()
        stale = self.settings.get("brain_watch", "stale_seconds") if self.settings else 90
        stale = stale if type(stale) is int and 30 <= stale <= 900 else 90
        out = {"observed_at": now, "journal": self.enabled(), "storage_error": self.storage_error,
               "stale_seconds": stale, "runs": [], "events": [], "acceptance": "unknown",
               "retention_events": 5000, "coverage": "instrumented_text_calls_and_task_events"}
        if not self.path.exists():
            return out
        with self.lock, self.db() as db:
            # Состояние незавершённых старых сессий не становится running после рестарта.
            for rid, pid, role, session, started, signal, ended, state in db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 100"):
                view = state if ended is not None else "outcome_unknown" if session != self.session else "no_fresh_signal" if now - signal > stale else "running"
                out["runs"].append({"id": rid, "profile": pid, "role": role, "started": started,
                                    "last_signal": signal, "ended": ended, "state": view,
                                    "elapsed_s": max(0, (ended if ended is not None else now) - started)})
            for seq, at, kind, ref, data in db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 100"):
                out["events"].append({"seq": seq, "at": at, "kind": kind, "ref": ref, **json.loads(data)})
        return out


def configure(settings):
    global _ledger
    from settings import STATE_DIR
    _ledger = Ledger(STATE_DIR / "brain-watch.sqlite3", settings)


def safe(method, *args):
    if _ledger is None:
        return None
    try:
        return getattr(_ledger, method)(*args)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        _ledger.storage_error = True
        return None


@contextmanager
def call(profile, role=None, cancel=None):
    if _current.get() is not None:
        yield _current.get()
        return
    rid = safe("start", profile or {}, role or (profile or {}).get("_brain_role", "unknown"))
    token = _current.set(rid)
    try:
        yield rid
    except BaseException as exc:
        safe("finish", rid, "interrupted" if isinstance(exc, (GeneratorExit, KeyboardInterrupt)) or (cancel and cancel.is_set()) else "failed")
        raise
    else:
        safe("finish", rid, "interrupted" if cancel and cancel.is_set() else "completed")
    finally:
        _current.reset(token)


def observed_stream(function):
    @functools.wraps(function)
    def wrapped(profile, *args, **kwargs):
        cancel = kwargs.get("cancel", args[2] if len(args) > 2 else None)
        with call(profile, kwargs.get("purpose"), cancel) as rid:
            for item in function(profile, *args, **kwargs):
                safe("signal", rid)
                yield item
    return wrapped


def observed_call(function):
    @functools.wraps(function)
    def wrapped(profile, text, cancel, *args, **kwargs):
        with call(profile, cancel=cancel):
            return function(profile, text, cancel, *args, **kwargs)
    return wrapped


def status(host):
    out = safe("snapshot") or {"storage_error": True, "runs": [], "events": [], "acceptance": "unknown"}
    profiles = host.s.get("llm", "profiles") or {}
    # Только локальное отображение: имена не сохраняются в журнал и не экспортируются.
    out["profiles"] = {tag(pid): str(p.get("name") or "Без названия")[:120] for pid, p in profiles.items()}
    out["tasks"] = [{"ref": tag(t.id), "state": t.status if t.status in STATES else "unknown"}
                    for t in list(getattr(getattr(host, "tasks", None), "tasks", {}).values())[:100]]
    return out
