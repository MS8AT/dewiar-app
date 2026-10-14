"""Тестировщик на Windows, 14.10:
1. «Нажал „Обновить“ — программа не перезапустилась сама, пришлось запускать». Установщик запускает новую версию
   сам (NSIS LaunchApp), а на случай, если не вышло, — сторож PowerShell: ждёт конца установщика, 10 с, и если Dewiar
   из папки установки не запущен — запускает (пробелы, кириллица и апостроф в пути не мешают).
2. «Цветной кружок у выбора персонажа читается как „в сети / не в сети“». Вместо кружка — контурный силуэт героини
   (длинные волосы) или героя (короткая стрижка) в стиле остальных значков; лицо в 20 px было «пятном» (14.10)."""
import base64, json, os, socket, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
TESTS = Path(__file__).resolve().parent
PY = os.environ.get("DEWIAR_PY") or sys.executable
sys.path.insert(0, str(ROOT / "ui"))
import app as A  # noqa: E402
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ── 1. сторож обновления ──
inst = r"C:\Users\Миша О'Нил\AppData\Local\Programs\Dewiar"
sc = A.relaunch_script(4242, inst, inst + r"\python\pythonw.exe", inst + r"\app\ui\app.py")
ok("Wait-Process -Id 4242" in sc and "Start-Sleep -Seconds 10" in sc, "ждёт конца установщика и ещё 10 с")
ok("$dir = 'C:\\Users\\Миша О''Нил\\AppData\\Local\\Programs\\Dewiar\\'" in sc, "папка установки — в кавычках PowerShell, апостроф удвоен")
ok("if (-not $up) { Start-Process -FilePath 'C:\\Users\\Миша О''Нил\\AppData\\Local\\Programs\\Dewiar\\python\\pythonw.exe'" in sc
   and "'\"C:\\Users\\Миша О''Нил\\AppData\\Local\\Programs\\Dewiar\\app\\ui\\app.py\"'" in sc, "запускает, только если Dewiar так и не поднялся")
enc = base64.b64encode(sc.encode("utf-16-le")).decode()
ok(base64.b64decode(enc).decode("utf-16-le") == sc, "-EncodedCommand: скрипт без кавычек в командной строке")
src = (ROOT / "ui/app.py").read_text(encoding="utf-8")
ok("relaunch_after(inst.pid," in src and '"powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand"' in src,
   "«Обновить» на Windows — установщик и сторож")

# ── 2. лицо персонажа вместо кружка ──
tmp = Path(tempfile.mkdtemp()); (tmp / "cfg").mkdir()
PORT = free()
(tmp / "cfg/settings.json").write_text(json.dumps({"persona": "lira", "stt": {"engine": "vosk"}, "tts": {"engine": "off"}, "audio": {"sounds": False},
                                                    "ui": {"intro": "done", "welcome": "done", "news_seen": "99.0.0"}, "report": {"pulse": False}}))
env = dict(os.environ, DEWIAR_CONFIG_DIR=str(tmp / "cfg"), DEWIAR_STATE_DIR=str(tmp / "st"), DEWIAR_PORT=str(PORT), DEWIAR_ASSUME_AEC="1",
           DEWIAR_WORKSPACE_DIR=str(tmp / "ws"), DEWIAR_FAKE_RAM_GB="16", DEWIAR_FAKE_CORES="8")
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
        b = p.chromium.launch(); hw = b.new_page(viewport={"width": 300, "height": 420}, device_scale_factor=2)
        hw.on("pageerror", lambda x: errs.append(str(x)))
        hw.goto((ROOT / "ui/hud.html").as_uri() + f"?token={(tmp / 'cfg/token').read_text().strip()}&port={PORT}&mode=card"); hw.wait_for_timeout(2500)
        T = hw.evaluate("""() => { const d = document.getElementById('team-dot');
            return { g: d.dataset.g, svg: !!d.querySelector('svg circle'), bg: d.style.backgroundImage, who: current && current.name, glow: getComputedStyle(d).boxShadow }; }""")
        ok(T["who"] == "Лира" and T["g"] == "female" and T["svg"] and not T["bg"] and T["glow"] in ("none", ""),
           f"у кнопки персонажа — контурный силуэт героини (не цветной кружок, не крошечное фото): {T}")
        hw.click("#b-team"); hw.wait_for_timeout(400)
        M = hw.evaluate("""() => [...document.querySelectorAll('#team button')].map(b => [b.querySelector('b').textContent, b.querySelector('i').dataset.g])""")
        ok(["Лира", "female"] in M and ["Патрик", "male"] in M, f"в списке — силуэты по полу: {M}")
        hw.evaluate("() => paintAv(document.getElementById('team-dot'), { name: 'Нова' })")
        ok(hw.evaluate("() => document.getElementById('team-dot').dataset.g") == "none", "пол не указан — просто силуэт")
        hw.evaluate("() => paintAv(document.getElementById('team-dot'), current)")
        hw.screenshot(path=os.environ.get("TEAM_SHOT") or str(tmp / "team.png"))
        b.close()
finally:
    core.terminate()
ok(not errs, "без ошибок JavaScript" + (f": {errs}" if errs else ""))
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
