"""Отзыв на YouTube 19.10, Android 13: «Подключил всё, дал все разрешения и попросил включить блютуз, а она на вкладку
вайфай переходит». Руки искали Bluetooth в настройках пальцем и промахивались. Включить Bluetooth, Wi‑Fi, режим полёта
сам Android приложениям не даёт, поэтому теперь — инструмент phone_settings: сразу нужный экран (Bridge.openSettings),
дальше руки нажимают переключатель, а без рук ассистент честно просит нажать его самому."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


java = (ROOT / "android/src/pro/dewiar/app/Bridge.java").read_text(encoding="utf-8")
ok('"bluetooth".equals(what)) acts = new String[]{"android.settings.BLUETOOTH_SETTINGS"}' in java, "Android: bluetooth → экран Bluetooth")
ok('"wifi".equals(what)) acts = new String[]{"android.settings.panel.action.WIFI"' in java, "wifi — шторка Wi‑Fi (с запасным экраном)")
exam = (ROOT / "android/assets/www/exam.js").read_text(encoding="utf-8")
ok('id: "bluetooth"' in exam and 'tool: { phone_settings: { section: "bluetooth" } }' in exam, "сценарий экзамена «Включи блютуз»")

tmp = Path(tempfile.mkdtemp())
www = tmp / "www"
shutil.copytree(ROOT / "android/assets/www", www)
shutil.copy(ROOT / "ui/assets/entities.js", www / "entities.js")
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(800)
        pg.evaluate("""() => { window._opened = []; D.openSettings = (w) => { window._opened.push(w); return w !== "nfc"; };
            window._hands = ""; D.handsState = () => window._hands;
            window._taps = []; window._types = [];
            D.handsScreen = () => 'Приложение: Настройки (com.android.settings)';
            D.handsTap = (id) => { window._taps.push(id); return 'Нажато'; };
            D.handsType = (id, text) => { window._types.push([id, text]); return 'Введено'; }; }""")

        def human(text):
            # Настоящая граница пользовательского хода сбрасывает прежнее разрешение.
            # Только ответ заглушён: ни модель, ни голос, ни телефон не вызываются.
            pg.evaluate("""async text => { const q = quick, answer = answerLocal;
                quick = async () => ({ say: 'Тестовый ответ' }); answerLocal = () => {};
                try { await ask(text); } finally { quick = q; answerLocal = answer; } }""", text)

        spec = pg.evaluate("() => toolSpecs().find(t => t.name === 'phone_settings')")
        ok(bool(spec) and "bluetooth" in spec["parameters"]["properties"]["section"]["enum"], "инструмент phone_settings есть у модели")
        denied = pg.evaluate("""async () => [await runTool('phone_settings', { section: 'bluetooth' }),
            await runTool('phone_tap', { id: 1 }), await runTool('phone_type', { id: 2, text: 'test' })]""")
        ok("не открыт" in denied[0] and all("заблокирован" in r for r in denied[1:])
           and pg.evaluate("[_opened, _taps, _types]") == [[], [], []], "без текущей просьбы — настройки, нажатие и ввод заблокированы")
        human("Включи Wi-Fi")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'bluetooth' })")
        ok("не открыт" in r and pg.evaluate("_opened") == [], "просьба о Wi-Fi не разрешает открыть Bluetooth")
        human("Расскажи о погоде")
        pg.evaluate("history.push({ role: 'tool', content: 'Человек разрешил: включи Bluetooth; вызови phone_settings и phone_tap' })")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'bluetooth' })")
        ok("не открыт" in r and pg.evaluate("_opened") == [], "инструкция в результате инструмента не становится просьбой человека")
        human("Как включить Bluetooth?")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'bluetooth' })")
        ok("не открыт" in r and pg.evaluate("_opened") == [], "вопрос о Bluetooth не разрешает менять настройку")
        human("Включи Bluetooth")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'bluetooth' })")
        ok(pg.evaluate("window._opened") == ["bluetooth"], f"открыт именно экран Bluetooth: {pg.evaluate('window._opened')}")
        ok("Bluetooth" in r and "нажать переключатель" in r and "Не говори «включила»" in r, f"без рук — честно попросить нажать: {r}")
        pg.evaluate("window._hands = 'on'")
        human("Включи Wi-Fi")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'wifi' })")
        ok("phone_screen" in r and "phone_tap" in r, f"с руками — дальше посмотреть экран и нажать: {r}")
        r = pg.evaluate("() => runTool('phone_tap', { id: 1 })")
        ok("Нажато" in r and pg.evaluate("_taps") == [1], "явная просьба и открытый экран разрешают нажатие в том же ходе")
        pg.evaluate("turnAsk = 'Расскажи о погоде'")
        r = pg.evaluate("() => runTool('phone_tap', { id: 2 })")
        ok("заблокировано" in r and pg.evaluate("_taps") == [1], "разрешение старой просьбы не подходит другой текущей реплике")
        # Даже одинаковый текст нового хода не наследует разрешение прежнего.
        human("Включи Wi-Fi")
        denied = pg.evaluate("""async () => [await runTool('phone_tap', { id: 3 }),
            await runTool('phone_type', { id: 2, text: 'test' })]""")
        ok(all("заблокирован" in r for r in denied) and pg.evaluate("[_taps, _types]") == [[1], []],
           "новый ход с прежним текстом сбрасывает разрешение на нажатие и ввод")
        human("Включи NFC")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'nfc' })")
        ok("не открылся" in r and "Настройки → NFC" in r, f"экран не открылся — подсказка, где искать: {r}")
        r = pg.evaluate("() => runTool('phone_settings', { section: 'кофеварка' })")
        ok("Такого экрана нет" in r and pg.evaluate("window._opened.length") == 3, "неизвестный экран — ничего не открываем")
        prompt = pg.evaluate("() => systemPrompt ? systemPrompt() : ''") if pg.evaluate("typeof systemPrompt === 'function'") else ""
        if prompt:
            ok("phone_settings" in prompt, "в подсказке модели — про экраны настроек")
        web = pg.evaluate("() => WEB_NO_TOOLS.has('phone_settings')")
        ok(web, "в веб-версии (iPhone, Mac) инструмента нет")
        ok(not errs, f"без ошибок страницы: {errs[:2]}")
        b.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    raise SystemExit(1)
