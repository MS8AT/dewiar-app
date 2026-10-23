# PATCH-013 — AI-доктор переполнения контекста

## ТЗ

Если обычная фоновая задача остановилась из-за переполнения окна контекста, Dewiar должен:

1. сохранить штатное сокращение истории из `llm.py`;
2. после повторного переполнения один раз собрать компактную системную подсказку;
3. оставить управление задачей и инструменты, нужные для задачи по коду либо обычной задачи;
4. записать диагноз, размеры до/после и результат лечения в журнал и `задача.json`;
5. после успешного лечения продолжить текущий запуск в компактном режиме;
6. после повторной ошибки остановиться с точным сообщением, не менять LM Studio и не создавать цикл повторов.

## Integration prompt (EN)

Add a bounded context-overflow doctor for background tasks. Preserve the normal request first. On a confirmed
context overflow, retry once with a compact task prompt and a task-type-specific tool set. Keep tool schemas intact,
log only safe size counters, never change model settings, and never loop retries. Continue the current run in compact
mode after recovery. Cover selection, prompt bounds, and safe diagnostics with offline unit tests.

## 集成提示词 (ZH)

为后台任务添加有界的上下文溢出修复。先保留正常请求；确认上下文溢出后，仅使用精简任务提示词和按任务类型
筛选的工具重试一次。工具参数结构保持不变，日志只记录安全的大小统计，不修改模型设置，也不循环重试。
修复成功后，本次运行继续使用精简模式，并用离线测试覆盖工具筛选、提示词边界和安全诊断。

## Файлы и проверка

- Runtime: `core/task_doctor.py`, `core/tasks.py`.
- Tests: `tests/task_doctor_test.py`, `tests/task_doctor_flow_test.py`, `tests/subscription_suite_test.py`.
- Rollback: вернуть эти файлы к предыдущему build и удалить feature `task_context_doctor_v1`.
