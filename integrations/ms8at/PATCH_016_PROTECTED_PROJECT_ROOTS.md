# PATCH-016 — закрытые корни проекта / Protected project roots / 受保护的项目根目录

## ТЗ / Specification / 规格

RU: режим «Код» не входит в корневые `Pass`, `Private` и `Runtime`, не переносит
их в рабочую копию и не прекращает обзор проекта из-за одного недоступного
незатреканного файла. Незавершённая git-копия безопасно доводится до baseline.

EN: Code mode excludes root-level `Pass`, `Private`, and `Runtime`, never copies
them into its worktree, and does not abort the whole project scan because one
untracked file is inaccessible. A partial Git worktree can finish its baseline.

中文：代码模式排除项目根目录中的 `Pass`、`Private` 和 `Runtime`，不会把它们复制到
工作副本中；单个不可访问的未跟踪文件也不会中断整个项目扫描。未完成的 Git 工作树可安全完成基线。

## Интеграционный промпт / Integration prompt / 集成提示词

Измени только `core/codework.py`. Сохрани отдельную рабочую копию и существующие
правила принятия изменений. Закрытые корни определяй только по первому компоненту
относительного пути без учёта регистра. Любой другой недоступный untracked-файл
пропускай с локальным warning без раскрытия пути в ответ модели. Добавь автономный
тест без чтения пользовательских `Pass/Private/Runtime`.

Change only `core/codework.py`. Preserve the isolated worktree and acceptance
workflow. Match protected roots only by the first relative path component,
case-insensitively. Skip any other inaccessible untracked file with a local warning
without exposing it to the model. Add an offline test that never reads user data.

仅修改 `core/codework.py`。保留独立工作副本和接受流程。只按相对路径的第一个组件进行
不区分大小写的受保护根匹配。其他不可访问的未跟踪文件只记录本地警告并跳过，不向模型暴露路径。
添加不读取用户数据的离线测试。

## Проверка / Verification / 验证

- `python -B tests/codework_protected_test.py`
- `python -B tests/subscription_suite_test.py`
- rollback: restore `core/codework.py` and remove the feature/test declaration.
