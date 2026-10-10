"""«Обещал, но не сделал»: модель отвечает «сейчас посмотрю и расскажу» и не вызывает ни одного действия, а на просьбу
о презентации не запускает задачу — ядро просит её сделать (quality.promise_nudge), и задача запускается. Обычный ответ и
уточняющий вопрос («Какой город?») не трогаем. Настоящее ядро по wav-файлу и своя модель-заглушка."""
import asyncio, json, os, re, socket, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import websockets
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
TESTS = Path(__file__).resolve().parent
PY = os.environ.get("DEWIAR_PY") or sys.executable
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


SEEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps({"data": [{"id": "m"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        user = next((m["content"] for m in reversed(msgs) if m["role"] == "user" and isinstance(m["content"], str)), "")
        first_q = next((m["content"] for m in reversed(msgs) if m["role"] == "user" and isinstance(m["content"], str)
                        and not m["content"].startswith("СТОП")), "")
        SEEN.append(user[:80])
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()

        def send(delta, fin=None):
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': fin}]}, ensure_ascii=False)}\n\n".encode())
        if msgs[-1]["role"] == "tool" or user.startswith("<tool_response>"):   # без инструментов история — текстом
            send({"content": "Взялась за презентацию — сообщу, когда будет готово."}); send({}, "stop")
        elif user.startswith("СТОП") and "start_task" in user:
            send({"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "start_task",
                  "arguments": json.dumps({"title": "Презентация погоды", "goal": "Презентация о погоде в Минске на завтра"}, ensure_ascii=False)}}]})
            send({}, "tool_calls")
        elif user.startswith("СТОП"):
            send({"content": "Завтра в Минске +12 и облачно."}); send({}, "stop")
        elif msgs[-1]["role"] == "tool":
            send({"content": "Взялась за презентацию — сообщу, когда будет готово."}); send({}, "stop")
        elif "город" in first_q:
            send({"content": "Какой город?"}); send({}, "stop")
        elif "презентац" in first_q or "погод" in first_q:
            send({"content": "Я сейчас посмотрю, какая будет погода на завтра, а затем расскажу."}); send({}, "stop")
        else:
            send({"content": "Привет! Всё хорошо."}); send({}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")


UP, PORT = free(), free()
srv = ThreadingHTTPServer(("127.0.0.1", UP), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp())
(tmp / "cfg").mkdir()
base = f"http://127.0.0.1:{UP}/v1"
(tmp / "cfg/settings.json").write_text(json.dumps({
    "persona": "lira", "stt": {"engine": "vosk"}, "tts": {"engine": "off"}, "audio": {"sounds": False}, "ui": {"intro": "done"},
    "report": {"pulse": False}, "team": {"route": False},
    "llm": {"active": "m", "tools_probe_v": 2, "tools_modes": {f"{base}|m": "native"},
            "profiles": {"m": {"name": "mock", "kind": "openai", "base_url": base, "model": "m"}}}}))
env = dict(os.environ, DEWIAR_CONFIG_DIR=str(tmp / "cfg"), DEWIAR_STATE_DIR=str(tmp / "st"), DEWIAR_PORT=str(PORT), DEWIAR_ASSUME_AEC="1",
           DEWIAR_WORKSPACE_DIR=str(tmp / "ws"), DEWIAR_FAKE_RAM_GB="16", DEWIAR_FAKE_CORES="8")
R = {}


async def session():
    core = subprocess.Popen([PY, str(ROOT / "core/main.py"), "--wav", str(TESTS / "silence90.wav"), "--null-audio"], env=env,
                            stdout=open(tmp / "core.log", "w"), stderr=subprocess.STDOUT)
    try:
        ws_ = None
        for _ in range(300):
            await asyncio.sleep(0.2)
            if (tmp / "cfg/token").exists():
                try:
                    ws_ = await websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None); break
                except OSError:
                    continue
        await ws_.send(json.dumps({"cmd": "hello", "token": (tmp / "cfg/token").read_text().strip()}))
        cnt, replies, events = [0], {}, []

        async def reader():
            async for raw in ws_:
                e = json.loads(raw)
                if e["type"] == "reply":
                    replies[e["id"]] = e
                elif e["type"] != "level":
                    events.append(e)
        rd = asyncio.ensure_future(reader())

        async def call(cmd, **args):
            cnt[0] += 1; i = cnt[0]
            await ws_.send(json.dumps({"id": i, "cmd": cmd, "args": args}))
            for _ in range(1200):
                if i in replies:
                    return replies.pop(i)
                await asyncio.sleep(0.05)

        async def final(mark, t=30):
            last_n, quiet = -1, 0
            for _ in range(t * 20):                      # ждём, пока ответы перестанут приходить 2 с
                d = [e for e in events[mark:] if e["type"] == "answer" and e.get("done")]
                quiet = quiet + 1 if d and len(events) == last_n else 0
                last_n = len(events)
                if quiet >= 40:
                    return d[-1].get("text", "")
                await asyncio.sleep(0.05)
            d = [e for e in events[mark:] if e["type"] == "answer" and e.get("done")]
            return d[-1].get("text", "") if d else ""
        for q, key in (("Сделай мне презентацию о завтрашней погоде", "pres"), ("Какая погода завтра?", "promise"),
                       ("Какая погода в моём городе?", "ask"), ("Привет", "plain")):
            m = len(events)
            await call("say", text=q)
            R[key] = await final(m)
            R[key + "_all"] = " | ".join(e.get("text", "") for e in events[m:] if e["type"] == "answer" and e.get("done"))
            await asyncio.sleep(1.0)
        rd.cancel(); await ws_.close()
    finally:
        core.terminate()
        try:
            core.wait(10)
        except subprocess.TimeoutExpired:
            core.kill()

asyncio.run(session())
log = (tmp / "core.log").read_text(encoding="utf-8", errors="replace")
srv.shutdown()
ok("Взялась за презентацию" in R["pres_all"] and "«Презентация погоды»" in R["pres_all"], f"презентация: обещание → задача запущена ({R['pres_all'][:160]})")
ok("+12" in R["promise"], f"«сейчас посмотрю» без действия → доделала: {R['promise'][-60:]}")
ok(R["ask"].strip() == "Какой город?", f"уточняющий вопрос не трогаем: {R['ask']}")
ok(R["plain"].startswith("Привет"), "обычный ответ не трогаем")
ok(log.count("✋ Модель") == 2, f"просили доделать дважды: {log.count('✋ Модель')}")
print("ИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
