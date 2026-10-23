"""Автономная проверка компактного режима AI-доктора без вызова модели."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import task_doctor as doctor  # noqa: E402


def spec(name, description="очень длинное описание " * 30):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}


class TaskDoctorTest(unittest.TestCase):
    def test_code_mode_keeps_control_code_and_web_only(self):
        source = [spec(n) for n in ("finish", "remember", "code_read", "code_run", "web_search",
                                          "write_file", "smart_home", "spawn_parts")]
        compact = doctor.compact_specs(source, project=True)
        names = {item["name"] for item in compact}
        self.assertEqual(names, {"finish", "remember", "code_read", "code_run", "web_search"})
        self.assertTrue(all(len(item["description"]) <= 220 for item in compact))
        self.assertEqual(compact[0]["parameters"], source[0]["parameters"])

    def test_non_code_mode_keeps_work_and_knowledge(self):
        source = [spec(n) for n in ("finish", "write_file", "run_python", "ask_knowledge", "code_edit", "power")]
        names = {item["name"] for item in doctor.compact_specs(source, project=False)}
        self.assertEqual(names, {"finish", "write_file", "run_python", "ask_knowledge"})

    def test_prompt_is_bounded_and_keeps_goal_plan_edges(self):
        prompt = doctor.compact_system(persona="Агент", title="Изучи", goal="G" * 5000,
                                       notebook="N" * 5000, plan="START\n" + "P" * 5000 + "\nEND",
                                       project=r"Z:\Source", task_dir=r"C:\Task", now="23.10.2026 20:00")
        self.assertLess(len(prompt), 5000)
        self.assertIn("ЗАДАЧА: Изучи", prompt)
        self.assertIn("START", prompt)
        self.assertIn("END", prompt)
        self.assertIn("сокращена AI-доктором", prompt)

    def test_report_contains_sizes_not_content(self):
        data = doctor.report("private prompt", [spec("finish")], "short", [spec("finish")])
        self.assertEqual(data["mode"], "context_compact")
        self.assertNotIn("private prompt", str(data))
        self.assertEqual(data["tools_after"], 1)


if __name__ == "__main__":
    unittest.main()
