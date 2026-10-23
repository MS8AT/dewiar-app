# Патчи MS8AT · MS8AT patches · MS8AT 补丁

Каждый патч — отдельный модуль поверх указанной версии upstream. Он обязан иметь ТЗ, интеграционный промпт,
перечень runtime-файлов, автономные тесты и способ отката. Промпт не является разрешением на запись, публикацию,
запуск модели или установку. / Every patch is a separate module over an exact upstream version and must include a
specification, integration prompt, runtime file list, offline tests, and rollback. A prompt grants no authority to
write, publish, call a model, or install. / 每个补丁都是叠加在指定上游版本之上的独立模块，必须包含规格、集成提示词、
运行时文件清单、离线测试和回滚方式。提示词本身不授予写入、发布、调用模型或安装的权限。

| ID | Назначение / Purpose / 用途 | ТЗ и промпт / Spec and prompt / 规格与提示词 |
|---|---|---|
| PATCH-001 | Локальный Codex / Local Codex / 本地 Codex | [общий интеграционный промпт](INTEGRATION_PROMPT_RU.md) |
| PATCH-002 | Назначения мозгов / Brain routing / 模型路由 | [архитектура](../../docs/BRAINS_HEARTBEAT_RU.md) |
| PATCH-003 | Heartbeat, CLI, API, SLI / 心跳、CLI、API、SLI | [архитектура](../../docs/BRAINS_HEARTBEAT_RU.md) |
| PATCH-004 | Подтверждаемое продление квоты задач Codex / Confirmed Codex task quota extension / 经确认的 Codex 任务配额扩展 | [ТЗ и промпт](PATCH_004_CODEX_TASK_QUOTA.md) |

Шаблон для следующих изменений: [prompts/PATCH_PROMPT_TEMPLATE.md](../../prompts/PATCH_PROMPT_TEMPLATE.md).
