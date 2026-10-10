"""Нехватка памяти прямо сейчас: компьютер мощный, но память заняли другие программы (браузер, Java, базы) — система
уходит в подкачку, окна открываются чёрными, голос запаздывает. Dewiar замечает это сам (две проверки подряд), один раз
объясняет, кто занимает память и что сделать, и показывает это в студии. Без настоящей нехватки: замер подменяется."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


import device as D  # noqa: E402

ok(D._judge(10, 0.4, 92, None)["tight"], "свободно 0,4 ГБ из 10 и подкачка полна — тесно")
ok(D._judge(10, 0.4, None, None)["tight"], "свободно 0,4 ГБ, подкачки нет — тесно")
ok(not D._judge(10, 0.4, 20, None)["tight"], "свободно мало, но подкачка почти пуста — ещё не тесно")
ok(not D._judge(16, 6.0, 80, None)["tight"], "памяти много — не тесно, даже если подкачка занята")
ok(D._judge(16, 6.0, None, 25.0)["tight"], "программы ждут память (PSI 25 %) — тесно")
ok(not D._judge(0, 0, None, None)["tight"], "не узнать — не тревожим")
os.environ["DEWIAR_FAKE_PRESSURE"] = "0.4,10,92"
p = D.pressure()
ok(p["tight"] and p["free"] == 0.4 and p["swap"] == 92, f"замер: {p}")
t = D.pressure_text(p, [("Chrome", 2.1), ("Java", 1.8), ("Milvus", 1.2)])
ok("Свободно 0,4 ГБ памяти из 10" in t and "подкачка заполнена на 92%" in t and "Chrome (2,1 ГБ), Java (1,8 ГБ), Milvus (1,2 ГБ)" in t
   and "лёгкий режим" in t, f"совет: {t}")
ok("лёгкий режим" not in D.pressure_text(p, [], light=True), "лёгкий режим уже включён — его не советуем")
del os.environ["DEWIAR_FAKE_PRESSURE"]
real = D.pressure()
ok(real["total"] > 0 and "tight" in real, f"настоящий замер этого компьютера: {real}")

# кто занимает: сам Dewiar называется по имени, мелочь не показывается
hog = subprocess.Popen([sys.executable, "-c", "import time; x = bytearray(450 * 2**20); x[::4096] = b'1' * len(x[::4096]); time.sleep(20)",
                        "dewiar-memory-test"])
time.sleep(2.5)
top = D.top_memory(8)
hog.kill()
ok(any(k == "Dewiar" and v >= 0.4 for k, v in top), f"процесс Dewiar назван по имени: {top}")
ok(all(v >= 0.3 for _, v in top), "мелкие программы (меньше 0,3 ГБ) не перечисляются")
ok(D._nice("chrome.exe") == "Chrome" and D._nice("java") == "Java" and D._nice("Isolated Web Co") == "Firefox", "понятные названия программ")

# в ядре: две проверки подряд — одно уведомление; выключено — молчит
import engine as E  # noqa: E402


class S:
    def __init__(self, warn=True):
        self.warn = warn

    def get(self, sec, key=None):
        return self.warn if (sec, key) == ("device", "mem_warn") else None


def run(warn=True, fake="0.4,10,92", seconds=1.2):
    os.environ.update(DEWIAR_FAKE_PRESSURE=fake, DEWIAR_MEM_WAIT="0.05", DEWIAR_MEM_EVERY="0.1")
    eng = E.Engine.__new__(E.Engine)
    eng.s = S(warn)
    eng.stopping = threading.Event()
    eng.pushed = []
    eng._push_quiet = lambda title, text: eng.pushed.append((title, text))
    eng.device_status = lambda: {"light": False, "advice": ""}
    th = threading.Thread(target=eng._memory_watch, daemon=True)
    th.start()
    time.sleep(seconds)
    eng.stopping.set()
    th.join(2)
    return eng


e = run()
ok(len(e.pushed) == 1 and e.pushed[0][0] == "Компьютеру не хватает памяти" and "Свободно 0,4 ГБ" in e.pushed[0][1],
   f"тесно — одно уведомление, не каждую минуту: {len(e.pushed)}")
ok(e.mem["tight"] and e.mem["streak"] >= 2 and e.mem.get("text"), "состояние для студии")
ok(not run(warn=False).pushed, "предупреждение выключено — молчит")
ok(not run(fake="6,16,10").pushed, "памяти хватает — молчит")
for k in ("DEWIAR_FAKE_PRESSURE", "DEWIAR_MEM_WAIT", "DEWIAR_MEM_EVERY"):
    os.environ.pop(k, None)

print("\nИТОГ:", "всё хорошо" if not fails else f"ошибок {len(fails)}")
sys.exit(1 if fails else 0)
