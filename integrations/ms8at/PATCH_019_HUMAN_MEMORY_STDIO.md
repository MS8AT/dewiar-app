[RU](#ru) | [ENG](#eng) | [CH](#ch)

## RU

Проблема: фасад Human Memory существует в отдельном проекте, но Windows Dewiar
не подключён к нему и показывает `not_connected`.

Решение: маленький stdio MCP-адаптер без дополнительного пакета MCP. Два
read-only инструмента: `human_memory_health` и `human_memory_recall`.
Они используют существующий `c_HUMAN_MEMORY/service.py` и Semantic Memory;
новая база, writer и модель не создаются.

`tools/stage_human_memory.py` читает Python AST и копирует только минимальные
исходники фасада и его относительные импорты. SHA-256 проверяются перед запуском;
временный staging удаляется. Конфигурация, ключи и база не копируются.
Полученная локальная копия имеет receipt со списком файлов и хешей.

MCP command: существующий Python Dewiar, `-B -X utf8 <local-bundle>/human_memory_stdio.py
--service-dir <local-bundle>/Source/c_HUMAN_MEMORY`. Переменные среды:
`AI_NEW_MEMORY_HOME`, `AI_NEW_MEMORY_CONFIG`, `AI_NEW_MEMORY_DB`,
`AI_NEW_MEMORY_READ_ONLY=1`. Пути задаёт владелец подключения.
При сохранении `settings.mcp.servers` необходимо передавать полный словарь
серверов: Dewiar заменяет этот словарь целиком.

Промпт интеграции: добавь только stdio-адаптер, staging и тесты. Не включай в
публикацию чужой корпус памяти или закрытые клиентские настройки. Проверь
initialize, tools/list, health, неизменность SHA базы и явный task scope перед
recall. `ready` подключения не означает, что конкретная задача включила память.

Локальная проверка: настоящий Dewiar MCP-клиент прошёл handshake и health;
существующая база содержит 31 фразу, integrity=ok, SHA после чтения не изменился.
Цитаты не выводились, live recall для пользовательского scope — NOT_RUN.
Откат: удалить только регистрацию `human_memory`; источник и базу сохранить.

## ENG

Connect Windows Dewiar to an existing Human Memory facade with a small stdio
MCP adapter. It exposes read-only health and bounded recall without a model,
writer, new database or extra MCP package. The staging tool resolves Python
imports with AST, copies only the necessary source files, checks SHA-256 and
removes its temporary directory. Credentials and the database stay in place.

Integration prompt: add the transport, source-staging helper and synthetic
tests. Register the verified local bundle with explicit configuration/database
paths. Preserve the complete existing `mcp.servers` mapping when saving.
Verify handshake, health and database hash; require an explicit task scope for
recall. Connection readiness does not opt a task into memory.

Live health passed with the existing 31-phrase snapshot; integrity and hashes
are unchanged. User-scope recall: NOT_RUN. Rollback removes only the matching
MCP registration.

## CH

使用轻量 stdio MCP 适配器，将 Windows Dewiar 连接到现有 Human Memory 服务。
仅提供只读健康检查和有限范围的 recall，不创建数据库、写入器或模型。
staging 工具通过 AST 解析相对导入，只复制必要源码，验证 SHA-256 并删除临时目录。
密钥、配置和数据库保留原位置。

集成提示词：添加传输适配器、源码 staging 工具和合成测试；用明确路径注册验证后的本地副本。
保存时保留完整的 `mcp.servers` 映射。验证握手、health 和数据库哈希；recall 必须有明确的任务范围。
连接就绪不等于任务已启用记忆。

现有 31 条短语快照的 health 与完整性检查通过，哈希保持不变。
用户任务范围的 recall 未运行。回滚只删除相应 MCP 注册。
