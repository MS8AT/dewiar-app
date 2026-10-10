"""Движок Dewiar — слух и голос: выбор движков распознавания и речи, скачивание моделей, аудиопоток
(VAD, слово запуска, нарезка фраз, перебивание), распознавание и поиск имени, созвоны, своё эхо.
Часть класса Engine (core/engine.py): методы смешиваются в него, self — это Engine.
Потоки: audio (_audio_loop → _listen), stt (_stt_worker), name-check (_check_worker) и фоновые циклы.
Числа в кадрах: один кадр — FRAME_S (32 мс), т. е. 31 кадр ≈ 1 с. Готовая фраза уходит в handle_text,
дальше — ask() в engine_answer.py."""
from engine_base import *  # noqa: F401,F403 — общие импорты и помощники движка


class AudioMixin:
    # ---------- настройка движков ----------

    def build_spotter(self):
        """Пересобирает слух имён. Имена, все слова которых есть в словаре Vosk, ловит быстрый WakeSpotter
        мгновенно; остальные (self.asr_names, например «Девиар») — только точной моделью в каждой фразе
        (_check_worker) или по отпечатку голоса. Обновляет и self.aliases — имена для find_name."""
        if self.vosk_model is None:           # слух ещё запускается — соберём, когда будет модель
            return
        only = None if self.s.get("all_names") else self.s.get("persona")
        wm = self.personas.wake_map(only=only)
        words = {w for phrase in wm for w in phrase.split()}
        vf = STATE_DIR / "vocab.json"                   # есть ли слово в словаре Vosk — помним между запусками: проверка
        if not self._vocab:                             # грузит модель ещё раз в отдельном процессе (секунды процессора)
            try:
                d = json.loads(vf.read_text(encoding="utf-8"))
                if d.get("model") == Path(self.vosk_dir).name:
                    self._vocab.update({k: bool(v) for k, v in (d.get("words") or {}).items()})
            except (OSError, ValueError, AttributeError):
                pass
        unknown = [w for w in words if w not in self._vocab]
        if unknown:
            miss = set(missing_words(self.vosk_dir, unknown))
            self._vocab.update({w: w not in miss for w in unknown})
            try:
                vf.write_text(json.dumps({"model": Path(self.vosk_dir).name, "words": self._vocab}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        fast = [p for p in wm if all(self._vocab.get(w) for w in p.split())]
        self.asr_names = sorted(p for p in wm if p not in fast)
        self.spotter = WakeSpotter(self.vosk_model, fast, self.decoys)
        self.aliases = {p["id"]: p.get("aliases") or p.get("wake") or [p["name"]]
                        for p in self.personas.all() if not only or p["id"] == only}
        log.info("Имена (мгновенно): %s; через точное распознавание: %s",
                 ", ".join(sorted(fast)) or "—", ", ".join(self.asr_names) or "—")
        self._names_note()

    def wake_checker(self):
        """Чем искать имя в произвольной фразе: локальный GigaAM, иначе ваш сервер распознавания."""
        if self.gigaam is not None and self.gigaam.ready:
            return self.gigaam
        if isinstance(getattr(self, "stt", None), RemoteSTT):
            return self.stt
        return None

    def _names_note(self):
        """Подсказка, если имя персонажа пока нечем надёжно услышать."""
        if not self.asr_names or not self.s.get("audio", "asr_wake") or self.wake_checker() is not None:
            return
        wm = self.personas.wake_map()
        untaught = [n for n in self.asr_names if not self.voiceprints.has(wm.get(n, ""))]
        if untaught:
            names = ", ".join(n.capitalize() for n in untaught)
            self.note(f"Научите меня имени «{names}»: студия → «Слух» → «Научить имени» (три раза сказать имя).")

    def apply_engines(self):
        """Выставляет распознаватель и удалённый голос по настройкам и сообщает статус в интерфейс.
        GigaAM пересоздаётся только при смене модели — загрузка тяжёлая (её делает _background_loads)."""
        if self.vosk_model is None:           # слух ещё запускается — движки выставит _start_hearing
            return
        st = self.s.get("stt")
        if st["engine"] == "remote" and st["remote"].get("base_url"):
            self.stt = RemoteSTT(st["remote"])
        elif st["engine"] == "gigaam":
            if not self.gigaam or self.gigaam.model_name != st["gigaam_model"]:
                self.gigaam = GigaAMSTT(st["gigaam_model"])
            self.stt = self.gigaam
        else:
            self.stt = self.vosk_stt
        tt = self.s.get("tts")
        self.tts_remote = RemoteTTS(tt["remote"]) if tt["engine"] == "remote" and tt["remote"].get("base_url") else \
            ElevenTTS(tt.get("eleven") or {}) if tt["engine"] == "elevenlabs" and (tt.get("eleven") or {}).get("api_key") else None
        prof = self.s.active_llm()
        self.status.update(stt=self.stt.name, stt_ready=getattr(self.stt, "ready", True),
                           tts={"piper": "Piper", "vosk": "Vosk TTS" + ("" if self.vosk_tts.ready else " (загружается, пока Piper)"),
                                "remote": "Удалённый голос", "elevenlabs": "ElevenLabs", "espeak": "Голос Windows" if os.name == "nt" else "eSpeak", "off": "Выключен"}.get(tt["engine"], tt["engine"]),
                           llm=(prof or {}).get("name", ""))
        self.emit("status", status=self.status)

    def _background_loads(self):
        """Поток loader: загрузка GigaAM (до готовности распознаёт Vosk, см. current_stt) и голоса персонажа."""
        low_priority()
        self._names_note()
        if isinstance(self.stt, GigaAMSTT) and not self.stt.ready:
            self.note("Загружаю GigaAM (при первом запуске ~250 МБ) — пока распознаю запасной моделью")
            self._load("stt", "Точное распознавание речи" if self.stt.cached() else "Скачиваю точное распознавание речи (~250 МБ)")
            if not self.stt.cached():
                m = self._mirror("gigaam")
                if m and m.get("name", self.stt.model_name) == self.stt.model_name:
                    self.stt.mirror = m
            ok = self.stt.load(on_progress=lambda f: self._dl("stt", f))
            self._loaded("stt")
            self.status["stt_ready"] = ok
            self.note("" if ok else f"GigaAM не загрузился: {self.gigaam.error}. Работаю на Vosk.")
            if not ok:
                self._names_note()
        self.ensure_voice(self.s.get("persona"))
        self.health_mark("full")                               # загрузилось всё: распознавание и голос персонажа

    def _mirror(self, key):
        """Модель на своём сайте (dewiar.pro/dwrapp): {"url", "sha256", …} или None."""
        try:
            return self.updater.model(key) if self.updater else None
        except Exception as e:  # noqa: BLE001
            log.info("Зеркало моделей: %s", e)
            return None

    def _mirror_url(self, key):
        """Адрес зеркала для малой модели Vosk — только если её ещё нет ни распакованной, ни архивом
        (проверка пути — именно vosk-model-small-ru-0.22, вызывается с key="vosk_small")."""
        have = (MODELS_DIR / "vosk-model-small-ru-0.22" / "am").exists() or (DATA_DIR / "vosk-model-small-ru-0.22.zip").exists()
        m = None if have else self._mirror(key)
        return (m or {}).get("url")

    def ensure_vosk_tts(self):
        """Голоса Vosk TTS: скачать (один раз) и загрузить в потоке vosk-tts; до готовности говорим Piper."""
        if self.vosk_tts.ready or self._vosk_loading:
            return
        self._vosk_loading = True
        # откуда качать: адрес из настроек → зеркало модели с сайта (с sha256) → зеркало из манифеста обновлений
        m = None if self.s.get("tts", "vosk_url") or self.vosk_tts.installed() else self._mirror("vosk_tts")
        self.vosk_tts.mirror = self.s.get("tts", "vosk_url") or (m or {}).get("url") or self.updater.mirrors.get("vosk_tts") or ""
        self.vosk_tts.mirror_sha = (m or {}).get("sha256") or ""

        def run():
            low_priority()
            self._load("voices", "Голоса персонажей" if self.vosk_tts.installed() else "Скачиваю голоса персонажей (~200 МБ)")
            try:
                self.vosk_tts.ensure(on_progress=lambda f: self._dl("voices", f), on_status=self.note)
                self.note("")
                log.info("Vosk TTS готов: %s", self.vosk_tts.speakers)
                self.emit("voices", speakers=self.vosk_tts.speakers)
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if isinstance(e, ImportError):
                    err = "не установлена библиотека vosk-tts — выполните в терминале: sudo /opt/dewiar/dewiar-env"
                self.vosk_tts.error = err
                log.warning("Vosk TTS не загрузился: %s", e)
                self.note(f"Новые голоса не загрузились ({err[:120]}) — говорю голосами Piper")
            finally:
                self._vosk_loading = False
                self._loaded("voices")
                self.apply_engines()
        threading.Thread(target=run, name="vosk-tts", daemon=True).start()

    def ensure_voice(self, pid):
        """Готовит голос персонажа: Vosk TTS (в фоне) и голос Piper — он нужен и как запасной для Vosk.
        Piper качается синхронно, в вызывающем потоке."""
        if self.s.get("tts", "engine") == "vosk":
            self.ensure_vosk_tts()
        if self.s.get("tts", "engine") not in ("piper", "vosk"):
            return
        vid = self.personas.get(pid)["voice"].get("piper", "ru_RU-denis-medium")
        if self.piper.has(vid):
            return
        try:
            self.note(f"Скачиваю голос {PIPER_VOICES.get(vid, vid)}…")
            self._load("voice", f"Скачиваю голос {PIPER_VOICES.get(vid, vid)}")
            self.piper.mirror = self._mirror("piper")
            self.piper.ensure(vid, on_progress=lambda f: self._dl("voice", f))
            self.note("")
        except Exception as e:  # noqa: BLE001
            log.warning("Голос не скачался: %s", e)
            self.note("Голос не скачался — пока говорю аварийным голосом eSpeak")
        finally:
            self._loaded("voice")

    def _dl(self, what, frac):
        """Ход скачивания: окнам — не на каждый кусок (их тысячи), а когда доля сдвинулась на 2%."""
        prev = self.status["downloads"].get(what)
        self.status["downloads"][what] = round(frac, 2)
        ld = self.status.setdefault("loading", {}).get(what)
        if ld is not None:
            ld["f"] = round(frac, 2)
        if prev is None or int(frac * 50) != int(prev * 50) or frac >= 1:
            self.emit("status", status=self.status)

    # ---------- первая загрузка: что готовится сейчас (виджет и студия показывают с долей) ----------

    def _load(self, key, label):
        """Этап загрузки начался: status.loading[key] = {t: что делаю, f: доля скачивания или None}."""
        self.status.setdefault("loading", {})[key] = {"t": label, "f": None, "ts": int(time.time())}
        self.emit("status", status=self.status)

    def _loaded(self, key):
        """Этап закончился (удачно или нет) — убрать из списка и из скачиваний."""
        changed = self.status.setdefault("loading", {}).pop(key, None) is not None
        changed = self.status["downloads"].pop(key, None) is not None or changed
        if changed:
            self.emit("status", status=self.status)

    def current_stt(self):
        """Выбранный распознаватель, а пока он не загрузился (GigaAM) — Vosk."""
        stt = getattr(self, "stt", None)
        if stt is None or not getattr(stt, "ready", True):
            return self.vosk_stt
        return stt

    # ---------- аудиопоток ----------

    def _open_audio(self):
        """Открывает микрофон и динамик. С эхоподавлением (AEC) слушаем его источник и играем в его приёмник,
        иначе — выбранные устройства напрямую. status["aec"] — можно ли слушать во время своего ответа."""
        a = self.s.get("audio")
        if self.wav_input:
            use_aec = os.environ.get("DEWIAR_ASSUME_AEC") == "1"      # тесты: в файле нет эха
        else:
            use_aec = a["echo_cancel"] and self.aec.setup(a["input"], a["output"])
        headphones = bool(a.get("headphones")) and not use_aec
        self.status["aec"] = bool(use_aec) or headphones        # «можно слушать во время ответа»: в наушниках эха нет
        self.status["headphones"] = headphones
        self.capture = Capture(device=AEC_SOURCE if use_aec else a["input"], wav_path=self.wav_input,
                               realtime=True)
        if self.player is None:                  # голос — и без микрофона: напечатанный вопрос получит ответ вслух
            self.player = Player(device=a["output"], on_level=lambda v: self._level(v, "voice"), null=self.null_player)
        self.status["input"] = self.capture.open()
        dev = AEC_SINK if use_aec else a["output"]
        if self.player is None or self.player.device != dev:
            self.player = Player(device=dev, on_level=lambda v: self._level(v, "voice"), null=self.null_player)
        log.info("Микрофон: %s; эхоподавление: %s", self.status["input"], "да" if use_aec else "нет")
        self.emit("status", status=self.status)

    def _audio_loop(self):
        """Поток audio: держит микрофон открытым и переоткрывает его после сбоя или restart_audio;
        нет микрофона — ждём подключения, отвечать можно по написанному. Для wav-файла (тесты) — один проход и «eof»."""
        last_err = None
        while not self.stopping.is_set():
            try:
                self._open_audio()
                last_err = None
                self._listen()
            except Exception as e:  # noqa: BLE001
                no_mic = "device -1" in str(e) or "No Default Input" in str(e) or "Invalid device" in str(e)
                if str(e) != last_err:              # подробно — один раз; повторы (нет микрофона) — строкой
                    if no_mic:
                        log.warning("Микрофон не найден (%s) — жду, пока его подключат", e)
                    else:
                        log.exception("Сбой аудиопотока")
                    last_err = str(e)
                else:
                    log.debug("Сбой аудиопотока (повтор): %s", e)
            if self.capture:
                self.capture.close()
            if self.wav_input:
                self.emit("eof")
                return
            if not self.stopping.is_set():
                if self.restart_audio.is_set():
                    self.restart_audio.clear()
                    self.aec.teardown()
                elif last_err and ("device -1" in last_err or "No Default Input" in last_err or "Invalid device" in last_err):
                    self.note("Микрофон не найден — подключите его или выберите в студии («Слух»)"
                              + ("; в Windows проверьте «Параметры → Конфиденциальность → Микрофон» — доступ для приложений"
                                 if os.name == "nt" else "") + ". Пока можно писать в виджете.")
                    self.stopping.wait(5)
                else:
                    self.note("Микрофон недоступен — переподключаюсь…")
                    time.sleep(2)

    def _mic_silent(self, exact=True):
        """Микрофон открыт, а звука нет: ровные нули (exact) — в Windows так выглядит запрет доступа к микрофону;
        почти нули — выбран виртуальный микрофон (HitPaw, VB-Cable, Voicemod…) или громкость записи на нуле.
        Подбирает подсказку по списку устройств и показывает её (заметка, уведомление, отчёт о проблеме);
        в Windows при запрете доступа сразу открывает нужную страницу параметров."""
        virt = re.compile(r"virtual|vb-audio|cable output|voicemod|hitpaw|stereo mix|стерео ?микшер|what u hear|loopback", re.I)
        mapper = re.compile(r"sound mapper|переназначение звук|первичный драйвер", re.I)
        try:
            srcs = [d for d in list_devices() if d.get("kind") == "source"]
        except Exception:  # noqa: BLE001
            srcs = []
        cur = self.s.get("audio", "input") or ""
        names = [(d.get("description") or d.get("name") or "") for d in srcs if not mapper.search(d.get("description") or d.get("name") or "")]
        fake = [n for n in names if virt.search(n)]
        real = [n for n in names if not virt.search(n)]
        if fake and not real:
            text = (f"Микрофон молчит: Windows видит только виртуальный микрофон «{fake[0]}» — настоящего нет. Подключите микрофон "
                    "(или включите его в «Параметры → Система → Звук»), затем выберите его в студии → «Слух»." if os.name == "nt" else
                    f"Микрофон молчит: есть только виртуальный «{fake[0]}». Подключите настоящий и выберите его в студии → «Слух».")
        elif virt.search(cur) or (not cur and fake and os.name == "nt"):
            text = (f"Микрофон почти ничего не слышит — похоже, слушаю виртуальный «{cur or fake[0]}». "
                    f"Выберите настоящий микрофон{' («' + real[0] + '»)' if real else ''} в студии → «Слух».")
        elif exact and os.name == "nt":
            text = ("Микрофон молчит: Windows не даёт программам его слушать. Откройте «Параметры → Конфиденциальность и защита → "
                    "Микрофон» и включите «Доступ к микрофону» и «Разрешить классическим приложениям доступ к микрофону». "
                    "Или выберите другой микрофон в студии → «Слух».")
        elif exact:
            text = "Микрофон молчит — проверьте, что он включён и не выключен звук записи, или выберите другой в студии → «Слух»."
        else:
            text = ("Микрофон почти ничего не слышит: громкость записи на нуле или выбран не тот микрофон. Проверьте уровень "
                    "микрофона в настройках звука системы или выберите другой в студии → «Слух».")
        if not exact and time.monotonic() - getattr(self, "_mic_hint_at", -1e9) < 1800:
            return                                       # «почти тишина» бывает и в очень тихой комнате — не чаще раза в полчаса
        self._mic_hint_at = time.monotonic()
        log.warning("🎤 15 с от микрофона %s — %s (микрофоны: %s)", "полная тишина (нули)" if exact else "почти тишина (пик ≤ 3)",
                    text[:80], ", ".join(names) or "—")
        self.note(text)
        self.push("Микрофон молчит", text, telegram=False)
        self.report_problem("mic_silent", "микрофон молчит: " + ("нули" if exact else "почти тишина") + f"; устройства: {', '.join(names)[:200]}")
        if exact and os.name == "nt" and not fake:
            try:
                os.startfile("ms-settings:privacy-microphone")  # noqa: S606 — сразу открыть нужную страницу настроек
            except OSError:
                pass

    def _listen(self):
        """Главный цикл слуха, кадр за кадром: проверка «микрофон молчит», полудуплекс во время ответа,
        слово запуска и «стоп» (быстрый слух Vosk), VAD — начало и конец фразы, перебивание речью поверх ответа.
        Готовая фраза → _on_utterance. Выход — конец потока или restart_audio."""
        self._pause_apply()                             # пауза конца фразы — своя у человека (_pause_*), меняется на ходу
        preroll = collections.deque(maxlen=12)          # ~0,4 с до срабатывания VAD — чтобы не терять начало слова
        in_speech, utt, silence, starts, speech_frames, t0 = False, [], 0, 0, 0, 0.0
        was_speaking = False
        bs, quiet, ducked = 0, 0, False                 # перебивание речью: кадры речи, тишины, приглушили ли
        echo = collections.deque(maxlen=90)             # громкость остаточного эха своего голоса (~3 с)
        half_echo = collections.deque(maxlen=100)       # полудуплекс: громкость своего голоса в микрофоне (~3 с)
        zero_since, zero_told, zero_all = None, False, True   # поток идёт, а в нём нули или почти нули (см. _mic_silent)
        while not self.stopping.is_set() and not self.restart_audio.is_set():
            frame = self.capture.read()
            if not frame:
                return
            now = time.monotonic()
            if self.muted:
                continue
            if not self.wav_input:
                # ровные нули (Windows запретил доступ) или «почти ничего» — пик ≤ 3 из 32767 (виртуальный микрофон вместо
                # настоящего, громкость записи на нуле): живой микрофон даже в тихой комнате шумит сильнее
                zeros = not frame.strip(b"\x00")
                peak = 0 if zeros else int(np.abs(np.frombuffer(frame, dtype=np.int16).astype(np.int32)).max())
                if peak > 3:
                    if zero_told:
                        self.note("")
                        log.info("🎤 Микрофон снова слышно")
                    zero_since, zero_told, zero_all = None, False, True
                elif zero_since is None:
                    zero_since, zero_all = now, zeros
                else:
                    zero_all = zero_all and zeros
                    if not zero_told and now - zero_since > 15:
                        zero_told = True
                        self._mic_silent(exact=zero_all)
            speaking = self.state == "speaking"
            if speaking and not self.status["aec"]:
                # полудуплекс: себя не слушаем — кроме короткого «стоп / хватит / пауза / отмена»
                if not was_speaking:
                    self.spotter.rec.Reset()
                    half_echo.clear()
                was_speaking = True
                a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(a * a)))
                half_echo.append(rms)
                w = self.spotter.feed_stop_only(frame) if self.s.get("audio", "barge_in") != "off" else None
                if w:
                    loud = sorted(half_echo)[len(half_echo) // 2] if half_echo else 0.0
                    if self._own_word(w):
                        log.info("«%s» — это моё же слово во фразе, не останавливаюсь", w)
                    elif max(list(half_echo)[-15:] or [0]) < 1.4 * loud:
                        log.info("«%s» тише моего голоса — похоже на эхо, не останавливаюсь", w)
                    else:
                        log.info("✋ «%s» — замолкаю (без эхоподавления)", w)
                        self.stop_utt, self.stop_time, self._stop_sleep = True, now, True
                        self.interrupt(w, follow=False)
                continue
            if was_speaking and not speaking:
                was_speaking = False
                self.vad.reset()
                self.spotter.rec.Reset()
                in_speech, utt, preroll = False, [], collections.deque(maxlen=12)

            barge = self.s.get("audio", "barge_in")
            for kind, phrase in self.spotter.feed(frame):
                if kind == "wake" and self._meeting_ignores(phrase):
                    log.info("🎧 Созвон — имя «%s» пропускаю (%s)", phrase, ", ".join(self.meeting) or "")
                    continue
                if kind == "wake" and self._noisy() and self.state == "idle" and self.wake_checker() is not None:
                    # вокруг много говорят (созвон, видео, гости): быстрый слух часто ошибается — сначала проверим
                    # фразу точной моделью и только потом откликнемся
                    log.info("🎤 «%s»? Вокруг разговор — проверю точной моделью", phrase)
                    self.vosk_wake_check, self._vosk_wake_word = self.utt_id, phrase
                    continue
                if kind == "wake":
                    log.info("🎤 Имя «%s» услышано", phrase)
                    self.wake_time, self._wake_phrase = now, phrase
                    if in_speech and len(utt) * FRAME_S > 2.5:
                        # имя посреди долгой «фразы» (играет музыка, вокруг говорят): иначе команда утонет в 20 секундах
                        # звука. Фраза начинается заново за 1,6 с до срабатывания — с самого имени.
                        keep = int(1.6 / FRAME_S)
                        log.info("🎤 Имя посреди долгого звука (%.1f с) — начинаю фразу с имени", len(utt) * FRAME_S)
                        utt = utt[-keep:]
                        t0, silence, speech_frames = now - len(utt) * FRAME_S, 0, len(utt)
                    self.emit("wake", phrase=phrase)
                    if self.state in ("speaking", "thinking") and barge != "off":
                        self.interrupt("имя")
                    elif self.state == "idle":
                        self.set_state("listening")
                        # звук «слушаю» — как только после имени пауза (≈0,25 с), а не поверх речи: звонок посреди
                        # «Лира, кратко как дела» попадал в микрофон и мешал распознать вопрос (отчёт 11.10)
                        self._wake_tone_at, self._wake_tone_due = now, now
                elif kind == "stop" and self.alarm:
                    log.info("✋ «%s» — выключаю будильник", phrase)
                    self.stop_utt, self.stop_time = True, now
                    self.alarm_finish("ack")
                elif kind == "stop" and self.state == "listening" and not self.meeting:
                    # ждём ответа («Ваша очередь») или вопроса после имени — «стоп», «хватит»: спим сразу (и музыку на
                    # паузу, если это «пауза»/«стоп»). Раньше «стоп» здесь уходил в ветку музыки и не усыплял (отчёт 11.10)
                    self.stop_utt, self.stop_time = True, now
                    self.go_sleep(phrase)
                elif kind == "stop" and self.state == "idle" and phrase in MEDIA_STOP and not self.meeting:
                    self._pending_media_stop = now            # решим, когда Vosk закончит фразу: одно слово — пауза
                elif kind == "stop" and self.state == "speaking" and self._own_word(phrase):
                    log.info("«%s» — это моё же слово во фразе (эхо), не останавливаюсь", phrase)
                elif kind == "stop" and self.state in ("speaking", "thinking") and barge != "off":
                    log.info("✋ «%s» — замолкаю", phrase)
                    self.stop_utt = now - self.wake_time > 3     # одно «стоп» — не вопрос; «стоп, лучше …» — вопрос
                    self.stop_time, self._stop_sleep = now, self.stop_utt
                    self.interrupt(phrase, follow=False)
                    self.follow_up_until = now + 3.0             # «стоп, лучше расскажи…» — договорить успеете

            fin = getattr(self.spotter, "last_final", None)
            if fin is not None:
                self.spotter.last_final = None
                if self._pending_media_stop and now - self._pending_media_stop < 4 and fin.strip() in MEDIA_STOP \
                        and self.state in ("idle", "listening"):
                    threading.Thread(target=self._media_stop_word, args=(fin.strip(),), daemon=True).start()
                elif fin.strip() in MEDIA_WORDS and self.radio.playing and self.state == "idle" and not self.meeting \
                        and not self.alarm:
                    threading.Thread(target=self._media_word, args=(fin.strip(),), daemon=True).start()
                self._pending_media_stop = 0.0

            p = self.vad.prob(frame)
            due = getattr(self, "_wake_tone_due", 0.0)
            if due and ((not in_speech and p < 0.5) or silence >= 8 or now - due > 6):
                self._wake_tone_due = 0.0                      # после имени замолчали — теперь «слушаю»
                if self.state in ("listening", "thinking") and now - due <= 6:
                    self.play_tone("wake")
            a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(a * a)))
            if self.state == "listening":                  # для журнала: насколько громко было, пока ждали вопрос
                self._listen_peak = max(self._listen_peak, rms)
                self._listen_vad = max(self._listen_vad, p)
            if self.state in ("idle", "listening") or not speaking:
                self._level(min(1.0, rms / 3000.0), "mic")
            if speaking and p < 0.6:
                echo.append(rms)                            # что остаётся от своего голоса после эхоподавления
            if not in_speech:
                preroll.append(frame)
                starts = starts + 1 if p > 0.5 else 0
                if starts >= 2:
                    in_speech, utt, silence, speech_frames = True, list(preroll), 0, 0
                    t0 = now - len(preroll) * FRAME_S
                    self.utt_id += 1
                    bs, quiet = 0, 0
                    self._pause_check(t0)
                    log.debug("речь началась (фраза %d, состояние %s)", self.utt_id, self.state)
            else:
                utt.append(frame)
                speech_frames += 1 if p > 0.5 else 0
                if p > 0.5:
                    self.mic_voice_t = now                    # суфлёр: «человек говорит» — для «замешкались» и пауз
                silence = silence + 1 if p < 0.35 else 0
                if speaking and barge in ("smart", "any_speech") and self.status["aec"]:
                    # Перебить можно просто начав говорить: через ~0,25 с речи ответ приглушается («слышу вас»),
                    # через ~0,8 с (any_speech — ~0,4 с) замолкает, а сказанное идёт как новый вопрос, без имени.
                    # Свой голос, просочившийся через эхоподавление, тише живой речи — порог считаем от него.
                    floor = max(220.0, 2.6 * float(np.median(echo)) if len(echo) > 10 else 400.0)
                    if p > 0.6 and rms > floor:
                        bs, quiet = bs + 1, 0
                    else:
                        quiet += 1
                        if quiet > 8:
                            bs = max(0, bs - 1)
                    if bs >= 8 and not ducked and self.player:
                        self.player.gain, ducked = 0.3, True
                        log.debug("слышу речь поверх ответа — приглушаю")
                    if bs >= (12 if barge == "any_speech" else 25):
                        self.barge_hit = self.utt_id           # эта фраза — новый вопрос
                        self.barge_speech = self.utt_id        # …возможно, с именем другого персонажа
                        bs, ducked = 0, False
                        self.interrupt("речь")
                if (speaking and barge != "off" and self.status["aec"] and speech_frames == 47
                        and now - self.wake_time > 3 and self.s.get("audio", "asr_wake")
                        and (self.wake_checker() or self.voiceprints.items)):
                    self.barge_sent = self.utt_id                 # 1.5 с речи поверх ответа — не имя ли это?
                    self.check_q.put(("barge", b"".join(utt), self.utt_id))
                if silence >= self._end_frames or len(utt) * FRAME_S > 25:  # фраза длиннее 25 с — режем принудительно
                    log.debug("речь кончилась (фраза %d, %.1f с)", self.utt_id, len(utt) * FRAME_S)
                    in_speech, starts = False, 0
                    if ducked and self.player:                  # кашлянули, «угу» — продолжаем как было
                        self.player.gain, ducked = 1.0, False
                    self._on_utterance(b"".join(utt[:len(utt) - max(0, silence - 6)]), t0, now)   # хвост тишины — не больше 6 кадров
                    utt = []

            # ждали вопрос, окно истекло, а фразы нет — засыпаем и пишем в журнал, почему могли не услышать
            if (self.state == "listening" and now > self.follow_up_until and not in_speech
                    and now - self.wake_time > 4 and self.stt_q.empty()):
                if self._listen_peak >= 500 and self._listen_vad >= 0.6:
                    log.info("🎤 Ждал вопрос — звук был (громкость %.0f, «это речь» %.2f), но фраза не сложилась: "
                             "вероятно, вокруг музыка или разговор", self._listen_peak, self._listen_vad)
                else:
                    log.info("🎤 Ждал вопрос — речи не услышал (громче всего: %.0f, уверенность «это речь»: %.2f; "
                             "обычный голос — от 500 и 0.6). Если вы говорили — микрофон слишком тихий или не тот",
                             self._listen_peak, self._listen_vad)
                self.set_state("idle")
                self.play_tone("sleep")                    # «больше не слушаю» — ниже, чем «слушаю»: понятно без взгляда на экран

    def _on_utterance(self, pcm, t0, now):
        """Фраза закончилась (pcm — 16 бит моно, t0/now — её начало и конец по monotonic). Решаем, куда её:
        в распознавание как вопрос (stt_q), в проверку имени точной моделью или отпечатком (check_q),
        ранней проверке, которая уже идёт, — или отбросить (короткий звук, «стоп», чужой разговор, своё эхо)."""
        dur = len(pcm) / 2 / RATE
        if self.stop_utt:
            self.stop_utt = False
            if dur < 1.6:                                  # было только «стоп»/«хватит» — замолчали и спим до имени
                if getattr(self, "_stop_sleep", False):    # (иначе разговор рядом, начатый в те 3 с, ушёл бы в вопрос)
                    self._stop_sleep = False
                    self.go_sleep("стоп", media=False)
                return
            self._stop_sleep = False
            self.barge_hit = self.utt_id                   # «стоп, расскажи лучше…» — это новый вопрос
        if dur < 0.35:                                     # щелчок, кашель — не речь
            return
        pr = getattr(self, "prompter", None)
        if pr is not None and (pr.on or pr.enrolling is not None):   # суфлёр: фразы — во встречу или в запись голоса
            pr.feed_me(pcm)
            return
        if self.calib is not None:
            threading.Thread(target=self._calib_sample, args=(pcm,), daemon=True).start()
            return
        uid = self.utt_id
        if self.vosk_wake_check == uid:                   # имя от быстрого слуха под сомнением — решит точная модель
            if self.check_q.qsize() < 3:
                self.check_q.put(("utt", pcm, uid))
            else:
                self.vosk_wake_check = -1
            return
        if self.barge_sent == uid and self.barge_hit != uid:
            # по этой фразе уже идёт ранняя проверка — решит она; звук оставляем ей
            self.barge_done[uid] = pcm
            return
        if self.barge_hit == uid and getattr(self, "barge_cut", None):
            (pid, cut), self.barge_cut = self.barge_cut, None
            self._after_name(pid, pcm, cut)
            return
        if self.barge_speech == uid:
            self.barge_speech = -1
            if self.voiceprints.items:                     # перебили речью — а не позвали ли другого по имени?
                pid, end, _ = self.voiceprints.match(pcm, allowed=set(self.aliases))
                if pid:
                    self.emit("wake", phrase=pid)
                    self._after_name(pid, pcm, end)
                    return
        by_wake = self.wake_time >= t0 - 1.5 or self.barge_hit == uid      # имя прозвучало в этой фразе или прямо перед ней
        follow = now < self.follow_up_until + dur                          # фраза началась, пока ждали продолжения
        lf = getattr(self, "_last_final", None)
        if lf and lf.get("cut") == uid and self.state == "thinking":
            # человек договаривал: первая часть ещё у модели — склеиваем обе в один вопрос (первая отменится, в историю не попадёт)
            gap = np.zeros(int(RATE * 0.25), dtype=np.int16).tobytes()
            pcm, by_wake, follow = lf["pcm"] + gap + pcm, lf["by_wake"], True
            self.cancel_turn()
            log.info("⏸ Фраза продолжилась после паузы — склеиваю в один вопрос (%.1f с)", len(pcm) / 2 / RATE)
        own_tail = not by_wake and (self.state == "speaking" or t0 < self.last_speak_end + 0.1)
        if not (by_wake or follow) and self.meeting and self._meeting_mode() == "pause":
            return                                         # созвон: фразы коллег не проверяем (и не грузим процессор)
        if own_tail or not (by_wake or follow):
            # Явного имени Vosk не слышал. Возможно, это имя, которого нет в его словаре
            # («Девиар») — проверяем точной моделью, спокойно, без смены состояния.
            may_barge = self.status["aec"] and self.s.get("audio", "barge_in") != "off"
            if (self.s.get("audio", "asr_wake") and (self.wake_checker() or self.voiceprints.items)
                    and (not own_tail or may_barge)):
                if self.check_q.qsize() < 2:
                    self.check_q.put(("utt", pcm, uid))
            return
        if by_wake:
            self.wake_time = 0.0
        log.info("Фраза %.1f с → распознаю (%s)", dur, "по имени" if by_wake else "продолжение разговора")
        self._last_final = {"t": now, "uid": uid, "pcm": pcm, "by_wake": by_wake}
        self.stt_q.put((pcm, by_wake, follow))
        self.set_state("thinking")

    # ---------- пауза конца фразы под манеру речи ----------

    def _pause_apply(self):
        """Сколько кадров тишины — конец фразы: end_silence_ms плюс выученная добавка (если подстройка включена)."""
        ms = int(self.s.get("audio", "end_silence_ms") or 650)
        if self.s.get("audio", "end_silence_auto") is not False:
            ms += int(self.s.get("audio", "end_silence_extra") or 0)
        self._end_frames = max(8, int(ms / 1000 / FRAME_S))
        return ms

    def _pause_check(self, t0):
        """Началась речь. Если прошлую фразу сочли законченной меньше 0,8 с назад, а ответа ещё нет (модель думает), —
        человек не договорил: ждать паузу дольше (+150 мс, до +900) и склеить обе части (_on_utterance)."""
        lf = getattr(self, "_last_final", None)
        if not lf or lf.get("cut") or self.state != "thinking" or t0 - lf["t"] > 0.8 or t0 < lf["t"] - 0.5:
            return
        lf["cut"] = self.utt_id
        if self.s.get("audio", "end_silence_auto") is False:
            return
        extra = min(900, int(self.s.get("audio", "end_silence_extra") or 0) + 150)
        self.s.update({"audio": {"end_silence_extra": extra}})
        ms = self._pause_apply()
        self._pause_debt = 0
        log.info("⏸ Похоже, перебил: вы продолжили через %.1f с — теперь жду конца фразы дольше: %d мс", max(0.0, t0 - lf["t"]), ms)
        self.emit("pause_learned", ms=ms, extra=extra)

    def _pause_ok(self):
        """Ответ на голосовой вопрос прошёл без обрыва — добавка понемногу тает: −10 мс за ответ (в настройки — по 50)."""
        lf = getattr(self, "_last_final", None)
        if not lf or lf.get("cut") or lf.get("ok") or time.monotonic() - lf["t"] > 180:
            return
        lf["ok"] = True
        extra = int(self.s.get("audio", "end_silence_extra") or 0)
        if extra <= 0 or self.s.get("audio", "end_silence_auto") is False:
            return
        self._pause_debt = getattr(self, "_pause_debt", 0) + 10
        if self._pause_debt >= min(50, extra):
            self.s.update({"audio": {"end_silence_extra": max(0, extra - self._pause_debt)}})
            self._pause_debt = 0
            self._pause_apply()

    # ---------- распознавание ----------

    def _stt_worker(self):
        """Поток stt: фразы из stt_q → текст → handle_text. Элемент очереди: (pcm, by_wake, follow[, pid]) —
        pid, если имя уже узнано по звуку и отрезано. Сбой основного распознавателя — повтор на Vosk."""
        while not self.stopping.is_set():
            item = self.stt_q.get()
            pcm, by_wake, follow = item[:3]
            forced = item[3] if len(item) > 3 else None
            stt = self.current_stt()
            t0 = time.monotonic()
            try:
                text = stt.transcribe(pcm).strip()
            except Exception as e:  # noqa: BLE001
                log.warning("%s не распознал: %s — пробую Vosk", stt.name, e)
                text = self.vosk_stt.transcribe(pcm).strip()
            from vault import mask as _mask                # продиктованный для сейфа секрет — не в журнал
            log.info("📝 %s (%s, %d мс)", _mask(text) or "—", stt.name, (time.monotonic() - t0) * 1000)
            self.emit("hearing", text=text, by=stt.name, name="", ms=int((time.monotonic() - t0) * 1000), full=True)
            self.handle_text(text, by_wake, follow, forced, dur=len(pcm) / 2 / RATE)

    def _check_worker(self):
        """Поток name-check: ищет имя во фразах из check_q — ("utt", pcm, uid) без явного имени и ("barge", …)
        поверх ответа. Сначала отпечаток голоса, затем точная модель + строгий find_name. Нашли — перебиваем ответ
        и отправляем фразу как вопрос; не нашли — это разговор «не мне» (учитывается в _noisy)."""
        head_bytes = int(2.2 * RATE) * 2                   # имя — в начале фразы («Девиар, …» — меньше секунды)
        if hasattr(os, "setpriority") and hasattr(threading, "get_native_id"):     # в Windows setpriority нет
            try:                                           # фоновая проверка имени уступает созвону и другим программам
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 5)
            except OSError:
                pass
        while not self.stopping.is_set():
            kind, pcm, uid = self.check_q.get()
            if self._check_voiceprint(kind, pcm, uid):
                continue
            checker = self.wake_checker()
            if checker is None:
                self.barge_done.pop(uid, None)
                continue
            try:
                t0 = time.monotonic()
                # короткую фразу — целиком (тогда текст сразу и вопрос); длинную — только начало, где имя
                chunk = pcm if len(pcm) <= int(3.0 * RATE) * 2 else pcm[:head_bytes]
                text = checker.transcribe(chunk).strip()
            except Exception as e:  # noqa: BLE001
                log.debug("проверка имени не удалась: %s", e)
                continue
            pid, _ = find_name(text, self._wake_aliases(), strict=True)
            ms = int((time.monotonic() - t0) * 1000)
            if pid:
                log.info("👂 %s: «%s» → %s (%d мс)", checker.name, text, pid, ms)
            else:                                      # чужие разговоры в журнал не пишем (только в подробном режиме)
                log.debug("👂 %s: «%s» → имени нет (%d мс)", checker.name, text, ms)
            self.emit("hearing", text=text, by=checker.name, name=pid or "", ms=ms)
            if not pid:
                self.barge_done.pop(uid, None)
                if len(text) > 12:
                    self._chatter.append(time.monotonic())     # вокруг разговаривают — не со мной
                if self.vosk_wake_check == uid:
                    self.vosk_wake_check = -1
                    log.info("🎧 «%s» от быстрого слуха не подтвердилось — вокруг разговор, пропускаю", self._vosk_wake_word)
                    self.set_state("idle")
                continue
            if self.vosk_wake_check == uid:
                self.vosk_wake_check = -1
            log.info("🎤 Имя распознано точной моделью: «%s»", text)
            self.emit("wake", phrase=pid)
            if kind == "barge":
                self.barge_hit = uid                        # фраза, когда закончится, пойдёт как вопрос
                self.interrupt("имя")
                ended = self.barge_done.pop(uid, None)
                if ended is not None:                       # …а если уже закончилась — отправляем сейчас
                    self.stt_q.put((ended, True, False))
                    self.set_state("thinking")
                continue
            if self.state in ("speaking", "thinking"):
                self.interrupt("имя")
            # распознали только начало или не тем распознавателем, что для вопросов, — фразу целиком распознаем заново
            if len(pcm) > len(chunk) or checker is not self.current_stt():
                self.stt_q.put((pcm, True, False))
                self.set_state("thinking")
            else:
                self.set_state("thinking")
                self.handle_text(text, True, False)

    # ---------- созвон ----------

    def _noisy(self):
        """Вокруг идёт разговор: за последние полторы минуты не меньше четырёх фраз «не мне»."""
        now = time.monotonic()
        return sum(1 for t in self._chatter if now - t < 90) >= 4

    def _meeting_mode(self):
        return self.s.get("audio", "meeting") or "pause"

    def _wake_aliases(self):
        """На созвоне в режиме «только главный» — откликаемся только на имя активного персонажа."""
        if self.meeting and self._meeting_mode() == "main":
            me = self.s.get("persona")
            return {me: self.aliases[me]} if me in self.aliases else self.aliases
        return self.aliases

    def _meeting_ignores(self, phrase):
        """Пропустить ли имя от быстрого слуха из-за созвона (только в покое): режим pause — любое,
        main — кроме имени активного персонажа. Включён суфлёр — любое и всегда: на встрече ассистент молчит."""
        pr = getattr(self, "prompter", None)
        if pr is not None and (pr.on or pr.enrolling is not None):
            return True
        if not self.meeting or self.state != "idle":
            return False
        mode = self._meeting_mode()
        if mode == "pause":
            return True
        if mode == "main":
            try:
                return self.personas.wake_map().get(phrase) not in (None, self.s.get("persona"))
            except Exception:  # noqa: BLE001
                return False
        return False

    # ---------- перезапуск и фоновые циклы ----------

    def restart_core(self, delay=1.5):
        """Перезапуск ядра через delay секунд (например, после восстановления из копии). Под systemd (есть INVOCATION_ID) —
        выход с кодом 75, служба поднимет заново; иначе — маленький процесс-посредник ждёт (до 30 с), пока освободится
        порт моста, и запускает ядро с теми же аргументами, а этот процесс сразу выходит."""
        import sys as _sys

        def go():
            time.sleep(delay)
            if os.environ.get("INVOCATION_ID"):
                log.info("Перезапуск ядра (служба поднимет заново)")
                os._exit(75)
            code = ("import socket,subprocess,sys,time\n"
                    "for _ in range(60):\n"
                    " s=socket.socket()\n"
                    " try:\n  s.bind(('127.0.0.1', %d)); s.close(); break\n"
                    " except OSError: time.sleep(0.5)\n"
                    "subprocess.Popen(sys.argv[1:], close_fds=True)\n") % self.bridge.port
            # Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW — посредник переживёт выход ядра
            flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0
            subprocess.Popen([_sys.executable, "-c", code, _sys.executable] + _sys.argv, close_fds=True,
                             start_new_session=os.name != "nt", creationflags=flags)
            log.info("Перезапуск ядра")
            os._exit(0)
        threading.Thread(target=go, daemon=True).start()

    def _calendar_loop(self):
        """Календари Google/Яндекс: обновлять раз в 30 минут; за N минут до встречи — напомнить."""
        told, last = set(), 0.0
        tick = float(os.environ.get("DEWIAR_CAL_TICK") or 30)      # шаг проверки, с; тесты ставят меньше
        self.stopping.wait(min(20, tick))
        while not self.stopping.is_set():
            try:
                if self.calendars.items() and time.monotonic() - last > 1800:
                    last = time.monotonic()
                    self.calendars.refresh()
                    self.emit("calendars", **self.calendars.public())
                mins = int(self.s.get("calendars", "remind_minutes") or 0)
                if mins > 0 and self.calendars.items():
                    now = datetime.now()
                    for e in self.calendars.events(now, now + timedelta(minutes=mins + 1)):
                        key = (e["cid"], e["title"], e["start"].isoformat())
                        if e["allday"] or key in told or e["start"] < now:
                            continue
                        told.add(key)
                        left = max(1, round((e["start"] - now).total_seconds() / 60))
                        text = f"{e['title']}" + (f", {e['place']}" if e.get("place") else "")
                        self.push(f"📅 Через {left} мин — {e['start']:%H:%M}", text)
                        if self.state == "idle" and not self.meeting:
                            self.announce(f"Через {left} минут: {e['title']}.")
            except Exception as e:  # noqa: BLE001
                log.warning("Календари: %s", e)
            self.stopping.wait(tick)

    def _auto_backup(self):
        """Поток backup: раз в неделю — тихая резервная копия (без сейфа и паролей); хранятся 4 последние
        (backup.py). Проверяем, не пора ли, раз в 6 часов."""
        from backup import default_dir, due
        self.stopping.wait(600)                          # не в момент запуска
        while not self.stopping.is_set():
            try:
                if self.s.get("backup", "auto") is not False:
                    folder = self.s.get("backup", "dir") or str(default_dir())
                    if due(self.backup.last_auto(folder)):
                        low_priority()
                        self.backup.make(folder, auto=True)
            except Exception as e:  # noqa: BLE001
                log.warning("Автокопия не сделана: %s", e)
            self.stopping.wait(6 * 3600)

    def _meeting_watch(self):
        """Поток meeting: раз в 3 секунды — не слушает ли микрофон другая программа (созвон); итог — self.meeting
        и status["meeting"]. В режиме normal созвон не отслеживается."""
        from meeting import mic_users
        while not self.stopping.is_set():
            apps = mic_users() if self._meeting_mode() != "normal" else []
            if apps != self.meeting:
                was = bool(self.meeting)
                self.meeting = apps
                if bool(apps) != was:
                    log.info("🎧 %s", f"Созвон ({', '.join(apps)}): " + {"pause": "имя не слушаю — говорите со мной по кнопке",
                                                                          "main": "слушаю только главное имя"}.get(self._meeting_mode(), "")
                             if apps else "Созвон закончился — слушаю как обычно")
                self.status["meeting"] = {"apps": apps, "mode": self._meeting_mode()} if apps else None
                self.emit("status", status=self.status)
                if apps and not was and not self.prompter.on and self.s.get("ui", "prompter_offer") is not False:
                    self.emit("prompter_offer", apps=apps)     # созвон начался — виджет предложит суфлёр
            self.stopping.wait(3.0)

    # ---------- имя по голосу, своё эхо, разбор распознанной фразы ----------

    def _check_voiceprint(self, kind, pcm, uid):
        """Имя по звучанию (голосовой отпечаток) -> True, если имя найдено и фраза обработана.
        Для ранней проверки поверх ответа ("barge") фраза может ещё не кончиться — тогда место разреза
        запоминается в barge_cut, и её подхватит _on_utterance."""
        if not self.voiceprints.items:
            return False
        t0 = time.monotonic()
        pid, end, dist = self.voiceprints.match(pcm, allowed=set(self._wake_aliases()))
        ms = int((time.monotonic() - t0) * 1000)
        if not pid:
            log.debug("отпечаток: имени нет (%.3f, %d мс)", dist, ms)
            if self.wake_checker() is None:
                self.emit("hearing", text="", by="отпечаток голоса", name="", ms=ms, dist=round(dist, 3))
            return False
        name = self.personas.get(pid)["name"]
        log.info("🎤 Имя «%s» узнано по голосу (%.3f, %d мс)", name, dist, ms)
        self.emit("hearing", text=f"«{name}» — по голосу", by="отпечаток голоса", name=pid, ms=ms)
        self.emit("wake", phrase=pid)
        if kind == "barge":
            self.barge_hit = uid
            self.interrupt("имя")
            ended = self.barge_done.pop(uid, None)
            if ended is not None:
                self._after_name(pid, ended, end)
            else:
                self.barge_cut = (pid, end)
            return True
        if self.state in ("speaking", "thinking"):
            self.interrupt("имя")
        self._after_name(pid, pcm, end)
        return True

    def _after_name(self, pid, pcm, end_sec):
        """Имя найдено по звуку: остаток фразы — вопрос."""
        if pid != self.s.get("persona"):
            self.switch_persona(pid)
        rest = pcm[int(end_sec * RATE) * 2:]
        if len(rest) / 2 / RATE < 0.45:
            self.listen_for_command()
            return
        self.set_state("thinking")
        self.stt_q.put((rest, True, False, pid))

    def _own_word(self, w):
        """Слово-команда («пауза», «стоп») есть в том, что ассистент сам говорит сейчас (или только что) — это эхо."""
        stem = _norm(w or "").strip()
        stem = stem[:max(4, len(stem) - 1)]
        now = time.monotonic()
        said = _norm(" ".join([self._now_saying or ""] + [t for at, t in list(self._said) if now - at < 8]))
        return bool(stem) and stem in said

    def _is_self_echo(self, text):
        """Микрофон услышал наш же голос из колонок (эхоподавление не справилось): фраза почти целиком — из того,
        что ассистент сказал за последние 25 секунд."""
        norm = lambda t: (t or "").lower().replace("ё", "е")  # noqa: E731
        words = re.findall(r"\w{3,}", norm(text))
        now = time.monotonic()
        if len(words) < 4 or (self.state != "speaking" and now - self._spoke_until > 3.5):
            return False                                  # эхо бывает, пока говорим, и сразу после
        said = set(re.findall(r"\w{3,}", norm(" ".join(t for at, t in list(self._said) if now - at < 25))))
        if not said:
            return False
        stems = {w[:5] for w in said if len(w) >= 5}
        hit = sum(1 for w in words if w in said or (len(w) >= 5 and w[:5] in stems))
        return hit / len(words) >= 0.75

    def _echo_heard(self, text):
        """Фраза оказалась нашим эхом: пропускаем. Второй раз за 3 минуты — на 10 минут отключаем «продолжение
        разговора» без имени (_echo_until, см. конец хода в engine_answer.py) и подсказываем про наушники."""
        now = time.monotonic()
        log.info("🔁 Услышал свой же голос — пропускаю: «%s»", text[:120])
        self._echo_hits = [t for t in self._echo_hits if now - t < 180] + [now]
        self.follow_up_until = 0.0
        if len(self._echo_hits) >= 2 and now > self._echo_until:
            self._echo_until = now + 600                  # 10 минут слушаем только по имени
            self.note("Я слышу сам себя: звук из колонок попадает в микрофон. Наденьте наушники или включите "
                      "эхоподавление (студия → «Звук и поведение»). Пока отвечаю только когда зовут по имени.")
        self.set_state("idle")

    def handle_text(self, text, by_wake, follow, forced=None, dur=None):
        """Распознанная фраза → что делать: эхо — пропустить; ответ на «выполнить?» или на вопрос задачи;
        имя + вопрос → ask(); имя + «стоп» → уснуть; продолжение разговора → ask(); иначе ложное срабатывание.
        by_wake — имя слышали по звуку, follow — шло «продолжение разговора», forced — pid, если имя уже отрезано,
        dur — длина фразы, с."""
        if text and not forced and self._is_self_echo(text):
            self._echo_heard(text)
            return
        if self._intro_ear is not None and self._intro_take(text, forced):
            return                                         # знакомство проверяет микрофон — фраза ему
        if forced:
            # имя уже узнано по звуку и отрезано; если распознаватель всё же написал его — уберём
            pid, end = find_name(text, self.aliases) if text else (None, 0)
            rest = text[end:].lstrip(" ,.!?:;—-").strip() if pid else text.strip()
            if len(re.sub(r"\W", "", rest)) < 2:
                self.listen_for_command()
            else:
                self.ask(rest)
            return
        if self.pending_confirm and text and self._answer_confirm(text):
            self.set_state("thinking")
            return
        wt = self.tasks.waiting() if text else None        # задача задала вопрос — фраза без имени идёт ей в ответ
        if wt and time.monotonic() < self.task_answer_until and not find_name(text, self.aliases)[0]:
            self.task_answer_until = 0.0
            self.tasks.answer(wt.id, text)
            log.info("Ответ в задачу «%s»: %s", wt.title, text)
            self.emit("heard", text=text)
            self.announce("Передал в задачу.")
            return
        pid, end = find_name(text, self.aliases) if text else (None, 0)
        if not pid and by_wake and dur is not None and dur <= 1.6 and len(text.split()) <= 2 and self._name_like(text):
            # Быстрый слух услышал имя, а точная модель в короткой фразе ослышалась («Игрова», «Элла» вместо «Эва»):
            # это и было имя. Слушаем вопрос, а не гаснем и не отправляем «Эллу» модели как вопрос.
            spotted = self.personas.wake_map().get(getattr(self, "_wake_phrase", ""))
            if spotted:
                log.info("🎤 Имя «%s» слышно, распознано как «%s» — слушаю вопрос", self._wake_phrase, text or "—")
                if spotted != self.s.get("persona"):
                    self.switch_persona(spotted)
                self.listen_for_command()
                return
        if pid:
            if pid != self.s.get("persona"):
                self.switch_persona(pid)
            rest = text[end:].lstrip(" ,.!?:;—-").strip()
            word = _norm(re.sub(r"[^\w ]", "", rest)).strip()
            if thanks_phrase(rest):                          # «Лира, спасибо» — «Пожалуйста!» и сон
                self._thanks(rest)
            elif word in STOP_WORDS or is_sleep_phrase(rest):
                self.go_sleep(word, media=False)
                if word in MEDIA_STOP:
                    threading.Thread(target=self._media_stop_word, args=(word, True), daemon=True).start()
            elif len(re.sub(r"\W", "", rest)) < 2:
                self.listen_for_command()
            else:
                self.ask(rest)
        elif follow and text:
            self.ask(text)
        else:
            if by_wake:
                log.info("Ложное срабатывание: имени во фразе нет (%d слов)", len(text.split()))
                log.debug("Ложное срабатывание — фраза: «%s»", text)
            back = "listening" if time.monotonic() < self.follow_up_until else "idle"
            self.set_state(back)
            if back == "idle" and time.monotonic() - getattr(self, "_wake_tone_at", 0.0) < 15:
                self.play_tone("sleep")                    # звучало «слушаю», а вопроса не было — так же ясно «не слушаю»

    def _name_like(self, text):
        """Похоже ли короткое распознанное на ослышанное имя («Игрова», «Элла» вместо «Эва»), а не на ответ человека.
        Отчёт 11.10: «Лира» → «Слушаю…», затем быстрое «спасибо» / «как дела» принимались за ослышанное имя — фраза
        терялась, и снова «Слушаю…». Пусто или первое слово хоть немного похоже на имя (≥ 0,55) — имя; иначе — фраза."""
        import difflib
        w = _norm(re.sub(r"[^\w ]", " ", text or "")).split()
        if not w:
            return True
        names = [_norm(a).replace(" ", "") for al in self.aliases.values() for a in al]
        return any(difflib.SequenceMatcher(None, w[0], a).ratio() >= 0.55 for a in names)

    def listen_for_command(self, seconds=8):
        """Имя услышали без вопроса: ждём вопрос seconds секунд (без имени) и даём короткий сигнал."""
        self._listen_peak, self._listen_vad = 0.0, 0.0
        log.info("🎤 Слушаю вопрос (%d с)", seconds)
        self.follow_up_until = time.monotonic() + seconds
        self.set_state("listening")
        self.emit("heard", text="")
        if time.monotonic() - getattr(self, "_wake_tone_at", 0.0) > 4:   # уже прозвучал на само имя — второй раз не нужен
            self.play_tone("wake")

    def play_tone(self, kind):
        """Короткий сигнал состояния. Вывод для сигналов держится открытым (ToneOut): открывать звук каждый раз —
        это заметная задержка, и «слушаю» звучало бы позже, чем человек договорил имя."""
        if not self.s.get("audio", "sounds") or self.player is None or self.state == "speaking":
            return
        out = getattr(self, "_tone_out", None)
        if out is None or out.device != self.player.device:
            out = self._tone_out = ToneOut(self.player.device, null=self.null_player)
        out.play(tone(kind))
