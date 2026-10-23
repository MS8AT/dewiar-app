"""Чистый выбор модели по назначению; сеть, настройки и запуск модели не выполняются."""

import re

_NOT_CHAT = re.compile(r"embed|rerank|ocr|whisper|tts|asr|speech|stt|clip|bge|e5-|guard|moderat", re.I)
_TASK_FAMILY = re.compile(r"qwen3|coder|tool|function|gpt-oss|deepseek|glm|mistral", re.I)
_SIZE = re.compile(r"(\d+(?:[.]\d+)?)b(?=$|[-_/])", re.I)


def _size(name):
    values = [float(x) for x in _SIZE.findall(str(name or ""))]
    return max(values, default=0.0)


def _chat(models):
    for pref in ("chat", "llm", "default"):
        if pref in models:
            return pref
    for rx in (r"chat|instruct", r"qwen|llama|mistral|gemma|glm|deepseek|phi"):
        hit = [name for name in models if re.search(rx, name, re.I)]
        if hit:
            return hit[0]
    return models[0] if models else ""


def _task_score(name):
    """Tool-friendly семейство и 7–14B выше: достаточно для действий без тяжёлого 35B по умолчанию."""
    size = _size(name)
    score = 300 if _TASK_FAMILY.search(name) else 0
    if re.search(r"coder|tool|function", name, re.I):
        score += 100
    if 7 <= size <= 14:
        score += 120
    elif 14 < size <= 24:
        score += 80
    elif 24 < size <= 40:
        score += 60
    elif 3 <= size < 7:
        score += 20
    elif 0 < size < 3:
        score -= 200
    if re.search(r"instruct", name, re.I):
        score += 20
    if re.search(r"(?:^|[-_/])wb-node\d+", name, re.I):
        score += 10                         # явный рабочий узел стабильнее локального алиаса той же модели
    return score + min(size, 60)


def choose(models, purpose="chat"):
    """Выбрать имя из списка. Явных capability-claims не создаёт: это только безопасный приоритет."""
    suitable = [str(name) for name in (models or ()) if name and not _NOT_CHAT.search(str(name))]
    if not suitable:
        return str(models[0]) if models else ""
    if purpose == "tasks":
        best = max(suitable, key=_task_score)
        if _task_score(best) > 0:
            return best
    return _chat(suitable)
