"""Синтез речи. У каждого движка synth(text, voice_cfg, speed) — генератор (частота, кусок PCM s16le mono).

VoskTTS — локально, на CPU, русские голоса с ударениями; одна модель (~0,2 ГБ) на несколько дикторов.
PiperTTS — локально, быстро; каждый голос качается отдельно (~60 МБ).
RemoteTTS — любой OpenAI-совместимый /audio/speech: Qwen3-TTS в vLLM-Omni (клонирование голоса, потоковый PCM), OpenAI…
EspeakTTS — аварийный, без скачивания (робот); в Windows вместо него — голоса системы (SapiTTS).
voice_cfg — голос персонажа (piper, vosk, remote, length_scale) и служебные _gender, _slot, _pid из _voice_cfg.
Цепочка движков, _voice_cfg и обработка голоса — engine_remote.py (_engines_for_speech, _speak_worker); эффекты — voicefx.py.
"""

import base64
import os
import json
import logging
import re
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import numpy as np

from settings import VOICES_DIR

log = logging.getLogger("dewiar.tts")

PIPER_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/{name}/{quality}/"
             "ru_RU-{name}-{quality}{ext}?download=true")


def _download(url, path, on_progress=None):
    from updater import download                     # докачка при обрыве, одно скачивание на файл, повтор переименования
    download(url, path, None, on_progress)


class PiperTTS:
    name = "Piper"

    def __init__(self):
        self.voices = {}
        self.mirror = None              # {"url": ".../models/piper/", "files": {имя: sha256}} — свой сайт
        self._lock = threading.Lock()

    def paths(self, voice_id):
        return VOICES_DIR / f"{voice_id}.onnx", VOICES_DIR / f"{voice_id}.onnx.json"

    def has(self, voice_id):
        m, c = self.paths(voice_id)
        return m.exists() and c.exists()

    def ensure(self, voice_id, on_progress=None):
        """Скачать голос «ru_RU-<имя>-<качество>», если его нет: со своего сайта (с проверкой sha256),
        иначе с Hugging Face. Конфиг — первым: голос считается скачанным, только когда есть оба файла."""
        if self.has(voice_id):
            return True
        _, name, quality = voice_id.split("-", 2)
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        m, c = self.paths(voice_id)
        log.info("Скачиваю голос %s ...", voice_id)
        files = (self.mirror or {}).get("files") or {}
        if self.mirror and m.name in files:
            from updater import download
            base = self.mirror["url"].rstrip("/") + "/"
            try:
                download(base + c.name, c, files.get(c.name))
                download(base + m.name, m, files.get(m.name), on_progress)
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("Голос %s со своего сайта не скачался (%s) — беру с Hugging Face", voice_id, e)
        _download(PIPER_URL.format(name=name, quality=quality, ext=".onnx.json"), c)
        _download(PIPER_URL.format(name=name, quality=quality, ext=".onnx"), m, on_progress)
        return True

    def _voice(self, voice_id):
        with self._lock:
            if voice_id not in self.voices:
                from piper import PiperVoice
                m, c = self.paths(voice_id)
                self.voices[voice_id] = PiperVoice.load(str(m), config_path=str(c))
            return self.voices[voice_id]

    def synth(self, text, voice_cfg, speed=1.0):
        from piper import SynthesisConfig
        v = self._voice(voice_cfg.get("piper", "ru_RU-denis-medium"))
        cfg = SynthesisConfig(length_scale=float(voice_cfg.get("length_scale", 1.0)) / max(0.5, speed))
        from speechnorm import speech_norm
        text = speech_norm(text, latin=False) or text          # 1437,50 руб. → «тысяча … рублей пятьдесят копеек»
        for chunk in v.synthesize(text, syn_config=cfg):
            yield chunk.sample_rate, chunk.audio_int16_bytes


VOSK_TTS_LIST = "https://alphacephei.com/vosk/models/model-list.json"
VOSK_TTS_DEFAULT = "vosk-model-tts-ru-0.9-multi"
VOSK_TTS_URL = "https://alphacephei.com/vosk/models/{name}.zip"


def estimate_f0(audio, rate):
    """Средняя высота голоса (Гц, 60…400) по автокорреляции звонких кусков — чтобы понять, мужской голос или женский.
    -> 0.0, если звонких кусков нет."""
    x = audio.astype(np.float32) / 32768.0
    win, hop = int(0.04 * rate), int(0.02 * rate)
    lo, hi = int(rate / 400), int(rate / 60)
    f0s = []
    energy_thr = 0.25 * float(np.sqrt(np.mean(x * x)) or 1e-4)
    for i in range(0, len(x) - win, hop):
        fr = x[i:i + win] - x[i:i + win].mean()
        if np.sqrt(np.mean(fr * fr)) < energy_thr:
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.35:
            f0s.append(rate / k)
    return float(np.median(f0s)) if f0s else 0.0


LAT = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к",
       "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
       "w": "в", "x": "кс", "y": "й", "z": "з"}


def cyr_only(text):
    """Грубая замена для повторной попытки, когда Vosk TTS не справился с текстом после speech_norm:
    латиница — русскими буквами по одной, лишние символы — прочь."""
    t = "".join(LAT.get(ch.lower(), ch) if "a" <= ch.lower() <= "z" else ch for ch in text)
    t = re.sub(r"[^А-Яа-яЁё0-9 ,.!?:;—-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class VoskProc:
    """Синтез Vosk TTS в отдельном процессе (core/tts_worker.py) — тот же вызов synth_audio, что у vosk_tts.Synth.
    Загрузка модели и синтез держат GIL десятками секунд: в процессе ядра они замораживали ответы студии и виджета.
    Конструктор ждёт, пока модель загрузится (вызывать в фоне). Процесс упал — следующий вызов поднимет его снова."""

    def __init__(self, path, timeout=600):
        self.path, self.timeout, self.p = str(path), timeout, None
        self._lock = threading.Lock()
        with self._lock:
            self._start()

    def _start(self):
        import sys
        # CREATE_NO_WINDOW: без чёрного окна; Linux/macOS — голоса уступают процессор другим программам (nice +5):
        # загрузка и синтез тяжёлые, а курсор и окна у человека не должны дёргаться
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {"preexec_fn": lambda: os.nice(5)}
        try:
            import ortcfg                               # не одновременно с загрузкой слуха (GigaAM): по очереди
            heavy = ortcfg.HEAVY
        except Exception:  # noqa: BLE001
            import contextlib
            heavy = contextlib.nullcontext()
        with heavy:
            self.p = subprocess.Popen([sys.executable, str(Path(__file__).with_name("tts_worker.py")), self.path],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw)
            r = self._read_json()
        if not r.get("ok"):
            self.close()
            raise RuntimeError(r.get("error") or "процесс голосов не запустился")

    def _read(self):
        h = self.p.stdout.read(4)
        if len(h) < 4:
            raise RuntimeError("процесс голосов Vosk TTS завершился")
        n = int.from_bytes(h, "big")
        b = self.p.stdout.read(n)
        if len(b) < n:
            raise RuntimeError("процесс голосов Vosk TTS оборвал ответ")
        return b

    def _read_json(self):
        return json.loads(self._read())

    def synth_audio(self, text, speaker_id=0, speech_rate=None):
        q = json.dumps({"text": text, "speaker_id": speaker_id, "speech_rate": speech_rate}, ensure_ascii=False).encode()
        with self._lock:
            for attempt in (0, 1):
                if self.p is None or self.p.poll() is not None:
                    if self.p is not None:
                        log.info("Процесс голосов Vosk TTS перезапускаю")
                    self.close()
                    self._start()
                try:
                    self.p.stdin.write(len(q).to_bytes(4, "big") + q)
                    self.p.stdin.flush()
                except OSError:                        # процесс умер, а poll() ещё не заметил — поднимаем и повторяем раз
                    self.close()
                    if attempt:
                        raise RuntimeError("процесс голосов Vosk TTS не отвечает")
                    continue
                try:
                    r = self._read_json()
                    if not r.get("ok"):
                        raise ValueError(r.get("error") or "синтез не удался")
                    return np.frombuffer(self._read(), dtype=np.int16)
                except ValueError as e:                # ошибка синтеза этой фразы — процесс жив, отвечаем исключением
                    raise RuntimeError(str(e)) from e
                except (OSError, RuntimeError) as e:   # процесс упал посреди фразы — следующая поднимет его заново
                    self.close()
                    raise RuntimeError(f"процесс голосов Vosk TTS: {e}") from e

    def close(self):
        p, self.p = self.p, None
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass


class VoskTTS:
    """Vosk TTS (Alpha Cephei, Apache 2.0): русские нейросетевые голоса с правильными ударениями, на CPU.
    Модель одна на несколько дикторов (~0,2 ГБ, скачивается один раз). Мужской/женский голос определяем
    сами — по высоте голоса на пробной фразе, и раздаём персонажам по полу."""
    name = "Vosk TTS"

    def __init__(self, models_dir):
        self.dir = models_dir
        self.synth_ = None
        self.speakers = []                  # [{"id", "gender", "f0"}]
        self.error = None
        self._lock = threading.Lock()
        self.path = None
        self.mirror = ""                    # свой адрес архива модели (например, на dewiar.pro) — пробуем первым
        self.mirror_sha = ""                # sha256 архива на своём сайте (из latest.json)

    @property
    def ready(self):
        return self.synth_ is not None

    def installed(self):
        """-> папка самой свежей скачанной модели (по номерам в имени) или None."""
        cands = [p for p in self.dir.glob("vosk-model-tts-ru*") if (p / "model.onnx").exists()] if self.dir.exists() else []
        return sorted(cands, key=lambda p: [int(n) for n in re.findall(r"\d+", p.name)])[-1] if cands else None

    def _choose(self):
        """Самая свежая русская модель из списка на сайте; нет связи — известная нам."""
        try:
            import httpx
            items = httpx.get(VOSK_TTS_LIST, timeout=10).json()
            ru = [m for m in items if "tts-ru" in m.get("name", "") and str(m.get("obsolete", "false")) != "true"]
            if ru:
                ru.sort(key=lambda m: [int(n) for n in re.findall(r"\d+", m["name"])])
                m = ru[-1]
                return m["name"], m.get("url") or VOSK_TTS_URL.format(name=m["name"]), m.get("md5")
        except Exception as e:  # noqa: BLE001
            log.info("Список моделей Vosk TTS недоступен (%s) — беру %s", e, VOSK_TTS_DEFAULT)
        return VOSK_TTS_DEFAULT, VOSK_TTS_URL.format(name=VOSK_TTS_DEFAULT), None

    def ensure(self, on_progress=None, on_status=None):
        """Скачать (если нет) и загрузить модель. Долго — вызывать в фоне. Источники по очереди: свой сайт
        (mirror — адрес .zip или папки с ним; проверка sha256), затем каталог alphacephei (md5 из каталога).
        RuntimeError — не скачалась ни откуда."""
        with self._lock:
            if self.ready:
                return True
            path = self.installed()
            if path is None:
                sources = []
                if self.mirror:
                    m = self.mirror.rstrip("/")
                    nm = m.rsplit("/", 1)[-1].removesuffix(".zip") if m.endswith(".zip") else VOSK_TTS_DEFAULT
                    sources.append((nm, m if m.endswith(".zip") else f"{m}/{VOSK_TTS_DEFAULT}.zip", "sha256:" + self.mirror_sha if self.mirror_sha else None))
                sources.append(self._choose())
                self.dir.mkdir(parents=True, exist_ok=True)
                last = None
                for name, url, md5 in sources:
                    z = self.dir / f"{name}.zip"
                    try:
                        if on_status:
                            on_status("Скачиваю новые русские голоса (Vosk TTS, один раз)…")
                        log.info("Скачиваю %s", url)
                        if md5 and md5.startswith("sha256:"):             # свой сайт — строгая проверка
                            from updater import download
                            download(url, z, md5[7:], on_progress)
                            md5 = None
                        else:
                            _download(url, z, on_progress)
                        with zipfile.ZipFile(z) as zz:
                            bad = zz.testzip()
                            if bad:
                                raise RuntimeError(f"архив повреждён ({bad})")
                            if md5:
                                import hashlib
                                h = hashlib.md5()
                                with open(z, "rb") as f:
                                    for b in iter(lambda: f.read(1 << 20), b""):
                                        h.update(b)
                                if h.hexdigest() != md5:   # каталог бывает не в ладу с архивом; целость уже проверил testzip
                                    log.warning("md5 архива %s не совпал с каталогом — архив цел, продолжаю", name)
                            zz.extractall(self.dir)
                        z.unlink()
                        break
                    except Exception as e:  # noqa: BLE001
                        last = e
                        log.warning("Голоса из %s не скачались: %s", url, e)
                        z.unlink(missing_ok=True)
                path = self.installed()
                if path is None:
                    raise RuntimeError(f"модель голосов не скачалась: {last}")
            self._load(path)
            return True

    def _load(self, path, synth=None):
        """Загрузить модель; synth — готовая заглушка (тесты). Пол дикторов определяется один раз и хранится
        в dewiar-speakers.json рядом с моделью: прослушивание всех дикторов занимает секунды."""
        if synth is None:
            if os.environ.get("DEWIAR_TTS_INPROC"):                       # по-старому, в процессе ядра (отладка)
                from vosk_tts import Model, Synth
                synth = Synth(Model(model_path=str(path)))
            else:
                import time as _t
                t0 = _t.monotonic()
                synth = VoskProc(path)
                log.info("Vosk TTS загружен в отдельном процессе за %.1f с", _t.monotonic() - t0)
        self.synth_, self.path = synth, path
        cache = path / "dewiar-speakers.json" if path else None
        if cache and cache.exists():
            try:
                self.speakers = json.loads(cache.read_text())
                return
            except ValueError:
                pass
        self.speakers = self.probe()
        if cache:
            cache.write_text(json.dumps(self.speakers))
        log.info("Vosk TTS: дикторы %s", self.speakers)

    def probe(self, limit=12):
        """Озвучить пробную фразу каждым диктором и определить пол по высоте (ниже 165 Гц — мужской).
        Число дикторов модель не сообщает — перебираем, пока синтез не откажет."""
        out = []
        for sid in range(limit):
            try:
                a = self.synth_.synth_audio("Здравствуйте! Чем могу помочь?", speaker_id=sid)
            except Exception:  # noqa: BLE001 — дикторов меньше
                break
            a = np.asarray(a)
            if a.size < 2000:
                break
            f0 = estimate_f0(a, 22050)
            out.append({"id": sid, "gender": "male" if 0 < f0 < 165 else "female", "f0": round(f0, 1)})
        return out

    def pick(self, voice_cfg):
        """Диктор для персонажа: заданный вручную или по полу (разным персонажам — разные)."""
        sid = voice_cfg.get("vosk")
        ids = [s["id"] for s in self.speakers]
        if isinstance(sid, int) and sid in ids:
            return sid
        g = "male" if voice_cfg.get("_gender") == "male" else "female"
        sp = [s for s in self.speakers if s["gender"] == g]
        if g == "female":                               # героиням — по высоте голоса: первой (Лире) самый звонкий и молодой
            sp = sorted(sp, key=lambda s: -float(s.get("f0") or 0))
        same = [s["id"] for s in sp] or ids or [0]
        n = voice_cfg.get("_slot")
        if not isinstance(n, int):
            n = sum(ord(c) for c in str(voice_cfg.get("_pid", "")))
        return same[n % len(same)]

    def synth(self, text, voice_cfg, speed=1.0):
        """Фраза целиком одним куском, 22 050 Гц. Последние ~40 фраз — в памяти (образцы голосов, частые ответы)."""
        if not self.ready:
            raise RuntimeError("голоса Vosk TTS ещё не готовы")
        rate = float(speed) / max(0.5, float(voice_cfg.get("length_scale", 1.0)))
        spk = self.pick(voice_cfg)
        key = (text, spk, round(rate, 3))
        cache = self.__dict__.setdefault("_cache", {})         # образцы и частые фразы — мгновенно со второго раза
        if key not in cache:
            with self.__dict__.setdefault("_synth_lock", threading.Lock()):   # ответ, напоминание и «послушать» — по очереди
                from speechnorm import speech_norm
                said = speech_norm(text) or text              # числа словами, латиница русскими буквами
                try:
                    audio = self.synth_.synth_audio(said, speaker_id=spk, speech_rate=rate)
                except Exception:  # noqa: BLE001 — редкие символы и слова: упрощаем и пробуем ещё раз тем же голосом
                    simple = cyr_only(said)
                    simple = re.sub(r"\d+", " ", simple).strip()
                    if not simple or simple == said:
                        raise
                    audio = self.synth_.synth_audio(simple, speaker_id=spk, speech_rate=rate)
            if len(cache) > 40:
                cache.pop(next(iter(cache)))
            cache[key] = np.asarray(audio, dtype=np.int16).tobytes()
        yield 22050, cache[key]


class EspeakTTS:
    """espeak-ng: аварийный голос, если другие не скачаны. WAV из stdout — разбираем заголовок сами."""
    name = "eSpeak (аварийный)"

    @staticmethod
    def available():
        return bool(shutil.which("espeak-ng"))

    def synth(self, text, voice_cfg, speed=1.0):
        female = voice_cfg.get("_gender") == "female"
        from speechnorm import speech_norm
        text = speech_norm(text, latin=False) or text
        r = subprocess.run(["espeak-ng", "-v", "ru+f3" if female else "ru", "-s", str(int(165 * speed)),
                            "--stdout", text], capture_output=True, timeout=30)
        data = r.stdout
        idx = data.find(b"data")
        rate = int.from_bytes(data[24:28], "little") if data[:4] == b"RIFF" else 22050
        yield rate, data[idx + 8:] if idx >= 0 else data


class SapiTTS:
    """Windows: встроенные голоса системы (SAPI 5 и голоса OneCore — «Ирина», «Павел» в русской Windows).
    Аварийный вариант, как eSpeak в Linux: без скачивания. Берём только русские голоса (язык 0x419)."""
    name = "Голос Windows"
    ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"
    _ok = None

    def _voices(self, sp):
        """[(описание, токен)] русских голосов: сначала OneCore (звучат лучше), потом классические SAPI."""
        import comtypes.client
        out = []
        try:
            cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
            cat.SetId(self.ONECORE, False)
            toks = cat.EnumerateTokens()
            out += [toks.Item(i) for i in range(toks.Count)]
        except Exception:  # noqa: BLE001 — старая Windows без OneCore
            pass
        toks = sp.GetVoices()
        out += [toks.Item(i) for i in range(toks.Count)]
        ru = []
        for tk in out:
            try:
                langs = str(tk.GetAttribute("Language") or "").lower().split(";")
                if "419" in langs:
                    ru.append((tk.GetDescription(0), tk, str(tk.GetAttribute("Gender") or "")))
            except Exception:  # noqa: BLE001
                continue
        return ru

    def available(self):
        import os
        if os.name != "nt":
            return False
        if SapiTTS._ok is None:
            try:
                import comtypes
                import comtypes.client
                comtypes.CoInitialize()
                SapiTTS._ok = bool(self._voices(comtypes.client.CreateObject("SAPI.SpVoice")))
                if not SapiTTS._ok:
                    log.warning("В Windows нет русского голоса: «Параметры» → «Время и язык» → «Речь» → «Добавить голоса»")
            except Exception as e:  # noqa: BLE001
                log.info("Голоса Windows недоступны: %s", e)
                SapiTTS._ok = False
        return SapiTTS._ok

    def synth(self, text, voice_cfg, speed=1.0):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()                         # у каждого потока свой COM
        sp = comtypes.client.CreateObject("SAPI.SpVoice")
        voices = self._voices(sp)
        if not voices:
            raise RuntimeError("в Windows нет русского голоса")
        want = "female" if voice_cfg.get("_gender") == "female" else "male"
        pick = next((v for v in voices if v[2].lower() == want), voices[0])
        sp.Voice = pick[1]
        sp.Rate = max(-10, min(10, round((float(speed) - 1.0) * 10)))
        fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = 22                                   # SAFT22kHz16BitMono
        ms = comtypes.client.CreateObject("SAPI.SpMemoryStream")
        ms.Format = fmt
        sp.AudioOutputStream = ms
        from speechnorm import speech_norm
        sp.Speak(speech_norm(text, latin=False) or text, 0)
        data = bytes(bytearray(ms.GetData()))
        yield 22050, data


class RemoteTTS:
    """OpenAI-совместимый /audio/speech (base_url — с /v1) с потоковым PCM. Понимает три формы ответа: сырой PCM
    (частота — из настройки sample_rate, по умолчанию 24 кГц, как у OpenAI), WAV (частота из заголовка) и SSE
    с base64-кусками (vLLM-Omni и шлюзы). cfg["extra"] дописывается в тело запроса как есть (параметры сервера)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = f"Удалённый ({cfg.get('base_url', '')})"

    def synth(self, text, voice_cfg, speed=1.0):
        import httpx
        c = self.cfg
        rate = int(c.get("sample_rate") or 24000)
        own = c.get("voice_f") if voice_cfg.get("_gender") == "female" else c.get("voice_m")   # голос героинь / героев с сервера
        body = {"model": c.get("model") or "tts-1", "input": text, "voice": own or voice_cfg.get("remote") or "alloy",
                "response_format": "pcm", "stream": True, "speed": speed}
        body.update(c.get("extra") or {})
        headers = {"Content-Type": "application/json"}
        if c.get("api_key"):
            headers["Authorization"] = f"Bearer {c['api_key']}"
        with httpx.stream("POST", c["base_url"].rstrip("/") + "/audio/speech", json=body, headers=headers,
                          timeout=httpx.Timeout(30, read=60)) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"TTS-сервер ответил {r.status_code}: {r.text[:200]}")
            ctype = r.headers.get("content-type", "")
            if "event-stream" in ctype:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload in ("", "[DONE]"):
                        continue
                    try:
                        obj = json.loads(payload)
                        b64 = obj.get("audio") or obj.get("delta") or obj.get("data") or ""
                    except ValueError:
                        b64 = payload
                    if b64:
                        yield rate, base64.b64decode(b64)
                return
            head, carry = b"", b""
            for chunk in r.iter_bytes(4096):
                if head is not None:
                    head += chunk
                    if len(head) < 44:
                        continue
                    if head[:4] == b"RIFF":
                        rate = int.from_bytes(head[24:28], "little")
                        i = head.find(b"data")
                        chunk = head[i + 8:] if i >= 0 else head[44:]
                    else:
                        chunk = head
                    head = None
                chunk = carry + chunk
                if len(chunk) % 2:                     # куски сети режут сэмпл пополам — нечётный байт ждёт следующего
                    carry, chunk = chunk[-1:], chunk[:-1]
                else:
                    carry = b""
                if chunk:
                    yield rate, chunk
            if head:
                yield rate, head[:len(head) // 2 * 2]


class ElevenTTS(RemoteTTS):
    """ElevenLabs своим ключом: потоковый PCM 24 кГц (/v1/text-to-speech/{голос}/stream, заголовок xi-api-key). Голос — героини
    или героя (cfg voice_f / voice_m, по умолчанию Sarah и George из стандартных голосов ElevenLabs). Платит человек сам по
    своему тарифу; не отвечает — цепочка переходит на Piper (engine_remote._engines_for_speech)."""
    VOICES = {"female": "EXAVITQu4vr4xnSDxMaL", "male": "JBFqnCBsd6RMkjVDRZzb"}
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.name = "ElevenLabs"

    def synth(self, text, voice_cfg, speed=1.0):
        import httpx
        from urllib.parse import quote
        c = self.cfg
        fem = voice_cfg.get("_gender") == "female"
        vid = (c.get("voice_f") if fem else c.get("voice_m")) or self.VOICES["female" if fem else "male"]
        body = {"text": text, "model_id": c.get("model") or "eleven_flash_v2_5",
                "voice_settings": {"speed": max(0.7, min(1.2, float(speed or 1.0)))}}
        with httpx.stream("POST", self.URL.format(vid=quote(vid, safe="")), params={"output_format": "pcm_24000"}, json=body,
                          headers={"xi-api-key": c.get("api_key", ""), "Content-Type": "application/json"},
                          timeout=httpx.Timeout(30, read=60)) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"ElevenLabs ответил {r.status_code}: {r.text[:200]}")
            carry = b""
            for chunk in r.iter_bytes(4096):
                chunk = carry + chunk
                if len(chunk) % 2:                     # сэмпл разрезан сетью пополам — нечётный байт ждёт следующего
                    carry, chunk = chunk[-1:], chunk[:-1]
                else:
                    carry = b""
                if chunk:
                    yield 24000, chunk
