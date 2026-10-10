"""Общая основа движка: импорты, константы и помощники, которые видят все части Engine (engine_*.py)
через `from engine_base import *` — поэтому всё нужное частям импортируется здесь (см. __all__ в конце).

Устройство движка: состояния idle → listening → thinking → speaking → (listening на время «продолжения
разговора») → idle, плюс muted. Потоки: audio — микрофон кадрами по 32 мс, VAD и слово запуска, нарезка фраз;
stt — очередь фраз → текст (GigaAM / удалённый / Vosk); turn — на каждый вопрос: токены модели → фразы →
синтез → динамик; новый вопрос или «стоп» сразу отменяет текущий ход.
Здесь же: поиск имени в начале фразы (find_name), фразы «замолчи» (is_sleep_phrase), скрытие паролей в журнале."""

import collections
import difflib
import json
import subprocess
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import voicefx
from workspace import Workspace, WorkspaceError
from tasks import TaskManager
from updater import Updater
from version import VERSION
from audio_io import AEC_SINK, AEC_SOURCE, AudioOutError, Capture, EchoCancel, FRAME, RATE, Player, ToneOut, list_devices, tone
from listen import MEDIA_WORDS, STOP_WORDS, SileroVAD, WakeSpotter, ensure_vosk, missing_words
from llm import (CodeFilter, LLMError, SentenceSplitter, discover_local, list_models, speakable, stream_chat, stream_events,
                 test_profile, tool_turn_messages, user_message, probe_tools)
from personas import PIPER_VOICES, pronounce
from settings import DATA_DIR, LLM_PRESETS, MODELS_DIR, OS_NAME, STATE_DIR
from stt import GigaAMSTT, RemoteSTT, VoskSTT
import provision
from mcp import MCPError, MCPManager
from skills import SkillError, Skills
from tools import Reminders, ToolError, Toolbox, desktop_notify
from tts import ElevenTTS, EspeakTTS, PiperTTS, RemoteTTS, SapiTTS, VoskTTS

log = logging.getLogger("dewiar.engine")
_report_tls = threading.local()

FRAME_S = FRAME / RATE
_WORD = re.compile(r"[\wёЁ]+(?:-[\wёЁ]+)*")
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря"]


def _norm(w):
    return w.lower().replace("ё", "е")


INTERJECTIONS = {"эй", "ну", "слушай", "привет", "окей", "ок", "хей", "алло", "так", "а"}


def find_name(text, aliases_by_pid, strict=False):
    """Ищет обращение по имени в начале фразы -> (pid, конец имени в тексте) или (None, 0).

    Обычный режим — имя уже подтвердил Vosk, достаточно похожести (≥ 0.75) среди первых трёх слов.
    Строгий режим — для имён, которых нет в словаре Vosk (например «Девиар»), имя ищется в каждой
    фразе, поэтому: только первое слово (или после «эй», «слушай»…), имена до 4 букв — только точно,
    длинные — очень близко (≥ 0.86). Иначе «игра» будила бы Лиру, а «дева» — Эву.
    Распознаватель рвёт имя («Де Виар») — два соседних слова пробуем и склеенными."""
    words = list(_WORD.finditer(text))
    if strict:
        start = 1 if words and _norm(words[0].group()) in INTERJECTIONS else 0
        positions = range(start, min(start + 1, len(words)))
    else:
        positions = range(min(3, len(words)))
    best = (0.0, None, 0)
    for i in positions:
        cands = [(_norm(words[i].group()), words[i].end(), False)]
        if i + 1 < len(words):                  # «Де виар», «деви ар» — склеиваем
            cands.append((_norm(words[i].group() + words[i + 1].group()), words[i + 1].end(), True))
        for w, end, joined in cands:
            if len(w) < 3:
                continue
            for pid, aliases in aliases_by_pid.items():
                for a in aliases:
                    a = _norm(a).replace(" ", "").replace("-", "")
                    if strict and len(a) <= 4:
                        r = 1.0 if w == a else 0.0
                    else:
                        r = difflib.SequenceMatcher(None, w, a).ratio()
                        if joined and r < 0.9 and strict:
                            r = 0.0
                    if r > best[0]:
                        best = (r, pid, end)
    need = 0.86 if strict else 0.75
    return (best[1], best[2]) if best[0] >= need else (None, 0)


_PW_PIPE = re.compile(r"((?:echo|printf)\s+)(['\"]?)([^'\"|;&\s]+)\2(\s*\|\s*sudo)")
_PW_WORD = re.compile(r"(парол\w*|password|passwd|pass)([^.\n]{0,60})", re.I)


def redact(text):
    """Пароли — не в журнал: «echo 'пароль' | sudo -S», «пароль администратора 1234abcd» → ***."""
    t = _PW_PIPE.sub(lambda m: m.group(1) + m.group(2) + "***" + m.group(2) + m.group(4), str(text or ""))
    return _PW_WORD.sub(lambda m: m.group(1) + re.sub(r"(?<![\w/])(?=\S*\d)\S{4,}", "***", m.group(2)), t)


def _spoken_question(q):
    """Вопрос «выполнить?» вслух — коротко: длинную команду не диктуем, она показана в виджете целиком."""
    q = (q or "").strip()
    if len(q) <= 90 and not re.search(r"[|;$`{}<>=\\&]|\s-{1,2}\w", q):
        return q
    code = re.compile(r"[|;$`{}<>=\\&/]|\s-{1,2}\w|^\s*(sudo|echo|cd|ls|cat|grep)\b")
    parts = q.split(": ")
    head = parts[0]
    for part in parts[1:]:
        if code.search(part) or len(head) + len(part) > 90:
            break
        head += ": " + part
    head = head.strip().rstrip("?")
    if len(head) > 90:
        head = head[:80].rsplit(" ", 1)[0]
    return f"{head}? Подробности — на экране."


def _tool_detail(name, args):
    """Что именно делает инструмент — одной строкой для «хода работы» (команда, запрос, файл, адрес)."""
    a = args if isinstance(args, dict) else {}
    for k in ("command", "query", "question", "url", "path", "file", "name", "text", "city", "title"):
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:240]
    for v in a.values():
        if isinstance(v, str) and v.strip():
            return v.strip()[:240]
    return ""


class Turn:
    """Один ход разговора (вопрос → ответ): номер, флаг отмены, сказанные фразы и полный текст ответа."""
    def __init__(self, n):
        self.n = n
        self.cancel = threading.Event()
        self.spoken = []
        self.full = ""
        self.via = None          # откуда вопрос не голосом (Telegram): {"done": f(text), "confirm": f(q), "speak": bool}
        self.report = None       # f(ok, text) после хода: ok — True/False, None — ход перебили (дела по расписанию)
        self.error = ""


SLEEP_STRONG = {"стоп", "stop", "хватит", "замолчи", "замолкни", "стой", "тихо", "тишина", "пауза", "достаточно", "помолчи",
                "прекрати", "прекращай", "остановись", "останови", "перестань", "отмена", "отмени", "отбой", "всё", "все",
                "спасибо", "спасиб", "пока", "стопэ", "стоб"}
SLEEP_SOFT = {"пожалуйста", "уже", "ну", "а", "давай", "же", "так", "на", "этом", "сейчас", "ладно", "хорошо", "окей", "ок",
              "ok", "okay", "it", "please", "молодец", "понял", "поняла", "спать", "пора", "говорить", "болтать"}


def low_priority():
    """Понижает приоритет текущего потока для тяжёлой фоновой работы (загрузка моделей): звук, слух и нажатия
    в виджете не должны ждать, пока грузится GigaAM на слабом компьютере. Linux/macOS — nice 10 для потока."""
    if os.name == "nt":                  # Windows: фоновый режим потока — ниже и процессор, и диск, и память
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.GetCurrentThread.restype = ctypes.c_void_p
            if not k.SetThreadPriority(ctypes.c_void_p(k.GetCurrentThread()), 0x00010000):      # THREAD_MODE_BACKGROUND_BEGIN
                k.SetThreadPriority(ctypes.c_void_p(k.GetCurrentThread()), -2)                 # THREAD_PRIORITY_LOWEST
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass


def is_sleep_phrase(text):
    """«Стоп», «Stop.», «хватит, спасибо», «всё, отбой», «ладно, помолчи» — фраза целиком про «замолчи».
    Такие фразы не идут в модель: ассистент засыпает до следующего имени (как «Алиса, хватит»)."""
    t = re.sub(r"[^\w\s]", " ", (text or "").lower().replace("ё", "е"))
    words = t.split()
    if not words or len(words) > 5:
        return False
    if " ".join(words) in {"не надо", "не нужно", "ничего", "забудь", "никак", "ничего не надо", "уже не надо", "не надо уже"}:
        return True
    strong = [w for w in words if w in SLEEP_STRONG or w.replace("е", "ё") in SLEEP_STRONG]
    if not strong or not all(w in SLEEP_STRONG or w in SLEEP_SOFT or w.replace("е", "ё") in SLEEP_STRONG for w in words):
        return False
    if set(strong) <= {"все", "всё", "спасибо", "спасиб", "пока"} and len(words) > 2:
        return False                                  # «спасибо, а что ещё…» — не прощание
    return True


# Окно ассистента голосом — фраза целиком (вежливые слова не мешают): «спрячься» — виджет в трей, ассистент слушает;
# «покажись» — вернуть виджет; «отключись» — выйти из Dewiar совсем (ядро тоже: голосом обратно уже не включить).
# Только целиком: «спрячь файл в папку» или «выключи компьютер» — не сюда (компьютер — pc.py).
# в начале может стоять имя («Лира, спрячься» — STT отдаёт его вместе с командой): одно слово, кроме «не»
_WIN_FILL = r"(?:(?!не\s)[a-zа-я]{2,15}\s+(?=(?:ну|а|давай|теперь|пока|уже|пожалуйста|можешь|ка|спрячь|скрой|исчезни|сверни|уйди|иди|уходи|убери|покаж|появись|вернись|выйди|верни|отключ|выключ|заверш|закр)))?" \
            r"(?:(?:ну|а|давай|теперь|пока|уже|пожалуйста|можешь|ка|совсем|полностью|насовсем)\s+)*"
_WIN_TRAY = r"(?:трей|трэй|tray|трея)"
WINDOW_RX = {
    "tray": re.compile(rf"^{_WIN_FILL}(?:(?:спрячься|скройся|исчезни|свернись|уйди)(?:\s+в\s+{_WIN_TRAY})?|"
                       rf"(?:спрячь|убери|сверни|скрой)\s+(?:виджет|окно|окошко|себя)(?:\s+в\s+{_WIN_TRAY})?|"
                       rf"(?:иди|уходи)\s+в\s+{_WIN_TRAY})(?:\s+пожалуйста)?$"),
    "show": re.compile(rf"^{_WIN_FILL}(?:покажись|появись|вернись\s+на\s+экран|выйди\s+из\s+{_WIN_TRAY}|"
                       r"(?:покажи|верни)\s+(?:виджет|окно|окошко|себя))(?:\s+пожалуйста)?$"),
    "quit": re.compile(rf"^{_WIN_FILL}(?:отключись|выключись|завершись|закройся|выйди\s+из\s+(?:программы|приложения)|"
                       r"(?:закрой|выключи|отключи)\s+(?:программу|приложение|ассистента|себя|dewiar|девиар|дьюар))"
                       r"(?:\s+(?:совсем|полностью|насовсем))?(?:\s+пожалуйста)?$"),
}


def window_phrase(text):
    """«Спрячься», «уйди в трей» -> "tray"; «покажись» -> "show"; «отключись», «закрой программу» -> "quit"; иначе None."""
    t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower().replace("ё", "е"))).strip()
    return next((k for k, rx in WINDOW_RX.items() if rx.match(t)), None)


MEDIA_STOP = {"пауза", "стоп", "стой", "хватит", "тихо", "тишина", "замолчи"}   # одно слово при музыке — пауза
# «позови Лиру», «дай слово Эве, пусть расскажет…» — передать разговор другому персонажу: группа 1 — имя, 2 — остаток фразы
CALL_RX = re.compile(r"^\s*(?:а\s+|ну\s+|слушай,?\s+)?(?:позови(?:те)?|зови|пригласи|дай(?:те)?\s+слово|передай\s+слово|"
                     r"переключи(?:сь)?\s+на|хочу\s+(?:поговорить|говорить)\s+с|пусть\s+(?:ответит|скажет|расскажет))"
                     r"\s+([\wё-]+)[\s,.!?:;—-]*(.*)$", re.I | re.S)


def _first_then_stream(gen):
    """Дождаться первого события потока (ошибка сервера всплывёт здесь, до первого слова), дальше — потоком."""
    import itertools
    try:
        first = next(gen)
    except StopIteration:
        return iter(())
    return itertools.chain([first], gen)


def _has_images(x):
    if isinstance(x, dict):
        return x.get("type") in ("image", "image_url") or any(_has_images(v) for v in x.values())
    if isinstance(x, list):
        return any(_has_images(v) for v in x)
    return False


def _drop_images(x):
    """Сообщения без картинок: вместо них — пометка, что модель их не видит."""
    if isinstance(x, list):
        out = []
        for v in x:
            if isinstance(v, dict) and v.get("type") in ("image", "image_url"):
                out.append({"type": "text", "text": "(картинка есть, но эта модель не умеет смотреть картинки — "
                                                    "скажи об этом пользователю честно, не выдумывай, что на ней)"})
            else:
                out.append(_drop_images(v))
        return out
    if isinstance(x, dict):
        d = {k: _drop_images(v) for k, v in x.items()}
        c = d.get("content")
        if d.get("role") in ("user", "assistant") and isinstance(c, list) and c and \
                all(isinstance(v, dict) and v.get("type") == "text" for v in c):
            d["content"] = "\n".join(v.get("text", "") for v in c)      # остался только текст — обычной строкой
        return d
    return x


# всё, что ниже, видят части движка (engine_*.py): from engine_base import *
__all__ = [n for n in dict(globals()) if not n.startswith("__")]
