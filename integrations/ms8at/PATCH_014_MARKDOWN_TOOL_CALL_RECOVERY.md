# PATCH-014 — строгое восстановление Markdown-вызова инструмента

## ТЗ (RU)

Некоторые локальные OpenAI-совместимые модели не возвращают родное поле `tool_calls`, а печатают вызов как
Markdown-карточку. Dewiar должен распознать такой ответ без расширения полномочий модели:

1. принимать только первую строгую пару `**Функция:**` / `**Аргументы:**` (также ENG/CH);
2. принимать только инструмент, который реально был передан модели в текущем запросе;
3. принимать аргументы только как ограниченный по размеру JSON-объект;
4. отбрасывать весь текст после вызова, потому что модель ещё не видела настоящий результат инструмента;
5. выполнять восстановленный вызов через обычный `_tool`, сохраняя подтверждения, запреты и рабочую копию;
6. не превращать цитаты, неизвестные имена, повреждённый JSON или большие ответы в действия;
7. проверять отдельно парсер и полный поток `Markdown → настоящий инструмент → finish`.

## Integration prompt (EN)

Add a narrowly scoped recovery path for local models that print a tool call as Markdown instead of returning native
`tool_calls`. Accept only the first exact Function/Arguments pair, only a tool offered in the current request, and only
a bounded JSON object. Discard all text after the recovered call because any printed tool result is untrusted fiction.
Route the recovered call through the existing permission and workspace enforcement. Reject quotes, unknown tools,
malformed arguments, oversized responses, and multiple-step simulation. Cover the parser and end-to-end task flow.

## 集成提示词 (ZH)

为把工具调用打印成 Markdown、而不是返回原生 `tool_calls` 的本地模型增加严格且有限的恢复路径。只接受第一组
精确的“函数/参数”字段，只允许当前请求实际提供的工具，并且参数必须是有大小限制的 JSON 对象。恢复调用后丢弃
其后的全部文本，因为模型打印的工具结果并不可信。恢复后的调用仍必须经过现有权限、确认和工作副本保护。拒绝
引用文本、未知工具、损坏参数、超大响应和一次模拟多个步骤，并用解析器测试及端到端任务测试覆盖。

## Файлы и проверка

- Runtime: `core/tool_call_recovery.py`, `core/tasks.py`.
- Tests: `tests/tool_call_recovery_test.py`, `tests/tool_call_recovery_flow_test.py`,
  `tests/subscription_suite_test.py`.
- Feature: `markdown_tool_call_recovery_v1`; fork build 16.
- Rollback: вернуть перечисленные файлы к build 15 и удалить feature из overlay/update policy.
