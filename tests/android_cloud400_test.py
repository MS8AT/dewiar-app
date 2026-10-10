"""Android с ключом Dewiar: «Проверить» проходит, а разговор — «upstream returned HTTP 400».
Сервер моделей за облаком отклоняет запрос с функциями полем tools. Проверяет, что телефон, как компьютер, повторяет
запрос с описанием функций в тексте: ответ приходит, вызовы <tool_call> распознаются, история вызовов — обычными
репликами."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []
def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c: fails.append(m)
www = Path(tempfile.mkdtemp()) / "www"
shutil.copytree(ROOT / "android/assets/www", www)
shutil.copy(ROOT / "ui/assets/entities.js", www / "entities.js")
shutil.copytree(ROOT / "ui/assets/live", www / "live", dirs_exist_ok=True)   # живое лицо Эвы
(www / "personas.js").write_text(subprocess.run([sys.executable, str(ROOT / "android/tools/personas_json.py"), str(ROOT)],
                                                capture_output=True, text=True, check=True).stdout, encoding="utf-8")
sse = lambda t: "".join("data: " + json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False) + "\n\n" for c in [t[i:i + 9] for i in range(0, len(t), 9)]) + "data: [DONE]\n\n"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((www / "index.html").as_uri()); pg.wait_for_timeout(800)
    R = pg.evaluate("""async ([callSse, textSse]) => {
        Object.assign(S.llm, { kind: "openai", base_url: "https://dewiar.pro/dwrapp/cloud.php?p=", model: "chat", cloud: true, disable_thinking: false });
        delete S.llm.tools_prompt;
        window.resolveModel = async () => "chat";
        const seen = [];
        window.http = async (m, u, o) => {
          const body = typeof o.body === "string" ? JSON.parse(o.body) : o.body; seen.push(body);
          if (body.tools) return { status: 502, body: JSON.stringify({ error: { message: "upstream returned HTTP 400" } }) };
          const last = JSON.stringify(body.messages[body.messages.length - 1]);
          const s = last.includes("tool_response") ? textSse : callSse;
          o.onChunk(s); return { status: 200, body: "" };
        };
        const tools = [{ name: "get_time", description: "Который час", parameters: { type: "object", properties: {} } }];
        const msgs = [{ role: "system", content: "Ты Лира." }, { role: "user", content: "Который час?" }];
        const r1 = await llmStream(msgs, tools, null);
        msgs.push({ role: "assistant", content: r1.text || "", tool_calls: r1.calls.map(c => ({ id: c.id, type: "function", function: { name: c.name, arguments: c.args } })) });
        msgs.push({ role: "tool", tool_call_id: "x", name: "get_time", content: "14:41" });
        const r2 = await llmStream(msgs, tools, null);
        return { r1, r2, seen, mode: S.llm.tools_prompt };
    }""", [sse('<tool_call>\n{"name": "get_time", "arguments": {}}\n</tool_call>'), sse("Сейчас 14:41.")])
    # Ошибка внутри потока (HTTP 200, строка error) — так отказ приходит через облако на телефоне с ключом Dewiar
    R["instream"] = pg.evaluate("""async (textSse) => {
        delete S.llm.tools_prompt; const seen = [];
        window.http = async (m, u, o) => {
          const body = typeof o.body === "string" ? JSON.parse(o.body) : o.body; seen.push(body);
          if (body.tools) { o.onChunk('data: {"error":{"message":"upstream returned HTTP 400"}}' + String.fromCharCode(10, 10)); return { status: 200, body: "" }; }
          o.onChunk(textSse); return { status: 200, body: "" };
        };
        const r = await llmStream([{ role: "system", content: "Ты Лира." }, { role: "user", content: "Привет" }],
                                  [{ name: "get_time", description: "Который час", parameters: { type: "object", properties: {} } }], null);
        return { text: r.text, n: seen.length, second_tools: !!seen[1].tools, prompt: seen[1].messages[0].content.includes("# Инструменты") };
    }""", sse("Привет! Всё хорошо."))
    H = pg.evaluate("""() => chatHistory([
        { role: "assistant", content: "Привет! Я на связи." },
        { role: "user", content: "Привет" },
        { role: "user", content: "Как дела?" },
        { role: "assistant", content: "Хорошо!", who: "patrik" },
        { role: "assistant", content: "А у тебя?", who: persona().id }], "Отлично")""")
    b.close()
I = R["instream"]
ok(I["text"].strip() == "Привет! Всё хорошо." and I["n"] == 2 and not I["second_tools"] and I["prompt"],
   f"«upstream returned HTTP 400» внутри потока — повтор с функциями текстом, ответ пришёл: {I}")
roles = [m["role"] for m in H]
ok(roles == ["user", "assistant", "user"] and H[0]["content"].startswith("Привет\n\nКак дела?") and "[Патрик ответил(а)]: Хорошо!" in H[0]["content"]
   and H[-1]["content"] == "Отлично", f"история: роли чередуются, начинается с пользователя, чужие реплики — с пометкой: {H}")
seen = R["seen"]
ok(seen[0].get("tools") and not seen[1].get("tools"), "сервер отклонил функции полем — повтор без поля tools")
ok("# Инструменты" in seen[1]["messages"][0]["content"] and "get_time" in seen[1]["messages"][0]["content"], "функции описаны в системном сообщении")
ok([c["name"] for c in R["r1"]["calls"]] == ["get_time"] and not R["r1"]["text"].strip(), f"вызов <tool_call> распознан, на экран не попал: {R['r1']}")
ok(R["mode"] == "https://dewiar.pro/dwrapp/cloud.php?p=", "режим «функции текстом» запомнен для этого сервера")
last = seen[-1]
ok(not last.get("tools") and all(m["role"] in ("system", "user", "assistant") for m in last["messages"]), "второй круг сразу текстом, без роли tool")
ok("<tool_response>" in last["messages"][-1]["content"] and "<tool_call>" in last["messages"][-2]["content"], "результат функции — репликой <tool_response>")
ok(R["r2"]["text"].strip() == "Сейчас 14:41.", f"ответ пришёл: {R['r2']['text']!r}")
ok(not errors, f"без ошибок на странице {errors}")
sys.exit(1 if fails else 0)
