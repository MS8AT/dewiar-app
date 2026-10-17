"""Виджет компьютера (отзыв 17.10):
- «шарик мелкий, часто не понятно, слушает она или нет… может этот кружочек вообще убрать?» — значка-шарика больше нет:
  окно одно (карточка), кнопки «свернуть в значок» нет, сохранённый режим «mini» открывается карточкой;
- подсказка у портрета («Удерживайте (или пробел) — диктовка любой длины…») вылезала за края виджета и обрезалась —
  подсказки теперь свои, внутри карточки, переносятся по словам."""
import os, re, sys
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


app = (ROOT / "ui/app.py").read_text(encoding="utf-8")
hud = (ROOT / "ui/hud.html").read_text(encoding="utf-8")
ok('BASE_SIZES = {"card": (300, 420)}' in app and app.count('for m in ("card",):') == 2 and 'uis.get("hud_mode") == "mini"' not in app,
   "одно окно виджета — карточка; сохранённый «mini» тоже открывается карточкой (Linux и Windows)")
ok('id="b-mini"' not in hud and "setMode(\"mini\")" not in hud, "в карточке нет кнопки «свернуть в значок»")

from playwright.sync_api import sync_playwright  # noqa: E402
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 300, "height": 420})
    pg.goto((ROOT / "ui/hud.html").as_uri()); pg.wait_for_timeout(800)
    pg.evaluate("() => { document.body.classList.remove('mini'); }")
    pg.hover("#orb"); pg.wait_for_timeout(900)
    r = pg.evaluate("""() => { const t = document.getElementById('htip'), b = t.getBoundingClientRect(), o = document.getElementById('orb');
        return { on: t.classList.contains('on'), text: t.textContent, l: b.left, r: b.right, top: b.top, bot: b.bottom, title: o.getAttribute('title') }; }""")
    ok(r["on"] and "диктовка любой длины" in r["text"] and r["l"] >= 0 and r["r"] <= 300 and r["top"] >= 0 and r["bot"] <= 420 and r["title"] is None,
       f"подсказка у портрета — внутри карточки, по словам, без системной: {r}")
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)
    ok(not pg.evaluate("document.getElementById('htip').classList.contains('on')"), "увели мышь — подсказка ушла")
    b.close()
print("\nИТОГ:", "всё прошло" if not fails else f"не прошло {len(fails)}")
sys.exit(1 if fails else 0)
