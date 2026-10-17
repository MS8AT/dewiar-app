"""Съёмка 17.10: на «Расскажи о себе, что ты умеешь» Лира раз за разом отвечала «Я Лира.» — модель (Qwen 27B) копировала
свой прошлый ответ из разговора. Теперь ответ слово в слово как недавний (короткий, без действий) — ядро просит модель
ответить по существу, и человек получает нормальный ответ. Первый раз «Я Лира.» не трогаем — повтора ещё нет.
Ядро — настоящее, модель — tests/mock_llm.py (на этот вопрос отвечает «Я Лира.», на просьбу не повторяться — по существу)."""
import asyncio, json, os, socket, subprocess, sys, tempfile, time
from pathlib import Path
import websockets
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
PY = os.environ.get("DEWIAR_PY") or sys.executable
TESTS = Path(__file__).resolve().parent
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


tmp = Path(tempfile.mkdtemp()); (tmp / "cfg").mkdir()
PORT, LLM = free(), free()
(tmp / "cfg/settings.json").write_text(json.dumps({
    "persona": "lira", "llm": {"active": "t", "profiles": {"t": {"name": "Mock", "kind": "openai", "base_url": f"http://127.0.0.1:{LLM}/v1", "disable_thinking": True}}},
    "stt": {"engine": "vosk"}, "tts": {"engine": "off"}, "audio": {"sounds": False, "follow_up_seconds": 0}}))
env = dict(os.environ, DEWIAR_CONFIG_DIR=str(tmp / "cfg"), DEWIAR_STATE_DIR=str(tmp / "st"), DEWIAR_PORT=str(PORT),
           DEWIAR_ASSUME_AEC="1", DEWIAR_WORKSPACE_DIR=str(tmp / "ws"))
mock = subprocess.Popen([sys.executable, str(TESTS / "mock_llm.py"), str(LLM)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
core = subprocess.Popen([PY, str(ROOT / "core/main.py"), "--wav", str(TESTS / "silence90.wav"), "--null-audio"], env=env,
                        stdout=open(tmp / "core.log", "w"), stderr=subprocess.STDOUT)
events = []


async def run():
    ws = None
    for _ in range(200):
        await asyncio.sleep(0.2)
        if (tmp / "cfg/token").exists():
            try:
                ws = await websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None); break
            except OSError:
                continue
    await ws.send(json.dumps({"cmd": "hello", "token": (tmp / "cfg/token").read_text().strip()}))

    async def reader():
        async for raw in ws:
            events.append(json.loads(raw))
    rd = asyncio.ensure_future(reader())
    await asyncio.sleep(3)
    for i in (1, 2):
        n0 = len([e for e in events if e.get("type") == "answer" and e.get("done")])
        await ws.send(json.dumps({"id": i, "cmd": "say", "args": {"text": "Расскажи о себе, что ты умеешь."}}))
        for _ in range(150):
            await asyncio.sleep(0.2)
            if len([e for e in events if e.get("type") == "answer" and e.get("done")]) > n0:
                break
        await asyncio.sleep(1)
    rd.cancel()

try:
    asyncio.run(run())
finally:
    core.terminate()
    try:
        core.wait(10)
    except subprocess.TimeoutExpired:
        core.kill()
    mock.terminate()
ans = [e.get("text", "") for e in events if e.get("type") == "answer" and e.get("done")]
log = (tmp / "core.log").read_text(encoding="utf-8", errors="replace")
ok(len(ans) >= 2 and ans[0].strip() == "Я Лира.", f"первый раз короткий ответ не трогаем: {ans[:1]}")
ok(len(ans) >= 2 and "напоминания" in ans[1] and "прошу ответить по существу" in log,
   f"второй раз то же самое — модель просят ответить по существу, человек получает нормальный ответ: {ans[1:2]}")
# «Звоню Людмиле.» без звонка (съёмка 17.10: раз сработало, потом только слова) — просим сделать
sys.path.insert(0, str(ROOT / "core"))
import quality as Q  # noqa: E402
c = {a: bool(Q.action_claim("Позвони Людмиле по видео", a)) for a in
     ("Звоню Людмиле.", "Звоню Людмиле по видео.", "Набираю маму.", "Отправила сообщение.", "Не звоню.", "Звонить ли Людмиле?", "Я Лира.")}
ok(c == {"Звоню Людмиле.": True, "Звоню Людмиле по видео.": True, "Набираю маму.": True, "Отправила сообщение.": True,
         "Не звоню.": False, "Звонить ли Людмиле?": False, "Я Лира.": False} and not Q.action_claim("x", "Звоню Людмиле.", {"close_call"}),
   f"«звоню / набираю / отправила» без вызова — просим сделать; с вызовом, отрицание или вопрос — нет: {c}")
# «Позвони Людмиле по видео» — человеку из «Близких» звоним сразу, без модели
import types  # noqa: E402
import engine_tools as ET  # noqa: E402
from close import CloseError, match_name  # noqa: E402
PEOPLE = [{"pid": "p1", "name": "Людмила Исаева", "devs": [{"dev": "d"}]}, {"pid": "p2", "name": "Мама", "devs": [{"dev": "d"}]}]


class FakeClose:
    def __init__(self): self.calls = []
    def person(self, who):
        p = match_name(who, PEOPLE)
        if not p:
            raise CloseError("нет")
        return p
    def call(self, who, video=False): self.calls.append((who, video)); return {"name": "Людмила Исаева"}


said = []
e = types.SimpleNamespace(emit=lambda *a, **k: None, close=FakeClose(), _say_quick=lambda msg, text, via=None, **k: said.append(msg))
r = [ET.ToolsMixin._call_cmd(e, q) for q in ("Позвони Людмиле Исаевой по видеосвязи.", "Лира, позвони Людмиле.", "Набери маме",
                                                "Позвони в такси", "Позвони Людмиле и скажи, что я задержусь на час, пожалуйста")]
ok(r == [True, True, True, False, False] and e.close.calls == [("p1", True), ("p1", False), ("p2", False)]
   and said[:2] == ["Звоню Людмиле Исаевой по видео.", "Звоню Людмиле."],
   f"«позвони Людмиле по видео» — звонок сразу, без модели; не из «Близких» или длинная просьба — модели: {r}, {e.close.calls}, {said}")
# «Отправь Людмиле сообщение: «…»» — сразу, без модели (съёмка 17.10: «говорит, что отправила, — и ничего»)
sent, said2 = [], []
PEOPLE += [{"pid": "p3", "name": "Андрей", "devs": [{"dev": "d"}]}, {"pid": "p4", "name": "Лёха", "devs": [{"dev": "d"}]}]
FakeClose.send = lambda self, pid, msg: sent.append((pid, msg))
e2 = types.SimpleNamespace(emit=lambda *a, **k: None, close=FakeClose(), _say_quick=lambda msg, text, via=None, **k: said2.append(msg), _SEND_RX=ET.ToolsMixin._SEND_RX)
qs = ["Отправь Людмиле сообщение: «Привет, как твои дела?»", "Напиши Андрею: «Привет. Как твои дела?»",
      "Отправь сообщение Лёхе. Лёха, привет! Как твои дела?", "Лира, напиши маме, что я задержусь",
      "Напиши письмо Андрею о встрече", "Напиши Андрею в телеграм: привет", "Напиши стих про осень"]
r = [ET.ToolsMixin._send_cmd(e2, q) for q in qs]
ok(r == [True, True, True, True, False, False, False]
   and sent == [("p1", "Привет, как твои дела?"), ("p3", "Привет. Как твои дела?"), ("p4", "Лёха, привет! Как твои дела?"), ("p2", "Я задержусь")]
   and said2[0] == "Отправила Людмиле.",
   f"сообщение близкому — сразу, без модели; письмо, Telegram, стих — модели: {r}, {sent}")
ok("self._send_cmd(text, via)" in (ROOT / "core/engine_answer.py").read_text(encoding="utf-8"), "быстрая отправка стоит перед моделью")
ok("self._call_cmd(text, via)" in (ROOT / "core/engine_answer.py").read_text(encoding="utf-8"), "быстрый звонок стоит перед моделью")
ok("or action_claim(text, step_text, called)" in (ROOT / "core/engine_answer.py").read_text(encoding="utf-8"), "проверка стоит в ходе разговора")
if fails:
    print("\n".join(l for l in log.splitlines() if "dewiar" in l)[-3000:])
print("\nИТОГ:", "всё прошло" if not fails else f"не прошло {len(fails)}")
sys.exit(1 if fails else 0)
