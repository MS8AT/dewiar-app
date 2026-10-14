"""Картинки к рассказу (просьба 14.10: «Лира рассказывает про руническую вязь — пусть показывает изображения, о которых
говорит»). Поиск — Wikimedia Commons: свободные изображения с автором и лицензией, без ключей. Модель вызывает
show_images(query) — запрос лучше по-английски (так у Commons больше находок), русский тоже ищется.
Адрес API можно подменить переменной DEWIAR_COMMONS_API (тесты, зеркало)."""
import html
import os
import re

import httpx

API = os.environ.get("DEWIAR_COMMONS_API") or "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "Dewiar/0.38 (voice assistant; https://dewiar.pro)"}
SKIP = re.compile(r"\b(?:logo|icon|flag of|coat of arms|map of|locator|signature|svg)\b", re.I)


def _clean(v):
    v = html.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))
    return re.sub(r"\s+", " ", v).strip()


def search(query, n=4, width=480):
    """-> [{src, full, page, title, author, license}] — до n картинок по запросу (сначала самые подходящие)."""
    q = (query or "").strip()
    if not q:
        return []
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 16,
              "gsrsearch": f"{q} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size",
              "iiurlwidth": width, "iiextmetadatafilter": "ObjectName|ImageDescription|Artist|LicenseShortName",
              "iiextmetadatalanguage": "ru"}
    r = httpx.get(API, params=params, headers=UA, timeout=12, follow_redirects=True)
    r.raise_for_status()
    pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        if not ii.get("thumburl") or not str(ii.get("mime", "")).startswith("image/") or ii.get("mime") == "image/svg+xml":
            continue
        if (ii.get("width") or 0) < 200:
            continue
        meta = ii.get("extmetadata") or {}
        name = re.sub(r"^File:|\.[a-z0-9]+$", "", p.get("title", ""), flags=re.I).replace("_", " ")
        title = _clean((meta.get("ObjectName") or {}).get("value")) or name
        if SKIP.search(name):
            continue
        thumb = ii["thumburl"]
        out.append({"src": thumb, "full": re.sub(r"/\d+px-", "/1280px-", thumb) if (ii.get("width") or 0) > 1280 else ii.get("url", thumb),
                    "page": ii.get("descriptionurl", ""), "title": title[:120],
                    "desc": _clean((meta.get("ImageDescription") or {}).get("value"))[:200],
                    "author": _clean((meta.get("Artist") or {}).get("value"))[:80],
                    "license": _clean((meta.get("LicenseShortName") or {}).get("value"))[:40]})
        if len(out) >= n:
            break
    return out
