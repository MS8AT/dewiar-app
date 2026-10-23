# PATCH-008 — надёжные команды задач в Windows

Этот файл — ТЗ и интеграционный промпт. Он не даёт модели новых полномочий:
guard и подтверждение человека проверяют исходную команду до нормализации.

[Русский](#ru) · [English](#en) · [中文](#zh)

<a id="ru"></a>
## RU · Что делает патч

Патч исправляет два сбоя фоновых задач в Windows:

1. Модель может прислать JSON-инструмент с полным путём `C:\...`, забыв JSON-экранирование.
   Dewiar восстанавливает только строки, явно похожие на путь с буквой диска; другой JSON не меняется.
2. Команда `python3 ...` запускается проверенным Python текущей установки Dewiar. PowerShell явно
   переходит в рабочую копию через `Set-Location -LiteralPath`, поэтому тест не запускается из `System32`.

Результаты и код возврата остаются в журнале задачи. Защита команд, подтверждение, изолированная
рабочая копия и ручное принятие изменений остаются обязательными.

<a id="en"></a>
## EN · What the patch does

The patch fixes two Windows background-task failures. It narrowly repairs unescaped backslashes only
inside JSON strings that clearly start with a drive path such as `C:\...`. A leading `python3` or
`python` command uses Dewiar's current verified interpreter. PowerShell explicitly enters the isolated
working copy with `Set-Location -LiteralPath`, so tests do not accidentally run from `System32`.

Command guards, human confirmation, the isolated worktree, journaling, and manual acceptance remain intact.

<a id="zh"></a>
## 中文 · 补丁作用

该补丁修复 Windows 后台任务中的两个故障。它只修复明显以盘符路径（例如 `C:\...`）开头的
JSON 字符串中未转义的反斜杠，不会修改其他 JSON。以 `python3` 或 `python` 开头的命令会使用
Dewiar 当前经过验证的解释器。PowerShell 通过 `Set-Location -LiteralPath` 明确进入隔离工作副本，
避免测试错误地从 `System32` 运行。

命令保护、人工确认、隔离工作树、日志记录和手动接受更改仍然保持有效。

## Runtime и критерии

- runtime-файлы: `core/llm.py`, `core/codework.py`;
- автономные регрессии: `tests/bare_calls_test.py`, `tests/tasks_test.py`;
- тест обязан подтвердить запись результата в `outputs/` и вывод теста в журнале;
- внешний inference, сеть и пользовательские проекты не используются.

## Откат

Вернуть предыдущий проверенный overlay целиком при закрытом Dewiar. Рабочие проекты,
задачи, журналы и память пользователя не удалять.
