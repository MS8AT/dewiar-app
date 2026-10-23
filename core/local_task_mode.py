"""Явное продолжение изучения проекта на своей модели, с прежней карточкой и журналом."""
import copy
import ipaddress
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

READ_TOOLS = {"update_plan", "log", "ask_user", "finish", "remember", "notes", "code_list", "code_read"}
STUDY_REVIEW = ("Проверь обзор изученного проекта. Результат этой задачи — содержательный текст со ссылками на "
                "прочитанные источники и ограничениями проверки. Исходники изменять не требуется. "
                "Не требуй diff, команд или новых файлов. Оцени соответствие цели и фактам. "
                "Ответь JSON: {\"verdict\":\"ok\"} или {\"verdict\":\"revise\",\"problems\":\"конкретная проблема\"}.")


def is_local(profile):
    """Только явный loopback/RFC1918 адрес; облачный профиль не становится локальным по имени."""
    if not isinstance(profile, dict) or profile.get("kind") not in {"openai", "ollama"}:
        return False
    try:
        url = urlsplit(profile.get("base_url") or "")
        if url.scheme not in {"http", "https"} or url.username or url.password or url.query or url.fragment:
            return False
        if url.hostname == "localhost":
            return True
        addr = ipaddress.ip_address(url.hostname or "")
        return addr.is_loopback or any(addr in ipaddress.ip_network(net) for net in
                                       ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
    except (ValueError, TypeError):
        return False


def task_profile(host, task):
    """Профиль привязанной локальной задачи, без наследования активного Codex."""
    pid = task.data.get("local_profile_id")
    if not pid:
        return host.llm_profile()
    profile = (host.s.get("llm", "profiles") or {}).get(pid)
    if not is_local(profile):
        raise ValueError("Локальная модель задачи удалена или её адрес изменён. Выберите свой сервер заново.")
    return dict(profile, id=pid, _brain_id=pid, _brain_role="tasks")


def select(manager, task, profile_id):
    """Сменить исполнителя остановленной задачи. Модель этим вызовом не запускается."""
    with task.control_lock:
        if task.data.get("status") not in {"paused", "stopped", "failed", "done"} or (task.thread and task.thread.is_alive()):
            raise ValueError("Сначала остановите задачу.")
        profile = (manager.host.s.get("llm", "profiles") or {}).get(profile_id)
        if not is_local(profile):
            raise ValueError("Выберите локальный или LAN-профиль модели.")
        previous = copy.deepcopy(task.data)
        if task.data.get("subscription_binding"):
            task.data["previous_codex"] = {key: copy.deepcopy(task.data[key]) for key in (
                "subscription_binding", "subscription_attempts", "subscription_request_limit", "subscription_quota_grants")
                if key in task.data}
            task.data.pop("subscription_binding", None)
        task.data.update(local_profile_id=profile_id, local_read_only=True, local_context_reset=True,
                         local_read_files=[], status="paused", error="", question="", wait_reason="",
                         wake_at="", auto_resume=False, finished=False, finish_checked=False, critic_done=False)
        try:
            task.save()
        except Exception:
            task.data.clear()
            task.data.update(previous)
            raise
        task.journal("🧠 Выбрана локальная модель: " + str(profile.get("model") or "автовыбор") +
                     ". Изучение проекта: чтение, план и итог; история Codex сохранена. Для запуска нажмите «Продолжить».")
    manager._emit(task)
    return task.public()


def read_project(task, name, args):
    """Обзор без клонирования всего проекта и без доступа к закрытым корням."""
    from subscription_context import ContextError, project_action
    try:
        if name == "code_list":
            pattern = str(args.get("pattern") or ".").replace("\\", "/")
            path = str(PurePosixPath(pattern).parent) if any(c in pattern for c in "*?[") else pattern.rstrip("/")
            return project_action(task, "project_list", path or ".") or "В этом каталоге нет доступных исходников."
        relative = str(args.get("path") or "")
        if PureWindowsPath(relative).drive or PureWindowsPath(relative).is_absolute() or relative.startswith("/"):
            return "Ошибка пути: нужен относительный путь от корня проекта, например README_RU.md или Source/AI_MASTER.md. Не добавляйте папку задачи."
        relative = relative.replace("\\", "/")
        result = project_action(task, "project_read", relative, str(args.get("start") or 1))
        if relative not in task.data.setdefault("local_read_files", []):
            task.data["local_read_files"] = (task.data["local_read_files"] + [relative])[-32:]
        return result
    except (ContextError, OSError, UnicodeError):
        return "Ошибка чтения: файл недоступен, защищён или не является текстовым исходником. Выберите другой файл."
