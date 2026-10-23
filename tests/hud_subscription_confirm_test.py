"""PATCH-006: виджет восстанавливает пропущенное локальное подтверждение Codex.

Проверка полностью автономна: заглушка ядра не вызывает модель и не использует сеть.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(condition, message):
    print(("✅ " if condition else "❌ ") + message)
    if not condition:
        fails.append(message)


tmp = Path(tempfile.mkdtemp()) / "ui"
shutil.copytree(SRC / "ui", tmp)
(tmp / "assets/dewiar.js").write_text(r"""
window.api = () => null;
window.__calls = [];
window.__pending = {ok: true, data: {id: 'codex-nonce-1', text: 'Запустить задачу через Codex?'}};
window.core = {
  connected: true, _on: {},
  on(k, f) { (this._on[k] = this._on[k] || []).push(f); return this; },
  emit(k, e) { for (const f of this._on[k] || []) f(e); },
  async call(name, args) {
    window.__calls.push([name, args || {}]);
    if (name === 'subscription_confirm_get') return window.__pending;
    if (name === 'subscription_confirm_answer') {
      if (args.id !== 'codex-nonce-1' || typeof args.ok !== 'boolean') return {ok: false, error: 'bad nonce'};
      window.__pending = {ok: true, data: null}; return {ok: true, data: null};
    }
    return {};
  }
};
""", encoding="utf-8")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 420, "height": 620})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto((tmp / "hud.html").as_uri())
    page.wait_for_function("document.querySelector('#yn').classList.contains('on')")
    ok(page.locator("#bot").inner_text() == "Запустить задачу через Codex?",
       "после загрузки восстановлен точный текст pending-подтверждения")
    ok(page.locator("#yn").get_attribute("data-confirm-id") == "codex-nonce-1",
       "восстановлен точный nonce")
    page.locator("#y").click()
    page.wait_for_function("!document.querySelector('#yn').classList.contains('on')")
    call = page.evaluate("window.__calls.filter(x => x[0] === 'subscription_confirm_answer').at(-1)")
    ok(call == ["subscription_confirm_answer", {"id": "codex-nonce-1", "ok": True}],
       "разрешение отправлено отдельной локальной командой с точным nonce")
    ok("Запускаю задачу" in page.locator("#bot").inner_text(), "после разрешения показан понятный статус")

    page.evaluate("""() => {
      window.__pending = {ok: true, data: {id: 'codex-nonce-1', text: 'Ещё одно подтверждение'}};
      window.dispatchEvent(new Event('focus'));
    }""")
    page.wait_for_function("document.querySelector('#yn').classList.contains('on')")
    page.evaluate("""() => { window.__pending = {ok: true, data: null}; window.dispatchEvent(new Event('focus')); }""")
    page.wait_for_function("!document.querySelector('#yn').classList.contains('on')")
    ok("истекло" in page.locator("#bot").inner_text(), "просроченный вопрос не остаётся похожим на активный")

    page.evaluate("""() => core.emit('confirm', {id: 'generic-1', text: 'Обычное подтверждение'});""")
    page.wait_for_function("document.querySelector('#yn').classList.contains('on')")
    page.locator("#n").click()
    page.wait_for_timeout(100)
    generic = page.evaluate("window.__calls.filter(x => x[0] === 'confirm_answer').at(-1)")
    ok(generic == ["confirm_answer", {"id": "generic-1", "ok": False}],
       "обычные подтверждения Dewiar сохранили прежний маршрут")
    ok(not errors, f"страница без JS-ошибок: {errors[:3]}")
    browser.close()

print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
