"""Служба голосов (server/voices/app.py, Qwen3-TTS) — без видеокарты, с поддельной моделью (TTS_FAKE=1):
— текст режется на фразы: первая короткая (раньше голос), длинное предложение — по запятой, ударения и разметка убираются;
— кто каким голосом говорит: персонаж (persona) сильнее псевдонима, псевдоним — своего голоса, OpenAI-имена и
  незнакомые — голос по умолчанию для пола, петли псевдонимов не вешают службу;
— /v1/audio/speech: pcm — поток 24 кГц, первая фраза отдельно, дальше пачкой; wav целиком — с честными длинами (телефон
  играет его MediaPlayer), wav потоком — с заголовком, sse — base64-кусками; скорость сокращает звук; манера на один ответ;
— клиент компьютера (RemoteTTS) говорит со службой напрямую и передаёт персонажа;
— свой голос по образцу: короткая запись — понятная ошибка, хорошая — голос в списке, образец слушается, персонаж говорит им;
— голос по описанию: проба с номером, большая модель сразу выгружается, проба сохраняется голосом;
— удалённый голос снимается с персонажей; ключ управления закрывает управление, но не озвучку;
— больше TTS_MAX_MODELS моделей одновременно не держится; два разговора сразу — оба договаривают."""
import http.client, io, json, os, shutil, sys, tempfile, threading, time, wave
from pathlib import Path
import numpy as np
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


tmp = Path(tempfile.mkdtemp())
os.environ.update(TTS_FAKE="1", TTS_DATA=str(tmp / "data"), TTS_MAX_MODELS="2", TTS_PRELOAD="custom")
sys.path.insert(0, str(ROOT / "server/voices"))
sys.path.insert(0, str(ROOT / "core"))
import app as A  # noqa: E402

# ── фразы ──
p = A.split_text("Привет! Сегодня у тебя три дела, и первое из них — позвонить маме, потому что она ждёт с утра. Потом спорт.")
ok(len(p) >= 3 and len(p[0][0]) <= 40 and p[0][0].startswith("Привет"), f"первая фраза короткая: {p[:2]}")
p = A.split_text("Длинное предложение без точки, " * 12)
ok(all(len(x) <= 220 for x, _ in p) and len(p) >= 2, f"длинное — по запятым, не длиннее 220: {[len(x) for x, _ in p]}")
ok(A.clean("**Дэвиа́р** — `код`") == "Дэвиар — код", f"ударение и разметка убраны: {A.clean('**Дэвиа́р** — `код`')!r}")
ok(A.lang_of("Привет") == "Russian" and A.lang_of("Hello") == "Auto" and A.lang_of("x", "en") == "English", "язык по тексту")

# ── кто каким голосом ──
A.cfg_save({"voices": {"anna": {"kind": "clone", "audio": "anna.wav", "text": "т", "gender": "female"}},
            "personas": {"lira": "anna"}, "aliases": {"serena": "vivian", "loop1": "loop2", "loop2": "loop1"},
            "default": {"female": "serena", "male": "ryan"}})
ok(A.resolve("serena", "lira")["id"] == "anna", "персонаж сильнее псевдонима: Лира говорит своим голосом")
ok(A.resolve("serena", "eva")["id"] == "vivian", "псевдоним: serena → vivian для остальных")
ok(A.resolve("aiden")["id"] == "aiden" and A.resolve("aiden")["kind"] == "speaker", "встроенный диктор")
ok(A.resolve("onyx")["id"] == "ryan" and A.resolve("nova")["id"] == "serena", "имена OpenAI — голос по умолчанию для пола")
ok(A.resolve("kto-to", gender="male")["id"] == "ryan", "незнакомый — по полу")
ok(A.resolve("loop1")["kind"] == "speaker", f"петля псевдонимов не вешает: {A.resolve('loop1')}")
A.cfg_save({})

srv = A.serve(0)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, body=None, headers=None, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    h = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data if raw else (json.loads(data or b"{}") if data[:1] in (b"{", b"[") else data)


def wav_of(sec, sr=16000):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        x = np.arange(int(sec * sr)) / sr
        w.writeframes((0.3 * np.sin(2 * np.pi * 180 * x) * 32767).astype("<i2").tobytes())
    return b.getvalue()


def multipart(fields, file):
    bnd = "----dw" + str(time.time_ns())
    out = b""
    for k, v in fields.items():
        out += f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="v.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + file + b"\r\n"
    out += f"--{bnd}--\r\n".encode()
    return out, {"Content-Type": "multipart/form-data; boundary=" + bnd}


try:
    st, _, h = req("GET", "/health")
    ok(st == 200 and h.get("ok") and h.get("fake"), f"/health: {st} {h.get('fake')}")

    TEXT = "Привет! Это проверка голоса. Вторая фраза. Третья фраза. Четвёртая фраза."
    A.ENGINE.calls.clear()
    st, hd, pcm = req("POST", "/v1/audio/speech", {"input": TEXT, "voice": "serena", "response_format": "pcm", "stream": True}, raw=True)
    ok(st == 200 and hd.get("content-type") == "audio/pcm" and hd.get("transfer-encoding") == "chunked" and hd.get("x-sample-rate") == "24000",
       f"pcm — поток 24 кГц: {st} {hd.get('content-type')} {hd.get('transfer-encoding')}")
    ok(len(pcm) % 2 == 0 and len(pcm) / 2 / 24000 > 2, f"звук пришёл целиком: {len(pcm) / 48000:.2f} с")
    ok([len(c["texts"]) for c in A.ENGINE.calls] == [1, 4] and A.ENGINE.calls[0]["voice"] == "serena" and A.ENGINE.calls[0]["lang"] == "Russian",
       f"первая фраза отдельно, остальные пачкой: {[c['texts'] for c in A.ENGINE.calls]}")

    st, hd, w = req("POST", "/v1/audio/speech", {"input": "Привет, я Лира.", "voice": "serena", "response_format": "wav", "speed": 1}, raw=True)
    with wave.open(io.BytesIO(w)) as wf:
        ok(st == 200 and wf.getframerate() == 24000 and wf.getnframes() * 2 + 44 == len(w), f"wav целиком — честные длины для телефона: {wf.getnframes()} кадров, {len(w)} байт")
        dur1 = wf.getnframes() / 24000
    ok(float(hd.get("x-audio-duration", 0)) > 0.5 and hd.get("x-voice") == "serena", f"длительность и голос в заголовках: {hd.get('x-audio-duration')} {hd.get('x-voice')}")
    st, hd, w2 = req("POST", "/v1/audio/speech", {"input": "Привет, я Лира.", "voice": "serena", "response_format": "wav", "speed": 1.5}, raw=True)
    with wave.open(io.BytesIO(w2)) as wf:
        dur2 = wf.getnframes() / 24000
    ok(dur2 < dur1 * 0.8, f"скорость 1.5 — короче: {dur1:.2f} → {dur2:.2f} с")
    st, hd, ws = req("POST", "/v1/audio/speech", {"input": "Раз. Два.", "voice": "aiden", "response_format": "wav", "stream": True}, raw=True)
    ok(st == 200 and ws[:4] == b"RIFF" and ws[36:40] == b"data" and len(ws) > 44, "wav потоком — с заголовком")
    st, hd, ev = req("POST", "/v1/audio/speech", {"input": "Раз. Два.", "voice": "aiden", "response_format": "pcm", "stream_format": "sse"}, raw=True)
    lines = [json.loads(x[5:]) for x in ev.decode().split("\n") if x.startswith("data:")]
    ok(hd.get("content-type") == "text/event-stream" and lines[-1]["type"] == "speech.audio.done" and lines[0].get("audio"), f"sse: {len(lines)} событий")
    A.ENGINE.calls.clear()
    req("POST", "/v1/audio/speech", {"input": "Ура!", "voice": "serena", "instruct": "радостно", "response_format": "wav"}, raw=True)
    ok(A.ENGINE.calls and A.ENGINE.calls[-1]["instruct"] == "радостно", f"манера на один ответ: {A.ENGINE.calls[-1:]}")
    st, _, e = req("POST", "/v1/audio/speech", {"input": "", "voice": "serena"})
    ok(st == 400 and "input" in e["error"]["message"], "пустой текст — 400 с объяснением")
    st, _, e = req("POST", "/v1/audio/speech", {"input": "а" * (A.MAX_CHARS + 1)})
    ok(st == 413, "слишком длинный — 413")

    # клиент компьютера — напрямую в службу
    from tts import RemoteTTS
    A.ENGINE.calls.clear()
    out = list(RemoteTTS({"base_url": f"http://127.0.0.1:{PORT}/v1"}).synth("Привет. Я Лира.", {"remote": "serena", "_gender": "female", "_pid": "lira"}, 1.0))
    ok(out and out[0][0] == 24000 and sum(len(b) for _, b in out) > 24000, f"RemoteTTS играет поток службы: {len(out)} кусков")

    # свой голос по образцу
    body, hh = multipart({"title": "Короткий", "text": "раз"}, wav_of(1.5))
    st, _, e = req("POST", "/v1/voices", body, hh)
    ok(st == 400 and "3 секунд" in e["error"]["message"], f"короткий образец — понятная ошибка: {e}")
    body, hh = multipart({"title": "Анна тёплая", "gender": "female", "text": "Привет, это мой голос для проверки."}, wav_of(6))
    st, _, e = req("POST", "/v1/voices", body, hh)
    ok(st == 200 and e["voice"]["id"] == "anna_teplaya" and e["voice"]["kind"] == "clone", f"образец принят, имя из названия: {e}")
    st, _, lst = req("GET", "/v1/audio/voices")
    ids = [v["id"] for v in lst["voices"]]
    ok("anna_teplaya" in ids and "serena" in ids and len([v for v in lst["voices"] if v["builtin"]]) == 9, f"в списке свой и 9 встроенных: {ids}")
    st, hd, smp = req("GET", "/v1/voices/anna_teplaya/sample", raw=True)
    ok(st == 200 and smp[:4] == b"RIFF", "образец слушается")
    st, _, e = req("POST", "/v1/voices/config", {"personas": {"Lira": "anna_teplaya"}})
    ok(st == 200 and e["personas"] == {"lira": "anna_teplaya"}, f"Лире — этот голос: {e.get('personas')}")
    st, _, e = req("POST", "/v1/voices/config", {"personas": {"lira": "net_takogo"}})
    ok(st == 400 and "net_takogo" in e["error"]["message"], "несуществующий голос персонажу не назначить")
    A.ENGINE.calls.clear()
    list(RemoteTTS({"base_url": f"http://127.0.0.1:{PORT}/v1"}).synth("Привет.", {"remote": "serena", "_gender": "female", "_pid": "lira"}, 1.0))
    ok(A.ENGINE.calls and A.ENGINE.calls[-1]["voice"] == "anna_teplaya" and A.ENGINE.calls[-1]["kind"] == "clone",
       f"компьютер передаёт персонажа — Лира говорит своим голосом: {A.ENGINE.calls[-1:]}")
    st, _, e = req("POST", "/v1/voices/update", {"id": "serena", "instruct": "мягко и тепло"})
    ok(st == 200 and A.resolve("serena")["instruct"] == "мягко и тепло", "встроенному можно задать манеру")

    # голос по описанию
    st, _, e = req("POST", "/v1/voices/design", {"instruct": "тихо"})
    ok(st == 400 and "подробнее" in e["error"]["message"], "слишком короткое описание — подсказка")
    A.ENGINE.calls.clear()
    st, hd, dw = req("POST", "/v1/voices/design", {"instruct": "Низкий мужской голос, лет сорок, спокойный, бархатный"}, raw=True)
    did = hd.get("x-draft-id", "")
    ok(st == 200 and dw[:4] == b"RIFF" and len(did) == 12 and A.ENGINE.calls[-1]["kind"] == "design" and len(A.ENGINE.calls[-1]["texts"]) == 1 and "рад " in A.ENGINE.calls[-1]["texts"][0],
       f"проба по описанию — одним проходом, мужская фраза: {st} {did} {A.ENGINE.calls[-1:]}")
    ok("design" not in A.STATE["loaded"], f"большая модель сразу выгружена: {A.STATE['loaded']}")
    st, hd, dd = req("GET", f"/v1/voices/drafts/{did}", raw=True)
    ok(st == 200 and dd == dw, "пробу можно переслушать")
    st, _, e = req("POST", "/v1/voices", {"draft": did, "title": "Бархат"})
    ok(st == 200 and e["voice"]["id"] == "barhat" and e["voice"]["designed"].startswith("Низкий") and e["voice"]["gender"] == "male",
       f"проба сохранена голосом: {e}")
    st, _, e = req("POST", "/v1/voices", {"draft": "0" * 12, "title": "x"})
    ok(st == 400 and "устарела" in e["error"]["message"], "чужая или старая проба — понятная ошибка")

    # удаление
    st, _, e = req("POST", "/v1/voices/delete", {"id": "anna_teplaya"})
    ok(st == 200 and A.cfg_load()["personas"] == {} and not (tmp / "data/voices/anna_teplaya.wav").exists(), "удалённый голос снят с Лиры, файл убран")
    st, _, e = req("POST", "/v1/voices/delete", {"id": "net"})
    ok(st == 404, "удалить несуществующий — 404")

    # ключ управления
    A.ADMIN_KEY = "adm"
    st, _, _ = req("POST", "/v1/voices/config", {"personas": {}})
    st2, _, _ = req("POST", "/v1/voices/config", {"personas": {}}, {"Authorization": "Bearer adm"})
    st3, _, _ = req("POST", "/v1/audio/speech", {"input": "Да.", "response_format": "wav"}, raw=True)
    ok(st == 401 and st2 == 200 and st3 == 200, f"ключ управления: без него {st}, с ним {st2}, озвучка {st3}")
    A.ADMIN_KEY = ""

    # модели в памяти и два разговора сразу
    ok(len(A.STATE["loaded"]) <= 2, f"не больше двух моделей: {A.STATE['loaded']}")
    A.ENGINE.delay = 0.05
    res = []

    def talk(v):
        res.append(req("POST", "/v1/audio/speech", {"input": "Раз. Два. Три. Четыре. Пять.", "voice": v, "response_format": "pcm"}, raw=True)[0])
    th = [threading.Thread(target=talk, args=(v,)) for v in ("serena", "barhat")]
    [t.start() for t in th]; [t.join(20) for t in th]
    ok(res == [200, 200], f"два разговора сразу — оба договорили: {res}")
    st, _, h = req("GET", "/health")
    ok(h["requests"] >= 8 and h["chars"] > 50 and h["audio_sec"] > 1 and h["ttfa_ms_avg"] >= 0 and h["waiting"] == 0, f"счётчики: {h['requests']} {h['chars']} {h['audio_sec']:.1f}")

    js = (ROOT / "android/assets/www/app.js").read_text(encoding="utf-8")
    ok('persona: persona().id || ""' in js, "телефон тоже передаёт персонажа в «Голос Dewiar»")
    # файлы для сервера на месте
    V = ROOT / "server/voices"
    ok((V / "Dockerfile").is_file() and "qwen-tts" in (V / "Dockerfile").read_text(encoding="utf-8"), "Dockerfile ставит qwen-tts")
    dc = (V / "docker-compose.dewiar-tts.yml").read_text(encoding="utf-8")
    ok("container_name: dewiar-tts" in dc and "tts:" in dc and "/data" in dc, "compose: служба tts с папкой голосов")
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
