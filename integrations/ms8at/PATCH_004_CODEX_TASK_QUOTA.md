# PATCH-004 — подтверждаемое продление квоты задач Codex

## RU — ТЗ и интеграционный промпт

**Проблема.** После исчерпания лимита задача оставалась на паузе, но UI показывал обычное «Продолжить». Повторный
запуск сразу возвращал ту же ошибку, потому что сохранённый счётчик не сбрасывался.

**Что изменить.** Добавить отдельную кнопку «Выдать ещё N запросов». Выдача разрешена только остановленной,
исчерпавшей лимит задаче, привязанной к тому же Codex-профилю и разрешениям. Каждая выдача — 1–20, общий лимит
задачи — 100. Перед изменением требуется локальное подтверждение с предупреждением о расходе подписки/кредитов.

**Что не делать.** Не сбрасывать число попыток, не запускать задачу и модель автоматически, не менять профиль,
не давать shell/MCP/сеть/подзадачи, не писать цель или содержимое задачи в heartbeat.

**Интеграция.** Backend: `core/subscription_quota.py`, `core/subscription_context.py`, `core/engine_commands.py`,
`core/tasks.py`. UI: `ui/studio/task_quota.js`, `ui/studio/tasks.js`, `ui/settings.html`. Наблюдение:
`core/brain_watch.py`, `core/diagnostics.py`. Manifest и overlay должны перечислить каждый runtime-файл.

**Приёмка.** Автономные Python/Node-тесты подтверждают выдачу, отказ без мутаций, лимиты, гонку подтверждения,
отсутствие вызова модели, безопасный журнал и замену ложной кнопки «Продолжить». Установка выполняется отдельно
только при закрытом Dewiar с резервной копией.

## EN — specification and integration prompt

Fix the exhausted Codex-task loop by adding an explicit “Grant N more requests” action. Permit it only for an
exhausted stopped task bound to the unchanged Codex profile and permission snapshot. Each confirmed grant is 1–20;
the lifetime task cap is 100. Warn about subscription/credit use. Preserve the attempt counter, do not call the
model, do not resume automatically, and never log task text in heartbeat. Integrate only the backend, UI,
observability, manifest, and test files listed above. Accept only after offline Python/Node tests pass; install later
with Dewiar closed and a rollback backup.

## 中文 — 规格与集成提示词

修复 Codex 任务配额耗尽后的循环：增加独立的“再授予 N 次请求”操作。只有已停止、配额已耗尽，并且仍绑定到同一
Codex 配置与权限快照的任务才能使用。每次人工确认可增加 1–20 次，单个任务累计上限为 100。确认窗口必须提示可能
消耗订阅额度或工作区积分。不得清零尝试次数，不得自动调用模型或恢复任务，不得把任务正文写入心跳日志。只集成上面
列出的后端、界面、可观测性、清单和测试文件。离线 Python/Node 测试全部通过后才可验收；安装必须在 Dewiar 完全退出
并已制作可回滚备份后单独执行。

## Проверки / Tests / 测试

- `python -B tests/subscription_quota_test.py`
- `python -B tests/subscription_context_test.py`
- `python -B tests/brain_watch_test.py`
- `python -B tests/diagnostics_test.py`
- `node --test tests/task_quota_ui.test.mjs`
- `python -B tests/subscription_suite_test.py`
- `python -B tools/verify_ms8at_overlay.py`
