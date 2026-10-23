"""Безопасное восстановление одного вызова инструмента из Markdown-ответа модели.

Некоторые OpenAI-совместимые локальные модели получают схемы инструментов, но вместо
родного ``tool_calls`` печатают понятную человеку карточку. Здесь принимается только
первая строгая пара «Функция/Аргументы», только для известного в текущем запросе
инструмента и только с JSON-объектом аргументов. Остальной текст модели не считается
результатом инструмента и не исполняется.
"""

import json
import re

MAX_RESPONSE_CHARS = 24000
MAX_ARGUMENT_CHARS = 8000

_NAME = re.compile(
    r"(?mi)^\s*\*\*(?:Функция|Function|函数):\*\*\s*([A-Za-z_][\w.-]*)\s*$"
)
_ARGS = re.compile(
    r"(?mi)^\s*\*\*(?:Аргументы|Arguments|参数):\*\*\s*"
)
_HEADING = re.compile(
    r"(?mi)^\s*#{1,6}\s*(?:Функция|Function|函数):\s*[A-Za-z_][\w.-]*\s*$\n?"
)


def recover_one(text, allowed_names):
    """Вернуть ``(видимый_текст, вызов)`` или ``(исходный_текст, None)``.

    После найденного вызова ответ отбрасывается: модель ещё не видела настоящий
    результат инструмента, поэтому любой напечатанный ею «Ответ от функции» выдуман.
    """
    source = str(text or "")
    allowed = {str(name) for name in (allowed_names or ())}
    if not source or len(source) > MAX_RESPONSE_CHARS or not allowed:
        return source, None

    match = _NAME.search(source)
    if not match or match.group(1) not in allowed:
        return source, None
    args_label = _ARGS.search(source, match.end())
    if not args_label or source[match.end():args_label.start()].strip():
        return source, None

    tail = source[args_label.end():].lstrip()
    if not tail.startswith("{"):
        return source, None
    try:
        args, end = json.JSONDecoder().raw_decode(tail)
    except ValueError:
        return source, None
    if not isinstance(args, dict) or end > MAX_ARGUMENT_CHARS:
        return source, None

    # До пары допускается пояснение, но не другая карточка вызова: исполняем ровно
    # один первый намеренный шаг и после реального результата снова спрашиваем модель.
    prefix = source[:match.start()]
    if _NAME.search(prefix) or _ARGS.search(prefix):
        return source, None
    prefix = _HEADING.sub("", prefix).rstrip()
    return prefix, {"name": match.group(1), "args": args}
