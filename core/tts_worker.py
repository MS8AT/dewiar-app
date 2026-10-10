"""Голоса Vosk TTS в отдельном процессе (его запускает и с ним говорит tts.VoskProc).

Зачем: загрузка модели (сессии onnxruntime и словарь ударений на сотни тысяч строк) и сам синтез держат GIL Python
десятки секунд. В том же процессе ядро всё это время не отвечало: студия пустела («нет связи с ядром»), виджет
писал «загружаю слух и голос» больше минуты после каждого запуска. Здесь они никому не мешают.

Ускорение повторных запусков: словарь ударений после первого разбора сохраняется рядом с моделью
(dewiar-dic.pickle, сверяется по размеру и времени файла dictionary) и дальше читается за секунду.

Обмен по stdin/stdout кадрами: 4 байта длины (big-endian) + содержимое. Запрос — JSON {"text", "speaker_id",
"speech_rate"}; ответ — JSON {"ok": true, "n": байт} и следом кадр с PCM int16 22 050 Гц, или {"ok": false, "error"}.
Первым делом worker шлёт {"ok": true, "ready": true} (модель загружена) или {"ok": false, "error"}."""
import io
import json
import pickle
import struct
import sys
from pathlib import Path


def _frame_out(out, data):
    out.write(struct.pack(">I", len(data)) + data)
    out.flush()


def _frame_in(inp):
    h = inp.read(4)
    if len(h) < 4:
        return None
    n = struct.unpack(">I", h)[0]
    return inp.read(n)


def load_model(path):
    """vosk_tts.Model с кэшем словаря. Если устройство библиотеки иное (словарь читается не через open в её модуле),
    кэш просто не используется — модель грузится как обычно."""
    try:                                                     # DEWIAR_ORT_THREADS — своё число потоков голосов (ortcfg)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ortcfg
        ortcfg.limit()
    except Exception:  # noqa: BLE001
        pass
    import vosk_tts.model as vm
    from vosk_tts import Model
    path = Path(path)
    dic_file, cache = path / "dictionary", path / "dewiar-dic.pickle"
    try:
        st = dic_file.stat()
        key = [st.st_size, int(st.st_mtime)]
    except OSError:
        return Model(model_path=str(path))
    dic = None
    if cache.exists():
        try:
            with open(cache, "rb") as f:
                saved = pickle.load(f)
            if saved.get("key") == key and isinstance(saved.get("dic"), dict):
                dic = saved["dic"]
        except Exception:  # noqa: BLE001 — испорченный кэш: разберём словарь заново
            dic = None
    if dic is None:
        m = Model(model_path=str(path))
        if isinstance(getattr(m, "dic", None), dict) and m.dic:
            try:
                tmp = cache.with_suffix(".tmp")
                with open(tmp, "wb") as f:
                    pickle.dump({"key": key, "dic": m.dic}, f, protocol=pickle.HIGHEST_PROTOCOL)
                tmp.replace(cache)
            except OSError:
                pass
        return m
    real_open = open

    def fake_open(f, *a, **kw):                  # словарь не разбираем — он уже есть в кэше
        if Path(str(f)) == dic_file:
            return io.StringIO("")
        return real_open(f, *a, **kw)
    vm.open = fake_open
    try:
        m = Model(model_path=str(path))
    finally:
        del vm.open
    m.dic = dic
    return m


def main():
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr                      # печать библиотек — в журнал, а не в канал обмена
    try:
        import numpy as np
        from vosk_tts import Synth
        synth = Synth(load_model(sys.argv[1]))
    except Exception as e:  # noqa: BLE001
        _frame_out(out, json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False).encode())
        return 1
    _frame_out(out, json.dumps({"ok": True, "ready": True}).encode())
    while True:
        raw = _frame_in(inp)
        if raw is None:
            return 0
        try:
            q = json.loads(raw)
            kw = {"speaker_id": int(q.get("speaker_id") or 0)}
            if q.get("speech_rate") is not None:
                kw["speech_rate"] = float(q["speech_rate"])
            audio = np.asarray(synth.synth_audio(q.get("text") or "", **kw), dtype=np.int16).tobytes()
        except Exception as e:  # noqa: BLE001
            _frame_out(out, json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False).encode())
            continue
        _frame_out(out, json.dumps({"ok": True, "n": len(audio)}).encode())
        _frame_out(out, audio)


if __name__ == "__main__":
    sys.exit(main())
