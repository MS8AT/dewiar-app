"""Движок Dewiar: вызов инструментов с подтверждением, напоминания и будильник, синхронизация устройств, деньги.
Примесь класса Engine (core/engine.py): методы смешиваются в него, self — это Engine.
Состав: _use_tool/_confirm (политика, защита и вопрос «да/нет» голосом или кнопками Telegram); звонок будильника
(_on_reminder → _alarm_loop → alarm_finish) и голосовые «отложи/понял»; команды студии для напоминаний и дел;
быстрые ответы без модели (_capture, _say_quick, _money_cmd); сводка месяца для календаря (calendar_month).
Связи: разбор времени — when.py, расписание дел — jobs.py, деньги — money.py, синхронизация — sync.py и cloud.php."""
from engine_base import *  # noqa: F401,F403 — общие импорты и помощники движка


class ToolsMixin:
    # ---------- инструменты ----------

    def _use_tool(self, turn, call, sentences):  # noqa: C901
        """Выполнить вызов инструмента от модели: политика (выключен / спросить), защита от опасного, подтверждение,
        запуск. Шлёт события «tool» в окно. -> результат инструмента или текст для модели (отказ, ошибка, защита)."""
        name, args = call["name"], call["args"]
        on, need_confirm = self.toolbox.policy(name)
        title = self.toolbox.title(name)
        log.info("🛠  %s %s", name, redact(json.dumps(args, ensure_ascii=False))[:200])
        if not on:
            return f"Инструмент {name} выключен пользователем."
        blocked, force, warn_q = self.toolbox.guard(name, args)
        if blocked:
            log.warning("🛡 Защита: %s %s — %s", name, json.dumps(args, ensure_ascii=False)[:200], blocked)
            self.emit("tool", name=name, title=title, status="error", error="защита: " + blocked)
            return (f"Защита Dewiar не дала это сделать: {blocked}. Объясни пользователю коротко и спокойно, что такое "
                    "ассистент не удаляет и не делает (это может сломать компьютер или стереть важное), и предложи "
                    "безопасный вариант — например, назвать конкретные файлы, которые убрать в корзину.")
        if need_confirm and not force and self.toolbox.auto_ok(name, args):
            need_confirm = False                       # команды «только посмотреть» (напр. на сервере) — без вопроса, если так настроено
        if need_confirm or force:
            question = warn_q or self.toolbox.describe(name, args)
            ok = self._confirm(turn, question, sentences)
            if not ok:
                self.emit("tool", name=name, title=title, status="declined")
                return "Пользователь отказался. Ничего не делай и коротко подтверди отказ."
        detail = _tool_detail(name, args)
        self.emit("tool", name=name, title=title, status="run", args=args, detail=detail)
        try:
            res = self.toolbox.run(name, args)
            turn.tools_ok = getattr(turn, "tools_ok", []) + [name]
            out = res["text"] if isinstance(res, dict) else str(res)
            self.emit("tool", name=name, title=title, status="done", detail=detail, result=out[:1500])
            log.info("   ↳ %s", (res["text"] if isinstance(res, dict) else res)[:160].replace("\n", " "))
            return res
        except (ToolError, SkillError, MCPError) as e:
            self.emit("tool", name=name, title=title, status="error", error=str(e))
            return f"Ошибка: {e}"
        except Exception as e:  # noqa: BLE001
            log.exception("инструмент %s", name)
            self.emit("tool", name=name, title=title, status="error", error=str(e))
            return f"Ошибка: {e}"

    def _confirm(self, turn, question, sentences, timeout=15):
        """Спросить голосом и кнопками, дождаться «да»/«нет». -> True, если согласились.
        Ответ приходит из другого потока через pending_confirm (_answer_confirm или кнопка). Голосом — сперва ждём,
        пока договорится уже начатый ответ, затем слушаем timeout секунд; молчание — это «нет»."""
        if turn.via and turn.via.get("confirm"):             # вопрос из Telegram — и подтверждение там же, кнопками
            box = {"event": threading.Event(), "answer": False}
            self.pending_confirm = box
            self.emit("confirm", text=question)
            turn.via["confirm"](question)
            box["event"].wait(300)
            self.pending_confirm = None
            self.emit("confirm_done", ok=box["answer"])
            log.info("Подтверждение (Telegram): %s", "да" if box["answer"] else "нет")
            return box["answer"] and not turn.cancel.is_set()
        sentences.put(_spoken_question(question) + " Скажите «да» или «нет».")
        drained = threading.Event()
        sentences.put(("sync", drained))
        drained.wait(30)
        if turn.cancel.is_set():
            return False
        box = {"event": threading.Event(), "answer": False}
        self.pending_confirm = box
        self.emit("confirm", text=question)
        self.follow_up_until = time.monotonic() + timeout
        self.set_state("listening")
        box["event"].wait(timeout)
        self.pending_confirm = None
        self.emit("confirm_done", ok=box["answer"])
        log.info("Подтверждение: %s", "да" if box["answer"] else "нет")
        self.set_state("thinking")
        return box["answer"]

    def _answer_confirm(self, text):
        """Разобрать услышанное как ответ на вопрос _confirm. -> True, если фраза была ответом и вопрос закрыт."""
        box = self.pending_confirm
        if not box:
            return False
        w = set(re.findall(r"[\wё]+", _norm(text)))
        if w & {"да", "давай", "выполняй", "подтверждаю", "конечно", "ага", "угу", "можно", "делай", "yes", "ок", "окей"}:
            box["answer"] = True
        elif not (w & {"нет", "не", "отмена", "отмени", "стоп", "no", "не надо"}):
            return False                       # непонятный ответ — ждём дальше
        box["event"].set()
        return True

    # ---------- напоминания и будильник ----------

    def _reminder_public(self, x):
        """Напоминание для окна: добавляет when (словами), repeat_text и at_hm («ЧЧ:ММ»)."""
        from when import describe_repeat, human
        try:
            at = datetime.fromisoformat(x["at"])
            when = human(at)
        except (KeyError, ValueError):
            at, when = None, x.get("at", "")
        return dict(x, when=when, repeat_text=describe_repeat(x.get("repeat")), at_hm=f"{at:%H:%M}" if at else "")

    def reminders_list(self):
        return [self._reminder_public(x) for x in self.reminders.items]

    # ---------- синхронизация устройств (core/sync.py) ----------

    def credentials(self):
        """Чем входить в облако. -> (токен, ключ_для_связки, базовый адрес cloud.php).
        Токен — вход в аккаунт dewiar.pro, иначе ключ Dewiar. Если есть и то и другое, ключ отдаётся вторым, чтобы
        сервер связал его с аккаунтом. Адрес — из настроек, иначе из данных аккаунта (services.cloud)."""
        from cloud import base_of
        acc = self.account.token() if self.account.logged_in() else ""
        key = self.s.get("cloud", "key") or ""
        url = self.s.get("cloud", "url") or ""
        if not url and acc:
            svc = (self.account.data.get("services") or {}).get("cloud") or "/dwrapp/cloud.php"
            url = svc if svc.startswith("http") else (self.account.data.get("server") or "https://dewiar.pro").rstrip("/") + "/" + svc.lstrip("/")
        token = acc or key
        return token, (key if acc else ""), base_of(url)

    def _dewiar_web(self, kind, value):
        """Поиск (kind="search") или текст страницы (kind="fetch") через cloud.php — когда провайдер режет поисковик или сайт.
        Нужен вход в аккаунт dewiar.pro или ключ Dewiar, иначе RuntimeError. -> список результатов / текст."""
        import httpx
        token, _, url = self.credentials()
        if not token:
            raise RuntimeError("нет входа в аккаунт dewiar.pro и ключа Dewiar")
        p = {"p": "/search", "q": value} if kind == "search" else {"p": "/fetch", "url": value}
        r = httpx.get(url, params=p, headers={"Authorization": "Bearer " + token}, timeout=40)
        try:
            d = r.json()
        except ValueError:
            d = {}
        if r.status_code != 200:
            raise RuntimeError((d.get("error") or {}).get("message") or f"сервер ответил {r.status_code}")
        return (d.get("results") or []) if kind == "search" else str(d.get("text") or "")

    # ---------- общее для своих устройств (close.own_send, сквозное шифрование): ключ умного дома ----------
    def own_snapshot(self):
        h = self.home.share()
        return {"home": h} if h else None

    def own_apply(self, body):
        h = (body or {}).get("home")
        if isinstance(h, dict) and self.home.adopt(h.get("token"), h.get("at")):
            self.emit("tools", tools=self.toolbox.catalog())

    def own_share(self):
        """Умный дом поменяли здесь — отправить своим устройствам (в фоне; нет связи — дойдёт со следующим изменением)."""
        snap = self.own_snapshot()
        if snap and self.credentials()[0]:
            import threading
            threading.Thread(target=self.close._own_quiet, args=(snap,), daemon=True).start()

    def device_name(self):
        from sync import default_device_name
        return default_device_name()

    def sync_public(self):
        st = dict(self.sync.status)
        tok, _, _ = self.credentials()
        st["available"] = bool(tok)
        st["on"] = self.s.get("sync", "enabled") is not False
        st["via"] = "аккаунту dewiar.pro" if self.account.logged_in() else ("ключу Dewiar …" + (self.s.get("cloud", "key") or "")[-4:] if tok else "")
        return st

    def _on_reminders_changed(self, items):
        """Список напоминаний изменился: поторопить синхронизацию, обновить файл в папке ассистента и окно."""
        sy = getattr(self, "sync", None)
        if sy is not None:
            sy.soon.set()                                         # телефону и другим компьютерам — сразу
        ev = getattr(self, "_tg_sync_soon", None)
        if ev is not None:
            ev.set()                                              # серверу Telegram — чтобы напомнил, даже если компьютер выключен
        self.workspace.sync_reminders(items)
        self.emit("reminders", items=[self._reminder_public(x) for x in items])

    def _on_reminder(self, item):
        """Сработало: окно-будильник по центру, звонок до «Готово»/«Отложить», голос, уведомление, Telegram."""
        text = item["text"]
        log.info("⏰ %s", text)
        self._log_reminder(item)
        if item.get("kind") == "job":                     # дело по расписанию: не звоним, а выполняем
            threading.Thread(target=self._run_job, args=(item,), name="job", daemon=True).start()
            return
        with self._alarm_lock:
            old = self.alarm
            if old:                                       # уже звенит другое — глушим его, оно станет «пропущенным»
                old["done"].set()
            a = {"item": item, "done": threading.Event(), "since": time.monotonic(), "result": ""}
            self.alarm = a
        from when import describe_repeat
        kind = item.get("kind") or "reminder"
        title = {"alarm": "Будильник", "timer": "Таймер"}.get(kind, "Напоминание")
        desktop_notify(f"⏰ {title}: {text}", critical=True)
        self.emit("alarm", id=item["id"], text=text, kind=kind, title=title, late=bool(item.get("late")),
                  at=item.get("at", ""), repeat_text=describe_repeat(item.get("repeat")),
                  window=self.s.get("reminders", "window") is not False)
        self.emit("reminder", text=text)
        if self.chat.notify_on():
            threading.Thread(target=self.chat.notify, args=(f"⏰ {title}: {text}",),
                             kwargs={"buttons": [("Готово", f"alarm:ack:{item['id']}"), ("Через 10 мин", f"alarm:snooze:{item['id']}:10"),
                                                 ("Через час", f"alarm:snooze:{item['id']}:60")]}, daemon=True).start()
        threading.Thread(target=self._alarm_loop, args=(a,), name="alarm", daemon=True).start()

    def _alarm_loop(self, a):
        """Поток звонка: звенит и иногда проговаривает текст, пока не ответят или не выйдет reminders.ring_minutes.
        Без ответа — результат «missed». a — общий с alarm_finish словарь (done, result)."""
        from audio_io import alarm_tone
        item = a["item"]
        kind = item.get("kind") or "reminder"
        limit = max(0.25, float(self.s.get("reminders", "ring_minutes") or 2)) * 60
        pcm = alarm_tone(self.s.get("reminders", "sound") or "bells")
        say = self.s.get("reminders", "speak") is not False
        phrase = ({"alarm": "Пора вставать! ", "timer": "Время вышло! "}.get(kind, "Напоминание: ") +
                  (item["text"] if item["text"] not in ("Будильник", "Таймер", "Напоминание") else "")).strip()
        if item.get("late"):
            phrase = "Пропущенное напоминание: " + item["text"]
        n = 0
        while not a["done"].is_set() and not self.stopping.is_set() and time.monotonic() - a["since"] < limit:
            for _ in range(60):                                # не перебиваем разговор: ждём конца ответа, но не дольше 15 с
                if self.state not in ("speaking", "thinking") or a["done"].is_set():
                    break
                time.sleep(0.25)
            if a["done"].is_set():
                break
            self._ring(pcm, a)
            if a["done"].is_set():
                break
            if say and n in (0, 3, 8):
                self._say_now(phrase, a)
                self.follow_up_until = time.monotonic() + 7    # «отложи на 10 минут» — можно без имени
                self.set_state("listening")
            a["done"].wait(1.2 if n < 3 else 3.0)
            n += 1
        with self._alarm_lock:
            if self.alarm is a:
                self.alarm = None
        if not a["result"]:
            a["result"] = "missed"
            log.info("⏰ Никто не ответил — «%s» отмечено пропущенным", item["text"])
            self.emit("alarm_done", id=item["id"], result="missed")
            if self.state == "listening" and self.turn is None:
                self.set_state("idle")

    def _ring(self, pcm, a):
        """Проиграть звонок один раз отдельным плеером (PCM 16 бит, 22050 Гц) — чтобы не мешать очереди речи."""
        if self.player is None:
            time.sleep(2.4)
            return
        pl = Player(device=self.player.device, null=self.null_player)
        try:
            pl.start(22050)
            step = 22050 * 2 // 10                               # по 0,1 с — чтобы «Готово» обрывало звонок сразу
            for i in range(0, len(pcm), step):
                if a["done"].is_set():
                    break
                pl.write(pcm[i:i + step])
            pl.finish()
        except Exception as e:  # noqa: BLE001
            log.info("Звонок не прозвучал: %s", e)
            time.sleep(1)

    def _say_now(self, text, a=None):
        """Сказать сразу и дождаться конца (из потока будильника)."""
        with self._turn_lock:
            self.turn_n += 1
            turn = Turn(self.turn_n)
            self.turn = turn
        q = queue.Queue()
        q.put(text)
        q.put(None)
        self.emit("answer", text=text, done=True)
        try:
            self._speak_worker(turn, q)
        finally:
            with self._turn_lock:
                if self.turn is turn:
                    self.turn = None
                    self.set_state("idle")

    def alarm_finish(self, result="ack", minutes=0, rid=None):
        """«Готово» или «Отложить на N минут» — кнопкой, голосом, из Telegram."""
        with self._alarm_lock:
            a = self.alarm
            if a is None or (rid and a["item"]["id"] != rid):
                return None
            self.alarm = None
        a["result"] = result
        a["done"].set()
        self.cancel_turn()
        item = a["item"]
        out = {"id": item["id"], "result": result}
        if result == "snooze":
            from when import human
            minutes = max(1, int(minutes or 10))
            when = datetime.now() + timedelta(minutes=minutes)
            new = self.reminders.add(when, item["text"], None, item.get("kind") or "reminder")
            out.update(snooze_id=new["id"], when=human(when))
            log.info("⏰ Отложено на %d мин: %s", minutes, item["text"])
        else:
            log.info("⏰ Готово: %s", item["text"])
        self.emit("alarm_done", **out)
        if self.state == "listening" and self.turn is None:
            self.set_state("idle")
        return out

    SNOOZE_RX = re.compile(r"\b(отлож\w*|позже|потом|ещ[её]\s+\d+|через\s+\d+|через\s+(?:минуту|полчаса|час)|дай\s+поспать|не\s+сейчас)\b")
    ACK_WORDS = {"понял", "поняла", "понятно", "хорошо", "ок", "окей", "ладно", "готово", "сделал", "сделала", "выключи",
                 "выключай", "отключи", "спасибо", "да", "встаю", "встал", "встала", "иду", "всё", "все"}

    def _alarm_voice(self, text):
        """Пока звенит: «отложи на 10 минут» — отложить; «понял/хватит/спасибо» — выключить. True — фраза разобрана."""
        if not self.alarm:
            return False
        low = _norm(text)
        if self.SNOOZE_RX.search(low):
            from when import _num_words
            m = re.search(r"(\d+)\s*(час|мин)?", _num_words(low))
            mins = 10
            if "полчаса" in low:
                mins = 30
            elif m:
                mins = int(m.group(1)) * (60 if (m.group(2) or "").startswith("час") else 1)
            elif re.search(r"\bчас\b", low):
                mins = 60
            r = self.alarm_finish("snooze", mins)
            if r:
                self.emit("heard", text=text)
                self.announce(f"Хорошо, напомню {r['when']}.")
            return True
        words = set(re.findall(r"[\wё]+", low))
        if is_sleep_phrase(text) or words & self.ACK_WORDS:
            if self.alarm_finish("ack"):
                self.emit("heard", text=text)
                self.play_tone("done")
            return True
        self.alarm_finish("ack")                       # заговорили о другом — значит, увидели; продолжаем разговор
        return False

    def _route(self, text):
        """Главный помощник передаёт вопрос специалисту команды (код — Кодеру, письмо — Лире, «включи» — Джарвису…).
        Только если сейчас говорит главный и в студии включено «Команда специалистов». → id или None."""
        if self.s.get("team", "route") is False:
            return None
        cur = self.personas.get(self.s.get("persona"))
        if not cur.get("main"):
            return None
        low = _norm(text)
        order = ["agent", "lira", "jarvis", "eva", "patrik"]
        others = sorted((p for p in self.personas.all() if p.get("route") and p["id"] != cur["id"]),
                        key=lambda p: order.index(p["id"]) if p["id"] in order else -1)   # свои и из галереи — первыми
        for p in others:
            try:
                if re.search(p["route"], low):
                    return p["id"]
            except re.error:
                continue
        return None

    def _alarm_public(self):
        """Что звенит сейчас — для окна-будильника, открытого позже звонка. -> словарь или None."""
        a = self.alarm
        if not a:
            return None
        from when import describe_repeat
        it = a["item"]
        kind = it.get("kind") or "reminder"
        return {"id": it["id"], "text": it["text"], "kind": kind, "late": bool(it.get("late")), "at": it.get("at", ""),
                "title": {"alarm": "Будильник", "timer": "Таймер"}.get(kind, "Напоминание"),
                "repeat_text": describe_repeat(it.get("repeat"))}

    def _reminder_cmd(self, cmd, a):
        """Студия и окно-будильник: список, добавить (словами или датой), изменить, удалить, «Готово», «Отложить»."""
        from tools import ToolError, _when
        from when import parse as parse_when
        if cmd == "reminders":
            return self.reminders_list()
        if cmd == "alarm_get":
            return self._alarm_public()
        if cmd == "alarm_ack":
            return self.alarm_finish("ack", rid=a.get("id"))
        if cmd == "alarm_snooze":
            return self.alarm_finish("snooze", int(a.get("minutes") or 10), rid=a.get("id"))
        if cmd == "alarm_test":                       # «Послушать звонок» в студии
            from audio_io import alarm_tone
            box = {"done": threading.Event()}
            pcm = alarm_tone(a.get("sound") or self.s.get("reminders", "sound") or "bells")
            threading.Thread(target=self._ring, args=(pcm, box), daemon=True).start()
            return True
        if cmd == "reminder_parse":                   # подсказка под полем ввода: как поняли фразу
            r = parse_when("напомни " + (a.get("phrase") or ""))
            if not r:
                return None
            from when import describe_repeat, human
            return {"text": r["text"], "when": human(r["at"]), "repeat_text": describe_repeat(r["repeat"]), "kind": r["kind"]}
        if cmd == "reminder_add":
            phrase = (a.get("phrase") or "").strip()
            if phrase:
                r = parse_when(phrase if re.match(r"(?i)\s*(напомни|напоминай|разбуди|будильник|таймер|засеки)", phrase)
                               else "напомни " + phrase)
                if not r:
                    raise ValueError("не понял, когда напомнить — например: «завтра в 9 позвонить маме»")
                item = self.reminders.add(r["at"], (a.get("text") or r["text"]), r["repeat"], r["kind"])
            else:
                try:
                    when, rep, text, kind = _when(a)
                except ToolError as e:
                    raise ValueError(str(e)) from e
                item = self.reminders.add(when, text or "Напоминание", rep, a.get("kind") or kind)
            return self._reminder_public(item)
        if cmd == "job_add":                          # «Готовые дела» в студии: фраза с расписанием + точный текст дела
            from jobs import parse as parse_job
            c = parse_job(a.get("phrase") or "")
            if not c or c.get("op") != "job":
                raise ValueError("не понял расписание — например: «каждый день в 8:00»")
            deliver = a.get("deliver") if a.get("deliver") in ("telegram", "max", "voice") else c["deliver"]
            bot = self._bot_for(deliver)
            if bot is not None and not bot.paired():
                raise ValueError(f"{bot.TITLE} ещё не подключён — подключите в «Подключение» или выберите «голосом»")
            task = (a.get("task") or c["task"]).strip()
            brief = bool(a["brief"]) if "brief" in a else c["brief"]
            item = self.reminders.add(c["at"], task, c["repeat"], "job", {"deliver": deliver, "brief": brief,
                                                                         "preset": a.get("preset") or ""})
            self.emit("reminder_set", item=self._reminder_public(item))
            return self._reminder_public(item)
        if cmd == "job_run":                          # «Попробовать сейчас» — выполнить дело один раз, не трогая расписание
            task = (a.get("task") or "").strip()
            if not task:
                raise ValueError("пустое дело")
            bot = self._bot_for(a.get("deliver"))
            deliver = a.get("deliver") if bot is not None and bot.paired() else "voice"
            threading.Thread(target=self._run_job, args=({"text": task, "brief": bool(a.get("brief")), "deliver": deliver},),
                             daemon=True).start()
            return {"ok": True, "deliver": deliver}
        if cmd == "reminder_update":
            patch = dict(a.get("patch") or {})
            if patch.get("when"):
                r = parse_when("напомни " + patch.pop("when"))
                if not r:
                    raise ValueError("не понял время")
                patch.update(at=r["at"].isoformat(timespec="seconds"), repeat=r["repeat"])
            r = self.reminders.update(a.get("id"), patch)
            if not r:
                raise ValueError("нет такого напоминания")
            return self._reminder_public(r)
        if cmd == "reminder_cancel":
            return self.reminders.cancel(a.get("id", ""))
        return None

    def _capture(self, c, said, via=None):
        """Заметка, пункт списка или факт о пользователе — сразу в папку ассистента, без модели."""
        try:
            if c["op"] == "note":
                rel = self.workspace.save_note(c["title"], c["text"])
                msg = f"Записал: «{c['title']}»."
                card = {"kind": "note", "title": c["title"], "path": rel, "text": c["text"]}
            elif c["op"] == "list":
                rel, new = self.workspace.list_add(c["name"], c["items"])
                msg = (f"Добавил в «{c['name']}»: {', '.join(new)}." if new else f"Это уже есть в «{c['name']}».")
                card = {"kind": "list", "title": c["name"], "path": rel, "text": ", ".join(c["items"])}
            else:
                msg = self.workspace.remember(c["fact"])
                if c.get("day") and msg != "Это я уже знаю.":     # план с датой — назвать её: человек сразу слышит, как поняли
                    from when import human
                    day = re.sub(r",?\s+в\s+\d{1,2}:\d\d$", "", human(datetime.combine(c["day"], datetime.min.time())))
                    msg = f"Запомнил — {day}."
                rel = "Память/Обо мне.md"
                card = {"kind": "fact", "title": "Память о вас", "path": rel, "text": c["fact"]}
        except WorkspaceError as e:
            log.info("Быстрая заметка не записалась (%s) — спрошу модель", e)
            return False
        log.info("📝 %s → %s", c["op"], rel)
        self.emit("note_saved", **card)
        self._say_quick(msg, said, via)
        return True

    def _say_quick(self, msg, said, via=None, then=None, note=None):
        """Ответить одной фразой без модели (поставил напоминание, записал заметку) и запомнить в разговоре.
        then() — когда фраза сказана (и если её не перебили): «спрячься» прячет виджет уже после «Прячусь».
        note — как получен ответ (расчёт с числами): только в историю, чтобы на «как ты посчитал?» модель знала."""
        msg = self._g(msg)                                  # в роде персонажа: «Выключила музыку»
        log.info("⚡ %s → %s", redact(said), redact(msg))      # быстрый ответ без модели — тоже в журнал
        if via:
            via["done"](msg)
            return
        self.emit("heard", text=said)
        self.emit("answer", text=msg, done=True)
        q = queue.Queue()
        q.put(msg)
        q.put(None)
        with self._turn_lock:
            self._cancel_locked()
            self.turn_n += 1
            turn = Turn(self.turn_n)
            self.turn = turn

        def run():
            self._speak_worker(turn, q)
            self.history += [{"role": "user", "content": said}, {"role": "assistant", "content": msg + (f" (Расчёт: {note}.)" if note else ""),
                                                                 "who": self.s.get("persona")}]
            self._conv_after()
            with self._turn_lock:
                if self.turn is turn:
                    self.turn = None
                    self.set_state("idle")
            if then and not turn.cancel.is_set():
                then()
        threading.Thread(target=run, daemon=True).start()

    # ---------- деньги: «купил … за …», «получил зарплату …», «сколько я потратил …» ----------

    def _default_currency(self):
        """Валюта из настроек, иначе догадка по часовому поясу системы (Минск, Киев, Алматы), по умолчанию RUB."""
        c = (self.s.get("money", "currency") or "").strip().upper()
        if c:
            return c
        try:
            tz = Path("/etc/timezone").read_text().strip() if Path("/etc/timezone").exists() else os.path.realpath("/etc/localtime")
        except OSError:
            tz = ""
        tz = tz or time.tzname[0]
        return "BYN" if "Minsk" in tz else "UAH" if "Kiev" in tz or "Kyiv" in tz else "KZT" if "Almaty" in tz else "RUB"

    def _money_cmd(self, text, via=None):
        """Записать доход/расход, отменить последнюю запись (не старше 3 дней) или ответить «сколько потратил».
        -> True, если фраза разобрана и ответ дан без модели."""
        from money import fmt, parse
        c = parse(text, self._default_currency())
        if not c:
            return False
        if c["op"] == "add":
            it = self.money.add(c["kind"], c["amount"], c["currency"], c["category"], c["note"], c["date"], said=text)
            what = "доход" if it["kind"] == "income" else "расход"
            today = datetime.now().date()
            d = datetime.fromisoformat(it["date"]).date()
            # пометку даты — по самой дате записи, не по «не сегодня»: иначе любой другой день назывался бы «вчера»
            day = "" if d == today else " (вчера)" if d == today - timedelta(days=1) else f" ({d:%d.%m})"
            msg = f"Записал {what}{day}: {fmt(it['amount'], it['currency'])} — {it['category'].lower()}" + \
                  (f", {it['note']}" if it["note"] and it["note"].lower() not in it["category"].lower() else "") + "."
            self.emit("money_saved", **it)
            self._say_quick(msg, text, via)
            return True
        if c["op"] == "undo":
            last = self.money.last()
            if not last or time.time() - last.get("created", 0) > 3 * 86400:
                return False
            self.money.delete(last["id"])
            self.emit("money_saved", deleted=last["id"])
            self._say_quick(f"Удалил запись: {fmt(last['amount'], last['currency'])} — {last['category'].lower()}.", text, via)
            return True
        if c["op"] == "query":
            s, e = c["period"]
            if not self.money.summary(s.isoformat(), e.isoformat())["count"]:
                return False                     # записей нет — пусть ответит модель: о деньгах могли говорить в разговоре
            self._say_quick(self.money.answer(c), text, via)
            return True
        return False

    def calendar_month(self, year, month):
        """Всё по дням месяца: напоминания (будущие и сработавшие), деньги, заметки, дневник, задачи."""
        import calendar as _cal
        from when import next_time
        first = datetime(year, month, 1)
        last = datetime(year, month, _cal.monthrange(year, month)[1], 23, 59, 59)
        days = {}

        def put(day, item):
            days.setdefault(day, []).append(item)
        for r in self.reminders.items:                          # будущие (с повторами — все случаи в месяце)
            try:
                at = datetime.fromisoformat(r["at"])
            except (KeyError, ValueError):
                continue
            n = 0
            while at <= last and n < 400:                        # предел — чтобы частый повтор не раздул месяц и не зациклил
                if at >= first:
                    put(at.date().isoformat(), {"type": "reminder", "id": r["id"], "time": at.strftime("%H:%M"),
                                                "title": r["text"], "kind": r.get("kind") or "reminder",
                                                "repeat": bool(r.get("repeat")), "paused": bool(r.get("paused"))})
                if not r.get("repeat"):
                    break
                at = next_time(r["repeat"], at)
                n += 1
        for h in self._reminder_log():                          # что уже звенело
            d = h.get("at", "")[:10]
            if first.date().isoformat() <= d <= last.date().isoformat():
                put(d, {"type": "reminder", "time": h["at"][11:16], "title": h.get("text", ""), "done": True,
                        "kind": h.get("kind") or "reminder"})
        for m in self.money.list(first.date().isoformat(), last.date().isoformat()):
            put(m["date"], {"type": "money", "id": m["id"], "kind": m["kind"], "amount": m["amount"],
                            "currency": m["currency"], "title": m["note"] or m["category"], "category": m["category"]})
        root = self.workspace.root
        for folder, typ in (("Заметки", "note"), ("Дневник", "diary")):
            base = root / folder
            if not base.is_dir():
                continue
            for p in base.rglob("*.md"):
                try:
                    mt = datetime.fromtimestamp(p.stat().st_mtime)
                except OSError:
                    continue
                if typ == "diary":
                    try:
                        mt = datetime.fromisoformat(p.stem[:10])
                    except ValueError:
                        pass
                if first <= mt <= last:
                    put(mt.date().isoformat(), {"type": typ, "title": p.stem if typ == "note" else "Дневник",
                                                "path": p.relative_to(root).as_posix(), "time": mt.strftime("%H:%M")})
        try:
            for e in self.calendars.events(first, last + timedelta(seconds=1)):
                d = e["start"]
                while d.date() <= min(e["end"] - timedelta(seconds=1), last).date():   # многодневные — на каждый день
                    if d >= first:
                        put(d.date().isoformat(), {"type": "event", "time": "" if e["allday"] else e["start"].strftime("%H:%M"),
                                                   "end": "" if e["allday"] else e["end"].strftime("%H:%M"), "title": e["title"],
                                                   "place": e.get("place", ""), "cal": e["cal"], "color": e["color"]})
                    d = datetime.combine(d.date() + timedelta(days=1), datetime.min.time())
                    if not e["allday"] and d >= e["end"]:
                        break
        except Exception as e:  # noqa: BLE001
            log.debug("календари: %s", e)
        try:                                                   # планы из памяти с датой: «встреча в среду» (capture.plan_day)
            from capture import PLAN_DAY
            for line in self.workspace.memory_get().splitlines():
                m = PLAN_DAY.search(line)
                if not m:
                    continue
                d = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                if first.date().isoformat() <= d <= last.date().isoformat():
                    t = re.sub(r"^\s*-\s*(?:Со слов пользователя:\s*)?", "", line[:m.start()]).strip(" .")
                    hm = re.search(r"\b(?:в|к)\s+(\d{1,2})[:.](\d\d)\b", t)
                    put(d, {"type": "event", "time": f"{int(hm.group(1)):02d}:{hm.group(2)}" if hm else "", "end": "",
                            "title": t[:1].upper() + t[1:], "place": "", "cal": "Память", "color": ""})
        except Exception:  # noqa: BLE001
            log.debug("календарь: планы из памяти", exc_info=True)
        try:
            for t in self.tasks.list():
                d = (t.get("created") or "")[:10]
                if first.date().isoformat() <= d <= last.date().isoformat():
                    put(d, {"type": "task", "id": t.get("id"), "title": t.get("title", ""), "status": t.get("status_ru", "")})
        except Exception:  # noqa: BLE001
            pass
        for v in days.values():
            v.sort(key=lambda x: (x.get("time") or "99", x["type"]))
        return {"year": year, "month": month, "days": days,
                "money": self.money.summary(first.date().isoformat(), last.date().isoformat()),
                "currency": self._default_currency()}

    def _reminder_log(self):
        """Журнал сработавших напоминаний (reminders-log.json, последние 2000): [{at, text, kind, id}]."""
        try:
            return json.loads((STATE_DIR / "reminders-log.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _log_reminder(self, item):
        log_ = self._reminder_log()[-1999:]
        log_.append({"at": datetime.now().isoformat(timespec="seconds"), "text": item.get("text", ""),
                     "kind": item.get("kind") or "reminder", "id": item.get("id")})
        try:
            p = STATE_DIR / "reminders-log.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(log_, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
