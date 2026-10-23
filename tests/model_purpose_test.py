"""Автономный выбор модели для чата и задач без сети и inference."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import llm  # noqa: E402
from model_purpose import choose  # noqa: E402

MODELS = ["openai/gpt-oss-20b", "wb-node21-qwen3.5-9b", "qwen2.5-1.5b-instruct",
          "qwen3.5-9b", "qwen/qwen3.8-27b", "qwen/qwen3.6-35b-a3b", "wb-node8-nomic-embed"]


class ModelPurposeTest(unittest.TestCase):
    def setUp(self):
        llm._model_cache.clear()

    def test_chat_keeps_light_instruct_choice(self):
        self.assertEqual(choose(MODELS, "chat"), "qwen2.5-1.5b-instruct")

    def test_tasks_choose_balanced_tool_family_and_skip_embedding(self):
        self.assertEqual(choose(MODELS, "tasks"), "wb-node21-qwen3.5-9b")
        self.assertNotIn("embed", choose(MODELS, "tasks"))

    def test_small_model_is_not_preferred_for_tasks(self):
        models = ["qwen2.5-1.5b-instruct", "qwen3.5-9b"]
        self.assertEqual(choose(models, "tasks"), "qwen3.5-9b")

    def test_explicit_model_is_never_replaced(self):
        self.assertEqual(llm.resolve_model({"model": "manual"}), "manual")

    def test_auto_cache_is_separate_by_role(self):
        base = {"kind": "openai", "base_url": "http://synthetic.invalid/v1"}
        with patch.object(llm, "list_models", return_value=MODELS):
            self.assertEqual(llm.resolve_model(dict(base, _brain_role="chat")), "qwen2.5-1.5b-instruct")
            self.assertEqual(llm.resolve_model(dict(base, _brain_role="tasks")), "wb-node21-qwen3.5-9b")
        self.assertEqual(len(llm._model_cache), 2)


if __name__ == "__main__":
    unittest.main()
