"""Пакеты 21–22.10: почти в каждом журнале «Проверка инструментов (native): сервер модели отклонил запрос (upstream returned
HTTP 400)» у облака Dewiar — и модель записывалась в «инструменты описанием в тексте», хотя на телефоне то же облако
вызывает их полем tools. Облако Ollama за шлюзом отклоняет незнакомое поле chat_template_kwargs (ошибкой внутри потока,
HTTP 200). Теперь первым делом — повтор без него (и запоминаем сервер), функции остаются полем; записи «prompt» один раз
проверяются заново (tools_probe_v 3); телефон пробует так же — сначала без chat_template_kwargs."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


import llm  # noqa: E402
seen = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append({"kw": "chat_template_kwargs" in b, "tools": bool(b.get("tools"))})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if "chat_template_kwargs" in b:
            self.wfile.write(b'data: {"error": {"message": "upstream returned HTTP 400"}}\n\n')
        elif b.get("tools"):
            d = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "get_time", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}
            self.wfile.write(b"data: " + json.dumps(d).encode() + b"\n\ndata: [DONE]\n\n")
        else:
            self.wfile.write(b'data: {"choices": [{"delta": {"content": "12:00"}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n')


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
prof = {"base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1", "model": "chat", "kind": "openai"}
mode = llm.probe_tools(prof)
ok(mode == "native", f"облако отклоняет chat_template_kwargs — проверка всё равно находит функции полем: {mode}, запросы {seen}")
ok(seen[0]["kw"] and not seen[1]["kw"] and seen[1]["tools"], "повтор — без chat_template_kwargs, функции остаются полем tools")
seen.clear()
list(llm.stream_events(prof, "s", [{"role": "user", "content": "привет"}]))
ok(seen and not seen[0]["kw"], "сервер запомнен: дальше сразу без chat_template_kwargs, без лишнего отказа")
srv.shutdown()

ea = (ROOT / "core/engine_answer.py").read_text(encoding="utf-8")
ok('"tools_probe_v") != 3' in ea and 'v == "native"' in ea, "записи «prompt» один раз проверяются заново (tools_probe_v 3)")
js = (ROOT / "android/assets/www/app.js").read_text(encoding="utf-8")
rr = js[js.index("const retryRejected"):]
ok(rr.index("body.chat_template_kwargs") < rr.index("if (body.tools)"), "телефон: при отказе сначала без chat_template_kwargs, потом функции текстом")
ok("delete S.llm.tools_prompt" in js, "телефон: запомненное «функции текстом» один раз проверяется заново")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
