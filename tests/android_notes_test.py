"""Заметки на телефоне — надёжно (отзыв 11.10: «Записала», а заметки нет; фото к заметке не прикрепить):
«запиши в заметки …» записывается сразу, без модели; голое «Записала.» без save_note ловится; фото из чата с просьбой
записать — в заметке; заметка открывается: правка, фото, файл, удаление вместе с вложениями; «Новая заметка»; новые
сверху; синхронизация не теряет вложения."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


tmp = Path(tempfile.mkdtemp())
www = tmp / "www"
shutil.copytree(ROOT / "android/assets/www", www)
for f in ("entities.js", "skins.css", "skins.js", "privacy.js"):
    shutil.copy(ROOT / "ui/assets" / f, www / f)
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
png = tmp / "чек.png"
from PIL import Image  # noqa: E402
Image.new("RGB", (64, 48), (200, 80, 120)).save(png)
doc = tmp / "договор.pdf"; doc.write_bytes(b"%PDF-1.4 test")
PIX = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    pg = b.new_page(viewport={"width": 393, "height": 820}); pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
    pg.route("https://**", lambda r: r.abort())
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(900)
    r = pg.evaluate("""async () => { fileSave('notes.json', '[]'); await ask('Лира, запиши в заметки настроенный умный дом с компьютера не синхронизируется с телефоном');
      await new Promise(r => setTimeout(r, 200)); return [notes().map(x => [x.title, x.text]), document.querySelector('#bot').textContent]; }""")
    ok(len(r[0]) == 1 and r[0][0][1].startswith("Настроенный умный дом") and "Записала в заметки" in r[1], f"«запиши в заметки …» — сразу и без модели: {r}")
    r = pg.evaluate("() => [noteQuick('что у меня в заметках'), noteQuick('запиши расход 450'), noteQuick('заметка: позвонить Ольге в пять'), notes().length]")
    ok(r[0] == "" and r[1] == "" and "Позвонить Ольге" in r[2] and r[3] == 2, f"вопрос о заметках и расход — не заметка; «заметка: …» — заметка: {r}")
    r = pg.evaluate("""() => [!!claimedAction('Записала.', new Set(), 'запиши это в заметки'), !!claimedAction('Записала.', new Set(['save_note']), 'запиши в заметки'),
      !!claimedAction('Записала.', new Set(), 'запиши расход 450 на продукты')]""")
    ok(r == [True, False, False], f"«Записала.» без save_note после просьбы о заметке — ловится (и только тогда): {r}")
    # фото из чата с просьбой записать
    r = pg.evaluate(f"""async () => {{ await ask('Сохрани в заметки чек из магазина', {{ attach: [{{ kind: 'image', name: 'чек.jpg', url: '{PIX}' }}] }});
      await new Promise(r => setTimeout(r, 200)); const x = notes().find(n => /чек/i.test(n.title));
      return [x && (x.att || []).length, x && fileGet('natt-' + x.att[0].id).slice(0, 15), document.querySelector('#bot').textContent]; }}""")
    ok(r[0] == 1 and r[1] == "data:image/png;" and "вложением" in r[2], f"фото из чата с «сохрани в заметки» — в заметке: {r}")
    r = pg.evaluate(f"""async () => {{ turnAtt = [{{ kind: 'image', name: 'доска.jpg', url: '{PIX}' }}]; const t = await runTool('save_note', {{ title: 'Доска', text: 'схема' }});
      return [t, (notes().find(n => n.title === 'Доска').att || []).length]; }}""")
    ok("вложений: 1" in r[0] and r[1] == 1, f"модель записала заметку — фото этого хода с ней: {r}")
    # лист заметок: новые сверху, миниатюра, открыть и поправить
    pg.evaluate("() => { renderDay && openSheet('#sh-day'); dayTab = 'notes'; renderDay(); }"); pg.wait_for_timeout(200)
    r = pg.evaluate("() => [[...document.querySelectorAll('#day-body .it.note b')].map(b => b.textContent).slice(0, 2), !!document.querySelector('#day-body .nthumb')]")
    ok(r[0][0].startswith("Доска") and r[1], f"новые сверху, у заметки с фото — миниатюра: {r}")
    pg.click("#day-body .it.note"); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.querySelector('#sh-note').classList.contains('on') && !!document.querySelector('#note-body .ntimg img')"), "заметка открывается целиком, с фото")
    pg.set_input_files("#nt-file", str(doc)); pg.wait_for_timeout(400)
    pg.fill("#nt-text", "схема на доске — переделать"); pg.click("#nt-save"); pg.wait_for_timeout(200)
    r = pg.evaluate("() => { const x = notes().find(n => n.title === 'Доска'); return [x.text, x.att.map(a => [a.name, a.type])]; }")
    ok(r[0] == "схема на доске — переделать" and len(r[1]) == 2 and r[1][1][0] == "договор.pdf", f"правка текста и файл к заметке: {r}")
    # новая заметка с фото
    pg.evaluate("() => openNote('')"); pg.wait_for_timeout(300)
    pg.fill("#nt-title", "Ремонт"); pg.fill("#nt-text", "обои в спальню"); pg.set_input_files("#nt-photo", str(png)); pg.wait_for_timeout(500)
    ok(pg.evaluate("document.querySelector('#nt-title').value") == "Ремонт", "добавили фото — набранное не стёрлось")
    pg.click("#nt-save"); pg.wait_for_timeout(200)
    r = pg.evaluate("() => { const x = notes().find(n => n.title === 'Ремонт'); return x && [x.text, (x.att || []).length, fileGet('natt-' + x.att[0].id).slice(0, 11)]; }")
    ok(r == ["обои в спальню", 1, "data:image/"], f"«Новая заметка» с фото: {r}")
    # синхронизация с компьютера не теряет вложения; удаление убирает файлы
    r = pg.evaluate("""() => { const x = notes().find(n => n.title === 'Ремонт'); syncApply({ kind: 'note', id: x.id, data: { title: 'Ремонт', text: 'обои и краска' }, updated: Date.now() });
      const y = notes().find(n => n.id === x.id); const aid = y.att[0].id; noteDelete(y.id, false); return [y.text, y.att.length, notes().some(n => n.id === x.id), fileGet('natt-' + aid)]; }""")
    ok(r == ["обои и краска", 1, False, ""], f"правка с компьютера сохраняет вложения; удаление — вместе с файлами: {r}")
    b.close()
ok(not errs, f"без ошибок на странице: {errs[:3]}")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
