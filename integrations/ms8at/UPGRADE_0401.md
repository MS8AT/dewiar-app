# Dewiar 0.40.1 + MS8AT build 24

[RU](#ru) | [ENG](#eng) | [CH](#ch)

Upstream: `616e70afada2ca3ebe95d894cb7d836592366aed` (`v0.40.1`).
Overlay: `overlay.json`; exact runtime hashes: `../../tools/local_codex_manifest.json`.
[Validation / Проверки / 验证](../../docs/VALIDATION_2026-10-24.md).

## RU

Обновление сохраняет самостоятельные модули MS8AT: Codex, назначения моделей,
локальные задачи, Human Memory, heartbeat, диагностику API/CLI/SLI и RU/ENG/CH.
Пользовательские профили, память и выбранные модели не входят в комплект.

Изменения совместимости:

- Сохранены исправления 0.40.1 для параметров OpenAI API, перегрузки серверов,
  установки в выбранный каталог, речи, интерфейса и недоступных сетевых файлов.
- В `codework.py` non-Git копия использует наш фильтр закрытых корней вместе
  с обработкой `shutil.Error` из upstream. Недоступный файл не мешает работать
  с остальными; `Pass`, `Private`, `Runtime` исключены до копирования.
- Проверенный локальный Codex CLI: `0.164.0-alpha.11.1`. Привязка к точному
  SHA-256 сохранена; произвольный новый CLI не допускается автоматически.
  Проверка протокола использует пустой профиль и закрытый HTTP proxy.
- Новый регрессионный тест подтверждает: ошибка подписки 503 или отозванный
  scope не попадает в общий механизм HTTP-повторов.
- Исправлена панель узкого HUD: ENG/CH/RU и остальные кнопки помещаются
  в окно шириной 280 px; переключение проверяется на 280, 300 и 440 px.

Порядок интеграции: новая локальная копия → точный upstream commit → перенос
адаптеров → пересчёт manifest → offline tests → review → установка при закрытом
приложении с backup → сверка каждого файла. `tools/upgrade_local_release.py`
создаёт план, проверяет зависимости, сохраняет backup и поддерживает rollback
тем же планом. План и backup находятся вне checkout и приложения.

AI20 подключается отдельным адаптером после проверки Manager→Router→Node,
прав задачи и memory scope. Этот выпуск не включает scheduler и не меняет
модели по умолчанию. Публикация исходников в PR не включает автоматический
выпуск установщика: `update_policy.effective=false` сохраняется.

## ENG

This update carries the independent MS8AT Codex, model routing, local-task,
Human Memory, heartbeat, API/CLI/SLI and RU/ENG/CH modules onto exact upstream
0.40.1. User profiles, memory and model choices are excluded from the payload.

Keep upstream API parameter, overload, installer, speech, UI and network-file
fixes. In non-Git `codework` copying, combine upstream `shutil.Error` handling
with our protected-root ignore callback. An inaccessible file must not stop
readable files; protected roots must never enter the copy. The CLI pin is updated
to verified `0.164.0-alpha.11.1`, retaining exact SHA-256 enforcement. The offline
protocol probe uses an empty profile and blocked HTTP proxy. A regression test
ensures subscription 503 and revoked-scope failures never enter generic retries.
The narrow HUD toolbar keeps all buttons visible; language switching is checked
at 280, 300 and 440 px, including the longer ENG label.

Integrate locally, verify hashes/tests, review, install only while stopped with
a backup, then compare every payload file. Roll back using the same plan and
backup. Keep AI20 as a separate adapter until Manager→Router→Node and task/memory
authorization are verified. No scheduler or model preference changes are made.
Source PR publication does not enable automatic installer releases.

## CH

本次更新把独立的 MS8AT Codex、模型路由、本地任务、Human Memory、heartbeat、
API/CLI/SLI 和 RU/ENG/CH 模块适配到精确的上游 0.40.1。用户配置、记忆与模型选择不在安装包中。

保留上游 API 参数、服务器繁忙、安装路径、语音、界面及网络文件修复。
non-Git 工作副本同时使用上游的 `shutil.Error` 处理和我们的受保护目录过滤器：
不可访问文件不影响其他文件，受保护目录必须在复制前排除。
Codex CLI 固定为已验证的 `0.164.0-alpha.11.1`，仍严格校验 SHA-256。
离线协议探测使用空配置和阻断 HTTP 的代理；回归测试确保订阅 503 和权限撤销不会触发通用重试。
修复窄窗口工具栏，在 280、300、440 px 下检查所有按钮及 ENG/CH/RU 切换。

流程：本地集成、哈希与测试、审查、关闭应用后备份安装、逐文件核对。
回滚使用同一计划和备份。AI20 仍是独立的后续适配器，须先验证 Manager→Router→Node
及任务和记忆权限。本次不启用调度器、不更改模型偏好；源代码 PR 不启用安装包自动发布。
