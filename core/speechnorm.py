"""Текст для русского синтеза речи: числа — словами, латиница — русскими буквами, служебные символы — прочь.

Голоса Vosk TTS знают только русские буквы: на «1», «USB», «16:30» синтез падает или фраза пропадает целиком.
Вызывается из VoskTTS.synth (tts.py) перед синтезом; итог должен состоять только из кириллицы и простой пунктуации
(последний фильтр в speech_norm). Новые английские слова с особым чтением — в _KNOWN.
    speech_norm("Ядро 6.17, порт USB 3, в 16:30 — 45%")
    → "Ядро шесть точка семнадцать, порт ю-эс-би три, в шестнадцать тридцать — сорок пять процентов"
"""

import re

_ONES = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать",
         "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать",
         "девятнадцать"]
_ONES_F = {1: "одна", 2: "две"}
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUND = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_SCALES = [(10 ** 12, ("триллион", "триллиона", "триллионов"), False), (10 ** 9, ("миллиард", "миллиарда", "миллиардов"), False),
           (10 ** 6, ("миллион", "миллиона", "миллионов"), False), (1000, ("тысяча", "тысячи", "тысяч"), True)]


def _plural(n, forms):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def _under_1000(n, fem=False):
    out = []
    if n >= 100:
        out.append(_HUND[n // 100])
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10])
        n %= 10
    if n or not out:
        if n or not out:
            out.append(_ONES_F.get(n, _ONES[n]) if fem and n in _ONES_F else _ONES[n])
    return [w for w in out if w and not (w == "ноль" and len(out) > 1)]


def number_words(n, fem=False):
    """Целое число → слова: 2026 → «две тысячи двадцать шесть»."""
    n = int(n)
    if n < 0:
        return "минус " + number_words(-n, fem)
    if n == 0:
        return "ноль"
    words = []
    for value, forms, female in _SCALES:
        if n >= value:
            k = n // value
            if k > 1:
                words += _under_1000(k, fem=female) if k < 1000 else number_words(k).split()
            words.append(_plural(k, forms))
            n %= value
    if n:
        words += _under_1000(n, fem)
    return " ".join(words)


_LETTER = {"a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч", "i": "ай", "j": "джей",
           "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи", "q": "кью", "r": "ар", "s": "эс", "t": "ти",
           "u": "ю", "v": "ви", "w": "дабл-ю", "x": "экс", "y": "уай", "z": "зед"}
_TR2 = [("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("ck", "к"), ("oo", "у"), ("ee", "и"), ("ea", "и"),
        ("ou", "ау"), ("qu", "кв"), ("kh", "х"), ("zh", "ж"), ("ya", "я"), ("yu", "ю"), ("yo", "ё"), ("ts", "ц")]
_TR1 = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "и", "z": "з"}
_KNOWN = {"linux": "линукс", "ubuntu": "убунту", "windows": "виндоус", "telegram": "телеграм", "max": "макс", "dewiar": "дэвиаар",
          "youtube": "ютуб", "google": "гугл", "yandex": "яндекс", "wifi": "вай-фай", "wi-fi": "вай-фай", "ok": "окей",
          "email": "имейл", "sudo": "судо", "python": "пайтон", "chrome": "хром", "obsidian": "обсидиан", "android": "андроид",
          "iphone": "айфон", "bluetooth": "блютус", "hdmi": "эйч-ди-эм-ай", "jazz": "джаз", "relax": "релакс", "fm": "эф-эм"}


def latin_word(w):
    low = w.lower()
    if low in _KNOWN:
        return _KNOWN[low]
    if w.isupper() and len(w) <= 6 or len(w) == 1:              # USB, HDMI, AI — по буквам
        return "-".join(_LETTER.get(c, c) for c in low)
    out, i = "", 0
    while i < len(low):
        for a, b in _TR2:
            if low.startswith(a, i):
                out, i = out + b, i + len(a)
                break
        else:
            out += _TR1.get(low[i], low[i])
            i += 1
    return out


def _num(m):
    s = m.group(0)
    if ":" in s:                                                  # время 16:30
        h, mi = s.split(":", 1)
        return number_words(int(h)) + (" ноль " + number_words(int(mi)) if mi.startswith("0") and mi != "00"
                                       else "" if mi == "00" else " " + number_words(int(mi)))
    parts = re.split(r"[.,]", s)
    if len(parts) == 1:                                           # длиннее 15 цифр (номера, коды) — по одной цифре
        return number_words(int(s)) if len(s) <= 15 else " ".join(number_words(int(c)) for c in s)
    return " точка ".join(number_words(int(p)) if p else "" for p in parts)


_FRAC = {1: ("десятая", "десятых", "десятых"), 2: ("сотая", "сотых", "сотых")}
_MONEY = {"rub": (("рубль", "рубля", "рублей"), ("копейка", "копейки", "копеек")),
          "usd": (("доллар", "доллара", "долларов"), ("цент", "цента", "центов")),
          "eur": (("евро", "евро", "евро"), ("цент", "цента", "центов"))}


def _money(m, cur):
    n, k = int(m.group("n")), m.group("k")
    rub, kop = _MONEY[cur]
    out = f"{number_words(n)} {_plural(n, rub)}"
    if k and int(k.ljust(2, "0")):
        kk = int(k.ljust(2, "0"))
        out += f" {number_words(kk, fem=cur == 'rub')} {_plural(kk, kop)}"
    return out


def _decimal(m):
    """«399,5» → «триста девяносто девять и пять десятых» (запятая — дробь; точка — версии и номера, «шесть точка семнадцать»)."""
    a, b = m.group(1), m.group(2)
    return f"{number_words(int(a), fem=True)} и {number_words(int(b), fem=True)} {_plural(int(b), _FRAC[len(b)])}"


def speech_norm(text, latin=True):
    """latin=False — только числа, суммы, проценты, время (Piper, eSpeak, голос Windows: латиницу они читают сами)."""
    t = str(text or "")
    for _ in range(3):                                             # «1 437 500» — одно число (разряды через пробел)
        t = re.sub(r"(?<![\d.,])(\d{1,3})[ \u00a0\u202f](?=\d{3}(?!\d))", r"\1", t)
    num = r"(?P<n>\d+)(?:[.,](?P<k>\d{1,2}))?"
    t = re.sub(num + r"\s*(?:руб(?:л[а-яё]*)?\.?|₽|р\.|BYN|RUB)(?![а-яёА-ЯЁA-Za-z])", lambda m: _money(m, "rub"), t)
    t = re.sub(r"\$\s*" + num + r"|" + num.replace("?P<n>", "?P<n2>").replace("?P<k>", "?P<k2>") + r"\s*(?:\$|долл\.|USD)",
               lambda m: _money(re.match(num, (m.group("n") or m.group("n2")) + ("," + (m.group("k") or m.group("k2")) if (m.group("k") or m.group("k2")) else "")), "usd"), t)
    t = re.sub(num + r"\s*(?:€|EUR)", lambda m: _money(m, "eur"), t)
    t = re.sub(r"(?<![\d.,:])(\d{1,9}),(\d{1,2})(?!\d|[.,]\d)", _decimal, t)
    t = re.sub(r"https?://\S+", "ссылка", t)
    if latin:
        t = re.sub(r"\b(?=\w*\d)(?=\w*[A-Za-z])[A-Za-z0-9_]{4,}\b", " ", t)   # 17e9, x86_64 — служебные метки вслух не нужны
    t = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", t)     # USB3 → USB 3: буквы и цифры читаются по-разному
    t = re.sub(r"(\d)\s*%", r"\1 процентов", t)
    t = re.sub(r"(?<![\w-])-(?=\d)", "минус ", t)
    t = re.sub(r"\b([01]?\d|2[0-3]):[0-5]\d\b|\d+(?:[.,]\d+)*", _num, t)
    if not latin:
        return re.sub(r"[ \t]+", " ", t.replace("№", "номер ")).strip()
    t = re.sub(r"[A-Za-z]+(?:-[A-Za-z]+)?", lambda m: latin_word(m.group(0)), t)
    t = t.replace("&", " и ").replace("+", " плюс ").replace("=", " равно ").replace("№", "номер ")
    t = re.sub(r"[^А-Яа-яЁё ,.!?:;—\-«»\"()']+", " ", t)
    return re.sub(r"\s+", " ", t).strip()
