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
if fails:
    print("\n".join(l for l in log.splitlines() if "dewiar" in l)[-3000:])
print("\nИТОГ:", "всё прошло" if not fails else f"не прошло {len(fails)}")
sys.exit(1 if fails else 0)
