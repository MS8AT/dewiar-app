"""Уши: детектор речи (Silero VAD), маленькая модель Vosk и слово запуска по Vosk-грамматике (WakeSpotter).

Имя ловим по ЧАСТИЧНОМУ результату Vosk — сразу, как прозвучало, не дожидаясь конца фразы. Это быстро, но бывают
ложные срабатывания, поэтому фразу затем целиком распознаёт точная модель (GigaAM или сервер, engine_audio.py).
Грамматика Vosk понимает только слова из своего словаря: имена с незнакомыми словами (missing_words) WakeSpotter
не ловит — их ищут точной моделью или по отпечатку голоса (voiceprint.py). Сборка слуха — build_spotter в engine_audio.py.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

log = logging.getLogger("dewiar.listen")

STOP_WORDS = ["стоп", "хватит", "замолчи", "стой", "тихо", "пауза", "достаточно", "помолчи", "прекрати", "остановись",
              "перестань", "отмена", "замолкни", "тишина"]
# Пока играет радио, одно слово без имени (как у умной колонки): переключить станцию, громче, тише.
# Слова есть в грамматике Vosk; срабатывают по целой фразе (last_final) в engine_audio.py
MEDIA_WORDS = ["дальше", "следующая", "следующую", "громче", "погромче", "тише", "потише"]


class SileroVAD:
    """Silero VAD (onnx) на 16 кГц: prob(кадр) -> вероятность речи 0…1. Модель с состоянием: кадры подавать
    подряд, после разрыва потока — reset(). Один поток ONNX — детектор работает на каждом кадре и не должен
    отнимать ядра у распознавания."""
    CONTEXT = 64                        # хвост прошлого кадра, который модель ожидает перед новым (64 сэмпла для 16 кГц)

    def __init__(self, model_path: Path):
        import onnxruntime as rt
        opts = rt.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.sess = rt.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.ctx = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def prob(self, frame_i16: bytes) -> float:
        x = np.frombuffer(frame_i16, dtype=np.int16).astype(np.float32)[None, :] / 32768.0
        inp = np.concatenate([self.ctx, x], axis=1)
        out, self.state = self.sess.run(None, {"input": inp, "state": self.state, "sr": np.array(16000, dtype=np.int64)})
        self.ctx = x[:, -self.CONTEXT:]
        return float(out[0][0])


VOSK_NAME = "vosk-model-small-ru-0.22"
VOSK_URLS = ["https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"]
if __import__("os").environ.get("DEWIAR_VOSK_URL"):                   # зеркало (например, ваш сервер)
    VOSK_URLS.insert(0, __import__("os").environ["DEWIAR_VOSK_URL"])
VOSK_SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"


def ensure_vosk(data_dir: Path, models_dir: Path, on_status=None, mirror=None) -> Path:
    """Маленькая модель Vosk (45 МБ): уже распакована → zip в data_dir → скачать в models_dir (с проверкой суммы).
    В пакете её нет, чтобы он оставался маленьким; packaging/DEBIAN/postinst скачивает её при установке,
    а если тогда не было сети — докачиваем здесь, при первом запуске. mirror — свой сервер, пробуется первым.
    -> папка модели; RuntimeError, если не скачалась ни с одного адреса."""
    if os.environ.get("DEWIAR_VOSK_OFF") == "1":   # проверки: как будто модель не скачалась (tests/hearing_nonames_test.py)
        raise RuntimeError("модель имён выключена для проверки (DEWIAR_VOSK_OFF)")
    model_dir = models_dir / VOSK_NAME
    if (model_dir / "am").exists():
        return model_dir
    zip_path = data_dir / f"{VOSK_NAME}.zip"
    if not zip_path.exists():
        import hashlib
        import httpx
        zip_path = models_dir / f"{VOSK_NAME}.zip"
        models_dir.mkdir(parents=True, exist_ok=True)
        last = None
        urls = ([mirror] if mirror else []) + [u for u in VOSK_URLS if u != mirror]   # свой сайт — первым
        for url in urls:
            try:
                if on_status:
                    on_status("Скачиваю модель распознавания имён (45 МБ, один раз)…")
                tmp = zip_path.with_suffix(".part")
                h = hashlib.sha256()
                with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(20, read=120)) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                            h.update(chunk)
                if h.hexdigest() != VOSK_SHA256:
                    raise ValueError("файл повреждён (контрольная сумма не совпала)")
                tmp.replace(zip_path)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("Модель Vosk не скачалась с %s: %s", url, e)
        else:
            raise RuntimeError(f"не удалось скачать модель Vosk: {last}")
    return unpack_vosk(zip_path, models_dir)


def unpack_vosk(zip_path: Path, target_dir: Path) -> Path:
    name = zip_path.name[:-4]
    model_dir = target_dir / name
    if not model_dir.exists():
        import zipfile
        target_dir.mkdir(parents=True, exist_ok=True)
        log.info("Распаковываю %s ...", zip_path.name)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(target_dir)
    return model_dir


def missing_words(model_dir: Path, words):
    """Каких слов нет в словаре Vosk (их нельзя сделать словом запуска).
    Vosk сообщает об этом только в лог, поэтому проверяем в отдельном процессе."""
    code = ("import vosk,json,sys;vosk.SetLogLevel(0);m=vosk.Model(sys.argv[1]);"
            "vosk.KaldiRecognizer(m,16000,json.dumps(json.loads(sys.argv[2])+['[unk]'],ensure_ascii=False))")
    flat = sorted({w for phrase in words for w in phrase.split()})
    r = subprocess.run([sys.executable, "-c", code, str(model_dir), json.dumps(flat, ensure_ascii=False)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                       stdin=subprocess.DEVNULL,                 # Kaldi пишет в UTF-8; в Windows иначе cp1251
                       creationflags=0x08000000 if os.name == "nt" else 0)
    miss = []
    for line in (r.stderr or "").splitlines():
        if "missing in vocabulary" in line:
            miss.append(line.rsplit("'", 2)[-2])
    return miss


class NoSpotter:
    """Слух без модели имён: Vosk ещё не скачалась (медленный интернет при первом запуске) или не скачивается вовсе
    (сайт модели закрыт). Имя и «стоп» голосом не ловим, но микрофон работает: кнопка, удержание и распознавание
    выбранным движком (CI 19.10: без модели не работала даже кнопка — «Удержание слишком короткое (0.0 с)»).
    Тот же интерфейс, что у WakeSpotter: rec.Reset(), feed(), feed_stop_only(), last_final."""

    class _Rec:
        def Reset(self):
            pass

    def __init__(self):
        self.rec = self._Rec()
        self.last_final = None

    def feed(self, frame):
        return ()

    def feed_stop_only(self, frame):
        return None


class NoSTT:
    """Распознаватель-заглушка, пока нет ни выбранного, ни запасного (Vosk): честная ошибка вместо падения."""
    name = "распознавание ещё готовится"
    ready = False

    def transcribe(self, pcm):
        raise RuntimeError("распознавание речи ещё готовится — модель скачивается")


class WakeSpotter:
    """Слушает поток (16 кГц, int16) и сообщает: feed() -> [('wake', фраза) | ('stop', слово)].
    Каждое событие — не больше одного раза за фразу Vosk. decoys (data/decoys.txt) — похожие по звучанию слова:
    без них грамматика из одних имён натягивала бы на имя любую речь, а с ними созвучное уходит в «приманку»."""

    def __init__(self, model, wake_phrases, decoys):
        from vosk import KaldiRecognizer
        self.wake_phrases = sorted({p.lower() for p in wake_phrases}, key=len, reverse=True)
        words = set()
        for p in self.wake_phrases + STOP_WORDS + MEDIA_WORDS:
            words.update(p.split())
        grammar = sorted(words) + [d for d in decoys if d not in words] + ["[unk]"]
        self.rec = KaldiRecognizer(model, 16000, json.dumps(grammar, ensure_ascii=False))
        self.fired_wake = False
        self.fired_stop = False

    def _scan(self, text):
        events = []
        if not text:
            return events
        tokens = text.split()
        joined = " " + text + " "
        if not self.fired_wake:
            for p in self.wake_phrases:
                if f" {p} " in joined:
                    self.fired_wake = True
                    events.append(("wake", p))
                    break
        if not self.fired_stop:
            for w in STOP_WORDS:
                if w in tokens:
                    self.fired_stop = True
                    events.append(("stop", w))
                    break
        return events

    def feed_stop_only(self, frame: bytes):
        """Полудуплекс (нет эхоподавления): пока ассистент говорит, ловим только слово-стоп, появившееся заново.
        -> слово или None. Эхо своего голоса Vosk раскладывает на «приманки» (decoys), а не на стоп-слова."""
        if self.rec.AcceptWaveform(frame):
            text = json.loads(self.rec.Result()).get("text", "")
            prev, self._half_prev = getattr(self, "_half_prev", ""), ""
        else:
            text = json.loads(self.rec.PartialResult()).get("partial", "")
            prev, self._half_prev = getattr(self, "_half_prev", ""), text
        new = text.split()[len(prev.split()):] if text.startswith(prev) else text.split()
        return next((w for w in STOP_WORDS if w in new), None)

    def feed(self, frame: bytes):
        if self.rec.AcceptWaveform(frame):
            text = json.loads(self.rec.Result()).get("text", "")
            self.last_final = text                            # вся фраза целиком: команды одним словом («пауза», «громче»)
            if text:
                log.debug("Vosk (имена): «%s»", text)
            ev = self._scan(text)
            self.fired_wake = self.fired_stop = False       # новая фраза Vosk — можно снова
            return ev
        return self._scan(json.loads(self.rec.PartialResult()).get("partial", ""))
