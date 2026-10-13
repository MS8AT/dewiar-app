"""Персонажи не отвечают друг за друга (отзыв 13.10: «обсудила задачу с Патриком, переключилась на Лиру — а она мне
про задачу Патрика»). core/engine_answer.team_window: разговор с коллегой — одной справкой «это их разговор, не
продолжай его», свой — дословно; перед вопросом после чужого разговора — «[Теперь пользователь обращается к тебе:]»."""
import os, sys
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "core"))
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


from engine_answer import team_window  # noqa: E402
NAMES = {"lira": "Лира", "patrik": "Патрик"}
H = [{"role": "user", "content": "Лира, привет"}, {"role": "assistant", "content": "Привет!", "who": "lira"},
     {"role": "user", "content": "Патрик, давай обсудим ремонт ванной"}, {"role": "assistant", "content": "План: плитка, сантехника.", "who": "patrik"},
     {"role": "user", "content": "Отлично, завтра начнём"}, {"role": "assistant", "content": "Всё записано, завтра начнём.", "who": "patrik"}]
w = team_window(H, "lira", NAMES.get)
ok([m["role"] for m in w] == ["user", "assistant", "user"] and w[0]["content"] == "Лира, привет" and w[1]["content"] == "Привет!",
   f"свой разговор — дословно: {[m['role'] for m in w]}")
ok(w[2].get("team") and "не с тобой, а с коллегой по имени Патрик" in w[2]["content"] and "Патрик: План: плитка" in w[2]["content"]
   and "Пользователь: Отлично, завтра начнём" in w[2]["content"], f"разговор с Патриком — одной справкой: {w[2]['content'][:160]}")
w2 = team_window(H, "patrik", NAMES.get)
ok(w2[0].get("team") and "коллегой по имени Лира" in w2[0]["content"] and [m["role"] for m in w2[1:]] == ["user", "assistant", "user", "assistant"],
   "для Патрика — наоборот: свой разговор дословно, с Лирой — справкой")
ok(team_window([{"role": "user", "content": "Как дела?"}], "lira", NAMES.get) == [{"role": "user", "content": "Как дела?"}], "без ответа — реплика нынешнего")


class P:
    def get(self, pid): return {"name": NAMES.get(pid, "Коллега")}


class S:
    def get(self, *k, default=None): return {("llm", "history_turns"): 20, ("llm", "history_reset_seconds"): 28800, ("persona",): "lira"}.get(tuple(k), default)


class C:
    def expired(self, s): return False
    def window(self, h, n): return h


import engine_answer as EA  # noqa: E402
eng = type("E", (), {"s": S(), "conv": C(), "history": H, "personas": P()})()
msgs = EA.AnswerMixin._messages(eng, "Помоги с поздравлением маме") if hasattr(EA, "AnswerMixin") else None
if msgs is None:
    cls = next(v for v in vars(EA).values() if isinstance(v, type) and hasattr(v, "_messages"))
    msgs = cls._messages(eng, "Помоги с поздравлением маме")
ok(msgs[-1]["role"] == "user" and "[Теперь пользователь обращается к тебе:]\nПомоги с поздравлением маме" in msgs[-1]["content"]
   and all("team" not in m for m in msgs), f"вопрос после чужого разговора — явно к Лире: {msgs[-1]['content'][-90:]!r}")
pp = (ROOT / "core/personas.py").read_text(encoding="utf-8")
app = (ROOT / "android/assets/www/app.js").read_text(encoding="utf-8")
ok("не продолжай его и не отвечай за коллегу" in pp and "не продолжай его и не отвечай за коллегу" in app, "правило команды — в подсказке на компьютере и телефоне")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
