# PATCH-009 — безопасное окно отключения профиля

Этот файл — ТЗ и интеграционный промпт. Он не разрешает отключение аккаунта:
решение остаётся за человеком в локальном окне Dewiar.

[Русский](#ru) · [English](#en) · [中文](#zh)

<a id="ru"></a>
## RU · Что делает патч

Кнопка отключения Codex/аккаунта больше не открывает системный JavaScript `confirm`,
который мог показывать технический адрес страницы и токен локальной связи. Вместо него
используется штатное окно Dewiar `ask`: «Отмена»/«Выйти», Escape означает отказ.

Также регрессия удержания диктовки теперь отделяет пользовательские команды от пассивного
локального чтения pending-подтверждения Codex. Само поведение диктовки не меняется.

<a id="en"></a>
## EN · What the patch does

The Codex/account disconnect button no longer opens a native JavaScript `confirm` that may
expose a technical page URL and local connection token. It uses Dewiar's local `ask` dialog
with explicit Cancel/Exit actions; Escape declines. The hold-to-dictate regression now ignores
the passive local Codex pending-confirmation read without weakening its interaction assertions.

<a id="zh"></a>
## 中文 · 补丁作用

Codex/账户断开按钮不再打开可能显示技术页面地址和本地连接令牌的系统 JavaScript
`confirm`。它改用 Dewiar 本地 `ask` 对话框，提供明确的“取消/退出”操作；按 Escape
表示拒绝。按住听写回归测试会忽略被动的本地 Codex 待确认读取，同时保留所有交互断言。

## Runtime и критерии

- runtime-файл: `ui/studio/subscription.js`;
- автономные регрессии: `tests/dialogs1021_test.py`, `tests/hold_dictation_test.py`;
- системные `confirm/prompt/alert` в студии запрещены;
- тесты не вызывают модель и не используют внешний аккаунт.

## Откат

Вернуть предыдущий проверенный overlay целиком при закрытом Dewiar. Профили и настройки не удалять.
