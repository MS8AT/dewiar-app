[RU](#ru) | [ENG](#eng) | [CH](#ch)

## RU

Задача: продолжать изучение проекта на локальной/LAN-модели после исчерпания
квоты Codex, сохраняя ту же карточку и журнал.

`task_use_local {id, profile}` выбирает существующий LAN-профиль только у
остановленной задачи. Не запускает модель. История квоты сохраняется в
`previous_codex`; исходные файлы задачи остаются на месте. После «Продолжить»
задача получает компактную подсказку и только чтение проекта, план, блокнот и
итог. Смена или удаление привязанного профиля не переносит задачу в облако.

Настройка `tasks.local_only` запрещает облачный маршрут всех обычных задач.
Для окна 8K порция чтения ограничена 1200 символами, история — 6000;
для большего окна — 4000 и 20000. Это консервативный лимит символов, не токены.
`code_read` учитывает `end`; пустой фрагмент не считается успешным чтением.
В интерфейсе: «Для задач только свои модели» и «Перейти на свою модель
(изучение)». Обычные задачи разработки сохраняют прежние инструменты.

Тесты: та же карточка проходит план → чтение → отмеченный план → `итог.md`;
закрытые каталоги не читаются, запись и команды запрещены режимом изучения;
активный Codex не получает запрос. Проверки локального адреса и отсутствующего
профиля выполняются до inference. Самопроверка использует профиль этой задачи.

Промпт интеграции: добавь `local_task_mode.py`, вызови его выбор из команды
`task_use_local`, используй привязанный профиль в основном цикле, переводе и
самопроверке. Для режима изучения фильтруй инструменты и проверяй вызов перед
исполнением. Не увеличивай квоту Codex. Запусти
`python tests/local_task_mode_test.py` и общий `subscription_suite_test.py`.

Откат: восстанови предыдущий проверенный overlay из резервной копии.
`previous_codex` и журнал сохранить; автоматического возврата в Codex нет.

## ENG

Continue a stopped project-study task with an existing local/LAN model while
preserving its card and journal. `task_use_local {id, profile}` does not call
a model. Previous Codex quota metadata remains in `previous_codex`.

On resume, the study mode allows project reads, the plan, notebook and final
report. It uses a compact prompt, validates protected paths and blocks writes
and commands. The main loop, translation and review use the task's local
profile. A missing profile fails before inference. `tasks.local_only` prevents
ordinary tasks from inheriting a cloud model.
Small-context profiles use 1200-character reads and 6000-character history;
larger contexts use 4000 and 20000. These are character heuristics, not token counts.
The reader honors `end` and does not count an empty fragment as source evidence.

Integration prompt: wire the local-mode helper into task selection, profile
resolution and tool dispatch, add the two UI controls and run the focused
local-task test plus the subscription suite. Do not change Codex quotas.
Rollback uses the previous verified overlay backup; preserve task history.

## CH

目的：Codex 配额用完后，使用已有的本地或局域网模型继续研究项目，保留同一任务卡和日志。
`task_use_local {id, profile}` 只选择已停止任务的执行模型，不调用模型。
之前的 Codex 配额信息保存在 `previous_codex` 中。

继续后，仅允许读取项目、更新计划、笔记和最终报告。研究模式使用精简提示词，
验证受保护路径，并禁止写入项目和执行命令。主循环、翻译和复查都使用该任务绑定的本地模型。
模型配置缺失时，在推理前停止。`tasks.local_only` 防止普通任务继承云端模型。
小上下文模型使用 1200 字符读取片段及 6000 字符历史；较大上下文使用 4000 和 20000。
这是字符启发式限制，不是 token 计数。读取遵守 `end`，空片段不算来源证据。

集成提示词：将本地模式模块接入模型选择、任务循环和工具调用，添加界面开关及切换按钮，
运行本地任务测试及完整订阅测试。不要增加 Codex 配额。
回滚使用上一份经过验证的备份，保留任务历史。
