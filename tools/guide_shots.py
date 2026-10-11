"""Снимки экранов для руководства на сайте (server/dwrapp/guide.php): телефон и студия с аккуратными примерами, без
сервера — мост телефона и ядро студии подменены. Пишет server/dwrapp/guide-*.webp.
    python3 tools/guide_shots.py"""
import io, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "server/dwrapp"
NOW = int(time.time() * 1000)


def save(png, name, w=None):
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if w and im.width > w:
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    im.save(OUT / f"guide-{name}.webp", "WEBP", quality=86, method=6)
    print("guide-" + name + ".webp", im.size)


www = Path(tempfile.mkdtemp()) / "www"
shutil.copytree(ROOT / "android/assets/www", www)
for f in ("entities.js", "skins.css", "skins.js", "privacy.js", "closecrypto.js", "qrcode.js", "call.js", "codes.js", "vendor/zxing.min.js"):
    shutil.copy(ROOT / "ui/assets" / f, www / Path(f).name)
shutil.copytree(ROOT / "ui/assets/skins", www / "skins", dirs_exist_ok=True)
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")

PEOPLE = """[{ pid: 'pmama', name: 'Мама', devs: [{ dev: 'd1', pub: 'x' }] }, { pid: 'pand', name: 'Андрей', devs: [{ dev: 'd2', pub: 'x' }] },
             { pid: 'pkat', name: 'Катя', devs: [{ dev: 'd3', pub: 'x' }] }]"""
HIST = f"""{{ pmama: [
  {{ t: 'Ты сегодня приедешь к ужину?', ts: {NOW - 52 * 60000}, out: false, mid: 'a' }},
  {{ t: 'Да, буду к семи 🙂', ts: {NOW - 50 * 60000}, out: true, mid: 'b' }},
  {{ t: 'Купи, пожалуйста, хлеба по дороге', ts: {NOW - 31 * 60000}, out: false, mid: 'c' }},
  {{ t: 'Хорошо! И вот рецепт, о котором говорили', ts: {NOW - 29 * 60000}, out: true, mid: 'd', f: [{{ name: 'Пирог с яблоками.pdf', size: 248000 }}] }},
  {{ t: 'Спасибо, родной ❤️', ts: {NOW - 3 * 60000}, out: false, mid: 'e' }}],
  pand: [{{ t: 'Созвонимся вечером?', ts: {NOW - 3 * 3600000}, out: false, mid: 'f' }}],
  pkat: [{{ t: 'Фото с выходных', ts: {NOW - 26 * 3600000}, out: true, mid: 'g', f: [{{ name: 'дача.jpg', size: 2100000 }}] }}] }}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 393, "height": 820}, device_scale_factor=2)
    pg.route("https://**", lambda r: r.abort())
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(1200)
    pg.evaluate("""() => { S.llm = Object.assign({}, S.llm, { cloud: true, api_key: 'dw-demo-key', model: 'chat' }); S.user_name = 'Миша'; saveS(); }""")
    # главный экран: разговор
    pg.evaluate("""() => { showYou('Напомни в пятницу в 15:00 позвонить Лёше'); showBot('Поставила: в пятницу в 15:00 — позвонить Лёше. Напомню и на часах.'); clearCard(); }""")
    pg.wait_for_timeout(500); save(pg.screenshot(), "phone-talk", 600)
    # «Близкие»: переписка с мамой
    pg.evaluate(f"""() => {{ const st = clLoad(); st.people = {PEOPLE}; st.hist = {HIST}; st.unread = {{ pand: 1 }}; st.me = {{ name: 'Миша' }};
      clHello = async () => {{}}; openClose('pmama'); }}""")
    pg.wait_for_timeout(600); save(pg.screenshot(), "phone-close-chat", 600)
    # «Близкие»: список и печать-приглашение
    pg.evaluate("""() => { clCur = ''; clRender(); clInvShow({ link: 'https://dewiar.pro/dwrapp/download.php?close=Gh7xQ2LmP9aKz3Vt', expires: Date.now() / 1000 + 6 * 86400 }); }""")
    pg.wait_for_timeout(600); save(pg.screenshot(), "phone-close-invite", 600)
    pg.close()

    # студия: «Близкие» в светлой теме — переписка и печать
    pg = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1.5)
    pg.add_init_script("window.pywebview = { api: new Proxy({}, { get: () => () => Promise.resolve(true) }) }; localStorage.setItem('studio_skin', 'snow');")
    pg.goto((ROOT / "ui/settings.html").as_uri() + "?port=1"); pg.wait_for_timeout(1200)
    pg.evaluate(f"""() => {{ const H = {HIST}, P = {PEOPLE}.map(x => Object.assign(x, {{ last: (H[x.pid] || []).slice(-1)[0], unread: x.pid === 'pand' ? 1 : 0 }}));
      core.call = (c, a) => c === 'close_state' ? Promise.resolve({{ me: {{ name: 'Миша' }}, people: P }})
        : c === 'close_history' ? Promise.resolve(H[a.pid] || []) : c === 'close_invite' ? Promise.resolve({{ link: 'https://dewiar.pro/dwrapp/download.php?close=Gh7xQ2LmP9aKz3Vt' }}) : Promise.resolve({{}});
      if (window.studioSkin) studioSkin('snow'); $('nav button[data-p="close"]').click(); }}""")
    pg.wait_for_timeout(900); pg.evaluate("async () => { await loadClose(); await clOpen('pmama'); }"); pg.wait_for_timeout(500)
    save(pg.screenshot(), "studio-close", 1600)
    pg.click("#cl-inv-go"); pg.wait_for_timeout(600)
    save(pg.locator("#cl-invite").screenshot(), "studio-seal", 1000)
    b.close()
