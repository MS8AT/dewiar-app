"""22.10, владелец: «Блокнот — вещь незаменимая. Можно, чтобы, как виджет Лиры, его можно было менять в размере? И менять
величину шрифта по умолчанию — кнопка с лупой или ползунок». Теперь:
- уголок внизу листа (дальний от виджета: лист слева — левый нижний) тянет размер: окно меняется на лету (Api.pad_resize),
  отпустили — размер в настройки (ui.pad_w / ui.pad_h, при масштабе 100 %), двойной щелчок — как было;
- «Aa» на панели — ползунок 80–170 %, A− / A+, щелчок по числу — 100 %; Ctrl+колёсико и Ctrl+= / Ctrl+− / Ctrl+0;
  размер — в настройки (ui.pad_text), заголовки и код растут вместе с текстом;
- ui/app.py: _pad_geom берёт свой размер (в пределах), pad_resize двигает лист так, что он остаётся прижат к виджету."""
import json, os, re, sys, types
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


# ---------- ui/app.py: геометрия листа со своим размером ----------
app = (ROOT / "ui/app.py").read_text(encoding="utf-8")
ns = {}
src = app[app.index("    def _pad_geom(self):"):app.index("    def pad_size(self):")]
consts = re.search(r"^PAD_W, PAD_MIN_H.*$", app, re.M).group(0) + "\n" + re.search(r"^PAD_W_MIN.*$", app, re.M).group(0) + "\n" + \
    re.search(r"^PAD_CLIP = .*$", app, re.M).group(0)
code = "import textwrap\nWIN = True\n" + consts + "\nclass winshell:\n    @staticmethod\n    def work_area(h=None):\n        return (0, 0, 1920, 1040) if h == 7 else (0, 0, 0, 0)\n" \
    "ZOOM = [1.0]\nSIZES = {'card': (340, 420)}\nclass A:\n" + src + "\n    def get_pos(self, m):\n        return (1500, 300)\n    def _hwnd(self, m):\n        return 7\n"
exec(code, ns)
a = ns["A"]()
a._pad_size = [None, None]
g0 = a._pad_geom()
ok(g0["w"] == 440 and g0["side"] == "left" and g0["x"] == 1500 - 14 - 440, f"как задумано — 440 px, слева от виджета: {g0}")
a._pad_size = [600, 700]
g1 = a._pad_geom()
ok(g1["w"] == 600 and g1["h"] == 700 and g1["x"] + g1["w"] + g1["gap"] == 1500, f"свой размер 600×700 — правый край по-прежнему у виджета: {g1}")
a._pad_size = [5000, 100]
g2 = a._pad_geom()
ok(g2["w"] == 1100 and g2["h"] == 300, f"в пределах: не шире 1100 и не ниже 300: {g2['w']}×{g2['h']}")
ok("def pad_resize" in app and "def pad_size" in app and '"pad_w"' in (ROOT / "core/settings.py").read_text(encoding="utf-8"),
   "Api.pad_resize / pad_size есть, ui.pad_w / pad_h / pad_text — в настройках")

# ---------- страница: уголок и размер текста ----------
from playwright.sync_api import sync_playwright  # noqa: E402
FAKE = """window.apiCalls = []; window.pywebview = { api: new Proxy({}, { get: (_, k) => (...a) => { apiCalls.push([k, ...a]);
  if (k === 'pad_size') return Promise.resolve([440, 520]);
  if (k === 'pad_resize') return Promise.resolve(a[0] ? [Math.round(a[0]), Math.round(a[1])] : [null, null]);
  return Promise.resolve(true); } }) };"""
CORE = r"""
(() => { window.calls = [];
  const ready = () => { if (!window.core) return setTimeout(ready, 5);
    core.retry = () => {}; core.connect = () => {}; if (core.ws) { core.ws.onclose = null; core.ws.onerror = null; try { core.ws.close(); } catch (e) {} }
    core.connected = true;
    core.call = async (c, a) => { calls.push([c, a]);
      if (c === "pad_tabs") return { tabs: [{ name: "Главное", mtime: 1 }], active: "Главное" };
      if (c === "pad_read") return { name: a.name, text: "# Заголовок\n\nТекст и `код`.\n", mtime: 1 };
      return {}; }; };
  ready(); })();
"""
with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    pg = b.new_page(viewport={"width": 454, "height": 560}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(FAKE); pg.add_init_script(CORE)
    pg.goto((ROOT / "ui/pad.html").as_uri() + "?skin=neusky&cfg=" + __import__("urllib.parse").parse.quote(json.dumps({"side": "left", "gap": 14, "clips": []})))
    pg.wait_for_timeout(1200)
    # уголок — слева внизу (лист слева от виджета)
    gb = pg.locator("#grip").bounding_box()
    ok(gb and gb["x"] < 30 and gb["y"] > 500, f"уголок — внизу слева, дальний от виджета: {gb}")
    pg.mouse.move(gb["x"] + 9, gb["y"] + 9); pg.mouse.down()
    pg.mouse.move(gb["x"] + 9 - 60, gb["y"] + 9 + 40, steps=6); pg.wait_for_timeout(150); pg.mouse.up(); pg.wait_for_timeout(400)
    calls = pg.evaluate("apiCalls")
    fin = [c for c in calls if c[0] == "pad_resize" and c[3] is True]
    ok(fin and fin[-1][1] == 500 and fin[-1][2] == 560, f"потянули влево-вниз на 60×40 — лист шире и выше: {fin[-1:] if fin else calls[-3:]}")
    saved = [c[1] for c in pg.evaluate("calls") if c[0] == "settings_save"]
    ok(any(s["patch"]["ui"].get("pad_w") == 500 and s["patch"]["ui"].get("pad_h") == 560 for s in saved), f"размер — в настройки: {saved[-1:]}")
    pg.dblclick("#grip"); pg.wait_for_timeout(300)
    ok(any(c[0] == "pad_resize" and c[1] == 0 for c in pg.evaluate("apiCalls")), "двойной щелчок по уголку — как было")
    # размер текста
    fs0 = pg.evaluate("parseFloat(getComputedStyle(document.querySelector('#ed')).fontSize)")
    h0 = pg.evaluate("parseFloat(getComputedStyle(document.querySelector('#ed h1')).fontSize)")
    pg.click("#b-size"); pg.wait_for_timeout(150)
    ok(pg.is_visible("#sz") and pg.inner_text("#sz-v") == "100 %", "«Aa» — открылся ползунок, сейчас 100 %")
    pg.click("#sz-p"); pg.click("#sz-p"); pg.wait_for_timeout(600)
    fs1 = pg.evaluate("parseFloat(getComputedStyle(document.querySelector('#ed')).fontSize)")
    h1 = pg.evaluate("parseFloat(getComputedStyle(document.querySelector('#ed h1')).fontSize)")
    ok(pg.inner_text("#sz-v") == "120 %" and abs(fs1 / fs0 - 1.2) < 0.02 and abs(h1 / h0 - 1.2) < 0.02, f"A+ дважды — 120 %: текст {fs0}→{fs1}, заголовок {h0}→{h1}")
    saved = [c[1] for c in pg.evaluate("calls") if c[0] == "settings_save"]
    ok(any(s["patch"]["ui"].get("pad_text") == 1.2 for s in saved), "размер текста — в настройки (ui.pad_text)")
    pg.mouse.click(200, 400); pg.wait_for_timeout(100)
    ok(not pg.is_visible("#sz"), "щелчок мимо — ползунок закрылся")
    pg.click("#ed"); pg.keyboard.press("Control+0"); pg.wait_for_timeout(100)
    ok(pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--pz').trim()") == "1", "Ctrl+0 — снова 100 %")
    pg.keyboard.press("Control+Equal"); pg.wait_for_timeout(100)
    ok(pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--pz').trim()") == "1.1", "Ctrl+= — крупнее")
    # пришло из настроек (другое окно поменяло) — применяется без записи обратно
    pg.wait_for_timeout(600)                                  # отложенная запись Ctrl+= ушла
    n = len([c for c in pg.evaluate("calls") if c[0] == "settings_save"])
    pg.evaluate("core.emit('settings', { settings: { ui: { pad_text: 1.5 } } })")
    pg.wait_for_timeout(700)
    ok(pg.inner_text("#sz-v") == "150 %" and len([c for c in pg.evaluate("calls") if c[0] == "settings_save"]) == n,
       "размер из настроек (сменили в другом окне) — применяется, без записи обратно")
    pg.screenshot(path="/tmp/claude-0/pad_size.png")
    ok(not errs, f"без ошибок на странице: {errs[:2]}")
    b.close()
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
