"""Заметки на компьютере легко найти (отзыв 11.10: «сложно найти, а они важны»): «Календарь» → «Заметки» — все заметки
папки ассистента (и пришедшие с телефона), новые сверху, поиск по словам в названии, тексте и папке (без регистра и «ё»),
подсветка найденного, правка на месте, «Новая заметка». Ядро — workspace.notes, студия — с подменённым ядром."""
import os, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
os.environ["DEWIAR_WORKSPACE"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "core"))
import workspace  # noqa: E402
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


w = workspace.Workspace(None); w.ensure()
w.save_note("Умный дом", "Настроенный умный дом с компьютера не синхронизируется с мобильным приложением")
time.sleep(0.05); w.save_note("Покупки", "молоко, хлеб, яблоки", folder="Дача")
time.sleep(0.05); w.save_note("Ёлка", "купить ёлку к Новому году")
ok([x["title"] for x in w.notes()] == ["Ёлка", "Покупки", "Умный дом"], "все заметки, новые сверху")
ok([x["title"] for x in w.notes("умный синхрон")] == ["Умный дом"] and [x["title"] for x in w.notes("елку")] == ["Ёлка"]
   and [x["title"] for x in w.notes("дача")] == ["Покупки"], "поиск: все слова, без регистра и «ё», и по папке")
ok(w.notes("умный")[0]["snippet"].startswith("Настроенный умный дом") and not w.notes("квантовая"), "в выдаче — кусок текста; ничего — пусто")
NOTES = w.notes()
with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    pg = b.new_page(viewport={"width": 1280, "height": 860}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script("window.pywebview = { api: new Proxy({}, { get: () => () => Promise.resolve(true) }) };")
    pg.goto((ROOT / "ui/settings.html").as_uri() + "?port=1"); pg.wait_for_timeout(1000)
    pg.evaluate("""(notes) => { window._calls = []; core.call = (c, a) => { _calls.push([c, a]);
        if (c === 'notes_list') { const q = (a.q || '').toLowerCase(); return Promise.resolve(notes.filter(n => !q || (n.title + ' ' + n.snippet).toLowerCase().includes(q))); }
        if (c === 'ws_read') return Promise.resolve({ path: a.path, text: '# Умный дом\\n\\nтекст заметки', mtime: Date.now() / 1000 });
        if (c === 'ws_write' || c === 'ws_new_note') return Promise.resolve({ path: 'Заметки/Новая заметка.md' });
        return Promise.resolve({}); };
      $('nav button[data-p="calendar"]').click(); }""", NOTES)
    pg.wait_for_timeout(300)
    pg.click('#cal-tabs button[data-ct="notes"]'); pg.wait_for_timeout(500)
    r = pg.evaluate("() => [[...document.querySelectorAll('#nt-list .nt-row b')].map(x => x.textContent), !!document.querySelector('#nt-text')]")
    ok(r[0] == ["Ёлка", "Покупки", "Умный дом"] and r[1], f"вкладка «Заметки»: список и первая открыта: {r}")
    pg.fill("#nt-q", "умный"); pg.wait_for_timeout(500)
    r = pg.evaluate("() => [[...document.querySelectorAll('#nt-list .nt-row b')].map(x => x.textContent), document.querySelectorAll('#nt-list mark').length]")
    ok(r[0] == ["Умный дом"] and r[1] >= 1, f"поиск на лету с подсветкой: {r}")
    pg.click("#nt-list .nt-row"); pg.wait_for_timeout(300); pg.fill("#nt-text", "# Умный дом\n\nновый текст"); pg.click("#nt-save"); pg.wait_for_timeout(300)
    ok(["ws_write", {"path": NOTES[2]["path"], "text": "# Умный дом\n\nновый текст"}] in pg.evaluate("_calls"), "правка заметки сохраняется на месте")
    pg.click("#nt-add"); pg.wait_for_timeout(400)
    ok(any(c[0] == "ws_new_note" for c in pg.evaluate("_calls")), "«Новая заметка»")
    b.close()
ok(not errs, f"без ошибок на странице: {errs[:3]}")
ok('cmd == "notes_list"' in (ROOT / "core/engine_commands.py").read_text(), "ядро: команда notes_list")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
