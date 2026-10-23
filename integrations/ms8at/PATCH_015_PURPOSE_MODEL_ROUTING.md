# PATCH-015 — автовыбор модели по назначению

## ТЗ (RU)

Если в профиле OpenAI-совместимого сервера модель не выбрана явно, Dewiar должен:

1. сохранить прежний лёгкий выбор для обычного чата;
2. для фоновых задач предпочесть tool-friendly семейство умеренного размера 7–14B;
3. не выбирать embedding, speech, rerank и другие неразговорные модели;
4. никогда не заменять явно выбранную человеком модель;
5. разделять кэш автоматического выбора по адресу сервера и назначению контура;
6. не запускать probe/inference внутри чистого алгоритма выбора;
7. подтвердить отдельно offline-алгоритм и короткий live tool-probe выбранных кандидатов.

## Integration prompt (EN)

Add purpose-aware automatic model selection for profiles without an explicit model. Preserve the existing lightweight
chat choice. For background tasks, prefer a tool-friendly 7–14B family over a tiny 1–2B instruct model or a heavy model
by default. Exclude embedding, speech, rerank, and moderation models. Never override an explicit user selection. Cache
automatic choices by both server endpoint and purpose. Keep selection pure; capability probes remain explicit tests.

## 集成提示词 (ZH)

为未明确选择模型的配置增加按用途自动选择。普通聊天继续使用原来的轻量选择；后台任务优先选择支持工具、规模在
7–14B 左右的模型，而不是默认使用 1–2B 小模型或过重模型。排除 embedding、语音、rerank 和审核模型。绝不覆盖
用户明确选择的模型；自动选择缓存必须同时按服务器地址和用途隔离。选择算法保持纯函数，能力探测只能作为显式测试。

## Файлы и проверка

- Runtime: `core/model_purpose.py`, `core/llm.py`.
- Tests: `tests/model_purpose_test.py`, `tests/llm_compat_test.py`, `tests/subscription_suite_test.py`.
- Feature: `purpose_model_routing_v1`; fork build 17.
- Rollback: вернуть эти файлы к build 16 и удалить feature из overlay/update policy.
