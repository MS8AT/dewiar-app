import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from engine_answer import AnswerMixin
from subscription_context import ContextError


PROFILE = {
    "kind": "chatgpt_subscription",
    "subscription_transport": "codex",
    "subscription_profile_id": "profile",
    "model": "model",
    "subscription_export": True,
    "subscription_usage_reviewed": True,
}


class Settings:
    def active_llm(self):
        return dict(PROFILE)


class Host:
    s = Settings()
    status = {"input": "mic", "stt_ready": True, "stt": "ready", "tts": "ready"}
    cloud = type("Cloud", (), {"key": ""})()
    updater = type("Updater", (), {"url": "https://example.invalid", "public": lambda self: {"available": ""}})()

    def device_status(self):
        return {"level": "ok", "stt_server": False, "ram": 16, "cores": 8, "light": False, "advice": ""}


class SubscriptionSelfCheckTest(unittest.TestCase):
    @patch("httpx.get")
    @patch("shutil.disk_usage", return_value=type("Disk", (), {"free": 10 * 2 ** 30})())
    @patch("engine_answer.list_models")
    @patch("subscription_context.ready")
    def test_subscription_uses_local_contract_without_inference(self, ready, list_models, _disk, http_get):
        http_get.return_value = type("Response", (), {"status_code": 200})()
        result = AnswerMixin.self_check(Host())
        brain = next(item for item in result if item["name"] == "Мозг")
        self.assertTrue(brain["ok"])
        self.assertIn("тестовый запрос не отправлялся", brain["detail"])
        ready.assert_called_once()
        list_models.assert_not_called()

    @patch("httpx.get")
    @patch("shutil.disk_usage", return_value=type("Disk", (), {"free": 10 * 2 ** 30})())
    @patch("engine_answer.list_models")
    @patch("subscription_context.ready", side_effect=ContextError("Выберите аккаунт и модель отдельного режима Codex."))
    def test_subscription_reports_local_contract_failure(self, _ready, list_models, _disk, http_get):
        http_get.return_value = type("Response", (), {"status_code": 200})()
        result = AnswerMixin.self_check(Host())
        brain = next(item for item in result if item["name"] == "Мозг")
        self.assertFalse(brain["ok"])
        self.assertEqual(brain["page"], "brain")
        list_models.assert_not_called()

    @patch("httpx.get")
    @patch("shutil.disk_usage", return_value=type("Disk", (), {"free": 10 * 2 ** 30})())
    @patch("engine_answer.list_models")
    @patch("subscription_context.ready", side_effect=RuntimeError("secret-profile-value"))
    def test_internal_failure_is_redacted(self, _ready, list_models, _disk, http_get):
        http_get.return_value = type("Response", (), {"status_code": 200})()
        result = AnswerMixin.self_check(Host())
        brain = next(item for item in result if item["name"] == "Мозг")
        self.assertFalse(brain["ok"])
        self.assertNotIn("secret-profile-value", brain["detail"])
        list_models.assert_not_called()


if __name__ == "__main__":
    unittest.main()
