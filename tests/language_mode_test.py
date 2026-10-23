"""PATCH-007: язык ответа и голоса без сети и вызова модели."""
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import language_mode as language
from engine_commands import CommandsMixin
from settings import DEFAULTS


assert DEFAULTS["language"] == "ru"
assert [language.normalize(x) for x in ("RU", "ENG", "CH", "zh-CN")] == ["ru", "en", "zh", "zh"]
try:
    language.normalize("de", strict=True)
    raise AssertionError("неизвестный язык принят")
except ValueError:
    pass

assert language.public("ru")["label"] == "RU"
assert language.public("en")["label"] == "ENG"
assert language.public("zh")["label"] == "CH"
assert "Respond in English" in language.prompt("en")
assert "简体中文" in language.prompt("zh")
assert language.voice_id("en", "female") == "en_US-amy-medium"
assert language.voice_id("en", "male") == "en_US-ryan-medium"
assert language.voice_id("zh", "male") == "zh_CN-huayan-medium"
assert language.voice_id("ru", "female") == ""

original = {"piper": "ru_RU-denis-medium", "_gender": "male", "length_scale": 1.2}
configured = language.voice_config("zh", original)
assert configured["piper"] == "zh_CN-huayan-medium"
assert configured["_language"] == "zh" and configured["_language_name"] == "Chinese"
assert original == {"piper": "ru_RU-denis-medium", "_gender": "male", "length_scale": 1.2}

# Оба маршрута ответа обязаны использовать один модуль; тест остаётся автономным.
answer_source = (ROOT / "core/engine_answer.py").read_text(encoding="utf-8")
codex_source = (ROOT / "core/subscription_context.py").read_text(encoding="utf-8")
commands_source = (ROOT / "core/engine_commands.py").read_text(encoding="utf-8")
remote_source = (ROOT / "core/engine_remote.py").read_text(encoding="utf-8")
assert "language_prompt(self.s.get(\"language\"))" in answer_source
assert "language_prompt(host.s.get(\"language\"))" in codex_source
assert 'if cmd == "language_set"' in commands_source
assert "_language_voice_fetch" in commands_source and "_language_voice_fetch" in remote_source


class FakeSettings:
    def __init__(self):
        self.data = {"language": "ru", "persona": "lira"}

    def get(self, *keys):
        value = self.data
        for key in keys:
            value = value.get(key)
        return copy.deepcopy(value)

    def update(self, patch):
        self.data.update(copy.deepcopy(patch))

    def snapshot(self):
        return copy.deepcopy(self.data)


class FakePersonas:
    @staticmethod
    def get(_pid):
        return {"gender": "female"}


class FakePiper:
    @staticmethod
    def has(voice_id):
        return voice_id == "en_US-amy-medium"


class FakeEngine:
    def __init__(self):
        self.s, self.personas, self.piper = FakeSettings(), FakePersonas(), FakePiper()
        self.events = []

    def emit(self, name, **data):
        self.events.append((name, data))

    def _language_voice_fetch(self, *_args):
        raise AssertionError("готовый тестовый голос не должен скачиваться")


fake = FakeEngine()
result = CommandsMixin.command(fake, "language_set", {"code": "ENG"})
assert result["code"] == "en" and result["voice_ready"] is True
assert fake.s.get("language") == "en"
assert fake.events[-1][0] == "settings" and fake.events[-1][1]["settings"]["language"] == "en"
try:
    CommandsMixin.command(fake, "language_set", {"code": "xx"})
    raise AssertionError("language_set принял неизвестный язык")
except ValueError:
    pass

print("ALL OK: RU/ENG/CH prompts, voices, chat routes and explicit command")
