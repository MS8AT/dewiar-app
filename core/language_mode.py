"""Язык ответа и голоса: один проверяемый источник правил для ядра, Codex и HUD.

Переключение языка не вызывает модель. Голоса Piper загружаются только после
явного выбора человеком; local_only остаётся безусловным стоп-краном.
"""

MODES = {
    "ru": {
        "label": "RU", "name": "Русский", "remote": "Russian",
        "prompt": "Отвечай на русском языке. Имена, цитаты, код и явно запрошенный перевод сохраняй в нужном языке.",
        "voices": {},
    },
    "en": {
        "label": "ENG", "name": "English", "remote": "English",
        "prompt": "Respond in English. Preserve names, quotations, code, and explicitly requested translations in their required language.",
        "voices": {"female": "en_US-amy-medium", "male": "en_US-ryan-medium"},
    },
    "zh": {
        "label": "CH", "name": "简体中文", "remote": "Chinese",
        "prompt": "请使用简体中文回答。姓名、引文、代码以及用户明确要求的翻译应保留所需语言。",
        "voices": {"female": "zh_CN-huayan-medium", "male": "zh_CN-huayan-medium"},
    },
}


def normalize(value, strict=False):
    code = str(value or "ru").strip().lower()
    aliases = {"rus": "ru", "russian": "ru", "eng": "en", "english": "en",
               "ch": "zh", "cn": "zh", "zh-cn": "zh", "chinese": "zh"}
    code = aliases.get(code, code)
    if code not in MODES:
        if strict:
            raise ValueError("язык должен быть RU, ENG или CH")
        return "ru"
    return code


def prompt(value):
    """Последнее системное правило: язык ответа, без полномочий на действие."""
    return MODES[normalize(value)]["prompt"]


def voice_id(value, gender="female"):
    voices = MODES[normalize(value)]["voices"]
    return voices.get("male" if gender == "male" else "female", "")


def voice_config(value, voice):
    """Копия конфигурации голоса с языком и, если нужен, языковым Piper."""
    code = normalize(value)
    out = dict(voice or {})
    out["_language"] = code
    out["_language_name"] = MODES[code]["remote"]
    selected = voice_id(code, out.get("_gender"))
    if selected:
        out["piper"] = selected
        out["length_scale"] = 1.0
    return out


def public(value, voice_ready=None, gender="female"):
    code = normalize(value)
    out = {"code": code, "label": MODES[code]["label"], "name": MODES[code]["name"],
           "voice_id": voice_id(code, gender)}
    if voice_ready is not None:
        out["voice_ready"] = bool(voice_ready)
    return out


def status_text(value, voice_ready=True):
    code = normalize(value)
    if code == "ru":
        return "Язык ответа и голоса: русский."
    if code == "en":
        return "Response language: English." if voice_ready else "English selected. Preparing the local voice; text is ready now."
    return "回答和语音语言：简体中文。" if voice_ready else "已选择简体中文。正在准备本地语音，文本现在即可使用。"
