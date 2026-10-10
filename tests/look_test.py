"""Оформление: темы виджета (calm — по умолчанию, graphite, neon — как раньше) и чем голос отзывается вокруг портрета
(лучи, пульс, волна). Виджет перекрашивается по настройкам ui.skin / ui.voice_fx, студия → «Оформление» — живые образцы
и выбор, телефон → «Ещё» → «Оформление». Облики рисуются в Chromium, ядро не нужно."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


from settings import DEFAULTS  # noqa: E402
ok(DEFAULTS["ui"]["skin"] == "calm" and DEFAULTS["ui"]["voice_fx"] == "bars", "по умолчанию — сдержанная тема и лучи")
sk = (ROOT / "ui/assets/skins.js").read_text(encoding="utf-8"); css = (ROOT / "ui/assets/skins.css").read_text(encoding="utf-8")
import re as _re
ids = _re.findall(r'id: "([a-z]+)"', sk)
ok(ids and all(f".skin-{i} " in css or f".skin-{i}," in css for i in ids) and all((ROOT / "ui/assets/skins" / f).exists() for f in _re.findall(r'skins/([a-z]+\.webp)', css)),
   f"у каждого фона из skins.js есть стиль, текстуры на месте: {ids}")
bs = (ROOT / "android/tools/build_apk.sh").read_text(encoding="utf-8")
ok("skins.css" in bs and "ui/assets/skins\"" in bs, "сборка телефона берёт те же темы")
IMG = (ROOT / "data/avatars/lira.webp").as_uri()
FAKE = "window.pywebview = { api: new Proxy({}, { get: () => () => Promise.resolve(true) }) };"
with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    # облики: каждая анимация рисует кадры, когда говорит, и в покое не мешает
    pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    d = Path(tempfile.mkdtemp()); (d / "p.html").write_text(f"""<!doctype html><meta charset=utf-8><body style="background:#111">
<script src="{(ROOT / 'ui/assets/entities.js').as_uri()}"></script><script>
window.E = {{}}; window.cnt = {{}};
for (const fx of ["bars", "pulse", "wave"]) for (const tone of ["mono", "color"]) {{
  const c = document.createElement("canvas"); c.style.cssText = "width:160px;height:160px"; document.body.appendChild(c);
  const id = fx + "-" + tone, e = new DewiarEntity(c, {{ style: "photo", color: "#B78CFF", image: null, plate: false, tone, fx }});   // без фото: холст не «заражён» file://
  const ctx = c.getContext("2d"), st = ctx.stroke.bind(ctx); cnt[id] = 0; ctx.stroke = (...a) => {{ cnt[id]++; return st(...a); }};
  e.set({{ state: "speaking", level: .6 }}); E[id] = e;
}}
</script>""", encoding="utf-8")
    pg.goto((d / "p.html").as_uri()); pg.wait_for_timeout(1500)
    c = pg.evaluate("cnt")
    ok(all(v > 10 for v in c.values()), f"лучи, пульс и волна рисуются в обоих тонах: {c}")
    px = pg.evaluate("""() => { const out = {}; for (const id of ['bars-mono', 'bars-color']) { const cv = E[id].canvas, x = cv.getContext('2d');
        const d = x.getImageData(0, 0, cv.width, cv.height).data; let r = 0, g = 0, b = 0, n = 0;
        for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200 && Math.hypot((i / 4) % cv.width - cv.width / 2, Math.floor(i / 4 / cv.width) - cv.height / 2) > cv.width * 0.36) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
        out[id] = n ? [r / n, g / n, b / n].map(Math.round) : null; } return out; }""")
    mono, color = px["bars-mono"], px["bars-color"]
    ok(mono and color and abs(mono[0] - mono[1]) < 30 and color[2] - color[1] > 25,
       f"сдержанный тон — белые лучи, цветной — цвета персонажа: {mono} / {color}")
    pg.close()

    # виджет: тема и анимация по настройкам
    pg = b.new_page(viewport={"width": 300, "height": 420}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(FAKE)
    pg.goto((ROOT / "ui/hud.html").as_uri() + "?mode=card&port=1"); pg.wait_for_timeout(800)
    w0 = pg.evaluate("() => [document.body.className, entity.tone, entity.fx]")
    ok("skin-calm" in w0[0] and w0[1] == "mono" and w0[2] == "bars", f"виджет по умолчанию: {w0}")
    pg.evaluate("() => core.emit('settings', { settings: { ui: { skin: 'neon', voice_fx: 'pulse' } } })")
    w1 = pg.evaluate("() => [document.body.className, entity.tone, entity.fx, getComputedStyle(document.getElementById('card')).backgroundImage.includes('51, 32, 58')]")
    ok("skin-neon" in w1[0] and "skin-calm" not in w1[0] and w1[1] == "color" and w1[2] == "pulse" and not w1[3], f"студия выбрала «Неон» и «Пульс» — виджет сразу перекрасился: {w1[:3]}")
    pg.evaluate("() => core.emit('settings', { settings: { ui: { skin: 'marble' } } })")
    ok("marble.webp" in pg.evaluate("getComputedStyle(document.getElementById('card')).backgroundImage"), "материал «Мрамор» — текстура подгрузилась в фон")
    pg.evaluate("() => core.emit('settings', { settings: { ui: { skin: 'calm' } } })")
    ok(pg.evaluate("getComputedStyle(document.getElementById('card')).backgroundImage.includes('51, 32, 58')"), "сдержанная тема — мягкий фон в фирменных цветах (#33203a в углу)")
    ok(pg.evaluate("getComputedStyle(document.getElementById('bubble')).borderTopWidth") == "0px", "строка состояния — без рамки")
    pg.close()

    # студия → «Оформление»
    pg = b.new_page(viewport={"width": 1100, "height": 760}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(FAKE)
    pg.goto((ROOT / "ui/settings.html").as_uri() + "?port=1"); pg.wait_for_timeout(1000)
    pg.evaluate("""(img) => { S = { ui: { skin: 'calm', voice_fx: 'bars' } }; personas = [{ id: 'lira', name: 'Лира', color: '#B78CFF', style: 'strings', avatar_url: img, live: 'lira' }];
      window.saved = []; window.save = (patch) => { saved.push(patch); Object.assign(S.ui, patch.ui || {}); return Promise.resolve(); };
      $('nav button[data-p="look"]').click(); }""", IMG)
    pg.wait_for_timeout(600)
    cards = pg.evaluate("() => [$$('#lk-skins .lk').length, $$('#lk-fx .lk canvas').length, $('#lk-skins .lk.on').dataset.skin, $('#lk-fx .lk.on').dataset.fx, $$('#lk-skins .lk-group').length]")
    ok(cards[0] >= 10 and cards[1:] == [3, "calm", "bars", 5], f"фоны по группам, три живых образца анимации, выбранное отмечено: {cards}")
    pg.click('.lk[data-skin="graphite"]'); pg.wait_for_timeout(300)
    pg.click('.lk[data-fx="wave"]'); pg.wait_for_timeout(300)
    ok(pg.evaluate("saved") == [{"ui": {"skin": "graphite"}}, {"ui": {"voice_fx": "wave"}}] and pg.evaluate("$('#lk-skins .lk.on').dataset.skin") == "graphite",
       f"выбор сохраняется сразу: {pg.evaluate('saved')}")
    pg.close()

    # телефон → «Ещё» → «Оформление»
    www = Path(tempfile.mkdtemp()) / "www"
    shutil.copytree(ROOT / "android/assets/www", www)
    shutil.copy(ROOT / "ui/assets/entities.js", www / "entities.js")
    for f in ("skins.css", "skins.js"):                     # как в сборке (android/tools/build_apk.sh)
        shutil.copy(ROOT / "ui/assets" / f, www / f)
    shutil.copytree(ROOT / "ui/assets/skins", www / "skins", dirs_exist_ok=True)
    shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)
    (www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                    capture_output=True, text=True, check=True).stdout, encoding="utf-8")
    pg = b.new_page(viewport={"width": 393, "height": 820}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://**", lambda r: r.abort())
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(900)
    th = pg.evaluate("async () => [(await quick('Спасибо большое')) || null, (await quick('ладно, благодарю')) || null, await quick('спасибо, а что ещё ты умеешь')]")
    ok(th[0] and th[1] and th[0]["say"].startswith(("Пожалуйста", "Обращайтесь")) and not th[2], f"телефон: «спасибо» — вежливый ответ без модели: {th}")
    ph0 = pg.evaluate("() => [document.body.className, orb.tone, orb.fx]")
    ok("skin-calm" in ph0[0] and ph0[1] == "mono" and ph0[2] == "bars", f"телефон по умолчанию: {ph0}")
    pg.evaluate("openSettings('more')"); pg.wait_for_timeout(400)
    card = pg.evaluate("() => [document.querySelector('#set-body').textContent.includes('№' + devId().slice(-4)), !!document.querySelector('#dev-ping')]")
    ok(card == [True, True], "«Этот телефон в кабинете»: №… как в списке экзамена и кнопка «Отметиться в кабинете»")
    ok(pg.evaluate("$$('#ap-skin option').length") >= 10 and pg.evaluate("$$('#ap-skin optgroup').length") == 5, "телефон: те же фоны по группам")
    pg.select_option("#ap-skin", "neon"); pg.select_option("#ap-fx", "pulse"); pg.wait_for_timeout(300)
    ph1 = pg.evaluate("() => [document.body.className, orb.tone, orb.fx, S.skin, S.voice_fx]")
    ok("skin-neon" in ph1[0] and ph1[1:] == ["color", "pulse", "neon", "pulse"], f"телефон: тема и анимация меняются и запоминаются: {ph1}")
    pg.close()
    b.close()
ok(not errs, f"без ошибок на страницах: {errs[:3]}")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
