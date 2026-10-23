"""PATCH-007: кнопка HUD циклически выбирает RU -> ENG -> CH -> RU.

Проверка автономна: заглушка ядра не вызывает модель и не использует сеть.
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
window.core = {
  connected: true, _on: {},
  on(k, f) { (this._on[k] = this._on[k] || []).push(f); return this; },
  emit(k, e) { for (const f of this._on[k] || []) f(e); },
  async call(name, args) {
    window.__calls.push([name, args || {}]);
    if (name === 'language_set') {
      const labels = {ru: 'RU', en: 'ENG', zh: 'CH'};
      return {code: args.code, label: labels[args.code], status: 'ok'};
    }
    if (name === 'subscription_confirm_get') return {ok: true, data: null};
    return {};
  }
};
""", encoding="utf-8")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 440, "height": 640})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto((tmp / "hud.html").as_uri())
    button = page.locator("#b-lang")
    ok(button.inner_text() == "RU", "по умолчанию видна кнопка RU")

    button.click()
    page.wait_for_function("document.querySelector('#b-lang').textContent === 'ENG'")
    button.click()
    page.wait_for_function("document.querySelector('#b-lang').textContent === 'CH'")
    calls = page.evaluate("window.__calls.filter(x => x[0] === 'language_set')")
    ok(calls == [["language_set", {"code": "en"}], ["language_set", {"code": "zh"}]],
       "ENG и CH идут через отдельную команду language_set")

    page.evaluate("core.emit('settings', {settings: {language: 'ru', ui: {}, privacy: {local_only: false}}})")
    page.wait_for_function("document.querySelector('#b-lang').textContent === 'RU'")
    ok("русский" in (button.get_attribute("title") or ""), "событие settings возвращает RU и русскую подсказку")
    ok(not errors, f"страница без JS-ошибок: {errors[:3]}")
    browser.close()

print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
