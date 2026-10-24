# Dewiar 0.40.1 / MS8AT build 24 — 2026-10-24

[RU](#ru) | [ENG](#eng) | [CH](#ch)

Base: `616e70afada2ca3ebe95d894cb7d836592366aed`.
[Per-test JSON](https://github.com/MS8AT/MS8AT8DEwiar/blob/main/compatibility/dewiar-0.40.1-tests.json)
· [Integration prompt](https://github.com/MS8AT/MS8AT8DEwiar/blob/main/prompts/DEWIAR_0401.md).

## RU

- **PASS:** subscription_suite — `ALL OK`; overlay — 55 runtime-файлов с точными SHA-256.
- **PASS:** восемь новых сценариев 0.40.1; Python syntax и 32 JS syntax checks.
- **PASS:** три дополнительных обязательных теста, защита Android-настроек от
  отсутствующего/устаревшего согласия и инструкций из tool-result.
- **PASS:** исправлены переполнение панели HUD и контраст кнопки языка.
  ENG/CH/RU и все кнопки помещаются при 280/300/440 px; contrast suite прошёл.
- **PASS:** 15 самостоятельных блоков, 32 запуска verify/тестов. Четыре
  устаревших модуля синхронизированы с приложением. Проверены 11 прямых
  совпадений, одно перенесённое и четыре inline-адаптера.
- **PASS:** локальная установка 313 файлов с backup и повторной сверкой;
  установленная версия 0.40.1 / build 24; CLI `test`, описание `api` и
  локальный Codex health. SHA пользовательских настроек не изменился.
- **PASS:** подпись OpenAI и offline initialize/config/read CLI
  `0.164.0-alpha.11.1`; пустой профиль, без входа и inference.
- **PARTIAL:** общий quick-набор — 165 сценариев: 150 PASS, 13 ошибок,
  воспроизводимых на exact upstream в этой же среде, и 2 NOT_RUN.
  Новых неустранённых ошибок относительно этой базы в проверенном наборе нет.
- **NOT_RUN:** `radio_silent` (Windows), `speech_server` (нет FastAPI);
  live GTK-часть `pad_reopen`; реальные модели, вход, live Human Memory,
  физический Android, полный ручной UI и live API установленного ядра.

13 baseline-сбоев: `memory_pressure`, `memcap`, `zoom`, `vosk_path1020`,
`lmstudio_start1020`, `brain_hint1023`, `pc_capture`, `pad_size1022`,
`silent_voice`, `linux_install1019`, `server_setup`, `export`, `repeat`.
Исходный runner считает пропуск speech_server положительным маркером (151/165);
здесь он честно указан NOT_RUN. Статическая часть pad_reopen прошла.

Проверки использовали изолированные временные настройки/каталоги и локальные
mock-серверы. Новых модельных запросов — 0. Доказанный backup/rollback на
синтетической копии не означает live-откат: рабочая установка оставлена новой.
Автоматический выпуск установщика и подключение AI20 не включены.
Состояние базы/индексов Human Memory после переноса проекта проверяется отдельно.

## ENG

PASS: focused subscription suite, 55-file overlay hashes, all eight new 0.40.1
scenarios, Python and 32 JS syntax checks, three extra required tests, Android
turn-bound consent tests, HUD language/resize and screenshot contrast checks.
All 15 standalone blocks passed 32 verify/test entrypoints. Four stale modules
were synchronized: 11 exact source matches, one relocated match, four inline
adapters. Updated archives include SHA-256 and reproducible packaging checks.

The local PC was upgraded using a verified 313-file plan and backup. Installed
version/build, offline CLI test/API schema and Codex health passed; settings
hash was unchanged. Signed Codex CLI 0.164.0-alpha.11.1 passed an offline empty-
profile protocol probe. No login or model requests were made.

The full quick set remains PARTIAL: 150 PASS, 13 failures reproduced on exact
upstream in the same environment, two NOT_RUN (Windows radio, missing FastAPI).
The GTK portion of pad_reopen was also skipped. There are no unresolved new
failures in the checked set. Live models, memory, installed-core API, physical
Android and exhaustive manual UI acceptance were not performed. Automatic
installer releases and AI20 execution remain disabled.

## CH

通过：订阅集成测试、55 文件 overlay 哈希、0.40.1 的八项新测试、Python 和 32 项 JS
语法检查、三个附加必需测试、Android 当前回合授权、窄 HUD 语言切换和截图对比度测试。
15 个独立模块通过 32 个验证/测试入口。四个旧模块已与应用同步：11 项直接一致、
1 项路径迁移后一致、4 项内联适配器；更新的压缩包校验 SHA-256 并验证可重复构建。

本机通过带备份的 313 文件计划升级。安装版本为 0.40.1 / build 24；离线 CLI 测试、
API 描述及 Codex health 通过，用户设置哈希不变。已签名的 Codex CLI 0.164.0-alpha.11.1
通过空配置离线协议探测，未登录、未调用模型。

完整 quick 集合为 PARTIAL：150 PASS、13 项在相同环境精确上游也失败、2 项 NOT_RUN
（Windows radio 和缺少 FastAPI）；pad_reopen 的实时 GTK 部分也未执行。
已检查集合中没有未解决的新失败。真实模型、记忆、已安装核心的 live API、实体 Android
及全部手动界面验收未运行；未启用自动安装包发布和 AI20 执行。
