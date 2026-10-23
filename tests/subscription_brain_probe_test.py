"""Подписочный мозг не проходит обычную фоновую проверку tools.

Проверка автономна: сеть, хранилище аккаунта и модель не вызываются.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from engine_answer import AnswerMixin  # noqa: E402


class Settings:
    def __init__(self, profile):
        self.profile = profile

    def active_llm(self):
        return dict(self.profile)


class Host(AnswerMixin):
    def __init__(self, profile):
        self.s = Settings(profile)
        self._probing = set()


class SubscriptionBrainProbeTests(unittest.TestCase):
    def test_subscription_profile_never_starts_generic_tools_probe(self):
        host = Host({"kind": "chatgpt_subscription", "subscription_transport": "codex",
                     "subscription_profile_id": "account", "model": "model"})
        with patch("engine_answer.probe_tools") as probe, patch("engine_answer.threading.Thread") as thread:
            host.probe_tools_bg(force=True)
        probe.assert_not_called()
        thread.assert_not_called()
        self.assertEqual(host._probing, set())


if __name__ == "__main__":
    unittest.main()
