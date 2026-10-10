"""Локальный WebSocket 127.0.0.1:8765 между ядром и интерфейсом.

Протокол — JSON:
  клиент → {"cmd": "hello", "token": "..."}      (первым сообщением, иначе разрыв)
  клиент → {"id": 7, "cmd": "persona_set", "args": {...}}
  ядро   → {"type": "hello", "data": ...}                 (ответ на верный токен — затем обычный обмен)
  ядро   → {"type": "reply", "id": 7, "ok": true, "data": ...}   или  {"ok": false, "error": "…"}
  ядро   → {"type": "state"|"level"|"heard"|"answer"|...}   (рассылка всем)

Токен обязателен: к 127.0.0.1 может подключиться любая программа или страница в браузере на этом компьютере,
а команды ядра управляют компьютером. Команды выполняются в пуле потоков (handler), рассылка — broadcast()
из любого потока. Ответ на «ping» — без пула, чтобы показать, чем ядро занято, даже когда пул забит.
"""

import asyncio
import hmac
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("dewiar.bridge")


class Bridge:
    def __init__(self, token, host="127.0.0.1", port=8765):
        self.token, self.host, self.port = token, host, port
        self.clients = set()
        self.seen = False          # окно хоть раз подключалось: значит, интерфейс есть (см. Engine._ui_wake)
        self.loop = None
        self.handler = None           # fn(cmd, args) -> data (вызывается в пуле потоков)
        self.ready = threading.Event()
        # Свой большой пул: в стандартном (ядер + 4) медленные команды (сеть, проверки) занимают все потоки,
        # и остальные кнопки интерфейса ждут.
        self.pool = ThreadPoolExecutor(max_workers=48, thread_name_prefix="cmd")
        self.inflight = {}            # id вызова → (команда, когда начата) — для «ping»: чем ядро занято

    def start(self):
        """Запустить сервер в своём потоке со своим циклом asyncio; ждём готовности не дольше 5 секунд."""
        threading.Thread(target=self._run, name="bridge", daemon=True).start()
        self.ready.wait(5)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())

    async def _serve(self):
        try:
            from websockets.asyncio.server import serve
        except ImportError:                                  # websockets < 13: нового модуля asyncio.server ещё нет
            from websockets import serve
        async with serve(self._client, self.host, self.port, max_size=16 * 1024 * 1024):   # 16 МБ: файлы и картинки из интерфейса
            log.info("Интерфейс может подключаться: ws://%s:%d", self.host, self.port)
            self.ready.set()
            await asyncio.Future()

    async def _client(self, ws, *_):
        """Одно подключение: первым сообщением (за 5 секунд) — токен, сравнение за постоянное время (hmac).
        Неверный — закрываем с кодом 4001. Каждая команда обрабатывается отдельно, не задерживая следующие."""
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if not hmac.compare_digest(str(first.get("token", "")), self.token):
                await ws.close(code=4001, reason="bad token")
                return
        except Exception:  # noqa: BLE001
            return
        try:
            data = await self._call("hello", {})
            await ws.send(json.dumps({"type": "hello", "data": data}, ensure_ascii=False))
            self.clients.add(ws)
            self.seen = True
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                asyncio.ensure_future(self._reply(ws, msg))
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.clients.discard(ws)

    async def _call(self, cmd, args):
        """Выполнить команду в пуле потоков, отмечая её в inflight на время выполнения."""
        key = object()
        self.inflight[key] = (cmd, time.monotonic())
        try:
            return await self.loop.run_in_executor(self.pool, self.handler, cmd, args)
        finally:
            self.inflight.pop(key, None)

    def busy(self):
        """Ответ на «ping» прямо из цикла связи (без пула): жив ли и что выполняется дольше всех."""
        now = time.monotonic()
        slow = sorted(((now - t, c) for c, t in list(self.inflight.values())), reverse=True)
        return {"ok": True, "inflight": len(slow), "oldest": round(slow[0][0], 1) if slow else 0,
                "cmd": slow[0][1] if slow else ""}

    async def _reply(self, ws, msg):
        mid = msg.get("id")
        try:
            data = self.busy() if msg.get("cmd") == "ping" else await self._call(msg.get("cmd"), msg.get("args") or {})
            out = {"type": "reply", "id": mid, "ok": True, "data": data}
        except Exception as e:  # noqa: BLE001
            if isinstance(e, (AttributeError, TypeError, KeyError, IndexError, NameError, ZeroDivisionError, AssertionError)):
                log.error("Команда %s упала: %s", msg.get("cmd"), e, exc_info=True)    # ошибка в программе — в отчёт разработчику
            else:
                log.warning("Команда %s: %s", msg.get("cmd"), e)
            out = {"type": "reply", "id": mid, "ok": False, "error": str(e)}
        try:
            await ws.send(json.dumps(out, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass

    def broadcast(self, event: dict):
        """Разослать событие всем интерфейсам. Можно звать из любого потока: отправка уходит в цикл связи.
        Клиент, которому не отправилось, убирается из списка."""
        if not self.loop or not self.clients:
            return
        text = json.dumps(event, ensure_ascii=False)

        async def send_all():
            for ws in list(self.clients):
                try:
                    await ws.send(text)
                except Exception:  # noqa: BLE001
                    self.clients.discard(ws)
        asyncio.run_coroutine_threadsafe(send_all(), self.loop)
