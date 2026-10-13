#!/usr/bin/env python3
"""
DEWIAR VOICES — живые голоса персонажей на своей видеокарте (Qwen3-TTS, Apache-2.0).

Одна служба на сервере, как распознавание GigaAM (dewiar-asr): модель держится в памяти, запросы идут по одному
на видеокарту, а длинный ответ звучит по фразам — первая фраза начинает играть, пока считаются следующие.

Откуда берутся голоса:
  • встроенные дикторы Qwen (serena, vivian, ono_anna, sohee — женские; aiden, ryan, dylan, eric, uncle_fu — мужские).
    Ими персонажи Dewiar говорят с первого дня, без настройки;
  • свой голос по образцу: 5–30 секунд чистой речи и её текст — голос повторяется по образцу (модель Base);
  • голос по описанию: «тёплый женский голос, лет тридцать, с лёгкой улыбкой» — модель VoiceDesign один раз говорит
    пробную фразу, понравившийся вариант сохраняется как образец, и дальше голос звучит одинаково.
Кому какой голос — в voices.json: personas (персонаж Dewiar → голос) сильнее aliases (имя от приложения → голос).
Всё это настраивается в панели («Голоса»), руками править файл не нужно.

API (только стандартная библиотека; стандарт OpenAI там, где он есть):
  GET  /health                     состояние: модели, видеопамять, очередь, сколько озвучено, время до первого звука
  GET  /v1/audio/voices            голоса, персонажи, псевдонимы (то же — /v1/voices)
  POST /v1/audio/speech            JSON {input, voice, persona?, speed?, response_format: pcm|wav|mp3|opus|aac|flac,
                                   stream?, stream_format?: "sse", language?, instruct?}.
                                   pcm — поток 16 бит 24 кГц моно; wav со stream — поток с заголовком;
                                   sse — base64-куски событиями speech.audio.delta
  GET  /v1/voices/<id>/sample      образец своего голоса (wav)
  POST /v1/voices                  добавить свой голос: multipart (file, name, title, gender, text) или JSON с draft
  POST /v1/voices/design           JSON {instruct, gender?, text?} → wav пробы, заголовок X-Draft-Id
  POST /v1/voices/update           JSON {id, title?, gender?, text?, instruct?}
  POST /v1/voices/delete           JSON {id}
  POST /v1/voices/config           JSON {personas?, aliases?, default?} — кому какой голос
Управление (всё, кроме speech и списка) закрывается ключом TTS_ADMIN_KEY, если он задан; служба живёт во внутренней
сети, наружу её отдаёт только шлюз — и только /v1/audio/speech и список голосов.

TTS_FAKE=1 — вместо модели тон нужной длины: для тестов без видеокарты.
"""
import base64
import gc
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s voices %(levelname)s %(message)s")
log = logging.getLogger("voices")

PORT = int(os.getenv("TTS_PORT", "8000"))
DEVICE_ENV = os.getenv("TTS_DEVICE", "auto")                       # auto | cpu | cuda | cuda:1
DTYPE = os.getenv("TTS_DTYPE", "bfloat16")
ATTN = os.getenv("TTS_ATTN", "")                                   # flash_attention_2, если он стоит; пусто — как решит torch
DATA = os.getenv("TTS_DATA", "/data")
MODELS = {
    "custom": os.getenv("TTS_CUSTOM_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"),
    "base": os.getenv("TTS_BASE_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
    "design": os.getenv("TTS_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"),
}
PRELOAD = [x.strip() for x in os.getenv("TTS_PRELOAD", "auto").split(",") if x.strip()]
MAX_MODELS = max(1, int(os.getenv("TTS_MAX_MODELS", "2")))         # больше — выгружается та, что дольше не звучала
GPU_MEM_GB = float(os.getenv("TTS_GPU_MEM_GB", "0") or 0)
BATCH = max(1, int(os.getenv("TTS_BATCH", "4")))                   # фраз за один проход после первой
MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "8000"))
OUT_SR = 24000                                                     # pcm без заголовка — 24 кГц, как у OpenAI
KEY = os.getenv("TTS_KEY", "")                                     # ключ для озвучки (пусто — внутренняя сеть)
ADMIN_KEY = os.getenv("TTS_ADMIN_KEY", "")                         # ключ для управления голосами
FAKE = os.getenv("TTS_FAKE", "") == "1"
REF_MAX_SEC = float(os.getenv("TTS_REF_MAX_SEC", "30"))
DRAFT_TTL = 3600

BUILTIN = {"serena": "female", "vivian": "female", "ono_anna": "female", "sohee": "female",
           "aiden": "male", "ryan": "male", "dylan": "male", "eric": "male", "uncle_fu": "male"}
BUILTIN_TITLE = {"serena": "Серена", "vivian": "Вивиан", "ono_anna": "Анна", "sohee": "Сохи", "aiden": "Эйден",
                 "ryan": "Райан", "dylan": "Дилан", "eric": "Эрик", "uncle_fu": "Дядя Фу"}
OPENAI = {"alloy": "female", "nova": "female", "shimmer": "female", "coral": "female", "sage": "female",
          "echo": "male", "onyx": "male", "fable": "male", "ash": "male", "ballad": "male", "verse": "male"}
SAMPLE = {"female": "Привет! Я так рада тебя слышать. Давай посмотрим, что у нас сегодня по плану, и начнём с самого важного.",
          "male": "Привет! Я рад тебя слышать. Давай посмотрим, что у нас сегодня по плану, и начнём с самого важного."}
NAME_RX = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,39}$")

STATE = {"loaded": [], "loading": "", "error": "", "device": "", "started": time.time(), "fake": FAKE,
         "requests": 0, "errors": 0, "chars": 0, "audio_sec": 0.0, "busy_sec": 0.0, "waiting": 0, "busy": False,
         "last_request": 0, "ttfa_ms_last": 0, "ttfa_ms_sum": 0, "ttfa_n": 0}
STATS = threading.Lock()


def stat_add(**kw):
    with STATS:
        for k, v in kw.items():
            STATE[k] = STATE.get(k, 0) + v


# ── настройки голосов ────────────────────────────────────────────────────
CFG_LOCK = threading.Lock()


def vdir(*p):
    return os.path.join(DATA, "voices", *p)


def cfg_path():
    return os.path.join(DATA, "voices.json")


def cfg_load() -> dict:
    try:
        with open(cfg_path(), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    c.setdefault("default", {})
    c["default"].setdefault("female", "serena")
    c["default"].setdefault("male", "aiden")
    for k in ("personas", "aliases", "voices"):
        if not isinstance(c.get(k), dict):
            c[k] = {}
    return c


def cfg_save(c: dict):
    os.makedirs(DATA, exist_ok=True)
    tmp = cfg_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg_path())


def exists(c: dict, vid: str) -> bool:
    return vid in c["voices"] or vid in BUILTIN


def resolve(voice: str = "", persona: str = "", gender: str = "") -> dict:
    """Какой голос звучит: персонаж → псевдоним → свой голос → встроенный → голос по умолчанию для пола."""
    c = cfg_load()
    name = c["personas"].get((persona or "").strip().lower(), "")
    if not name:
        v = (voice or "").strip().lower()
        name = c["aliases"].get(v, v)
    for _ in range(3):                                   # псевдоним на псевдоним — не дальше трёх шагов
        if name in c["voices"]:
            spec = dict(c["voices"][name], id=name)
            spec.setdefault("kind", "clone")
            if spec["kind"] == "speaker":
                spec.setdefault("speaker", name if name in BUILTIN else "serena")
            return spec
        if name in BUILTIN:
            return {"id": name, "kind": "speaker", "speaker": name, "gender": BUILTIN[name]}
        g = OPENAI.get(name) or (gender if gender in ("female", "male") else "female")
        nxt = c["default"].get(g) or ("serena" if g == "female" else "aiden")
        if nxt == name:
            break
        name = nxt
    return {"id": "serena", "kind": "speaker", "speaker": "serena", "gender": "female"}


def voices_public() -> dict:
    c = cfg_load()
    out = []
    for vid, g in BUILTIN.items():
        own = c["voices"].get(vid) or {}
        out.append({"id": vid, "title": own.get("title") or BUILTIN_TITLE[vid], "gender": g, "kind": "speaker",
                    "builtin": True, "instruct": own.get("instruct", "")})
    for vid, v in c["voices"].items():
        if vid in BUILTIN:
            continue
        out.append({"id": vid, "title": v.get("title") or vid, "gender": v.get("gender", ""), "kind": v.get("kind", "clone"),
                    "builtin": False, "text": v.get("text", ""), "instruct": v.get("instruct", ""),
                    "designed": v.get("designed", ""), "added": v.get("added", 0)})
    return {"object": "list", "voices": out, "data": [{"id": x["id"], "object": "voice"} for x in out],
            "personas": c["personas"], "aliases": c["aliases"], "default": c["default"]}


# ── текст → фразы ────────────────────────────────────────────────────────
def clean(text: str) -> str:
    text = text.replace("́", "").replace("­", "")              # знаки ударения и мягкие переносы модели не нужны
    text = re.sub(r"[*_`#>|~]+", " ", text)                              # разметка из ответа модели
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_text(text: str, first_max: int = 70, max_len: int = 220):
    """Фразы с паузой после каждой. Первая — короткая: чем быстрее она готова, тем раньше начинается голос."""
    text = clean(text)
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    out = []
    for p in parts:
        while len(p) > max_len:                                           # длинное предложение — по запятой, иначе по пробелу
            cut = max((m.end() for m in re.finditer(r"[,;:—–]\s", p[:max_len])), default=0)
            if cut < 40:
                cut = p.rfind(" ", 0, max_len) + 1 or max_len
            out.append((p[:cut].strip(), 0.12))
            p = p[cut:].strip()
        if p:
            out.append((p, 0.24 if p[-1] in ".!?…" else 0.12))
    if out and len(out[0][0]) > first_max:
        p, pause = out[0]
        m = re.search(r"[,;:—–]\s", p[25:first_max + 40])
        if m:
            cut = 25 + m.end()
            out[0:1] = [(p[:cut].strip(), 0.1), (p[cut:].strip(), pause)]
    return out


def lang_of(text: str, asked: str = "") -> str:
    if asked:
        return {"ru": "Russian", "en": "English", "zh": "Chinese", "de": "German", "fr": "French", "es": "Spanish",
                "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean"}.get(asked.lower()[:2], asked)
    return "Russian" if re.search(r"[А-Яа-яЁё]", text) else "Auto"


# ── звук ─────────────────────────────────────────────────────────────────
def to_mono(w) -> np.ndarray:
    a = np.asarray(w, dtype=np.float32)
    return a.mean(axis=0 if a.shape[0] < a.shape[-1] else 1) if a.ndim > 1 else a


def resample(a: np.ndarray, sr: int, to: int = OUT_SR) -> np.ndarray:
    if sr == to or a.size == 0:
        return a
    n = int(round(a.size * to / sr))
    return np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a).astype(np.float32)


def trim(a: np.ndarray, sr: int = OUT_SR) -> np.ndarray:
    """Тишина по краям фразы убирается — паузы между фразами задаём сами, ровные."""
    if a.size == 0:
        return a
    fr = max(1, sr // 100)
    n = a.size // fr
    if n < 3:
        return a
    rms = np.sqrt((a[:n * fr].reshape(n, fr) ** 2).mean(axis=1))
    on = np.where(rms > max(0.006, rms.max() * 0.02))[0]
    if on.size == 0:
        return a[:0]
    s = max(0, (on[0] - 4) * fr)
    e = min(a.size, (on[-1] + 7) * fr)
    return a[s:e]


def level(a: np.ndarray) -> np.ndarray:
    """Громкость ровная от фразы к фразе и от голоса к голосу: средняя −20 дБ, пики не выше −1 дБ."""
    if a.size == 0:
        return a
    rms = float(np.sqrt((a ** 2).mean()))
    if rms > 1e-5:
        a = a * min(3.0, max(0.5, 0.1 / rms))
    pk = float(np.abs(a).max())
    return a * (0.89 / pk) if pk > 0.89 else a


def tempo(a: np.ndarray, speed: float, sr: int = OUT_SR) -> np.ndarray:
    """Темп без смены высоты голоса (ffmpeg atempo); у модели своего параметра скорости нет."""
    if abs(speed - 1.0) < 0.04 or a.size == 0 or not shutil.which("ffmpeg"):
        return a
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(sr),
                        "-ac", "1", "-i", "-", "-af", f"atempo={speed:.3f}", "-f", "f32le", "-"],
                       input=a.astype(np.float32).tobytes(), capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy() if r.returncode == 0 and r.stdout else a


def pcm16(a: np.ndarray) -> bytes:
    return (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()


def wav_bytes(a: np.ndarray, sr: int = OUT_SR) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16(a))
    return b.getvalue()


def wav_head_stream(sr: int = OUT_SR) -> bytes:
    """Заголовок WAV для потока: длина неизвестна — максимальная, как делают потоковые серверы."""
    big = 0xFFFFFFFF - 36
    return (b"RIFF" + (big + 36).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
            + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + sr.to_bytes(4, "little")
            + (sr * 2).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
            + b"data" + big.to_bytes(4, "little"))


def encode(a: np.ndarray, fmt: str) -> tuple:
    if fmt == "pcm":
        return pcm16(a), "audio/pcm"
    w = wav_bytes(a)
    if fmt == "wav" or not shutil.which("ffmpeg"):
        return w, "audio/wav"
    codec = {"mp3": ("mp3", "libmp3lame", "audio/mpeg"), "opus": ("ogg", "libopus", "audio/ogg"),
             "aac": ("adts", "aac", "audio/aac"), "flac": ("flac", "flac", "audio/flac")}.get(fmt)
    if not codec:
        return w, "audio/wav"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "-",
                        "-c:a", codec[1], "-b:a", "96k", "-f", codec[0], "-"], input=w, capture_output=True)
    return (r.stdout, codec[2]) if r.returncode == 0 and r.stdout else (w, "audio/wav")


def read_audio(data: bytes, max_sec: float = REF_MAX_SEC) -> np.ndarray:
    """Образец голоса из любого файла → моно 24 кГц. Без ffmpeg читается только WAV."""
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "-", "-vn", "-ac", "1",
                            "-ar", str(OUT_SR), "-f", "f32le", "-"], input=data, capture_output=True)
        if r.returncode != 0:
            raise ValueError("не получилось прочитать запись: " + r.stderr.decode("utf-8", "replace")[-200:])
        a = np.frombuffer(r.stdout, dtype=np.float32).copy()
    else:
        with wave.open(io.BytesIO(data)) as w:
            sr, ch = w.getframerate(), w.getnchannels()
            a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
            if ch > 1:
                a = a.reshape(-1, ch).mean(axis=1)
            a = resample(a, sr)
    a = trim(a)
    if a.size < OUT_SR * 3:
        raise ValueError("в записи меньше 3 секунд речи — нужно 5–30 секунд чистого голоса")
    if a.size > OUT_SR * max_sec:
        raise ValueError(f"запись длиннее {int(max_sec)} секунд — возьмите кусок 5–30 секунд, где человек говорит ровно и без музыки")
    return level(a)


# ── модели ───────────────────────────────────────────────────────────────
GPU = threading.Lock()                                   # одна видеокарта — один проход за раз, остальные ждут


class QwenEngine:
    def __init__(self):
        self.models = {}                                 # роль → [модель, когда звучала]
        self.prompts = {}                                # ключ образца → подсказка клонирования
        self.sr = OUT_SR

    def device(self):
        import torch
        dev = DEVICE_ENV
        if dev == "auto":
            dev = "cuda:0" if torch.cuda.is_available() else "cpu"
        if dev == "cuda":
            dev = "cuda:0"
        return dev

    def get(self, role):
        if role in self.models:
            self.models[role][1] = time.time()
            return self.models[role][0]
        while len(self.models) >= MAX_MODELS:            # место на видеокарте — за счёт той, что дольше молчит
            old = min(self.models, key=lambda r: self.models[r][1])
            self.unload(old)
        import torch
        from qwen_tts import Qwen3TTSModel
        dev = self.device()
        if dev.startswith("cuda") and GPU_MEM_GB > 0 and not self.models:
            total = torch.cuda.get_device_properties(torch.device(dev)).total_memory / 1024 ** 3
            torch.cuda.set_per_process_memory_fraction(min(1.0, GPU_MEM_GB / total), torch.device(dev))
        kw = {"device_map": dev, "dtype": getattr(torch, DTYPE) if dev != "cpu" else torch.float32}
        if ATTN:
            kw["attn_implementation"] = ATTN
        STATE["loading"] = role
        t0 = time.time()
        log.info("загружаю %s (%s) на %s", role, MODELS[role], dev)
        try:
            try:
                m = Qwen3TTSModel.from_pretrained(MODELS[role], **kw)
            except Exception as e:  # noqa: BLE001
                # Видеокарта общая с vLLM: второй модели может не хватить места — тогда держим одну, а не падаем
                if "out of memory" not in str(e).lower() or not self.models:
                    raise
                log.warning("для %s не хватило видеопамяти — выгружаю %s и пробую снова", role, ", ".join(self.models))
                for r in list(self.models):
                    self.unload(r)
                m = Qwen3TTSModel.from_pretrained(MODELS[role], **kw)
        finally:
            STATE["loading"] = ""
        log.info("%s готова за %.1f с", role, time.time() - t0)
        self.models[role] = [m, time.time()]
        STATE.update(device=dev, loaded=sorted(self.models), error="")
        return m

    def unload(self, role):
        if self.models.pop(role, None) is None:
            return
        if role == "base":
            self.prompts.clear()
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        STATE["loaded"] = sorted(self.models)
        log.info("%s выгружена", role)

    def prompt(self, path, text):
        key = (path, os.path.getmtime(path), text)
        if key not in self.prompts:
            m = self.get("base")
            a = trim(read_wav(path))
            self.prompts[key] = m.create_voice_clone_prompt(ref_audio=(a, OUT_SR), ref_text=text or None,
                                                            x_vector_only_mode=not text)
        return self.prompts[key]

    def generate(self, spec, texts, lang):
        try:
            return self._generate(spec, texts, lang)
        except ValueError as e:                           # язык не из списка модели — пусть определит сама
            if "language" not in str(e).lower() or lang == "Auto":
                raise
            log.warning("язык %s не принят моделью — говорю с Auto", lang)
            return self._generate(spec, texts, "Auto")

    def _generate(self, spec, texts, lang):
        n = len(texts)
        kind = spec.get("kind")
        if kind == "clone":
            p = self.prompt(vdir(spec["audio"]), spec.get("text", ""))
            wavs, sr = self.get("base").generate_voice_clone(text=texts, language=[lang] * n, voice_clone_prompt=p * n)
        elif kind == "design":
            wavs, sr = self.get("design").generate_voice_design(text=texts, instruct=[spec.get("instruct", "")] * n,
                                                                language=[lang] * n)
        else:
            ins = spec.get("instruct") or ""
            wavs, sr = self.get("custom").generate_custom_voice(text=texts, speaker=[spec["speaker"]] * n,
                                                                language=[lang] * n, instruct=[ins] * n)
        return [to_mono(w) for w in wavs], int(sr)


class FakeEngine:
    """Без модели: тон длиной по тексту. Записывает вызовы — тесты видят, что и каким голосом просили."""

    def __init__(self):
        self.calls = []
        self.models = {}
        self.delay = float(os.getenv("TTS_FAKE_DELAY", "0"))

    def get(self, role):
        if role not in self.models:
            while len(self.models) >= MAX_MODELS:
                self.unload(min(self.models, key=lambda r: self.models[r][1]))
            self.models[role] = [role, time.time()]
            STATE.update(loaded=sorted(self.models), device="fake")
        self.models[role][1] = time.time()
        return role

    def unload(self, role):
        self.models.pop(role, None)
        STATE["loaded"] = sorted(self.models)

    def generate(self, spec, texts, lang):
        role = {"clone": "base", "design": "design"}.get(spec.get("kind"), "custom")
        self.get(role)
        self.calls.append({"voice": spec.get("id"), "kind": spec.get("kind"), "texts": list(texts), "lang": lang,
                           "speaker": spec.get("speaker"), "instruct": spec.get("instruct", "")})
        if self.delay:
            time.sleep(self.delay)
        sr = 24000
        out = []
        for t in texts:
            n = int(sr * (0.2 + 0.05 * len(t)))
            x = np.arange(n) / sr
            out.append((0.3 * np.sin(2 * np.pi * 220 * x)).astype(np.float32))
        return out, sr


ENGINE = FakeEngine() if FAKE else QwenEngine()


def read_wav(path) -> np.ndarray:
    with wave.open(path) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return resample(a, sr)


def on_gpu(fn):
    """Проход по видеокарте: по одному, с учётом очереди и занятого времени — для панели."""
    stat_add(waiting=1)
    with GPU:
        stat_add(waiting=-1)
        STATE["busy"] = True
        t0 = time.time()
        try:
            return fn()
        finally:
            STATE["busy"] = False
            stat_add(busy_sec=time.time() - t0)


def synth_iter(text, spec, speed=1.0, lang="Russian"):
    """Фраза за фразой: первая — одна (быстрее голос), дальше пачками по BATCH. Каждая пачка отдельно встаёт в очередь
    видеокарты, поэтому два разговора одновременно не ждут друг друга целиком."""
    parts = split_text(text)
    i = 0
    while i < len(parts):
        group = parts[i:i + (1 if i == 0 else BATCH)]
        i += len(group)
        wavs, sr = on_gpu(lambda g=group: ENGINE.generate(spec, [p for p, _ in g], lang))
        for (_, pause), w in zip(group, wavs):
            a = level(trim(resample(to_mono(w), sr)))
            a = tempo(a, speed)
            yield np.concatenate([a, np.zeros(int(OUT_SR * pause / max(0.5, speed)), dtype=np.float32)])


def preload():
    want = PRELOAD
    if want == ["auto"]:
        c = cfg_load()
        want = ["custom"]
        if any(v.get("kind", "clone") == "clone" for k, v in c["voices"].items() if k not in BUILTIN):
            want.append("base")
    for role in want[:MAX_MODELS]:
        if role not in MODELS:
            continue
        try:
            spec = {"kind": "clone" if role == "base" else role if role == "design" else "speaker", "speaker": "serena",
                    "instruct": "спокойный голос"}
            if role == "base":
                on_gpu(lambda: ENGINE.get("base"))
                continue
            for _ in synth_iter("Проверка голоса.", spec):                # прогрев: первый проход на CUDA медленный
                pass
        except Exception as e:  # noqa: BLE001
            STATE["error"] = f"{role}: {e}"
            log.exception("не загрузилась %s", role)


# ── управление голосами ──────────────────────────────────────────────────
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                     "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(title: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in (title or "").lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:32]
    return s or "voice_" + uuid.uuid4().hex[:6]


def drafts_clean():
    d = os.path.join(DATA, "drafts")
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if time.time() - os.path.getmtime(p) > DRAFT_TTL:
                os.remove(p)
    except OSError:
        pass


def add_voice(name, title, gender, text, audio: np.ndarray = None, draft: str = "", designed: str = "") -> dict:
    title = (title or "").strip()[:60]
    name = (name or "").strip().lower() or slug(title)
    if not NAME_RX.match(name):
        raise ValueError("имя голоса — латиницей, цифрами и _ (например anna_warm)")
    if name in BUILTIN:
        raise ValueError(f"«{name}» — встроенный диктор, выберите другое имя")
    if gender not in ("female", "male"):
        gender = ""
    if draft:
        if not re.match(r"^[a-f0-9]{12}$", draft):
            raise ValueError("нет такой пробы")
        src = os.path.join(DATA, "drafts", draft + ".wav")
        meta_p = os.path.join(DATA, "drafts", draft + ".json")
        if not os.path.isfile(src):
            raise ValueError("проба устарела — сделайте новую")
        with open(meta_p, encoding="utf-8") as f:
            meta = json.load(f)
        audio = read_wav(src)
        text = meta.get("text", "")
        designed = meta.get("instruct", "")
        gender = gender or meta.get("gender", "")
    if audio is None:
        raise ValueError("нужна запись голоса")
    text = clean(text or "")
    os.makedirs(vdir(), exist_ok=True)
    fn = name + ".wav"
    with open(vdir(fn), "wb") as f:
        f.write(wav_bytes(audio))
    entry = {"kind": "clone", "title": title or name, "gender": gender, "audio": fn, "text": text,
             "added": int(time.time())}
    if designed:
        entry["designed"] = designed
    if not FAKE:                                          # образец проверяется сразу: плохой файл — ошибка сейчас, а не в разговоре
        try:
            on_gpu(lambda: ENGINE.prompt(vdir(fn), text))
        except Exception as e:  # noqa: BLE001
            os.remove(vdir(fn))
            raise ValueError(f"модель не приняла образец: {e}") from e
    with CFG_LOCK:
        c = cfg_load()
        c["voices"][name] = entry
        cfg_save(c)
    return dict(entry, id=name)


def design_draft(instruct, gender="", text="", lang="") -> tuple:
    instruct = (instruct or "").strip()
    if len(instruct) < 8:
        raise ValueError("опишите голос подробнее: пол, возраст, тембр, манера — например «тёплый женский голос, лет тридцать, говорит с улыбкой»")
    g = gender if gender in ("female", "male") else ("male" if re.search(r"мужск|male\b|man\b", instruct, re.I) else "female")
    text = clean(text or SAMPLE[g])
    spec = {"id": "_design", "kind": "design", "instruct": instruct}
    # Проба — одним проходом: голос по описанию каждый раз немного другой, и фразы по отдельности звучали бы разными людьми
    wavs, sr = on_gpu(lambda: ENGINE.generate(spec, [text], lang_of(text, lang)))
    a = level(trim(resample(to_mono(wavs[0]), sr)))
    if os.getenv("TTS_DESIGN_KEEP", "") != "1":           # большая модель нужна на минуту — видеопамять возвращаем сразу
        on_gpu(lambda: ENGINE.unload("design"))
    drafts_clean()
    did = uuid.uuid4().hex[:12]
    d = os.path.join(DATA, "drafts")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, did + ".wav"), "wb") as f:
        f.write(wav_bytes(a))
    with open(os.path.join(d, did + ".json"), "w", encoding="utf-8") as f:
        json.dump({"text": text, "instruct": instruct, "gender": g}, f, ensure_ascii=False)
    return did, a


def update_voice(vid, body) -> dict:
    with CFG_LOCK:
        c = cfg_load()
        if vid in BUILTIN:
            e = c["voices"].setdefault(vid, {"kind": "speaker", "speaker": vid, "gender": BUILTIN[vid]})
        elif vid in c["voices"]:
            e = c["voices"][vid]
        else:
            raise KeyError(vid)
        for k in ("title", "instruct", "text"):
            if k in body:
                e[k] = clean(str(body[k] or ""))[:400]
        if body.get("gender") in ("female", "male") and vid not in BUILTIN:
            e["gender"] = body["gender"]
        if vid in BUILTIN and not e.get("title") and not e.get("instruct"):
            c["voices"].pop(vid)                              # пустая настройка встроенного — как будто её нет
        cfg_save(c)
        return dict(e, id=vid)


def delete_voice(vid):
    with CFG_LOCK:
        c = cfg_load()
        e = c["voices"].pop(vid, None)
        if e is None:
            raise KeyError(vid)
        for m in ("personas", "aliases"):                     # кто говорил этим голосом — вернётся к голосу по умолчанию
            c[m] = {k: v for k, v in c[m].items() if v != vid}
        cfg_save(c)
    if e.get("audio"):
        try:
            os.remove(vdir(e["audio"]))
        except OSError:
            pass


def set_config(body):
    with CFG_LOCK:
        c = cfg_load()
        for m in ("personas", "aliases"):
            if isinstance(body.get(m), dict):
                new = {}
                for k, v in body[m].items():
                    k, v = str(k).strip().lower(), str(v or "").strip().lower()
                    if not k or not v:
                        continue
                    if not exists(c, v):
                        raise ValueError(f"нет голоса «{v}»")
                    new[k] = v
                c[m] = new
        if isinstance(body.get("default"), dict):
            for g in ("female", "male"):
                v = str(body["default"].get(g) or "").strip().lower()
                if v:
                    if not exists(c, v):
                        raise ValueError(f"нет голоса «{v}»")
                    c["default"][g] = v
        cfg_save(c)
        return c


# ── HTTP ─────────────────────────────────────────────────────────────────
def parse_multipart(ctype: str, body: bytes):
    from email.parser import BytesParser
    from email.policy import default as email_default
    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
    fields, file = {}, None
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True) or b""
        if part.get_filename() is not None or name == "file":
            file = (data, part.get_filename() or "audio")
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, file


class H(BaseHTTPRequestHandler):
    server_version = "dewiar-voices/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if "/health" not in (args[0] if args else ""):
            log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code, body: bytes, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _err(self, code, msg, typ="invalid_request_error"):
        self.close_connection = True                     # тело запроса могло остаться непрочитанным
        self._json(code, {"error": {"message": msg, "type": typ, "code": code}})

    def _key_ok(self, key) -> bool:
        if not key:
            return True
        h = self.headers.get("Authorization", "")
        return h == "Bearer " + key or self.headers.get("X-Admin-Key", "") == key

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 60 * 1024 * 1024:
            raise ValueError("слишком большой запрос")
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            info = {"ok": True, **STATE, "uptime": int(time.time() - STATE["started"]), "models": MODELS,
                    "max_models": MAX_MODELS, "voices": len(cfg_load()["voices"]),
                    "instruct_ok": "0.6B" not in MODELS["custom"],          # манеру встроенным дикторам понимает только 1.7B
                    "ttfa_ms_avg": int(STATE["ttfa_ms_sum"] / STATE["ttfa_n"]) if STATE["ttfa_n"] else 0}
            info.pop("ttfa_ms_sum", None)
            try:
                import sys
                torch = sys.modules.get("torch")
                if torch is not None and str(STATE.get("device", "")).startswith("cuda") and torch.cuda.is_available():
                    d = torch.device(STATE["device"])
                    info["gpu_allocated_mb"] = int(torch.cuda.memory_allocated(d) / 1048576)
                    info["gpu_reserved_mb"] = int(torch.cuda.memory_reserved(d) / 1048576)
                    info["gpu_name"] = torch.cuda.get_device_name(d)
            except Exception:  # noqa: BLE001
                pass
            return self._json(200, info)
        if u.path in ("/v1/audio/voices", "/v1/voices"):
            return self._json(200, voices_public())
        if u.path in ("/v1/models", "/models"):
            return self._json(200, {"object": "list", "data": [{"id": "qwen3-tts", "object": "model", "owned_by": "dewiar"},
                                                               {"id": "tts-1", "object": "model", "owned_by": "dewiar"}]})
        m = re.match(r"^/v1/voices/([a-z0-9_-]+)/sample$", u.path)
        if m:
            if not self._key_ok(ADMIN_KEY):
                return self._err(401, "нужен ключ управления")
            e = cfg_load()["voices"].get(m.group(1)) or {}
            p = vdir(e["audio"]) if e.get("audio") else ""
            if not p or not os.path.isfile(p):
                return self._err(404, "у этого голоса нет образца")
            with open(p, "rb") as f:
                return self._send(200, f.read(), "audio/wav")
        m = re.match(r"^/v1/voices/drafts/([a-f0-9]{12})$", u.path)
        if m:
            p = os.path.join(DATA, "drafts", m.group(1) + ".wav")
            if not os.path.isfile(p):
                return self._err(404, "проба устарела")
            with open(p, "rb") as f:
                return self._send(200, f.read(), "audio/wav")
        self._err(404, "not found")

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path in ("/v1/audio/speech", "/audio/speech"):
                return self._speech()
            if not u.path.startswith("/v1/voices"):
                return self._err(404, "not found")
            if not self._key_ok(ADMIN_KEY):
                return self._err(401, "нужен ключ управления")
            raw = self._body()
            ctype = self.headers.get("Content-Type", "")
            if u.path == "/v1/voices" and ctype.lower().startswith("multipart/form-data"):
                f, file = parse_multipart(ctype, raw)
                if not file:
                    return self._err(400, "нужен файл с голосом (поле file)")
                v = add_voice(f.get("name", ""), f.get("title", ""), f.get("gender", ""), f.get("text", ""),
                              audio=read_audio(file[0]))
                return self._json(200, {"ok": True, "voice": v})
            body = json.loads(raw or b"{}")
            if u.path == "/v1/voices":
                v = add_voice(body.get("name", ""), body.get("title", ""), body.get("gender", ""), body.get("text", ""),
                              audio=read_audio(base64.b64decode(body["audio_b64"])) if body.get("audio_b64") else None,
                              draft=str(body.get("draft") or ""))
                return self._json(200, {"ok": True, "voice": v})
            if u.path == "/v1/voices/design":
                did, a = design_draft(body.get("instruct", ""), body.get("gender", ""), body.get("text", ""),
                                      body.get("language", ""))
                return self._send(200, wav_bytes(a), "audio/wav", {"X-Draft-Id": did})
            if u.path == "/v1/voices/update":
                return self._json(200, {"ok": True, "voice": update_voice(str(body.get("id", "")), body)})
            if u.path == "/v1/voices/delete":
                delete_voice(str(body.get("id", "")))
                return self._json(200, {"ok": True})
            if u.path == "/v1/voices/config":
                set_config(body)
                return self._json(200, {"ok": True, **voices_public()})
            if u.path == "/v1/voices/unload":
                on_gpu(lambda: ENGINE.unload(str(body.get("role", ""))))
                return self._json(200, {"ok": True, "loaded": STATE["loaded"]})
            return self._err(404, "not found")
        except KeyError as e:
            return self._err(404, f"нет голоса «{e.args[0] if e.args else ''}»")
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("ошибка")
            stat_add(errors=1)
            return self._err(500, f"{type(e).__name__}: {e}", "server_error")

    def _chunk(self, data: bytes):
        if data:
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()

    def _speech(self):
        if not self._key_ok(KEY):
            return self._err(401, "нужен ключ")
        body = json.loads(self._body() or b"{}")
        text = str(body.get("input") or "")
        if not text.strip():
            return self._err(400, "нужен JSON с полем input — текст для озвучки")
        if len(text) > MAX_CHARS:
            return self._err(413, f"текст длиннее {MAX_CHARS} знаков")
        spec = resolve(str(body.get("voice") or ""), str(body.get("persona") or ""), str(body.get("gender") or ""))
        if body.get("instruct") and spec.get("kind") == "speaker":          # манера на один ответ: «радостно», «шёпотом»
            spec = dict(spec, instruct=(spec.get("instruct", "") + " " + str(body["instruct"])).strip())
        speed = min(2.0, max(0.5, float(body.get("speed") or 1.0)))
        fmt = str(body.get("response_format") or "mp3").lower()
        sse = str(body.get("stream_format") or "") == "sse"
        stream = sse or fmt == "pcm" or (bool(body.get("stream")) and fmt == "wav")
        lang = lang_of(text, str(body.get("language") or ""))
        t0 = time.time()
        stat_add(requests=1, chars=len(text))
        STATE["last_request"] = int(t0)
        hdr = {"X-Voice": spec["id"], "X-Chars": str(len(text))}
        gen = synth_iter(text, spec, speed, lang)
        total = 0
        if not stream:
            try:
                parts = list(gen)
            except Exception as e:  # noqa: BLE001
                stat_add(errors=1)
                log.exception("озвучка")
                return self._err(500, f"озвучка не удалась: {e}", "server_error")
            a = np.concatenate(parts) if parts else np.zeros(0, np.float32)
            self._ttfa(t0)
            stat_add(audio_sec=a.size / OUT_SR)
            data, ct = encode(a, fmt)
            return self._send(200, data, ct, dict(hdr, **{"X-Audio-Duration": f"{a.size / OUT_SR:.2f}"}))
        try:                                                 # первая фраза — до заголовков: ошибка модели ещё может стать 500
            first = next(gen, None)
        except Exception as e:  # noqa: BLE001
            stat_add(errors=1)
            log.exception("озвучка")
            return self._err(500, f"озвучка не удалась: {e}", "server_error")
        self._ttfa(t0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if sse else "audio/wav" if fmt == "wav" else "audio/pcm")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Sample-Rate", str(OUT_SR))
        self.send_header("Cache-Control", "no-store")
        for k, v in hdr.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            if fmt == "wav" and not sse:
                self._chunk(wav_head_stream())
            a = first
            while a is not None:
                total += a.size
                b = pcm16(a)
                if sse:
                    ev = {"type": "speech.audio.delta", "audio": base64.b64encode(b).decode()}
                    self._chunk(b"data: " + json.dumps(ev).encode() + b"\n\n")
                else:
                    self._chunk(b)
                a = next(gen, None)
            if sse:
                self._chunk(b'data: {"type": "speech.audio.done"}\n\n')
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log.info("слушатель ушёл на середине — озвучка остановлена")
            self.close_connection = True
        except Exception:  # noqa: BLE001
            stat_add(errors=1)
            log.exception("озвучка оборвалась")
            self.close_connection = True
        finally:
            gen.close()
            stat_add(audio_sec=total / OUT_SR)

    def _ttfa(self, t0):
        ms = int((time.time() - t0) * 1000)
        with STATS:
            STATE["ttfa_ms_last"] = ms
            STATE["ttfa_ms_sum"] += ms
            STATE["ttfa_n"] += 1


def serve(port=PORT):
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    return srv


def main():
    os.makedirs(vdir(), exist_ok=True)
    threading.Thread(target=preload, daemon=True).start()
    log.info("голоса слушают :%d, модели %s, %s", PORT, ", ".join(MODELS.values()), "без модели (TTS_FAKE)" if FAKE else DEVICE_ENV)
    serve().serve_forever()


if __name__ == "__main__":
    main()
