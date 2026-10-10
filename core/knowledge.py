"""Знания на этом компьютере: документы пользователя в папке «Знания» (внутри папки ассистента).

Без сервера и без интернета: текст достаётся из файлов (.md .txt .html .pdf .docx .odt .csv; extract() берёт и
workspace.read), режется на отрывки ~900 знаков с нахлёстом 150 и ищется по словам (BM25 со своим грубым русским
«стеммингом» — отрезаем окончания; он не тот же, что в recall.py). В индексе — отрывки текста, а не слова: основы
считаются при каждом поиске. Индекс хранится в STATE_DIR/knowledge.json (входит в резервную копию) и пересчитывается
только для изменившихся файлов (по времени и размеру).
"""

import html
import json
import logging
import math
import re
import subprocess
import threading
import zipfile
from pathlib import Path

log = logging.getLogger("dewiar.knowledge")
FOLDER = "Знания"
EXTS = {".md", ".txt", ".html", ".htm", ".pdf", ".docx", ".odt", ".csv"}
CHUNK, OVERLAP = 900, 150
MAX_FILE = 60 * 1024 * 1024
README = """# Знания

Положите сюда свои документы — инструкции, договоры, регламенты, книги, конспекты.
Ассистент найдёт в них ответ, когда вы спросите: «что в моих документах про отпуск?».

Подходят: PDF, Word (.docx), OpenOffice (.odt), текст (.txt, .md), веб-страницы (.html), таблицы .csv.
Всё остаётся на этом компьютере. Папки внутри — можно.
"""

_END = re.compile(r"(ами|ями|ого|его|ому|ему|ыми|ими|ах|ях|ов|ев|ей|ой|ий|ый|ая|яя|ое|ее|ые|ие|ую|юю|ом|ем|ам|ям|"
                  r"ть|ти|ла|ло|ли|ет|ит|ут|ют|ат|ят|ешь|ишь|ем|им|ете|ите|ся|сь|а|я|о|е|ы|и|у|ю|ь)$")


def stem(w):
    """Короткие и нерусские слова — как есть; иначе без одного окончания (основа не короче 3 букв)."""
    w = w.lower().replace("ё", "е")
    if len(w) <= 4 or not re.match(r"[а-я]", w):
        return w
    s = _END.sub("", w)
    return s if len(s) >= 3 else w[:4]


def words(text):
    return [stem(w) for w in re.findall(r"[\wё]+", text.lower()) if len(w) > 1]


# ---------- извлечение текста ----------

def _xml_text(xml, para_tag):
    """Текст из XML документа Word/ODT: конец абзаца para_tag — перевод строки, прочие теги — прочь."""
    xml = re.sub(rf"</{para_tag}>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def extract(p: Path) -> str:
    """Текст документа; незнакомый формат — "". PDF — через pypdf (если не установлен — RuntimeError), до 500 страниц;
    скан без текстового слоя даёт пустой текст."""
    ext = p.suffix.lower()
    if ext in (".md", ".txt", ".csv"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext in (".html", ".htm"):
        t = p.read_text(encoding="utf-8", errors="replace")
        t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>|</tr>", "\n", t)
        return html.unescape(re.sub(r"<[^>]+>", " ", t))
    if ext == ".docx":
        with zipfile.ZipFile(p) as z:
            return _xml_text(z.read("word/document.xml").decode("utf-8", "replace"), "w:p")
    if ext == ".odt":
        with zipfile.ZipFile(p) as z:
            return _xml_text(z.read("content.xml").decode("utf-8", "replace"), "text:p")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("для PDF нужна библиотека pypdf") from e
        r = PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in r.pages[:500])
    return ""


def chunks(text):
    """Отрывки до CHUNK знаков, конец — по абзацу или предложению во второй половине; соседние перекрываются
    на OVERLAP, чтобы ответ на стыке не потерялся."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + CHUNK)
        if end < len(text):                                   # режем по абзацу или предложению
            cut = max(text.rfind("\n\n", i + CHUNK // 2, end), text.rfind(". ", i + CHUNK // 2, end))
            if cut > 0:
                end = cut + 1
        piece = text[i:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        i = max(end - OVERLAP, i + 1)                         # i + 1 — чтобы не зациклиться на коротком отрывке
    return out


class Knowledge:
    def __init__(self, workspace, index_path):
        self.ws, self.index_path = workspace, Path(index_path)
        self._lock = threading.Lock()
        self.index = self._load()          # rel -> {"mtime", "size", "chunks": [..], "error"}

    @property
    def root(self):
        """Папка «Знания»; при первом обращении кладёт в неё «О папке.md» с объяснением (в индекс он не входит)."""
        d = self.ws.root / FOLDER
        if not (d / "О папке.md").exists():
            d.mkdir(parents=True, exist_ok=True)
            (d / "О папке.md").write_text(README, encoding="utf-8")
        return d

    def _load(self):
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.index, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.index_path)
        except OSError as e:
            log.warning("Индекс знаний не сохранён: %s", e)

    def files(self):
        root = self.root
        out = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in EXTS and not any(x.startswith(".") for x in p.relative_to(root).parts) \
                    and p.name != "О папке.md":
                out.append(p)
        return out

    def has_files(self):
        try:
            return bool(self.files())
        except OSError:
            return False

    def refresh(self):
        """Пересчитать отрывки для новых и изменившихся файлов, забыть удалённые. -> сколько файлов обработано.
        Ошибка чтения файла не прерывает остальные — она остаётся в записи индекса (её видно в списке студии)."""
        with self._lock:
            root, seen, changed = self.root, set(), 0
            for p in self.files():
                rel = p.relative_to(root).as_posix()
                seen.add(rel)
                st = p.stat()
                old = self.index.get(rel)
                if old and old.get("mtime") == st.st_mtime and old.get("size") == st.st_size:
                    continue
                entry = {"mtime": st.st_mtime, "size": st.st_size, "chunks": []}
                try:
                    if st.st_size > MAX_FILE:
                        raise RuntimeError("файл больше 60 МБ")
                    entry["chunks"] = chunks(extract(p))
                    if not entry["chunks"]:
                        entry["error"] = "в файле нет текста (скан без распознавания?)"
                except Exception as e:  # noqa: BLE001
                    entry["error"] = str(e)[:200]
                    log.info("Знания: %s — %s", rel, entry["error"])
                self.index[rel] = entry
                changed += 1
            for rel in list(self.index):
                if rel not in seen:
                    del self.index[rel]
                    changed += 1
            if changed:
                self._save()
            return changed

    def list(self):
        self.refresh()
        return [{"path": rel, "size": e["size"], "chunks": len(e["chunks"]), "error": e.get("error", "")}
                for rel, e in sorted(self.index.items())]

    def search(self, query, limit=5):
        """-> [{path, score, text}] — лучшие отрывки, не больше двух из файла. Путь файла тоже участвует в поиске."""
        self.refresh()
        q = [w for w in words(query) if len(w) > 2] or words(query)     # короткие основы — только если других нет
        if not q:
            return []
        docs = [(rel, i, c, words(rel + " " + c)) for rel, e in self.index.items() for i, c in enumerate(e["chunks"])]
        if not docs:
            return []
        n = len(docs)
        avg = sum(len(d[3]) for d in docs) / n or 1
        df = {w: sum(1 for d in docs if w in d[3]) for w in set(q)}
        scored = []
        for rel, i, c, ws in docs:
            tf = {}
            for w in ws:
                if w in df:
                    tf[w] = tf.get(w, 0) + 1
            if not tf:
                continue
            s = 0.0
            for w, f in tf.items():
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                # BM25: k1=1.2, b=0.75 (как в recall.py)
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(ws) / avg))
            s *= 1 + 0.3 * (len(tf) - 1)                        # совпало больше разных слов — выше
            scored.append((s, rel, i, c))
        scored.sort(key=lambda x: -x[0])
        out, per_file = [], {}
        for s, rel, i, c in scored:
            if per_file.get(rel, 0) >= 2:                       # не больше двух отрывков из одного файла
                continue
            per_file[rel] = per_file.get(rel, 0) + 1
            out.append({"path": rel, "score": round(s, 2), "text": c})
            if len(out) >= limit:
                break
        return out

    def add(self, name, data: bytes):
        """Документ из студии — в корень «Знаний» под свободным именем. Из name берётся только имя файла: путь
        от браузера не должен увести запись за пределы папки. -> путь внутри «Знаний»."""
        name = Path(str(name or "")).name.strip()
        if not name or Path(name).suffix.lower() not in EXTS:
            raise ValueError("такие файлы не подходят: нужны PDF, Word, ODT, текст, Markdown, HTML или CSV")
        dst = self.root / name
        n = 2
        while dst.exists():
            dst = self.root / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        dst.write_bytes(data)
        self.refresh()
        return dst.relative_to(self.root).as_posix()

    def remove(self, rel):
        """Документ — в корзину (как всё удаление в Dewiar, см. workspace.remove); путь проверяется — только внутри
        «Знаний». Не удалось отправить в корзину — ValueError, файл остаётся на месте."""
        p = (self.root / str(rel)).resolve()
        if self.root.resolve() not in p.parents or not p.is_file():
            raise ValueError("нет такого файла в «Знаниях»")
        import guard
        try:
            guard.trash([{"path": str(p), "dir": False, "files": 1, "size": p.stat().st_size}])
        except (guard.Blocked, OSError, subprocess.SubprocessError) as e:
            raise ValueError(f"не удалось убрать «{p.name}» в корзину: {e}") from e
        self.refresh()
        return True
