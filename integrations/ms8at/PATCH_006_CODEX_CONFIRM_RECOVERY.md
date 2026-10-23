# PATCH-006 — восстановление подтверждения Codex

Этот файл — ТЗ и интеграционный промпт. Он не разрешает установку, публикацию или
вызов модели. Реализация работает только с локальным ожидающим подтверждением.

## RU · Что делает патч

Если окно агента пропустило одноразовое событие `confirm` при перезагрузке, сворачивании
или переключении режима, оно безопасно читает текущее локальное pending-состояние и
возвращает кнопки «Да/Нет». Ответ принимается только вместе с точным nonce. Истёкший
вопрос закрывается с понятным сообщением; он не остаётся на экране как активный.

Патч не повторяет задачу, не вызывает модель, не входит в аккаунт и не использует сеть.
Обычные подтверждения Dewiar продолжают идти через прежний `confirm_answer`.

## EN · What the patch does

If the Agent window misses the one-shot `confirm` event during reload, hide, or mode
switch, it reads the current local pending state and restores the Yes/No controls.
Answers require the exact nonce. An expired question is closed with an explicit status.
The recovery performs no model call, login, retry, or network request.

## 中文 · 补丁作用

如果代理窗口在重新加载、隐藏或切换模式时错过一次性的 `confirm` 事件，界面会读取
本地待确认状态并恢复“是/否”按钮。回答必须携带准确的 nonce。过期问题会关闭并显示明确
状态。恢复过程不会调用模型、登录、重试任务或访问网络。

## Runtime и критерии

- runtime-файлы: `ui/hud.html`, `core/subscription_context.py`, `core/fork_update_policy.py`;
- автономный тест: `tests/hud_subscription_confirm_test.py`;
- регрессия: `tests/hud_tight_test.py`, `tests/subscription_confirm.test.mjs`;
- все проверки должны выполнить `model_calls=0`;
- локальный PASS не означает установку в рабочий Dewiar и не означает публикацию.

## Откат

Восстановить предыдущий проверенный overlay целиком при закрытом Dewiar. Не удалять
пользовательские задачи, настройки или память.
