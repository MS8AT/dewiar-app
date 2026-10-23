# PATCH-007 — RU / ENG / CH: язык ответа и голоса

Этот файл — ТЗ и интеграционный промпт. Он не разрешает установку, публикацию,
вызов модели или загрузку голоса без явного выбора человеком.

[Русский](#ru) · [English](#en) · [中文](#zh)

<a id="ru"></a>
## RU · Что делает патч

В нижней панели HUD появляется компактная кнопка `RU / ENG / CH`. Нажатие циклически
выбирает русский, английский или упрощённый китайский язык. Выбранное значение хранится
в настройках и применяется к обычному чату и отдельному Codex-контуру.

Для английского используются локальные голоса Piper `en_US-amy-medium` и
`en_US-ryan-medium` по полу персонажа. Для китайского используется
`zh_CN-huayan-medium`. Голос загружается только после явного выбора языка; режим
`local_only` запрещает загрузку. До готовности голоса текстовый язык уже действует.

Граница: патч не переводит весь интерфейс Dewiar и не меняет язык распознавания команд.
Он управляет языком ответа модели и синтеза речи.

<a id="en"></a>
## EN · What the patch does

The HUD bottom bar gets a compact `RU / ENG / CH` button. Each click cycles through
Russian, English, and Simplified Chinese. The persisted setting applies to both the
regular chat route and the isolated Codex subscription route.

English uses local Piper voices `en_US-amy-medium` and `en_US-ryan-medium`, selected
by persona gender. Chinese uses `zh_CN-huayan-medium`. A voice is downloaded only
after the user explicitly selects that language; `local_only` blocks the download.
Text switches immediately while the local voice is being prepared.

Scope boundary: this patch does not localize the whole Dewiar UI and does not change
speech-command recognition. It controls model response language and speech synthesis.

<a id="zh"></a>
## 中文 · 补丁作用

HUD 底部栏新增紧凑的 `RU / ENG / CH` 按钮。每次点击会在俄语、英语和简体中文之间
循环切换。所选设置会保存，并同时应用于普通聊天路径和隔离的 Codex 订阅路径。

英语使用本地 Piper 语音 `en_US-amy-medium` 或 `en_US-ryan-medium`，并根据角色性别
选择。中文使用 `zh_CN-huayan-medium`。只有用户明确选择相应语言后才会下载语音；
`local_only` 会阻止下载。本地语音准备期间，文本语言会立即切换。

范围边界：此补丁不会翻译整个 Dewiar 界面，也不会更改语音命令识别语言；它只控制
模型回答语言和语音合成。

## Runtime и критерии

- runtime-файлы: `core/language_mode.py`, `core/settings.py`, `core/engine_answer.py`,
  `core/subscription_context.py`, `core/engine_commands.py`, `core/engine_remote.py`,
  `core/tts.py`, `ui/hud.html`;
- автономные тесты: `tests/language_mode_test.py`, `tests/hud_language_test.py`;
- регрессия: API/SLI, чаты, команды, задачи, HUD и subscription suite;
- автоматические проверки выполняются с `model_calls=0`;
- загрузка голоса и реальный inference не входят в автономный тест.

## Откат

Вернуть предыдущий проверенный overlay целиком при закрытом Dewiar. Настройки,
пользовательские задачи, память и уже загруженные голоса не удалять.
