"""Звук выключен — голос не синтезируем (идея 15.10: «если звук на телефоне или компе выключен, сервер синтеза всё равно
работает — сэкономить»): кнопка «без голоса» так и работала; теперь и звук на нуле.
— телефон: громкость музыки 0 — ответ только на экране, синтез (и «Голос Dewiar») не вызывается, подсказка один раз;
  прибавили — снова голос;
— компьютер (Linux): звук выключен или на нуле (pactl) — фразы не синтезируются, проверка раз в 5 с."""
import os, shutil, subprocess, sys, tempfile, types
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


import engine_remote as ER  # noqa: E402
calls = []
answers = {"mute": "Mute: no", "vol": "Volume: front-left: 0 /   0% / -inf dB,   front-right: 0 /   0% / -inf dB"}


def fake_run(cmd, **k):
    calls.append(cmd[1])
    return types.SimpleNamespace(stdout=answers["mute" if cmd[1] == "get-sink-mute" else "vol"], returncode=0)


orig_run, orig_which = subprocess.run, shutil.which
subprocess.run, shutil.which = fake_run, (lambda n: "/usr/bin/pactl" if n == "pactl" else orig_which(n))
os.environ.pop("DEWIAR_FAKE_OUTPUT_MUTED", None)
try:
    f = types.SimpleNamespace(server=False)
    m1 = ER.RemoteMixin._output_muted(f)
    n1 = len(calls)
    m2 = ER.RemoteMixin._output_muted(f)
    ok(sys.platform.startswith("linux") and m1 is True and m2 is True and len(calls) == n1, f"громкость 0 % — «выключен»; второй раз — из памяти (5 с): {calls}")
    f2 = types.SimpleNamespace(server=False); answers.update(mute="Mute: yes")
    ok(ER.RemoteMixin._output_muted(f2) is True, "звук выключен (Mute: yes) — «выключен»")
    f3 = types.SimpleNamespace(server=False); answers.update(mute="Mute: no", vol="Volume: front-left: 40000 /  61% / -12 dB")
    ok(ER.RemoteMixin._output_muted(f3) is False, "звук есть — говорим")
    f4 = types.SimpleNamespace(server=True)
    ok(ER.RemoteMixin._output_muted(f4) is False, "сервер без звука (Telegram) — не проверяем")
finally:
    subprocess.run, shutil.which = orig_run, orig_which
src = (ROOT / "core/engine_remote.py").read_text(encoding="utf-8")
ok("if self._output_muted():" in src and "return self._drain_worker(turn, sentences)" in src, "озвучка на компьютере сверяется со звуком")

tmp = Path(tempfile.mkdtemp()); www = tmp / "www"
shutil.copytree(ROOT / "android/assets/www", www)
for x in ("entities.js", "rich.js", "skins.js", "skins.css"):
    if (ROOT / "ui/assets" / x).exists():
        shutil.copy(ROOT / "ui/assets" / x, www / x)
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 400, "height": 820})
    pg.on("pageerror", lambda x: errs.append(str(x)))
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(1000)
    R = pg.evaluate("""() => { D.mock = false; let vol = 0; D.volume = () => vol; S.textMode = false;
        const n0 = sayN; say('Привет, это проверка.'); say('И ещё одна фраза.'); const n1 = sayN;
        const t = document.getElementById('toast') ? document.getElementById('toast').textContent : '';
        vol = 50; say('Теперь со звуком.'); const n2 = sayN; stopVoice && stopVoice(); D.mock = true; return [n1 - n0, n2 - n1, t]; }""")
    ok(R[0] == 0, f"громкость 0 — голос не синтезируется (ни одной фразы): {R[0]}")
    ok("на нуле" in R[2] and "текстом" in R[2], f"подсказка: {R[2]!r}")
    ok(R[1] == 1, f"прибавили громкость — снова голос: {R[1]}")
    b.close()
ok(not errs, "без ошибок JavaScript" + (f": {errs}" if errs else ""))
shutil.rmtree(tmp, ignore_errors=True)
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
