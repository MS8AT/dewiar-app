"""Картинки к рассказу и схемы в ответах (просьба 14.10: «Лира рассказывает про руническую вязь: „вот смотри такое-то
изображение“ — а изображения нет; пусть подтягивает картинки, о которых говорит» и «может ли она показывать диаграммы,
типа mermaid?»). Поддельные Wikimedia Commons и модель:
— компьютер: модель вызывает show_images → картинки сразу в виджете (событие media), в ленте «Чата» — галереей у ответа
  со ссылкой на источник; модель получает, что показано; ```mermaid в ответе — вслух не читается (и без «код на экране»),
  в «Чате» и «Открыть целиком» — схемой (mermaid грузится только при первой схеме);
— телефон: show_images — галерея под ответом и в истории разговора; схема — картинкой; блок ``` вслух не читается,
  даже если пришёл кусками; «вот смотри изображение» без show_images — ловится (просьба сделать)."""
import asyncio, http.server, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
from playwright.sync_api import sync_playwright
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


# ── поддельный Commons: поиск и сами картинки ──
from PIL import Image  # noqa: E402
import io  # noqa: E402
buf = io.BytesIO(); Image.new("RGB", (480, 360), (120, 80, 40)).save(buf, "PNG"); PNG = buf.getvalue()
CPORT = free()
SEEN_Q = []


class C(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send_response(200); self._cors(); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(PNG))); self.end_headers(); self.wfile.write(PNG); return
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        SEEN_Q.append(q.get("gsrsearch", [""])[0])
        base = f"http://127.0.0.1:{CPORT}"
        pages = {}
        for i, (name, w) in enumerate([("Urnes stave church portal.jpg", 2400), ("Runestone U 1043.jpg", 1600), ("Logo runes.png", 800),
                                        ("Tiny.jpg", 120), ("Ringerike style.jpg", 900)]):
            pages[str(100 + i)] = {"index": i + 1, "title": "File:" + name, "imageinfo": [{
                "thumburl": f"{base}/img/480px-{i}.png", "url": f"{base}/img/full-{i}.png", "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{i}",
                "mime": "image/jpeg", "width": w, "height": 600,
                "extmetadata": {"ObjectName": {"value": name.rsplit('.', 1)[0]}, "ImageDescription": {"value": f"<b>Описание {i}</b> — звериный стиль"},
                                "Artist": {"value": "<a href='x'>Автор</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}
        b = json.dumps({"query": {"pages": pages}}).encode()
        self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


csrv = http.server.ThreadingHTTPServer(("127.0.0.1", CPORT), C)
threading.Thread(target=csrv.serve_forever, daemon=True).start()
COMMONS = f"http://127.0.0.1:{CPORT}/w/api.php"
DIAG = "Вот как связаны стили:\n\n```mermaid\nflowchart LR\n  A[Оусеберг] --> B[Борре] --> C[Еллинге] --> D[Урнес]\n```\n\nГлавное — от Оусеберга к Урнесу узор становится тоньше."

# ── 1. ядро: show_images и схема ──
sys.path.insert(0, str(ROOT / "core"))
os.environ["DEWIAR_COMMONS_API"] = COMMONS
import images  # noqa: E402
images.API = COMMONS
it = images.search("Urnes style", 4)
ok([x["title"] for x in it] == ["Urnes stave church portal", "Runestone U 1043", "Ringerike style"] and it[0]["full"].endswith("1280px-0.png")
   and it[0]["author"] == "Автор" and it[0]["license"] == "CC BY-SA 4.0" and "звериный стиль" in it[0]["desc"] and "<b>" not in it[0]["desc"],
   f"Commons: без логотипов и мелочи, крупные — уменьшенной копией, автор и лицензия без HTML: {[x['title'] for x in it]}")


class M(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        b = json.dumps({"data": [{"id": "m"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()

        def send(delta, fin=None):
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': fin}]}, ensure_ascii=False)}\n\n".encode())
        if msgs[-1]["role"] == "tool":
            MODEL_SAW.append(msgs[-1]["content"])
            for i in range(0, len(DIAG), 9):
                send({"content": DIAG[i:i + 9]})
            send({}, "stop")
        else:
            send({"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "show_images", "arguments": json.dumps({"query": "Urnes style runestone", "count": 3})}}]})
            send({}, "tool_calls")
        self.wfile.write(b"data: [DONE]\n\n")


MODEL_SAW = []
UP, PORT = free(), free()
msrv = http.server.ThreadingHTTPServer(("127.0.0.1", UP), M)
threading.Thread(target=msrv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp()); (tmp / "cfg").mkdir()
base = f"http://127.0.0.1:{UP}/v1"
(tmp / "cfg/settings.json").write_text(json.dumps({
    "persona": "lira", "stt": {"engine": "vosk"}, "tts": {"engine": "off"}, "audio": {"sounds": False}, "ui": {"intro": "done", "welcome": "done", "news_seen": "99.0.0"},
    "report": {"pulse": False}, "team": {"route": False},
    "llm": {"active": "m", "tools_probe_v": 2, "tools_modes": {f"{base}|m": "native"}, "profiles": {"m": {"name": "mock", "kind": "openai", "base_url": base, "model": "m"}}}}))
env = dict(os.environ, DEWIAR_CONFIG_DIR=str(tmp / "cfg"), DEWIAR_STATE_DIR=str(tmp / "st"), DEWIAR_PORT=str(PORT), DEWIAR_ASSUME_AEC="1",
           DEWIAR_WORKSPACE_DIR=str(tmp / "ws"), DEWIAR_FAKE_RAM_GB="16", DEWIAR_FAKE_CORES="8", DEWIAR_COMMONS_API=COMMONS)
core = subprocess.Popen([PY, str(ROOT / "core/main.py"), "--wav", str(TESTS / "silence90.wav"), "--null-audio"], env=env,
                        stdout=open(tmp / "core.log", "w"), stderr=subprocess.STDOUT)
for _ in range(150):
    time.sleep(0.2)
    if (tmp / "cfg/token").exists():
        break
time.sleep(2.5)
errs = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1300, "height": 950})
        pg.on("pageerror", lambda x: errs.append(str(x)))
        events = []
        pg.goto((ROOT / "ui/settings.html").as_uri() + f"?token={(tmp / 'cfg/token').read_text().strip()}&port={PORT}#chat"); pg.wait_for_timeout(2500)
        pg.evaluate("() => { window.__ev = []; core.on('media', e => window.__ev.push(e)); }")
        pg.fill("#ch-text", "Расскажи про урнесский стиль и покажи"); pg.press("#ch-text", "Enter")
        pg.wait_for_selector("#ch-msgs .cl-m:not(.out) .dw-gallery", timeout=25000)
        pg.wait_for_selector("#ch-msgs .dw-diagram svg", timeout=25000); pg.wait_for_timeout(500)
        R = pg.evaluate("""() => { const m = [...document.querySelectorAll('#ch-msgs .cl-m:not(.out)')].pop();
            return { pics: [...m.querySelectorAll('.dw-pic')].map(a => [a.getAttribute('href'), a.querySelector('img').getAttribute('src')]),
                     credit: (m.querySelector('.dw-credit') || {}).textContent, svg: !!m.querySelector('.dw-diagram svg'),
                     svgText: (m.querySelector('.dw-diagram') || {}).textContent, pre: !!m.querySelector('pre'), ev: window.__ev.length,
                     text: m.querySelector('.tx').textContent }; }""")
        ok(R["ev"] >= 1 and len(R["pics"]) == 3 and R["pics"][0][0].startswith("https://commons.wikimedia.org/wiki/") and "/img/480px-0.png" in R["pics"][0][1],
           f"«Чат»: картинки — галереей у ответа, ссылка на источник: {R['pics']}")
        ok("Wikimedia Commons" in (R["credit"] or "") and "CC BY-SA 4.0" in R["credit"], f"подпись: откуда и лицензия: {R['credit']}")
        ok(R["svg"] and "Урнес" in R["svgText"] and not R["pre"] and "Главное" in R["text"], "схема ```mermaid — картинкой, а не текстом")
        # виджет: событие media → миниатюры; «Открыть целиком» — галерея и схема
        hw = b.new_page(viewport={"width": 400, "height": 640})
        hw.on("pageerror", lambda x: errs.append(str(x)))
        hw.goto((ROOT / "ui/hud.html").as_uri() + "?token=x&port=1"); hw.wait_for_timeout(600)
        H = hw.evaluate(f"""async () => {{ tlReset("Покажи руны");
            const items = {json.dumps(it)};
            TL.media = items; TL.answer = {json.dumps(DIAG)}; moreBtn(); openReader();
            await new Promise(r => setTimeout(r, 2500));
            return {{ gal: document.querySelectorAll('#rd-body .dw-pic').length, svg: !!document.querySelector('#rd-body .dw-diagram svg'),
                      cap: capText({json.dumps(DIAG)}), more: document.getElementById('more').classList.contains('on') }}; }}""")
        ok(H["gal"] == 3 and H["svg"] and "схема" in H["cap"] and "flowchart" not in H["cap"] and H["more"],
           f"виджет: «Открыть целиком» — картинки и схема; в подписи — «схема», а не её текст: {H}")
        b.close()
    core.terminate(); core.wait(10)
    log = (tmp / "core.log").read_text(encoding="utf-8")
    chat = [json.loads(x) for x in (tmp / "st/chat.jsonl").read_text(encoding="utf-8").splitlines()]
    a = chat[-1]
    ok(a["role"] == "assistant" and [x["name"] for x in a.get("att", [])] == ["Urnes stave church portal", "Runestone U 1043", "Ringerike style"]
       and a["att"][0]["url"].startswith("https://commons"), f"в ленте «Чата» картинки остались у ответа: {[x.get('name') for x in a.get('att', [])]}")
    ok(MODEL_SAW and "показано картинок: 3" in MODEL_SAW[0] and "Runestone U 1043" in MODEL_SAW[0], f"модель знает, что показано: {MODEL_SAW[:1]}")
    ok(SEEN_Q and SEEN_Q[-1] == "Urnes style runestone filetype:bitmap", f"запрос к Commons: {SEEN_Q[-1:]}")
    ok("Команды и код" not in log, "схема вслух не читается (и без «код на экране»)")
finally:
    core.terminate()

# ── 2. телефон ──
www = tmp / "www"
shutil.copytree(ROOT / "android/assets/www", www)
for f in ("entities.js", "rich.js"):
    shutil.copy(ROOT / "ui/assets" / f, www / f)
(www / "vendor").mkdir(exist_ok=True); shutil.copy(ROOT / "ui/assets/vendor/mermaid.min.js", www / "vendor/mermaid.min.js")
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 400, "height": 820})
    pg.on("pageerror", lambda x: errs.append(str(x)))
    pg.add_init_script(f"window.DEWIAR_COMMONS = {json.dumps(COMMONS)};")
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(900)
    P = pg.evaluate(f"""async () => {{
        const said = [], realSay = window.say; say = (t) => said.push(t);
        turnMedia = null;
        const r = await webImages("Urnes style runestone", 3);
        const sk = sentenceSink(); const t = {json.dumps(DIAG)};
        for (let i = 0; i < t.length; i += 7) sk.push(t.slice(i, i + 7));
        sk.flush(); say = realSay;
        showBot(t); frameAnswer(t);
        await new Promise(r => setTimeout(r, 2500));
        const bot = document.getElementById('bot');
        history.push({{ role: "assistant", content: t, who: "lira", img: turnMedia }});
        document.getElementById('b-hist').onclick(); await new Promise(r => setTimeout(r, 2500));
        const claim = claimedAction("Вот, смотри, такое изображение рунической вязи.", new Set(), "покажи");
        return {{ tool: r, n: (turnMedia || []).length, said, gal: bot.querySelectorAll('.dw-pic').length, svg: !!bot.querySelector('.dw-diagram svg'),
                  hist: document.querySelectorAll('#hlist .dw-pic').length, hsvg: !!document.querySelector('#hlist .dw-diagram svg'),
                  claim: claim && claim.tool }}; }}""")
    pg.click("#hlist .dw-pic"); pg.wait_for_timeout(300)
    pv = pg.evaluate("() => { const v = document.getElementById('picview'); return [!!v && v.classList.contains('on'), v && v.querySelector('img').getAttribute('src')]; }")
    b.close()
ok(P["n"] == 3 and "показано картинок: 3" in P["tool"], f"телефон: show_images — 3 картинки, модели — что показано: {P['tool'][:80]}")
ok(P["gal"] == 3 and P["svg"], f"телефон: под ответом — галерея и схема картинкой: {P['gal']} {P['svg']}")
ok(P["hist"] == 3 and P["hsvg"], "телефон: в истории разговора — тоже картинки и схема")
spoken = " ".join(P["said"])
ok("flowchart" not in spoken and "Оусеберг]" not in spoken and "Вот как связаны стили" in spoken and "Главное" in spoken,
   f"телефон: блок схемы вслух не читается, даже кусками: {P['said']}")
ok(P["claim"] == "show_images", "«вот, смотри, изображение» без show_images — ловится")
ok(pv[0] and "1280px-0.png" in (pv[1] or ""), f"нажали на картинку — на весь экран, крупная копия: {pv}")
ok(not errs, "без ошибок JavaScript" + (f": {errs}" if errs else ""))
csrv.shutdown(); msrv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
