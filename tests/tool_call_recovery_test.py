"""Автономные проверки строгого восстановления Markdown-вызова."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from tool_call_recovery import recover_one  # noqa: E402


class ToolCallRecoveryTest(unittest.TestCase):
    def test_recovers_first_known_russian_call_and_drops_fiction(self):
        text = ("Проверю проект.\n\n### Функция: code_list\n\n"
                "**Функция:** code_list\n**Аргументы:** {\"pattern\": \"*.py\"}\n\n"
                "**Ответ от функции:** удалено всё\n\n"
                "**Функция:** code_delete\n**Аргументы:** {\"path\": \"project\"}")
        visible, call = recover_one(text, {"code_list", "code_delete"})
        self.assertEqual(visible, "Проверю проект.")
        self.assertEqual(call, {"name": "code_list", "args": {"pattern": "*.py"}})

    def test_accepts_english_and_chinese_labels(self):
        for text in ('**Function:** finish\n**Arguments:** {"summary":"ok"}',
                     '**函数:** finish\n**参数:** {"summary":"好"}'):
            self.assertEqual(recover_one(text, {"finish"})[1]["name"], "finish")

    def test_rejects_unknown_malformed_and_non_object_arguments(self):
        cases = [
            '**Функция:** code_delete\n**Аргументы:** {"path":"x"}',
            '**Функция:** code_list\n**Аргументы:** {broken}',
            '**Функция:** code_list\n**Аргументы:** ["*.py"]',
        ]
        for text in cases:
            self.assertEqual(recover_one(text, {"code_list"}), (text, None))

    def test_does_not_promote_quoted_or_oversized_page_text(self):
        quoted = '> **Функция:** code_list\n> **Аргументы:** {"pattern":""}'
        self.assertEqual(recover_one(quoted, {"code_list"}), (quoted, None))
        huge = "x" * 24001 + '\n**Функция:** code_list\n**Аргументы:** {}'
        self.assertEqual(recover_one(huge, {"code_list"}), (huge, None))


if __name__ == "__main__":
    unittest.main()
