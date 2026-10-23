"""Ограниченное самовосстановление фоновой задачи после переполнения контекста.

Доктор не меняет настройки модели и не повторяет запрос бесконечно. Он готовит
один компактный запрос: оставляет цель, текущий план и блокнот, а из инструментов
берёт только управление задачей и рабочий набор для её типа.
"""

CONTROL_TOOLS = {
    "update_plan", "log", "ask_user", "finish", "remember", "notes", "notify", "wait",
}
WEB_TOOLS = {"web_search", "read_webpage", "open_url"}
CODE_TOOLS = {
    "code_list", "code_read", "code_search", "code_edit", "code_write", "code_delete",
    "code_run", "code_process", "code_undo", "code_diff",
}
WORK_TOOLS = {"write_file", "read_file", "list_files", "run_python", "show", "transcribe", "download"}
KNOWLEDGE_TOOLS = {"search_documents", "ask_knowledge", "find_notes", "save_note"}


def _clip(text, limit):
    """Оставить начало и свежий хвост длинного поля, явно отметив пропуск."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    return text[:head].rstrip() + "\n… (середина сокращена AI-доктором) …\n" + text[-tail:].lstrip()


def compact_system(*, persona, title, goal, notebook, plan, project="", task_dir="", parent=False, now=""):
    """Короткая, но достаточная системная инструкция для аварийного шага."""
    mode = (
        "Изучи проект инструментами code_list/code_search/code_read. Правь только если этого требует цель; "
        "после правок запусти тесты и проверь code_diff."
        if project else
        "Проверяй сведения доступными инструментами; нужный результат сохраняй в папке задачи."
    )
    role = "Ты выполняешь одну порученную часть; итог прочитает основная задача." if parent else "Ты выполняешь фоновую задачу пользователя."
    return (
        f"Ты — {str(persona or 'Агент')[:120]}. {role}\n"
        f"ЗАДАЧА: {_clip(title, 240)}\nЦЕЛЬ: {_clip(goal, 900)}\n"
        + (f"Сейчас: {now}.\n" if now else "")
        + (f"ПРОЕКТ: {_clip(project, 500)}\n" if project else "")
        + (f"ПАПКА ЗАДАЧИ: {_clip(task_dir, 500)}\n" if task_dir else "")
        + "\nПравила: не выдумывай результат; действуй инструментами. Сначала update_plan, важное записывай через "
          "remember. Если без решения человека нельзя — ask_user. finish вызывай только после проверки результата. "
          "Один и тот же ошибочный шаг не повторяй.\n"
        + mode
        + f"\n\nБЛОКНОТ:\n{_clip(notebook, 1000) or '(пусто)'}"
        + f"\n\nПЛАН:\n{_clip(plan, 1000) or '(ещё не составлен)'}"
    )


def compact_specs(specs, *, project=False):
    """Оставить рабочее ядро инструментов и укоротить только их пояснения."""
    allowed = CONTROL_TOOLS | WEB_TOOLS | (CODE_TOOLS if project else WORK_TOOLS | KNOWLEDGE_TOOLS)
    out = []
    for spec in specs or []:
        if spec.get("name") not in allowed:
            continue
        item = dict(spec)
        desc = " ".join(str(item.get("description") or "").split())
        item["description"] = _clip(desc, 180)
        out.append(item)
    return out


def report(normal_system, normal_specs, compact_prompt, compact_tools):
    """Безопасная диагностика для журнала: только размеры, без текста и ключей."""
    return {
        "mode": "context_compact",
        "system_chars_before": len(normal_system or ""),
        "system_chars_after": len(compact_prompt or ""),
        "tools_before": len(normal_specs or []),
        "tools_after": len(compact_tools or []),
    }
