"""Голоса Vosk TTS — в отдельном процессе (tts.VoskProc + core/tts_worker.py).
Было: загрузка модели (onnxruntime, словарь ударений) и синтез держали GIL, и после каждого запуска ядро больше минуты
не отвечало — студия пустая, виджет «загружаю слух и голос». Подменная библиотека vosk_tts грузится 3 с, держа GIL
(чистый цикл Python), и синтезирует так же. Проверяем:
- пока голоса грузятся, поток ядра тикает без задержек (раньше — замирал на всё время загрузки);
- синтез работает (речь — PCM int16), дикторы, скорость доходят до библиотеки;
- словарь ударений после первого разбора берётся из кэша (второй запуск его не читает);
- процесс голосов упал — следующая фраза поднимает его сама; ошибка синтеза — исключение, а не зависание."""
import json, os, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
tmp = Path(tempfile.mkdtemp())
FAILS = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        FAILS.append(m)


fake = tmp / "fake" / "vosk_tts"
fake.mkdir(parents=True)
(fake / "__init__.py").write_text("from .model import Model\nfrom .synth import Synth\n")
(fake / "model.py").write_text('''
import json, os, time
class Model:
    def __init__(self, model_path=None, **kw):
        end = time.time() + float(os.environ.get("FAKE_LOAD", "3"))
        x = 0
        while time.time() < end:          # как onnxruntime: держим GIL
            x += 1
        self.dic, n = {}, 0
        for line in open(model_path + "/dictionary", encoding="utf-8"):
            k, p, v = line.split(maxsplit=2); self.dic[k] = v; n += 1
        with open(model_path + "/reads.log", "a") as f:
            f.write(f"{n}\\n")
''')
(fake / "synth.py").write_text('''
import numpy as np
class Synth:
    def __init__(self, model): self.m = model
    def synth_audio(self, text, speaker_id=0, speech_rate=1.0):
        if text == "сломайся": raise ValueError("плохой текст")
        if text == "умри": import os; os._exit(3)
        n = int(2205 * (1 + speaker_id)) + len(self.m.dic)
        return (np.sin(np.arange(n) / 5) * 8000 * float(speech_rate or 1)).astype(np.int16)
''')
model = tmp / "vosk-model-tts-ru-0.9-multi"
model.mkdir()
(model / "model.onnx").write_bytes(b"x")
(model / "dictionary").write_text("".join(f"слово{i} 1.0 s l o v o\n" for i in range(5000)), encoding="utf-8")
os.environ["PYTHONPATH"] = str(tmp / "fake") + os.pathsep + os.environ.get("PYTHONPATH", "")
sys.path.insert(0, str(ROOT / "core"))
import tts  # noqa: E402

gaps, stop = [], threading.Event()


def ticker():
    last = time.monotonic()
    while not stop.is_set():
        time.sleep(0.05)
        now = time.monotonic(); gaps.append(now - last); last = now


th = threading.Thread(target=ticker, daemon=True); th.start()
v = tts.VoskTTS(tmp)
t0 = time.monotonic()
v._load(model)
load = time.monotonic() - t0
stop.set(); th.join()
ok(v.ready and load >= 2.5, f"модель загружена (в отдельном процессе за {load:.1f} с)")
ok(max(gaps) < 0.5, f"пока голоса грузились, ядро не замирало (самая долгая пауза {max(gaps):.2f} с)")
ok(len(v.speakers) == 12 and all("gender" in s for s in v.speakers), f"дикторы определены: {len(v.speakers)}")
rate, pcm = next(v.synth("Привет, мир", {"vosk": 1}, speed=1.0))
ok(rate == 22050 and len(pcm) == 2 * (2205 * 2 + 5000), f"синтез через процесс: {len(pcm)} байт")
ok((model / "dewiar-dic.pickle").exists(), "словарь ударений сохранён в кэш")
reads1 = (model / "reads.log").read_text().split()
v.synth_.close()
v2 = tts.VoskTTS(tmp)
(model / "dewiar-speakers.json").unlink()
v2._load(model)
reads2 = (model / "reads.log").read_text().split()
rate, pcm = next(v2.synth("Ещё раз", {"vosk": 0}))
ok(reads2[-1] == "0" and reads1[-1] == "5000" and len(pcm) == 2 * (2205 + 5000),
   f"второй запуск — словарь из кэша, не разбирается заново (строк прочитано: {reads1[-1]} → {reads2[-1]}), слова на месте")
try:
    v2.synth_.synth_audio("сломайся"); ok(False, "ошибка синтеза — исключение")
except RuntimeError as e:
    ok("плохой текст" in str(e), f"ошибка синтеза — исключение с причиной: {e}")
pid = v2.synth_.p.pid
try:
    v2.synth_.synth_audio("умри")
except RuntimeError:
    pass
a = v2.synth_.synth_audio("снова", speaker_id=0)
ok(len(a) == 2205 + 5000 and v2.synth_.p.pid != pid, "процесс голосов упал — следующая фраза подняла его заново")
v2.synth_.close()
print("ALL OK" if not FAILS else f"ошибок: {len(FAILS)}")
sys.exit(1 if FAILS else 0)
