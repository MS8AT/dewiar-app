"""Слушание после имени. Ловит случаи из журнала разговора:
  «🎤 Имя «эва» услышано → 📝 Игрова. → Ложное срабатывание» (ассистент гаснет), «📝 Элла. → ❓ Элла.» (модель ищет «Элла»),
  «Фраза 22.4 с» под музыку (команда тонет), «Играй. → Играю.» (модель отвечает словами — тишина),
  радио на 5% после «тише» (кажется, что не играет).
Проверяем сами решения: короткая фраза с услышанным именем — это имя; фраза под музыкой начинается с имени;
радио молчит, пока слушаем; «играй» без плеера — последняя станция; тихое радио — так и говорим."""
import collections, os, queue, sys, threading, time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
ok = lambda c, m: print(("✅ " if c else "❌ ") + m)
import engine as E  # noqa: E402
from radio import Radio  # noqa: E402

ALIASES = {"eva": ["эва"], "lira": ["лира"], "patrik": ["патрик"]}


def stub():
    e = E.Engine.__new__(E.Engine)
    e.calls = []
    e._said, e.state, e._spoke_until = collections.deque(maxlen=40), "listening", 0.0
    e.pending_confirm, e.task_answer_until = None, 0.0
    e.tasks = SimpleNamespace(waiting=lambda: None)
    e.aliases = ALIASES
    e.personas = SimpleNamespace(wake_map=lambda only=None: {"эва": "eva", "лира": "lira", "патрик": "patrik"})
    e.s = SimpleNamespace(get=lambda *k, default=None: {"persona": "eva"}.get(k[0], default) if len(k) == 1 else default)
    e.follow_up_until = 0.0
    e._wake_phrase = ""
    e.switch_persona = lambda pid: e.calls.append(("persona", pid))
    e.listen_for_command = lambda seconds=8: e.calls.append(("listen",))
    e.ask = lambda t, **k: e.calls.append(("ask", t))
    e.go_sleep = lambda *a, **k: e.calls.append(("sleep",))
    e.set_state = lambda st: e.calls.append(("state", st))
    e.emit = lambda *a, **k: None
    return e


def run(text, by_wake, follow=False, dur=1.0, phrase="эва"):
    e = stub(); e._wake_phrase = phrase
    if follow:
        e.follow_up_until = time.monotonic() + 5
    E.Engine.handle_text(e, text, by_wake, follow, None, dur=dur)
    return e.calls


ok(run("Игрова.", True, dur=0.9) == [("listen",)], "«Эва» услышана, распознано «Игрова.» — слушаю вопрос, а не гасну")
ok(run("", True, dur=1.0) == [("listen",)], "распознавание вернуло пусто — тоже слушаю")
ok(run("Элла.", True, follow=True, dur=1.0) == [("listen",)], "«Элла.» во время ожидания — не вопрос модели, а имя")
ok(run("Ира.", True, dur=0.8, phrase="лира") == [("persona", "lira"), ("listen",)], "«Лира» → «Ира.»: переключаюсь на Лиру и слушаю")
r = run("Так что вот, в принципе, всё, что будем делать. Позвонили, всё, потом дальше", True, dur=9.2, phrase="агент")
ok(("listen",) not in r and ("state", "idle") in r, "длинный чужой разговор с «именем» — по-прежнему ложное срабатывание")
ok(run("Лира, включи радио", True, dur=1.8, phrase="лира") == [("persona", "lira"), ("ask", "включи радио")], "«Лира, включи радио» одной фразой — как раньше")
ok(run("Играй.", False, follow=True) == [("ask", "Играй.")], "после «слушаю» — «Играй.» идёт вопросом")
ok(run("Привет", False, follow=False) == [("state", "idle")], "без имени и не в ожидании — не отвечаем")

# --- цикл слушания: 20 с «музыки», которую детектор принимает за речь, и имя в конце ---
FR = E.FRAME
e = stub()
e.s = SimpleNamespace(get=lambda *k, default=None: {("audio", "end_silence_ms"): 650, ("audio", "barge_in"): "smart"}.get(k, default))
e.stopping, e.restart_audio, e.muted, e.state = threading.Event(), threading.Event(), False, "idle"
e.status, e.meeting, e.alarm, e.utt_id, e.wake_time = {"aec": True}, [], None, 0, 0.0
e._listen_peak = e._listen_vad = 0.0
e._pending_media_stop, e.check_q, e.stt_q = 0.0, queue.Queue(), queue.Queue()
e.radio = SimpleNamespace(playing=True)
e._meeting_ignores = lambda p: False
e._noisy = lambda: False
e.wake_checker = lambda: None
e._level = lambda *a: None
e.interrupt = lambda *a, **k: None
got = []
e._on_utterance = lambda pcm, t0, now: got.append(len(pcm) / 2 / 16000)
frames = int(20 / E.FRAME_S)
name_at = frames - int(0.4 / E.FRAME_S)                  # быстрый слух отозвался почти в конце 20 с
after = int(2.0 / E.FRAME_S)                             # потом радио замолчало: тишина
total = frames + after
state = {"i": 0}


def read():
    i = state["i"]; state["i"] += 1
    if i >= total:
        e.stopping.set()
        return b"\0" * (FR * 2)
    return (np.random.default_rng(i).normal(0, 2000, FR)).astype(np.int16).tobytes() if i < frames else b"\0" * (FR * 2)


e.capture = SimpleNamespace(read=read)
e.vad = SimpleNamespace(prob=lambda f: 0.9 if state["i"] <= frames else 0.05, reset=lambda: None)
e.spotter = SimpleNamespace(feed=lambda f: [("wake", "лира")] if state["i"] == name_at else [], rec=SimpleNamespace(Reset=lambda: None),
                            last_final=None)
e.set_state = lambda st: setattr(e, "state", st)
e.wav_input = None                 # не запись из файла — обычный микрофон
E.Engine._listen(e)
ok(len(got) == 1 and got[0] < 3.0, f"имя под музыку: фраза начинается с имени, а не тянется 20 с ({got[0] if got else '—':.1f} с)")
ok(e._wake_phrase == "лира" and e.state == "listening", "имя запомнено, ассистент слушает")

# --- радио: молчит, пока слушаем и думаем; тихо под голосом; тише 10% не бывает ---
r = Radio(lambda: None, lambda: None)
seen = {}
e2 = stub(); e2.muted, e2.state, e2.radio = False, "idle", r
e2.emit = lambda *a, **k: None
for st in ("listening", "thinking", "speaking", "idle"):
    E.Engine.set_state(e2, st); seen[st] = r._duck
ok(seen == {"listening": 0.0, "thinking": 0.0, "speaking": 0.25, "idle": 1.0}, f"радио: слушаем/думаем — тишина, говорим — 25%, потом как было: {seen}")
r.set_volume(0.05)
ok(r.volume == 0.1, "громкость радио не опускается до неслышных 5%")

# --- «играй» ---
import tools as _tools  # noqa: E402
_tools.media_players = lambda: 0
e3 = stub()
e3.radio = SimpleNamespace(playing=False, paused=None, last={"name": "Радио Джаз", "url": "u1", "tags": "jazz"}, volume=0.8, station=None)
e3.music = SimpleNamespace(stations=lambda: [{"name": "Джаз 2", "url": "u2", "tags": "jazz"}, {"name": "Рок", "url": "u3", "tags": "rock"}],
                           genres=lambda: ["джаз", "рок"])
e3._music_service = lambda: "radio"
played = []
e3._play_station = lambda c, said, ph: played.append([x["name"] for x in c])
e3._say_quick = lambda m, s, via=None: played.append(m)
e3._music_asked = 0.0
ok(E.Engine._music_cmd(e3, "Играй") is True and played and played[0][0] == "Радио Джаз" and played[0][1] == "Джаз 2",
   f"«Играй» без плеера — снова последняя станция (запасные — того же жанра): {played[:1]}")
played.clear(); e3.radio.last = None
ok(E.Engine._music_cmd(e3, "Играй") is True and "Что включить" in played[0], "ничего ещё не играло — спрашиваю, что включить")
played.clear(); e3.radio = SimpleNamespace(playing=True, paused=None, last=None, volume=0.1, station={"name": "Медляк FM"})
ok(E.Engine._music_cmd(e3, "Играй") is True and "тихо" in played[0] and "10%" in played[0], f"радио играет на 10% — так и говорю: {played[0]}")
