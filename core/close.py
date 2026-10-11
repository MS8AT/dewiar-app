"""«Близкие»: переписка между помощниками разных людей через облако Dewiar — со сквозным шифрованием.

«Лира, напиши Андрею, что я задержусь» — у Андрея его помощник покажет сообщение и скажет вслух: «Сообщение от Михаила…».
Близкими становятся по приглашению: ссылка (…/download.php?close=ТОКЕН) или QR с ней; принять — accept(ссылка).
Устройство хранит свою пару ключей X25519 (закрытый — зашифрован ключом этого компьютера, crypt.device_key) и шлёт
серверу только открытый (/close/hello). Сообщение шифруется для всех устройств получателя и для других своих
(closecrypto.encrypt_for); сервер (server/dwrapp/cloud.php, close_handler) видит лишь, кому и когда.
Входящие забирает фоновый поток (loop): раз в 20 с, если есть близкие или висит приглашение, иначе — раз в 10 минут.
Файлы — до 10 МБ, шифруются отдельным ключом и сами сохраняются в папку ассистента «Близкие/<имя>».
Телефон делает то же самое в app.js (раздел «Близкие») — формат общий."""

import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

import closecrypto as CC
from settings import CONFIG_DIR, STATE_DIR

log = logging.getLogger("dewiar.close")
HIST_MAX = 300
FILE_MAX = 10 * 1024 * 1024


class CloseError(Exception):
    """Ошибка с понятным человеку текстом."""


def token_of(link):
    """Ссылка-приглашение в любом виде (…download.php?close=…, dewiar://close?t=…, сам токен) -> токен."""
    s = (link or "").strip()
    if "://" in s or "?" in s:
        q = parse_qs(urlparse(s).query)
        s = (q.get("close") or q.get("t") or [""])[0]
    s = re.sub(r"[^A-Za-z0-9_-]", "", s)
    return s if 8 <= len(s) <= 64 else ""


def _stem(w):
    w = re.sub(r"[^а-яёa-z]", "", (w or "").lower().replace("ё", "е"))
    return w


def match_name(name, people):
    """«Андрею», «маме», «Свете» -> человек из близких (по общему началу имени), иначе None (или несколько — тоже None)."""
    q = _stem(name)
    if not q:
        return None
    best, score, tie = None, 0, False
    for p in people:
        for word in [p.get("name", "")] + p.get("name", "").split():
            n = _stem(word)
            if not n:
                continue
            k = 0
            while k < min(len(n), len(q)) and n[k] == q[k]:
                k += 1
            need = min(len(n), 3) if len(n) <= 4 else max(3, len(n) - 2)
            if k >= need or n == q:
                s = k + (10 if n == q else 0)
                if s > score:
                    best, score, tie = p, s, False
                elif s == score and best is not p:
                    tie = True
    return None if tie else best


COLORS = ["#9BD4FF", "#FFB547", "#3DF5C8", "#FF7AB6", "#B78CFF", "#9BE15D", "#7C8CFF", "#FF6B5A"]


def _color_of(pid):
    """Цвет кружка близкого — как в студии и на телефоне (по сумме кодов символов pid)."""
    return COLORS[sum(ord(ch) for ch in str(pid)) % len(COLORS)]


class Close:
    def __init__(self, host, state_path=None, key_path=None):
        """host: credentials() -> (token, link, url), emit(event, **kw), s (настройки), announce(text), push(title, text),
        workspace (root), device_name()."""
        self.host = host
        self.path = Path(state_path or STATE_DIR / "close.json")
        self.key_path = Path(key_path or CONFIG_DIR / "close.key")
        self._lock = threading.RLock()
        self.soon = threading.Event()
        self.error = ""
        self.st = self._load()
        self._priv = None
        self.calls = {}                 # id звонка → {role, pid, name, video, offer, token, at, fast}

    # ---------- состояние ----------
    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("dev", "pc-" + uuid.uuid4().hex[:10])
        d.setdefault("cursor", 0)
        d.setdefault("people", [])
        d.setdefault("me", {})
        d.setdefault("hist", {})
        d.setdefault("unread", {})
        d.setdefault("seen_mid", [])
        return d

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.st, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.exception("близкие: сохранить")

    def _keys(self):
        """Своя пара ключей: закрытый — в состоянии, зашифрованный ключом этого компьютера."""
        if self._priv:
            return self._priv, self.st["pub"]
        from crypt import CryptError, device_key, seal, unseal
        dk = device_key(self.key_path)
        if self.st.get("priv"):
            try:
                self._priv = unseal(CC.b64d(self.st["priv"]), dk)
                return self._priv, self.st["pub"]
            except (CryptError, ValueError):
                log.warning("близкие: ключ устройства не открылся — создаю новый")
        priv, pub = CC.keypair()
        self.st.update(priv=CC.b64e(seal(priv, dk)), pub=CC.b64e(pub))
        self._priv = priv
        self._save()
        return priv, self.st["pub"]

    # ---------- сеть ----------
    def _req(self, method, path, body=None, raw=None, params=None, timeout=20):
        token, link, url = self.host.credentials()
        if not token:
            raise CloseError("«Близкие» работают через Dewiar: войдите аккаунтом dewiar.pro или подключите ключ Dewiar.")
        h = {"Authorization": "Bearer " + token}
        params = dict(params or {}, p=path)              # httpx заменяет запрос в адресе целиком — p кладём сюда же
        if link and link != token:
            h["X-Sync-Link"] = link
        try:
            if raw is not None:
                h["Content-Type"] = "application/octet-stream"
                r = httpx.post(url, content=raw, headers=h, params=params, timeout=120)
            elif method == "GET":
                r = httpx.get(url, headers=h, params=params, timeout=timeout)
            else:
                r = httpx.post(url, json=body or {}, headers=h, params=params, timeout=timeout)
        except httpx.HTTPError as e:
            raise CloseError("нет связи с Dewiar — проверьте интернет") from e
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = f"облако ответило {r.status_code}"
            raise CloseError(msg)
        return r

    def _people(self, d):
        with self._lock:
            self.st["me"] = d.get("me") or {}
            self.st["people"] = d.get("people") or []
            self._save()
        self.host.emit("close", state=self.state())

    def hello(self):
        """Представиться серверу: открытый ключ этого устройства и имя для близких. -> состояние."""
        _, pub = self._keys()
        name = (self.host.s.get("close", "name") or self.host.s.get("user_name") or "").strip()
        d = self._req("POST", "/close/hello", {"dev": self.st["dev"], "pub": pub, "devname": self.host.device_name(), "name": name}).json()
        self.st["hello_at"] = time.time()
        self._people(d)
        return self.state()

    def state(self):
        with self._lock:
            people = [dict(p, unread=int(self.st["unread"].get(p["pid"], 0)),
                           last=(self.st["hist"].get(p["pid"]) or [{}])[-1]) for p in self.st["people"]]
            return {"me": self.st.get("me") or {}, "people": people, "error": self.error, "invite": self.st.get("invite") or None,
                    "ready": bool(self.st.get("pub"))}

    def history(self, pid, mark_read=True):
        with self._lock:
            if mark_read and self.st["unread"].pop(pid, None):
                self._save()
                self.host.emit("close", state=self.state())
            return list(self.st["hist"].get(pid) or [])

    def set_name(self, name):
        self.host.s.update({"close": {"name": (name or "").strip()[:40]}})
        return self.hello()

    def invite(self, renew=False):
        d = self._req("POST", "/close/invite", {"renew": bool(renew)}).json()
        self.st["invite"] = {"link": d["link"], "app": d.get("app", ""), "expires": d.get("expires", 0)}
        self._save()
        self.soon.set()
        return self.st["invite"]

    def peek(self, link):
        t = token_of(link)
        if not t:
            raise CloseError("Это не ссылка-приглашение в «Близкие».")
        return self._req("GET", "/close/peek", params={"t": t}).json()

    def accept(self, link):
        t = token_of(link)
        if not t:
            raise CloseError("Это не ссылка-приглашение в «Близкие».")
        self._keys()
        if not self.st["me"]:
            self.hello()
        d = self._req("POST", "/close/accept", {"t": t}).json()
        self._people(d)
        self.soon.set()
        return d.get("person") or {}

    def remove(self, pid):
        self._people(self._req("POST", "/close/remove", {"pid": pid}).json())
        return self.state()

    def person(self, who):
        """pid или имя («Андрею», «маме») -> запись человека; нет — CloseError с подсказкой."""
        with self._lock:
            people = list(self.st["people"])
        p = next((x for x in people if x["pid"] == who), None) or match_name(who, people)
        if not p:
            names = ", ".join(x["name"] for x in people) or "пока никого"
            raise CloseError(f"Не нашла «{who}» среди близких (сейчас: {names}). Добавить — студия → «Близкие» → «Пригласить».")
        return p

    # ---------- отправка ----------
    def _targets(self, p):
        devs = {d["dev"]: CC.b64d(d["pub"]) for d in p.get("devs") or [] if d.get("pub")}
        devs.update({d["dev"]: CC.b64d(d["pub"]) for d in (self.st.get("me") or {}).get("devs") or [] if d.get("pub")})
        devs[self.st["dev"]] = CC.b64d(self._keys()[1])
        return devs

    def send(self, who, text="", files=None, kind="msg", payload=None):
        """Сообщение близкому (text и/или файлы — список путей). -> запись истории."""
        p = self.person(who)
        priv, _ = self._keys()
        if not self.st.get("me") or time.time() - float(self.st.get("hello_at") or 0) > 600:
            self.hello()
            p = self.person(p["pid"])
        if not p.get("devs"):
            raise CloseError(f"У {p['name']} Dewiar ещё не открывался после приглашения — сообщение дойдёт, когда откроет.")
        fl = []
        for path in files or []:
            fl.append(self._upload(p, Path(path)))
        body = dict(payload or {}, t=(text or "").strip(), ts=int(time.time() * 1000), mid=uuid.uuid4().hex[:16],
                    name=(self.st.get("me") or {}).get("name", ""))
        if fl:
            body["f"] = fl
        if kind == "msg" and not body["t"] and not fl:
            raise CloseError("пустое сообщение")
        env = CC.encrypt_for(body, priv, self.st["dev"], self._targets(p))
        d = self._req("POST", "/close/send", {"to": p["pid"], "env": env, "kind": kind}).json()
        if kind != "msg":
            return d
        item = {"mid": body["mid"], "ts": body["ts"], "out": True, "t": body["t"], "f": [dict(x, path=str(Path(f).resolve())) for x, f in zip(fl, files or [])]}
        self._add(p["pid"], item)
        log.info("💌 Близким: %s ← %s", p["name"], (body["t"] or "файл")[:60])
        return item

    def _upload(self, p, path):
        data = path.read_bytes()
        if len(data) > FILE_MAX:
            raise CloseError(f"«{path.name}» больше 10 МБ — такие пока не отправить.")
        fk = os.urandom(32)
        d = self._req("POST", "/close/file", raw=CC.seal(fk, data), params={"to": p["pid"]}).json()
        return {"id": d["id"], "name": path.name, "size": len(data), "type": mimetypes.guess_type(path.name)[0] or "", "key": CC.b64e(fk)}

    def _add(self, pid, item):
        with self._lock:
            h = self.st["hist"].setdefault(pid, [])
            if any(x.get("mid") == item.get("mid") for x in h):
                return False
            h.append(item)
            h.sort(key=lambda x: x.get("ts", 0))
            del h[:-HIST_MAX]
            self._save()
        self.host.emit("close", state=self.state())
        return True

    # ---------- приём ----------
    def poll(self):
        """Забрать новое. -> сколько новых входящих сообщений."""
        priv, _ = self._keys()
        d = self._req("GET", "/close/inbox", params={"after": int(self.st["cursor"])}).json()
        got, refreshed = 0, False
        for it in d.get("items") or []:
            env, peer = it.get("env") or {}, it.get("peer", "")
            pub = self._pub_of(peer, env.get("fd", ""), it.get("out"))
            if pub is None and not refreshed:
                refreshed = True
                try:
                    self.hello()
                except CloseError:
                    pass
                pub = self._pub_of(peer, env.get("fd", ""), it.get("out"))
            if pub is None:
                log.info("близкие: неизвестное устройство %s — пропускаю", env.get("fd"))
                continue
            try:
                body = CC.decrypt_from(env, priv, self.st["dev"], pub)
            except CC.CloseCryptoError as e:
                log.info("близкие: не открылось (%s)", e)
                continue
            if it.get("kind") == "sig":
                self._sig(peer, it.get("name", ""), body)
                continue
            item = {"mid": body.get("mid") or str(it.get("id")), "ts": int(body.get("ts") or it.get("ts", 0) * 1000), "out": bool(it.get("out")),
                    "t": str(body.get("t") or "")[:20000], "f": [x for x in body.get("f") or [] if isinstance(x, dict)][:10]}
            if not self._add(peer, item) or item["out"]:
                continue
            got += 1
            name = it.get("name") or "близкого"
            with self._lock:
                self.st["unread"][peer] = int(self.st["unread"].get(peer, 0)) + 1
                self._save()
            self.host.emit("close_msg", pid=peer, name=name, text=item["t"], files=[x.get("name") for x in item["f"]])
            if item["f"]:
                threading.Thread(target=self._fetch_files, args=(peer, name, item), daemon=True).start()
            self._tell(name, item)
        with self._lock:
            self.st["cursor"] = max(int(self.st["cursor"]), int(d.get("last") or 0))
            self._save()
        if got:
            self.host.emit("close", state=self.state())
        return got

    def _pub_of(self, peer, dev, out):
        who = self.st.get("me") if out else next((p for p in self.st["people"] if p["pid"] == peer), None)
        for d in (who or {}).get("devs") or []:
            if d.get("dev") == dev:
                return CC.b64d(d["pub"])
        if out and dev == self.st["dev"]:
            return CC.b64d(self._keys()[1])
        return None

    def _tell(self, name, item):
        """Вслух и в окна: «Сообщение от Михаила: …» (если не выключено в студии)."""
        files = item.get("f") or []
        what = item["t"] or ""
        if files:
            what = (what + " " if what else "") + ("Файл «" + files[0].get("name", "") + "»." if len(files) == 1 else f"Файлов: {len(files)}.")
        text = f"{name} пишет: {what}".strip()              # без склонения имени: «Анна пишет: …»
        try:
            self.host.push(f"💌 {name}", what or "сообщение", telegram=False)
        except TypeError:
            self.host.push(f"💌 {name}", what or "сообщение")
        if self.host.s.get("close", "speak") is not False:
            self.host.announce(text[:600])

    def _fetch_files(self, pid, name, item):
        """Скачать и расшифровать файлы в папку ассистента «Близкие/<имя>»."""
        root = Path(self.host.workspace.root) / "Близкие" / re.sub(r'[\\/:*?"<>|]', "_", name or "без имени")
        for f in item.get("f") or []:
            try:
                r = self._req("GET", "/close/file", params={"id": f["id"]}, timeout=120)
                data = CC.unseal(CC.b64d(f["key"]), r.content)
                root.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", f.get("name") or "файл")[:120] or "файл"
                out = root / safe
                n = 1
                while out.exists() and hashlib.sha1(out.read_bytes()).hexdigest() != hashlib.sha1(data).hexdigest():
                    out = root / f"{Path(safe).stem} ({n}){Path(safe).suffix}"
                    n += 1
                out.write_bytes(data)
                f["path"] = str(out)
            except (CloseError, CC.CloseCryptoError, OSError, KeyError) as e:
                f["error"] = str(e)
                log.info("близкие: файл %s не скачался: %s", f.get("name"), e)
        with self._lock:
            for x in self.st["hist"].get(pid) or []:
                if x.get("mid") == item["mid"]:
                    x["f"] = item["f"]
            self._save()
        self.host.emit("close", state=self.state())

    # ---------- фон ----------
    def active(self):
        return bool(self.st["people"] or (self.st.get("invite") and time.time() < float(self.st["invite"].get("expires") or 0)))

    def loop(self, stopping):
        time.sleep(8)
        while not stopping.is_set():
            try:
                token = self.host.credentials()[0]
                if token:
                    if time.time() - float(self.st.get("hello_at") or 0) > 6 * 3600:
                        self.hello()
                    self.poll()
                    self.error = ""
            except CloseError as e:
                self.error = str(e)
                log.info("Близкие: %s", e)
            except Exception:  # noqa: BLE001
                log.exception("Близкие")
            self.soon.wait(1 if self._fast() else 6 if self.active() else 600)
            self.soon.clear()

    # ---------- звонки (страница ui/call.html в браузере, assets/call.js — WebRTC) ----------
    CALL_CMDS = ("call_info", "call_sig", "call_ice", "call_fast", "call_done")

    def _fast(self):
        """Идёт звонок — опрос раз в секунду (сигналы WebRTC не должны ждать)."""
        now = time.time()
        for cid, c in list(self.calls.items()):
            if now - c["at"] > 4 * 3600:
                self.calls.pop(cid, None)
        return any(c.get("fast") and now - c["at"] < 3600 for c in self.calls.values())

    def _open_call(self, c):
        import callpage
        token = "c-" + uuid.uuid4().hex
        self.host.bridge.allow(token, self.CALL_CMDS)
        url = f"{callpage.base()}/call.html?call={c['call']}&token={token}&port={self.host.bridge.port}"
        from tools import launch
        launch(["xdg-open", url])
        return url

    def call(self, who, video=False):
        """Позвонить близкому: открыть страницу звонка в браузере (она сама звонит). -> {call, name}."""
        p = self.person(who)
        if not p.get("devs"):
            raise CloseError(f"У {p['name']} Dewiar ещё не открывался — позвонить пока нельзя.")
        cid = uuid.uuid4().hex[:12]
        c = self.calls[cid] = {"call": cid, "role": "caller", "pid": p["pid"], "name": p["name"], "video": bool(video), "offer": "", "at": time.time(), "fast": True}
        self.soon.set()
        self._open_call(c)
        return {"call": cid, "name": p["name"]}

    def _sig(self, peer, name, body):
        s = (body or {}).get("s") or {}
        if s.get("type") == "ring":
            if time.time() * 1000 - float(s.get("ts") or 0) > 45000 or s.get("call") in self.calls:
                return
            if any(c for c in self.calls.values() if time.time() - c["at"] < 3600 and not c.get("ended")):
                try:                                   # уже идёт звонок — «занято»
                    self.send(peer, kind="sig", payload={"s": {"type": "busy", "call": s.get("call")}})
                except CloseError:
                    pass
                return
            p = next((x for x in self.st["people"] if x["pid"] == peer), None)
            if not p:
                return
            c = self.calls[s["call"]] = {"call": s["call"], "role": "callee", "pid": peer, "name": p["name"], "video": bool(s.get("video")),
                                         "offer": s.get("sdp") or "", "at": time.time(), "fast": True}
            log.info("📞 Звонит %s", p["name"])
            self.soon.set()
            self._open_call(c)
            try:
                self.host.push(f"📞 {p['name']}", "видеозвонок" if c["video"] else "звонит", telegram=False)
            except TypeError:
                self.host.push(f"📞 {p['name']}", "звонит")
            self.host.emit("close_ring", pid=peer, name=p["name"], video=c["video"])
            if self.host.s.get("close", "speak") is not False:     # окно звонка в браузере может не сыграть звонок само
                self.host.announce(f"{p['name']} звонит{' по видео' if c['video'] else ''}. Окно звонка открыто.")
            return
        self.host.emit("close_sig", peer=peer, name=name, sig=body)

    def call_cmd(self, cmd, a):
        """Команды страницы звонка (временный токен — только они)."""
        c = self.calls.get(a.get("call", ""))
        if cmd == "call_ice":
            return self._req("GET", "/close/ice").json().get("iceServers") or []
        if not c:
            raise CloseError("звонок уже закончился")
        if cmd == "call_info":
            return {"call": c["call"], "role": c["role"], "video": c["video"], "offer": c["offer"],
                    "peer": {"pid": c["pid"], "name": c["name"], "color": _color_of(c["pid"])}}
        if cmd == "call_sig":
            self.send(c["pid"], kind="sig", payload={"s": dict(a.get("s") or {}, call=c["call"])})
            return {"ok": True}
        if cmd == "call_fast":
            c["fast"] = bool(a.get("on"))
            self.soon.set()
            return {"ok": True}
        if cmd == "call_done":
            c["ended"], c["fast"] = True, False
            secs = int(a.get("secs") or 0)
            t = f"📞 Звонок · {secs // 60:02d}:{secs % 60:02d}" if secs else "📞 " + (a.get("reason") or "Звонок")
            self._add(c["pid"], {"mid": "call" + c["call"] + c["role"], "ts": int(time.time() * 1000), "out": c["role"] == "caller", "t": t, "call": True})
            self.host.emit("call_end", call=c["call"])
            return {"ok": True}
        raise CloseError("неизвестная команда звонка")

    # ---------- для помощницы ----------
    def prompt(self):
        with self._lock:
            names = [p["name"] for p in self.st["people"]]
        if not names:
            return ""
        return ("\n\nБЛИЗКИЕ (переписка с их помощниками Dewiar, сообщения шифруются): " + ", ".join(names)
                + ". «Напиши/передай/скажи Андрею…» кому-то из них — инструмент close_send (дойдёт в его Dewiar, он услышит вслух); "
                  "«что мне писали», «что ответила мама» — close_read; «позвони маме» — close_call (откроется окно звонка). Другим людям (не из этого списка) — как обычно, мессенджерами.")

    def recent(self, who="", n=8):
        with self._lock:
            people = list(self.st["people"])
        ps = [self.person(who)] if who else people
        out = []
        for p in ps:
            for m in (self.st["hist"].get(p["pid"]) or [])[-n:]:
                out.append((m.get("ts", 0), f"{time.strftime('%d.%m %H:%M', time.localtime(m.get('ts', 0) / 1000))} "
                                            f"{'вы → ' + p['name'] if m.get('out') else p['name']}: {m.get('t') or ''}"
                                            + (f" [файлы: {', '.join(x.get('name', '') for x in m.get('f') or [])}]" if m.get("f") else "")))
            self.st["unread"].pop(p["pid"], None)
        self._save()
        out.sort()
        return "\n".join(x for _, x in out[-n * 2:]) or "Сообщений пока нет."
