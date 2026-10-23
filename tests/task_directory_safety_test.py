"""Уникальность каталогов задач и безопасный точечный откат."""
from pathlib import Path
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from tasks import TaskManager


class TaskDirectorySafetyTests(unittest.TestCase):
    def test_same_title_same_minute_uses_distinct_directories_and_delete_is_local(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            host = types.SimpleNamespace(
                workspace=types.SimpleNamespace(ensure=lambda: base),
                persona_name=lambda: "Synthetic", emit=Mock())
            manager = object.__new__(TaskManager)
            manager.host, manager.tasks = host, {}
            first = manager.create("Same title", "Goal one", start=False)
            second = manager.create("Same title", "Goal two", start=False)
            self.assertNotEqual(first.dir, second.dir)
            self.assertIn(first.id, first.dir.name); self.assertIn(second.id, second.dir.name)
            self.assertEqual(first.id, json.loads((first.dir / "задача.json").read_text(encoding="utf-8"))["id"])
            manager.delete(second.id)
            self.assertTrue(first.dir.is_dir()); self.assertFalse(second.dir.exists())

    def test_discard_created_does_not_depend_on_broken_save_or_emit(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            host = types.SimpleNamespace(workspace=types.SimpleNamespace(ensure=lambda: base),
                                         persona_name=lambda: "Synthetic", emit=Mock())
            manager = object.__new__(TaskManager); manager.host, manager.tasks = host, {}
            task = manager.create("Rollback", "Goal", start=False)
            task.save = Mock(side_effect=OSError("persistent synthetic failure"))
            self.assertTrue(manager.discard_created(task))
            self.assertNotIn(task.id, manager.tasks); self.assertFalse(task.dir.exists())
            task = manager.create("Rollback", "Goal", start=False)
            with patch("shutil.rmtree", side_effect=OSError("persistent synthetic failure")):
                self.assertFalse(manager.discard_created(task))
            self.assertIs(manager.tasks[task.id], task); self.assertTrue(task.dir.exists())


if __name__ == "__main__":
    unittest.main()
