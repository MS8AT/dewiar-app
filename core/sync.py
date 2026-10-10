"""Синхронизация устройств одного человека через облако Dewiar (cloud.php ?p=/sync): компьютер ↔ телефон ↔ другой компьютер.

Что синхронизируется (вид записи → что это): reminder — напоминания и будильники (дела по расписанию — нет, они
выполняются на этом компьютере); note — заметки и списки (папка «Заметки»); money — расходы и доходы; memory — строки
«Обо мне». Дополнительные виды (EXTRA_KINDS) идут, только если их знает сервер: soul/mind — душа персонажей,
конституция и выводы на завтра; diary — последние дни дневника (пишет компьютер, телефон читает); dayturn — разговор
с телефона в дневник дня и taskreq — задача с телефона (компьютер забирает их и тем самым удаляет из облака); task —
ход задач для показа на телефоне; vault — всё хранилище Obsidian между компьютерами (если включено).

Как: каждое устройство раз в минуту (и сразу после своих изменений, событие soon) сравнивает свои данные с тем, что
уже отправляло (отпечатки в STATE_DIR/sync.json), шлёт изменения и удаления и забирает чужие, начиная с номера
последнего полученного изменения (rev). Запись, которой больше нет в снимке, уходит как удаление — поэтому всё, что
выпало из snapshot() (не прочиталось, стало слишком большим), другие устройства тоже удалят. При правке одной записи
на двух устройствах сервер оставляет более позднюю (по часам устройства); для vault — см. _apply_vault.
Формат записей и порядок обмена совпадают с syncSnapshot()/syncRun() в android/assets/www/app.js и с ?p=/sync в cloud.php.

Чьи данные: аккаунт dewiar.pro (если вошли) или ключ Dewiar (dw-…). Если на устройстве есть и то и другое — сервер
связывает их в одно пространство (X-Sync-Link), чтобы телефон с ключом и компьютер с аккаунтом видели одно и то же.
"""

import datetime as dt
import hashlib
import json
import logging
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path

import httpx

from settings import STATE_DIR

log = logging.getLogger("dewiar.sync")

BASE_KINDS = ("reminder", "note", "money", "memory")          # знает любой сервер
EXTRA_KINDS = ("soul", "mind", "diary", "dayturn", "taskreq", "task", "vault")   # тот же список $extra в cloud.php
VAULT_MAX = 300_000                               # сервер не принимает запись больше 300 КБ — такие заметки не шлём
VAULT_FILES = 15000
CHUNK = 400                                       # изменений за один запрос (сервер берёт до 2000; первая отправка большого хранилища — частями)
DIARY_DAYS = 30                                   # сколько последних дней дневника видно на телефоне
TASKS_SHOWN = 15
NOTES = "Заметки"
MEMORY = Path("Память") / "Обо мне.md"
NOTE_MAX = 300_000
_FACT = re.compile(r"^- (.+?)(?: _\(\d\d\.\d\d\.\d{4}\)_)?\s*$")


def _now_ms():
    return int(time.time() * 1000)


def _h(data):
    """Отпечаток записи «как она лежит у нас». Только локальный: телефон считает свой иначе, сравнивать их нельзя."""
    return hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _fact_id(text):
    """id строки памяти — по её тексту; нормализация та же, что у factId() в app.js, иначе телефон и компьютер
    разойдутся в id и удаление строки на одном не найдёт её на другом."""
    return "f" + hashlib.sha1(re.sub(r"\s+", " ", text.strip().lower().rstrip(".")).encode("utf-8")).hexdigest()[:12]


class SyncError(Exception):
    pass


class Sync:
    def __init__(self, host):
        """host: reminders, money, workspace, credentials() -> (token, link_token, cloud_url), device_name(), push();
        по желанию soul, diary, tasks, obsidian — без них соответствующие виды просто не собираются."""
        self.host = host
        self.path = STATE_DIR / "sync.json"
        self._lock = threading.Lock()
        self.soon = threading.Event()
        self.state = self._load()
        self.status = {"enabled": False, "ok": None, "at": 0, "error": "", "devices": [], "space": "", "counts": {}}
        self._claims = {}            # задачи с телефона, которые надо занять в облаке, прежде чем браться (см. _claim_tasks)

    # ---------- состояние ----------

    def _load(self):
        """sync.json: rev — номер последнего полученного изменения; device — id этого устройства («pc-…»: по приставке
        сервер отличает компьютеры от телефонов); idx — ключ записи → {h: наш отпечаток, u: время версии, del, skip,
        b: для vault — отпечаток версии, с которой облако согласно}; map — id заметки → путь в «Заметках»; who — чей ключ;
        kinds — какие виды знает сервер; mt/vt/vmap — кэши заметок и хранилища."""
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("idx", {})
                d.setdefault("map", {})
                return d
        except (OSError, ValueError):
            pass
        return {"rev": 0, "device": "pc-" + uuid.uuid4().hex[:10], "idx": {}, "map": {}, "who": ""}

    def _save(self):
        # через временный файл: оборванная запись не испортит sync.json (иначе всё ушло бы заново и с удалениями)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- снимок данных этого устройства: ключ → (data, hash) ----------

    def _notes_root(self):
        return self.host.workspace.ensure() / NOTES

    def snapshot(self):
        """-> {«вид:id»: данные}. Для заметок и хранилища ещё «ключ#t» — время правки файла (мс) и, если файл не менялся
        с прошлого раза, данные None и «ключ#h» — отпечаток из кэша (сам текст читаем, только когда его надо отправить).
        Попутно обновляет map и кэш mt. Чего нет в снимке — уйдёт удалением, см. шапку."""
        out = {}
        for r in list(self.host.reminders.items):
            if r.get("kind") == "job":
                continue
            try:
                at = int(dt.datetime.fromisoformat(r["at"]).timestamp() * 1000)
            except (KeyError, ValueError):
                continue
            d = {"text": r.get("text", ""), "at": at, "kind": r.get("kind") or "reminder",
                 "repeat": r.get("repeat") or None, "paused": bool(r.get("paused"))}
            out["reminder:" + r["id"]] = d
        for m in list(self.host.money.items):
            d = {k: m.get(k) for k in ("date", "kind", "amount", "currency", "category", "note")}
            out["money:" + m["id"]] = d
        root = self._notes_root()
        by_path = {v: k for k, v in self.state["map"].items()}
        cache = self.state.setdefault("mt", {})
        seen_paths = set()
        if root.is_dir():
            for p in sorted(root.rglob("*.md"))[:3000]:
                rel = p.relative_to(root).as_posix()
                if any(part.startswith(".") for part in p.relative_to(root).parts):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size > NOTE_MAX:
                    continue
                sid = by_path.get(rel) or "f" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
                self.state["map"][sid] = rel
                seen_paths.add(rel)
                key = "note:" + sid
                out[key + "#t"] = st.st_mtime_ns // 1_000_000     # когда правили на самом деле: старая копия не перебьёт новую
                sig = f"{st.st_mtime_ns}:{st.st_size}"
                c = cache.get(rel)
                if c and c[0] == sig:                     # файл не менялся — не читаем его каждую минуту
                    out[key] = None
                    out[key + "#h"] = c[1]
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                folder = p.parent.relative_to(root).as_posix()
                d = {"title": p.stem, "text": text, "folder": "" if folder == "." else folder}
                out[key] = d
                cache[rel] = [sig, _h(d)]
        for rel in [r for r in cache if r not in seen_paths]:
            cache.pop(rel, None)
        # id пропавшей заметки забываем, только если синхронизация о ней не знает: известному id путь ещё понадобится
        for sid in [s for s, r in self.state["map"].items() if r not in seen_paths and "note:" + s not in self.state["idx"]]:
            self.state["map"].pop(sid, None)
        for fact in self._facts():
            out["memory:" + _fact_id(fact)] = {"text": fact}
        if set(EXTRA_KINDS) & set(self.state.get("kinds") or ()):     # только виды, которые знает сервер
            self.state["_extra_failed"] = False
            try:
                self._snap_extra(out)
            except Exception as e:  # noqa: BLE001 — душа, дневник и задачи не должны ломать напоминания и заметки
                self.state["_extra_failed"] = True
                log.warning("Синхронизация: душа/дневник/задачи не собрались: %s", e)
        return out

    def _snap_extra(self, out):
        h = self.host
        ok = set(self.state.get("kinds") or ())
        soul = getattr(h, "soul", None)
        if soul is not None and "soul" in ok:
            for name in soul.souls():
                text = soul.soul(name)
                if text.strip():
                    out["soul:" + name] = {"text": text}
        if soul is not None and "mind" in ok:
            out["mind:constitution"] = {"text": soul.constitution()}
        if "mind" in ok:                       # дела по расписанию (утренняя сводка, итоги) — телефону только показать: делает компьютер
            from when import describe_repeat
            jobs = []
            for r in list(h.reminders.items):
                if r.get("kind") != "job":
                    continue
                try:
                    at = int(dt.datetime.fromisoformat(r["at"]).timestamp() * 1000)
                except (KeyError, ValueError):
                    continue
                try:
                    rep = describe_repeat(r.get("repeat")) if r.get("repeat") else ""
                except Exception:  # noqa: BLE001
                    rep = ""
                jobs.append({"text": str(r.get("text", ""))[:200], "at": at, "repeat": rep, "paused": bool(r.get("paused"))})
            # своя запись у каждого компьютера (jobs-<устройство>): два компьютера не перетирают друг друга по кругу;
            # без дел — не шлём (а если раньше были — шлём пустой список, чтобы телефон их убрал)
            if jobs or self.state.get("jobs_sent"):
                out["mind:jobs-" + self.state["device"]] = {"items": sorted(jobs, key=lambda j: j["at"])[:30]}
            self.state["jobs_sent"] = bool(jobs)
        diary = getattr(h, "diary", None)
        if diary is not None and "mind" in ok and (diary.data.get("insights") or {}).get("lines"):
            ins = diary.data["insights"]
            out["mind:insights"] = {"day": ins.get("day", ""), "title": ins.get("title", ""), "lines": list(ins.get("lines") or [])}
        if "diary" in ok:
            d = h.workspace.ensure() / "Дневник"
            titles = (diary.data.get("titles") if diary is not None else None) or {}
            for p in sorted(d.glob("*.md"), reverse=True)[:DIARY_DAYS] if d.is_dir() else []:
                try:
                    dt.date.fromisoformat(p.stem)
                    text = p.read_text(encoding="utf-8")
                except (ValueError, OSError):
                    continue
                t = titles.get(p.stem) or {}
                out["diary:" + p.stem] = {"text": text[:NOTE_MAX], "title": t.get("title", ""), "mood": t.get("mood", "")}
        ob = getattr(h, "obsidian", None)
        if ob is not None and "vault" in ok and ob.sync_all():
            self._snap_vault(out, ob)
        tasks = getattr(h, "tasks", None)
        if tasks is not None and "task" in ok:
            for t in sorted(tasks.tasks.values(), key=lambda x: str(x.data.get("updated", "")), reverse=True)[:TASKS_SHOWN]:
                dd = t.data
                out["task:" + t.id] = {"title": dd.get("title", ""), "status": dd.get("status", ""), "goal": str(dd.get("goal", ""))[:400],
                                       "result": str(dd.get("result", ""))[:1200], "error": str(dd.get("error", ""))[:300],
                                       "question": str(dd.get("question", ""))[:400], "activity": str(dd.get("activity", ""))[:200],
                                       "updated": dd.get("updated", ""), "created": dd.get("created", ""),
                                       "outputs": [str(o.get("path", ""))[-80:] for o in (dd.get("outputs") or [])][:8],
                                       "files": dd.get("files") or []}

    def _facts(self):
        try:
            text = (self.host.workspace.ensure() / MEMORY).read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            m = _FACT.match(line.strip())
            if m:
                out.append(m.group(1).strip())
        return out

    def _hash_of(self, snap, key):
        if key + "#h" in snap:
            return snap[key + "#h"]
        return _h(snap[key])

    # ---------- применить чужое изменение ----------

    def _apply(self, it):
        """Применяет запись с другого устройства. -> False, если она осознанно не легла здесь (прошедшее разовое
        напоминание, удаление души или дневника, чужой ход задачи, хранилище выключено): в idx она помечается skip,
        и её отсутствие у нас не уходит в облако удалением. Как в syncApply() в app.js."""
        kind, iid, d = it["kind"], it["id"], it.get("data") or {}
        deleted = it.get("deleted")
        if kind == "reminder":
            if deleted:
                self.host.reminders.remove(iid)
                return
            at = dt.datetime.fromtimestamp(int(d.get("at") or 0) / 1000).replace(microsecond=0)
            if not d.get("repeat") and at < dt.datetime.now() - dt.timedelta(minutes=5) and not self.host.reminders.get(iid):
                return False                               # разовое и уже прошло — звенеть задним числом незачем
            self.host.reminders.upsert({"id": iid, "at": at.isoformat(timespec="seconds"), "text": d.get("text") or "Напоминание",
                                        "repeat": d.get("repeat") or None, "kind": d.get("kind") or "reminder",
                                        "paused": bool(d.get("paused"))})
        elif kind == "money":
            if deleted:
                self.host.money.delete(iid)
            elif float(d.get("amount") or 0) > 0:
                self.host.money.upsert(dict(d, id=iid))
        elif kind == "note":
            self._apply_note(iid, d, deleted)
        elif kind == "memory":
            self._apply_fact(iid, d.get("text") or "", deleted)
        elif kind == "vault":
            return self._apply_vault(iid, d, deleted, it)
        elif kind in EXTRA_KINDS:
            return self._apply_extra(kind, iid, d, deleted, it.get("updated"))

    # ---------- всё хранилище Obsidian (по желанию): одинаковое на всех компьютерах ----------
    def _vault_files(self, ob):
        """-> (корень хранилища или None, {путь в хранилище: Path}) — тексты .md, кроме папки ассистента (она ходит
        своими видами записей), служебных и скрытых папок (SKIP_DIRS из obsidian.py) и корзины; не больше VAULT_FILES."""
        v = ob.vault()
        mir = ob.mirror()
        if v is None:
            return None, {}
        out = {}
        from obsidian import SKIP_DIRS
        for p in v.rglob("*.md"):
            try:
                rel = p.relative_to(v)
            except ValueError:
                continue
            parts = rel.parts
            if any(x in SKIP_DIRS or x.startswith(".") for x in parts[:-1]) or (mir is not None and parts[0] == mir.name):
                continue
            out[rel.as_posix()] = p
            if len(out) >= VAULT_FILES:
                break
        return v, out

    def _snap_vault(self, out, ob):
        v, files = self._vault_files(ob)
        if v is None:
            return
        vmap = self.state.setdefault("vmap", {})              # id → путь (удаление приходит без пути)
        cache = self.state.setdefault("vt", {})
        for rel, p in files.items():
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > VAULT_MAX:
                continue
            vid = "v" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]     # id из пути: одинаков на всех компьютерах
            vmap[vid] = rel
            key = "vault:" + vid
            out[key + "#t"] = st.st_mtime_ns // 1_000_000
            sig = f"{st.st_mtime_ns}:{st.st_size}"
            c = cache.get(rel)
            if c and c[0] == sig:
                out[key] = None
                out[key + "#h"] = c[1]
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            d = {"path": rel, "text": text}
            out[key] = d
            cache[rel] = [sig, _h(d)]
        for rel in [r for r in cache if r not in files]:
            cache.pop(rel, None)

    def _really_gone(self, key):
        """Запись пропала из снимка — это удаление, только если её источника правда нет. Отключённый диск с хранилищем,
        выключенная галочка «всё хранилище», заметка сверх предела или больше 300 КБ, файл, который сейчас не читается, —
        не удаление: иначе другие устройства отправили бы эти заметки в корзину."""
        kind, iid = key.split(":", 1)
        if kind == "note":
            rel = self.state.get("map", {}).get(iid)
            return not (rel and (self._notes_root() / rel).exists())
        if kind == "vault":
            ob = getattr(self.host, "obsidian", None)
            v = ob.vault() if ob is not None else None
            if v is None or not ob.sync_all():
                return False
            rel = self.state.get("vmap", {}).get(iid)
            return not (rel and (v / rel).exists())
        if kind in ("soul", "mind", "diary", "task") and self.state.get("_extra_failed"):
            return False
        return True

    def _vault_read(self, vid):
        ob = getattr(self.host, "obsidian", None)
        rel = self.state.get("vmap", {}).get(vid)
        v = ob.vault() if ob is not None else None
        if not rel or v is None:
            return None
        try:
            return {"path": rel, "text": (v / rel).read_text(encoding="utf-8")}
        except (OSError, UnicodeDecodeError):
            return None

    def _apply_vault(self, vid, d, deleted, it):
        """Чужая правка заметки хранилища. Удаление — в корзину Obsidian (.trash), не насовсем. Пришедшая версия
        ложится поверх здешней, но если здесь заметку правили (текст не совпадает с версией b, с которой облако было
        согласно) и это не первая встреча с ней либо здешний файл новее пришедшего, — здешний текст сохраняется рядом
        копией «(конфликт, устройство дата)». Так ничья правка не теряется молча (см. prev/lost в run_once)."""
        ob = getattr(self.host, "obsidian", None)
        v = ob.vault() if ob is not None else None
        if v is None or not ob.sync_all():
            return False
        rel = str(d.get("path") or self.state.get("vmap", {}).get(vid) or "")
        relp = Path(rel)
        # путь пришёл из облака: не даём выйти за пределы хранилища и писать в служебные папки и не-.md файлы
        if not rel or relp.is_absolute() or ".." in relp.parts or relp.suffix.lower() != ".md" or relp.parts[0] in (".obsidian", ".trash"):
            return False
        p = v / relp
        if deleted:
            if p.exists():
                dst = v / ".trash" / relp
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    dst = dst.with_name(f"{dst.stem} {int(time.time())}{dst.suffix}")
                shutil.move(str(p), str(dst))
            self.state.get("vt", {}).pop(rel, None)
            return None
        text = str(d.get("text") or "")
        self.state.setdefault("vmap", {})[vid] = rel
        if p.exists():
            try:
                cur = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                cur = None
            if cur == text:
                return None
            base = (self.state.get("idx", {}).get("vault:" + vid) or {}).get("b")
            local_edit = cur is not None and _h({"path": rel, "text": cur}) != base
            newer_here = p.stat().st_mtime * 1000 > int(it.get("updated") or 0)
            if cur is not None and local_edit and (base is not None or newer_here):
                alt = p.with_name(f"{p.stem} (конфликт, {self.host.device_name()} {dt.datetime.now():%d.%m %H-%M}){p.suffix}")
                alt.write_text(cur, encoding="utf-8")
                log.info("🔄 Хранилище: «%s» правили и здесь, и на другом устройстве — здешняя версия рядом: %s", rel, alt.name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return None

    def _apply_extra(self, kind, iid, d, deleted, it_updated=0):
        """Душа, конституция, выводы, дневник — удалением не стираются: у другого устройства запись могла просто
        выпасть из снимка (дневник там — за DIARY_DAYS дней), а написанное терять нельзя. Разговор (dayturn) и задачу (taskreq)
        с телефона забираем к себе; в следующем снимке их нет — и run_once сам шлёт их удаление, облако их забывает.
        Ход задач другого компьютера (task) — только для телефона: пропускаем."""
        h = self.host
        if kind in ("soul", "mind", "diary", "task") and deleted:
            return False
        if kind == "soul":
            text = str(d.get("text") or "")
            if text.strip() and text.strip() != h.soul.soul(iid).strip():
                h.soul.save_soul(iid, text)
                log.info("🔄 Душа «%s» — правка с другого устройства", iid)
        elif kind == "mind" and iid == "constitution":
            text = str(d.get("text") or "")
            if text.strip() and text.strip() != h.soul.constitution().strip():
                h.soul.save_constitution(text)
                log.info("🔄 Конституция — правка с другого устройства")
        elif kind == "mind" and iid == "insights":
            cur = h.diary.data.get("insights") or {}
            if d.get("lines") and str(d.get("day", "")) > str(cur.get("day", "")):
                h.diary.data["insights"] = {"day": d.get("day"), "title": d.get("title", ""), "lines": list(d.get("lines") or [])}
                h.diary._save()
        elif kind == "diary":
            try:
                dt.date.fromisoformat(iid)
            except ValueError:
                return False
            p = h.workspace.ensure() / "Дневник" / f"{iid}.md"
            text = str(d.get("text") or "")
            if text.strip() and (not p.exists() or p.read_text(encoding="utf-8").strip() != text.strip()):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
        elif kind == "dayturn":
            if not deleted:
                when = None
                try:
                    when = dt.datetime.fromtimestamp(int(d.get("ts") or 0) / 1000)
                except (ValueError, OSError, OverflowError):
                    pass
                h.diary.log.add(str(d.get("you") or ""), str(d.get("bot") or ""), who=str(d.get("who") or ""), via="телефон", when=when)
        elif kind == "taskreq":
            # Два компьютера взялись бы за одну задачу оба: сначала занимаем её в облаке (taken_by, с prev — облако
            # отклонит, если занял другой), и только занявший берётся — _claim_tasks после обмена.
            if deleted:
                return None
            if d.get("taken_by") and d.get("taken_by") != self.state.get("device"):
                return False
            if str(d.get("goal") or d.get("title") or "").strip() and not d.get("taken_by"):
                self._claims[iid] = (dict(d), int(it_updated or 0))
        elif kind == "task" or (kind == "mind" and iid.startswith("jobs")):
            return False                                   # ход задач и дела по расписанию другого компьютера — для телефона
        return None

    def _upload_outputs(self, url, token):
        """Файлы-результаты законченных задач (показанные show, до 10 МБ) — в облако (?p=/files), один раз каждый:
        телефон открывает и сохраняет их из «Задач» и из разговора. Облако старое (нет /files) — не пробуем сутки."""
        tasks = getattr(self.host, "tasks", None)
        if tasks is None or time.time() < float(self.state.get("files_off_until") or 0):
            return
        for t in list(tasks.tasks.values())[-TASKS_SHOWN * 2:]:
            if t.data.get("status") not in ("done", "failed", "stopped") or not t.data.get("outputs"):
                continue
            sent = t.data.setdefault("cloud_files", {})
            files, changed = [], False
            for o in (t.data.get("outputs") or [])[-8:]:
                p = t.dir / str(o.get("path") or "")
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size > 10 * 1024 * 1024:
                    continue
                key = f"{o.get('path')}|{st.st_size}|{int(st.st_mtime)}"
                if key not in sent:
                    try:
                        r = httpx.post(url, params={"p": "/files", "name": p.name}, content=p.read_bytes(),
                                       headers={"Authorization": "Bearer " + token}, timeout=120)
                    except (httpx.HTTPError, OSError) as e:
                        log.info("Файл задачи не отправлен: %s", e)
                        return
                    if r.status_code == 404:
                        self.state["files_off_until"] = time.time() + 86400
                        return
                    if r.status_code >= 400:
                        continue
                    try:
                        sent[key] = r.json()["id"]
                    except (ValueError, KeyError):
                        continue
                    changed = True
                files.append({"name": p.name, "id": sent[key], "size": st.st_size, "title": str(o.get("title") or p.stem)[:120]})
            if changed or t.data.get("files") != files:
                t.data["files"] = files
                t.save()

    def _claim_tasks(self, url, headers, idx):
        """Задачи с телефона, увиденные в этом обмене: записать в облако taken_by с prev (версия, которую видели).
        Облако приняло — задача наша: создаём; отклонило (lost) — её уже взял другой компьютер. В следующем снимке
        записи нет — run_once пошлёт удаление, как и раньше."""
        claims, self._claims = self._claims, {}
        if not claims:
            return
        h = self.host
        now = int(time.time() * 1000)
        body = {"since": int(self.state.get("rev") or 0), "device": self.state["device"], "name": h.device_name(), "kinds": ["taskreq"],
                "changes": [{"kind": "taskreq", "id": iid, "data": dict(d, taken_by=self.state["device"]), "updated": now, "prev": prev}
                            for iid, (d, prev) in claims.items()]}
        try:
            r = httpx.post(url + "?p=/sync", json=body, headers=headers, timeout=30)
            lost = set(r.json().get("lost") or ()) if r.status_code < 400 else None
        except (httpx.HTTPError, ValueError):
            lost = None
        for iid, (d, prev) in claims.items():
            key = "taskreq:" + iid
            if lost is None:                                  # облако не ответило — попробуем занять в следующий обмен
                self._claims[iid] = (d, prev)
                idx.pop(key, None)
                continue
            if key in lost:                                   # уже взял другой компьютер
                idx[key] = {"h": None, "u": prev, "skip": True}
                continue
            idx[key] = {"h": None, "u": now}
            goal = str(d.get("goal") or d.get("title") or "").strip()
            t = h.tasks.create(str(d.get("title") or goal[:50]), goal + "\n\n(Задачу поставили с телефона — результат он увидит.)")
            log.info("🔄 Задача с телефона: «%s»", t.title)
            try:
                h.push("Задача с телефона", f"Взялся: «{t.title}». Ход — в «Задачах», на телефоне тоже.", telegram=False)
            except Exception:  # noqa: BLE001
                pass

    def _apply_note(self, sid, d, deleted):
        """Удаление — в корзину Dewiar (workspace.remove). Новая заметка получает свободное имя по заголовку в своей
        папке; известная перезаписывается на месте — смена заголовка или папки на другом устройстве файл не переносит.
        Имена из облака чистит _clean_name, «..» отбрасывается: выйти из «Заметок» нельзя."""
        ws = self.host.workspace
        root = self._notes_root()
        rel = self.state["map"].get(sid)
        if deleted:
            if rel and (root / rel).exists():
                ws.remove(f"{NOTES}/{rel}")
            self.state["map"].pop(sid, None)
            return
        if not rel:
            from workspace import _clean_name
            folder = "/".join(_clean_name(x) for x in str(d.get("folder") or "").split("/") if x.strip() and x not in (".", ".."))
            base = _clean_name(d.get("title") or "Заметка") or "Заметка"
            rel = (folder + "/" if folder else "") + base + ".md"
            n = 2
            taken = set(self.state["map"].values())
            while (root / rel).exists() or rel in taken:
                rel = (folder + "/" if folder else "") + f"{base} ({n}).md"
                n += 1
            self.state["map"][sid] = rel
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        text = str(d.get("text") or "")
        if not text.lstrip().startswith("#"):              # заметка с телефона: заголовок — как у заметок компьютера
            text = f"# {d.get('title') or p.stem}\n\n{text}\n"
        p.write_text(text, encoding="utf-8")

    def _apply_fact(self, fid, fact, deleted):
        """Строка «Обо мне»: новую дописываем, если такой (по id) ещё нет. Удаление приходит без текста — ищем строку
        по её id (отпечатку текста, см. _fact_id)."""
        fact = re.sub(r"\s+", " ", fact.strip())
        ws = self.host.workspace
        if not deleted:
            if not fact:
                return
            if _fact_id(fact) not in {_fact_id(x) for x in self._facts()}:
                ws.remember(fact)
            return
        p = ws.ensure() / MEMORY
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        keep = [ln for ln in lines if not ((m := _FACT.match(ln.strip())) and _fact_id(m.group(1)) == fid)]
        if len(keep) != len(lines):
            p.write_text("\n".join(keep) + "\n", encoding="utf-8")

    # ---------- обмен ----------

    def run_once(self):
        """Один обмен с облаком: отправить свои изменения и удаления, применить чужие, сохранить sync.json.
        -> True после обмена, False — синхронизация выключена (нет ключа). Ошибки облака — SyncError.
        Под self._lock: обмен из цикла и по кнопке не идут одновременно. Порядок тот же, что у syncRun() в app.js."""
        token, link, url = self.host.credentials()
        if not token:
            self.status.update(enabled=False, ok=None, error="")
            return False
        with self._lock:
            who = hashlib.sha1(token.encode()).hexdigest()[:12]
            if self.state.get("who") and self.state["who"] != who:
                # другой ключ или аккаунт — начинаем с чистого листа: свои данные отправим заново, чужие получим
                # (idx обнуляем, а не сравниваем: удаления из старого пространства в новое уйти не должны)
                self.state.update(rev=0, idx={})
            self.state["who"] = who
            self.status["enabled"] = True
            self._upload_outputs(url, token)
            snap = self.snapshot()
            idx = self.state["idx"]
            now = _now_ms()
            changes = []
            keys = [k for k in snap if not k.endswith(("#h", "#t"))]
            for key in keys:
                h = self._hash_of(snap, key)
                st = idx.get(key)
                if st and st.get("h") == h and not st.get("del"):
                    continue
                data = snap[key]
                if data is None and key.startswith("vault:"):
                    data = self._vault_read(key.split(":", 1)[1])
                    if data is None:
                        continue
                elif data is None:                        # файл не менялся (отпечаток из кэша), а отправить надо — читаем
                    rel = self.state["map"].get(key.split(":", 1)[1])
                    root = self._notes_root()
                    try:
                        text = (root / rel).read_text(encoding="utf-8")
                    except (OSError, TypeError, UnicodeDecodeError):
                        continue
                    folder = str(Path(rel).parent.as_posix())
                    data = {"title": Path(rel).stem, "text": text, "folder": "" if folder == "." else folder}
                kind, iid = key.split(":", 1)
                changes.append({"kind": kind, "id": iid, "data": data, "updated": min(now, int(snap.get(key + "#t") or now)), "_h": h})
                if kind == "vault" and st and st.get("u") is not None:
                    changes[-1]["prev"] = st["u"]       # от какой версии облака правили (облако отклонит правку поверх устаревшей)
            present = set(keys)
            for key, st in list(idx.items()):
                if key not in present and not st.get("del") and not st.get("skip") and self._really_gone(key):
                    kind, iid = key.split(":", 1)
                    changes.append({"kind": kind, "id": iid, "data": {}, "updated": now, "deleted": True, "_h": None})
            sent = {(c["kind"] + ":" + c["id"]): c for c in changes}
            # хранилище Obsidian сейчас недоступно (диск отключён, галочку сняли) — его записи не берём: иначе они
            # применились бы «в никуда», а номер rev ушёл бы вперёд. Вернулось — забираем историю заново с начала.
            ob = getattr(self.host, "obsidian", None)
            vault_on = ob is not None and ob.sync_all()
            kinds = [k for k in BASE_KINDS + EXTRA_KINDS if k != "vault" or vault_on]
            if vault_on and self.state.get("vault_paused"):
                self.state["vault_paused"] = False
                self.state["rev"] = 0
            elif not vault_on and "vault" in (self.state.get("kinds") or ()):
                self.state["vault_paused"] = True
            body = {"since": int(self.state.get("rev") or 0), "device": self.state["device"], "name": self.host.device_name(),
                    "kinds": kinds,
                    "changes": []}
            rest = [{k: v for k, v in c.items() if k != "_h"} for c in changes]
            body["changes"], rest = rest[:CHUNK], rest[CHUNK:]
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
            if link and link != token:
                headers["X-Sync-Link"] = link
            got = 0
            for _ in range(400):                         # чужое сервер отдаёт по 1000 («more»), своё шлём по CHUNK; 400 — предохранитель
                try:
                    r = httpx.post(url + "?p=/sync", json=body, headers=headers, timeout=30)
                except httpx.HTTPError as e:
                    raise SyncError(f"облако Dewiar не ответило: {e}") from e
                if r.status_code >= 400:
                    try:
                        msg = r.json()["error"]["message"]
                    except (ValueError, KeyError, TypeError):
                        msg = f"облако ответило {r.status_code}"
                    raise SyncError(msg)
                d = r.json()
                srv = tuple(d.get("kinds") or BASE_KINDS)
                lost = set(d.get("lost") or ())
                # запоминаем отпечаток отправленного; если сервер оставил более позднюю чужую версию (lost),
                # она придёт в items и ляжет поверх, обновив запись в idx
                for c in body["changes"]:
                    key = c["kind"] + ":" + c["id"]
                    if c["kind"] not in srv:            # сервер такого вида ещё не знает — отправим, когда узнает
                        continue
                    if key in lost and c["kind"] == "vault":   # облако не приняло (правили поверх устаревшей) — придёт свежая
                        continue
                    idx[key] = {"h": sent[key]["_h"], "u": c["updated"], "del": bool(c.get("deleted"))}
                    if c["kind"] == "vault":
                        idx[key]["b"] = sent[key]["_h"]          # с этой версией облако согласно — от неё и считаем «правили здесь»
                if set(srv) - set(self.state.get("kinds") or BASE_KINDS) - ({"vault"} if self.state.get("vault_paused") else set()):
                    # сервер знает виды, которых этот компьютер от него ещё не получал: забираем всю историю с начала
                    self.state["kinds"] = list(srv)
                    self.state["rev"] = 0
                    body["since"] = 0
                    body["changes"] = []
                    continue
                body["changes"], rest = rest[:CHUNK], rest[CHUNK:]
                for it in d.get("items") or []:
                    key = it["kind"] + ":" + it["id"]
                    st = idx.get(key) or {}
                    if it.get("dev") == self.state["device"] and st.get("u") == it.get("updated"):
                        continue                          # своё же изменение вернулось — уже на месте
                    try:
                        if self._apply(it) is False:
                            idx[key] = {"h": None, "u": it.get("updated"), "skip": True}
                            continue
                    except Exception as e:  # noqa: BLE001
                        log.warning("Синхронизация: %s %s не применилось: %s", it.get("kind"), it.get("id"), e)
                        continue
                    got += 1
                    if it.get("deleted"):
                        idx[key] = {"h": None, "u": it.get("updated"), "del": True}
                    else:
                        idx[key] = {"h": None, "u": it.get("updated")}
                        if it["kind"] == "vault":
                            idx[key]["b"] = _h(it.get("data") or {})
                self.state["rev"] = int(d.get("rev") or self.state.get("rev") or 0)
                body["since"] = self.state["rev"]
                if not d.get("more") and not body["changes"]:
                    break
            self._claim_tasks(url, headers, idx)
            if got:                                       # отпечатки принятого — по тому, как оно легло у нас, иначе ушло бы обратно
                snap2 = self.snapshot()
                for key, st in idx.items():
                    if st.get("h") is None and not st.get("del") and key in snap2:
                        st["h"] = self._hash_of(snap2, key)
            self._save()
            self.status.update(ok=True, at=int(time.time()), error="", devices=d.get("devices") or [], space=d.get("space", ""),
                               counts={"sent": len(changes), "got": got})
            if changes or got:
                log.info("🔄 Синхронизация: отправлено %d, получено %d", len(changes), got)
            return True

    def loop(self, stopping, interval=60):
        """Фоновый поток: обмен раз в interval секунд или раньше — по self.soon.set() после своих правок."""
        time.sleep(5)
        while not stopping.is_set():
            try:
                self.run_once()
            except SyncError as e:
                self.status.update(ok=False, error=str(e), at=int(time.time()))
                log.info("Синхронизация: %s", e)
            except Exception as e:  # noqa: BLE001
                self.status.update(ok=False, error=str(e), at=int(time.time()))
                log.exception("Синхронизация")
            self.soon.wait(interval)
            self.soon.clear()
            time.sleep(2)                                # несколько правок подряд — одним обменом


def default_device_name():
    try:
        return socket.gethostname()[:40] or "Компьютер"
    except OSError:
        return "Компьютер"
