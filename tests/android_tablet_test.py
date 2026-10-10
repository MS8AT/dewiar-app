"""Телефон и планшет без сервисов Google (отчёт с планшета Huawei): вход аккаунтом — и всё работает само.
- вход логином сайта, даже если сайт не назвал облако в services, — мозг подключён сразу, «Проверить» отвечает;
- распознаватель устройства «есть», но молчит — через 4 с слушает сервер Dewiar (и дальше — сразу он), кнопка не залипает;
- нажали микрофон, пока «слушаю», а распознаватель не отвечает — через 2 с снова можно говорить;
- нет русского голоса, а в облаке есть озвучка — говорит голос Dewiar (свой у персонажа);
- экран лёжа: облик слева, разговор справа (картинки — в папку из аргумента)."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


www = Path(tempfile.mkdtemp()) / "www"
shutil.copytree(ROOT / "android/assets/www", www)
shutil.copy(ROOT / "ui/assets/entities.js", www / "entities.js")
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)   # живое лицо Эвы
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
# сайт и облако — подделка http(): login.php без cloud в services (как на живом сайте), облако с распознаванием и озвучкой
FAKE = """
window._req = []; window._said = []; window._heard = [];
window.http = async (method, url, o = {}) => {
  window._req.push(method + " " + url);
  const J = (st, d) => ({ status: st, body: JSON.stringify(d) });
  if (/login\\.php/.test(url)) return J(200, { ok: true, token: "tok-1", user: { login: "Andrej", id: 8 }, services: { rag: "/synapbase/api_rag", tg: "/dwrapp/tg.php" } });
  if (/p=\\/balance/.test(url)) return J(200, { ok: true, percent: 99, turns: 971, balance: 0.99, label: "Andrej" });
  if (/p=\\/models/.test(url)) return J(200, { data: [{ id: "chat", title: "DWR Chat Qwen 3.8" }], stt: true, tts: true });
  if (/p=\\/usage/.test(url)) return J(200, { days: [], answers: 0 });
  if (/chat\\/completions/.test(url)) return J(200, { choices: [{ message: { content: "готово" } }] });
  return J(404, {});
};
"""
with sync_playwright() as p:
    b = p.chromium.launch(); errors = []
    pg = b.new_page(viewport={"width": 800, "height": 1280})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(600)
    pg.evaluate(FAKE)
    R = pg.evaluate("""async () => {
        const x = await accountLogin("", "Andrej", "secret");
        return { x, llm: S.llm, acc: S.accCloud };
    }""")
    ok(R["llm"].get("cloud") and R["llm"].get("account") and R["llm"].get("base_url", "").endswith("cloud.php?p="),
       f"вход аккаунтом (сайт не назвал облако) — модели Dewiar подключены сразу: {R['llm'].get('base_url')}")
    ok(R["acc"].get("stt") and R["acc"].get("tts"), "облако умеет слушать и говорить — запомнено")
    pg.evaluate("openSettings('brain')"); pg.wait_for_timeout(300)
    ok(pg.evaluate("!!document.querySelector('.card.brain.ok') && !document.querySelector('.tile[data-w=dewiar]')"),
       "«Мозг»: видно «Подключено», непонятного «Сервер Dewiar» больше нет")
    pg.click("#br-test"); pg.wait_for_timeout(500)
    ok("Работает" in pg.inner_text("#br-res"), f"«Проверить» отвечает: {pg.inner_text('#br-res')}")
    if SHOTS:
        pg.screenshot(path=str(SHOTS / "tablet-brain.png"))
    pg.evaluate("closeSheets()")

    # распознаватель устройства «есть», но молчит
    R = pg.evaluate("""async () => {
        Dewiar.recognizer = () => true; Dewiar.listen = (g) => { window._heard.push("system"); window._g = g; };
        Dewiar.listenServer = (g, u, k, m) => { window._heard.push("server " + u + " " + m); window._g = g; };
        S.stt = Object.assign({}, DEF.stt);
        await listen(); const st1 = state;
        await new Promise(r => setTimeout(r, 4600));
        return { st1, heard: window._heard.slice(), stt: S.stt, st2: state };
    }""")
    ok(R["st1"] == "listening" and R["heard"][0] == "system", "сначала слушает распознаватель устройства")
    ok(len(R["heard"]) == 2 and R["heard"][1].startswith("server ") and "p=/audio/transcriptions" in R["heard"][1],
       f"молчит 4 с — этот вопрос слушает сервер Dewiar: {R['heard']}")
    ok(R["stt"].get("engine") == "system" and R["stt"].get("sysFails") == 1, "первый раз — не насовсем: распознаватель мог просто долго подключаться")
    R = pg.evaluate("""async () => {
        // поздняя ошибка «отменено» от прежнего (системного) сеанса — не сбивает серверный
        N.ev(JSON.stringify({ type: "stt_error", g: window._g - 1, code: 5, msg: "отменено" })); await new Promise(r => setTimeout(r, 50));
        const still = state === "listening" && sttActive;
        N.ev(JSON.stringify({ type: "stt_result", g: window._g, text: "привет" })); await new Promise(r => setTimeout(r, 50));
        return { still, you: document.querySelector("#you").textContent };
    }""")
    ok(R["still"], "поздняя ошибка прежнего сеанса не сбивает новый (кнопка не залипает)")
    ok("привет" in R["you"], "сказанное сервером — принято как вопрос")
    pg.wait_for_timeout(600)
    R = pg.evaluate("""async () => {
        if (state !== "idle") finishTurn();
        window._heard = [];
        await listen(); await new Promise(r => setTimeout(r, 4600));
        return { heard: window._heard.slice(), stt: S.stt };
    }""")
    ok(R["heard"][0] == "system" and R["stt"].get("engine") == "server" and R["stt"].get("auto"),
       f"молчит второй раз подряд — дальше сразу сервер Dewiar (запомнено): {R['stt'].get('engine')}")
    pg.evaluate("stopListen(); setState('idle')")

    # кнопка микрофона не залипает
    R = pg.evaluate("""async () => {
        Dewiar.listenServer = () => {}; Dewiar.stopListen = () => {};
        if (state !== "idle") finishTurn();
        await listen(); const a = state; document.querySelector("#mic").click();
        await new Promise(r => setTimeout(r, 2300));
        return { a, b: state, on: document.querySelector("#mic").classList.contains("on") };
    }""")
    ok(R["a"] == "listening" and R["b"] == "idle" and not R["on"], f"нажали «хватит», распознаватель молчит — через 2 с снова можно говорить: {R}")

    # голос Dewiar, если в устройстве нет русского голоса
    R = pg.evaluate("""() => {
        Dewiar.ttsReady = () => false; Dewiar.speakRemote = (id, url, key, body) => window._said.push({ url, key, body: JSON.parse(body) });
        S.persona = "lira"; applyPersona(); say("Привет, это Лира.");
        return window._said;
    }""")
    ok(len(R) == 1 and R[0]["url"].endswith("cloud.php?p=/audio/speech") and R[0]["key"] == "tok-1"
       and R[0]["body"]["voice"] == "serena" and R[0]["body"]["input"].startswith("Привет"),
       f"нет русского голоса — говорит голос Dewiar, у Лиры — свой: {R}")
    # «погода в виде презентации»: модель узнала погоду, а «сделала презентацию» только словами — просим сделать по-настоящему
    R = pg.evaluate("""async () => {
        const NL = String.fromCharCode(10, 10), sse = (o) => "data: " + JSON.stringify(o) + NL, seen = [];
        const tc = (name, args) => sse({ choices: [{ delta: { tool_calls: [{ index: 0, id: "c" + seen.length, function: { name, arguments: JSON.stringify(args) } }] } }] });
        const SLIDES = "<!doctype html><html><body style='background:#123;color:#fff'><section><h1>Погода в Минске</h1><p>+12, облачно</p></section></body></html>";
        window.http = async (m, u, o) => {
          if (!o.onChunk) return { status: 200, body: JSON.stringify({ current: { temperature_2m: 12 }, daily: {} }) };
          const body = typeof o.body === "string" ? JSON.parse(o.body) : o.body; seen.push(body);
          const last = body.messages[body.messages.length - 1], made = body.messages.some(x => x.role === "tool" && /make_app|Открыто|открыт/i.test(x.content || "") && x.tool_call_id && x.tool_call_id !== "c0");
          let out;
          if (seen.length === 1) out = tc("weather", { city: "Минск", days: 2 });
          else if (String(last.content || "").startsWith("СТОП")) { window._stop = true; out = tc("make_app", { title: "Погода на завтра", html: SLIDES }); }
          else if (last.role === "tool" && seen.length > 2) out = sse({ choices: [{ delta: { content: "Готово — презентация на экране." } }] });
          else out = sse({ choices: [{ delta: { content: "Завтра в Минске пасмурно, около двенадцати. Я сделала для тебя мини-презентацию — она уже открылась на экране." } }] });
          o.onChunk(out + "data: [DONE]" + NL); return { status: 200, body: "" };
        };
        await ask("Какая погода на завтра в Минске, сделай в виде презентации");
        for (let i = 0; i < 200 && busy; i++) await new Promise(r => setTimeout(r, 50));
        await new Promise(r => setTimeout(r, 300));
        return { asks: seen.length, stop: !!window._stop, view: !!document.querySelector("#appview.on iframe"), apps: apps().map(a => a.title) };
    }""")
    ok(R["stop"] and R["view"] and "Погода на завтра" in R["apps"],
       f"«сделала презентацию» словами после погоды — замечено, презентация сделана по-настоящему и открыта: {R}")
    ok(not errors, f"без ошибок {errors}")
    b.close()

    # экран лёжа
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(600)
    pg.evaluate("showBot('Сегодня облачно, плюс двенадцать.')")
    r = pg.evaluate("""() => { const o = document.querySelector('#orbwrap').getBoundingClientRect(), t = document.querySelector('#bot').getBoundingClientRect();
        return { orbRight: o.right, botLeft: t.left, orbW: o.width }; }""")
    ok(r["orbRight"] <= r["botLeft"] and r["orbW"] > 250, f"экран лёжа: облик слева, разговор справа {r}")
    if SHOTS:
        pg.screenshot(path=str(SHOTS / "tablet-landscape.png"))
    b.close()
man = (ROOT / "android/AndroidManifest.xml").read_text(encoding="utf-8")
ok('screenOrientation="portrait"' not in man, "экран поворачивается (в манифесте нет запрета)")
print("ИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
