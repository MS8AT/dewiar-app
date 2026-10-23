"""Minimal source staging and cleanup using synthetic local files only."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("stage_human", Path(__file__).resolve().parents[1] / "tools/stage_human_memory.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StageTest(unittest.TestCase):
    def test_copies_import_closure_without_data_and_removes_temporary_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workspace"
            service = root / "Source/c_HUMAN_MEMORY/service.py"
            service.parent.mkdir(parents=True)
            service.write_text("# Synthetic facade\n", encoding="utf-8")
            package = root / "Source/c_AI_SEMANTIC_MEMORY/09_runtime/src/ai_new_memory"
            package.mkdir(parents=True)
            for name, text in {"__init__.py": "", "config.py": "", "human_memory.py": "from . import helper\n",
                               "helper.py": "", "unused.py": "", "data.sqlite3": "PRIVATE", ".env": "PRIVATE"}.items():
                (package / name).write_text(text, encoding="utf-8")
            adapter = Path(temporary) / "adapter.py"
            adapter.write_text("# Synthetic transport\n", encoding="utf-8")
            receipt = module.stage(root, Path(temporary) / "local", adapter)
            names = {row["path"] for row in receipt["files"]}
            self.assertEqual(len(names), 6)
            self.assertFalse(any(name.endswith((".sqlite3", ".env", "unused.py")) for name in names))
            self.assertTrue(receipt["temporary_stage_removed"])
            self.assertFalse(receipt["key_copied"])
            self.assertFalse(receipt["database_copied"])
            for row in receipt["files"]:
                self.assertEqual(hashlib.sha256((Path(receipt["target"]) / row["path"]).read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
