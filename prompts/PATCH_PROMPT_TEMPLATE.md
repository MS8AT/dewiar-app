# Шаблон промпта-патча · Patch prompt template · 补丁提示词模板

## RU

Перенеси патч `<ID>` на exact upstream `<commit>`. Цель: `<результат>`. Измени только `<файлы/модули>`.
Сохрани `<контракты upstream>`. Не получай доступ к `<запрещённые данные/действия>`. Добавь автономные тесты
`<команды>`, обнови manifest и напиши способ отката. Не вызывай реальные модели/API и не устанавливай патч без
отдельного разрешения. Отчёт: base/fork commit, изменённые файлы, PASS/PARTIAL/NOT_RUN, публикация и установка.

## EN

Port patch `<ID>` onto exact upstream `<commit>`. Goal: `<outcome>`. Change only `<files/modules>` and preserve
`<upstream contracts>`. Do not access `<denied data/actions>`. Add offline tests `<commands>`, update the manifest,
and document rollback. Do not call live models/APIs or install without separate authority. Report base/fork commits,
changed files, PASS/PARTIAL/NOT_RUN, publication, and installation.

## 中文

把补丁 `<ID>` 迁移到精确的上游提交 `<commit>`。目标：`<结果>`。仅修改 `<文件/模块>`，并保持 `<上游契约>`。
不得访问 `<禁止的数据/操作>`。添加离线测试 `<命令>`，更新清单并说明回滚方式。未经单独授权不得调用真实模型/API，
也不得安装。报告基础/分支提交、修改文件、PASS/PARTIAL/NOT_RUN、发布状态和安装状态。
