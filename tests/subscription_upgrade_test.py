"""Полный выпуск и откат на синтетической копии, без пользовательских файлов и сети."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import upgrade_local_release as upgrade


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source, self.app, self.backup, self.plan = (root / p for p in ("source", "app", "backup", "plan.json"))
        self.names = sorted(upgrade.REQUIRED - {"core/version.py"}) + ["data/example.txt", "icons/example.png", "core/version.py"]
        for target in (self.app, self.source):
            for name in self.names:
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).write_bytes(b"lock" if name == "requirements-win.lock" else
                                            b"before" if target == self.app else b"after")
        (self.app / "data/example.txt").unlink()
        (self.app / "user-extra.txt").write_bytes(b"preserve")
        mocked = patch.object(upgrade, "payload", return_value=self.names)
        mocked.start()
        self.addCleanup(mocked.stop)

    def prepare(self):
        return upgrade.prepare(self.app, self.plan, self.source)

    def call(self, mode):
        return upgrade.execute(mode, self.app, self.backup, self.plan, self.source)

    def test_plan_check_install_rollback(self):
        self.assertEqual(self.prepare(), 7)
        self.call("check")
        self.assertFalse(self.backup.exists())
        self.call("install")
        self.assertEqual((self.app / "core/version.py").read_bytes(), b"after")
        self.call("rollback")
        self.assertEqual((self.app / "core/version.py").read_bytes(), b"before")
        self.assertFalse((self.app / "data/example.txt").exists())
        self.assertEqual((self.app / "user-extra.txt").read_bytes(), b"preserve")

    def test_dependency_change_refused(self):
        (self.app / "requirements-win.lock").write_bytes(b"different")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.plan.exists())

    def test_baseline_change_refused(self):
        self.prepare()
        (self.app / "ui/app.py").write_bytes(b"user edit")
        with self.assertRaises(ValueError):
            self.call("install")
        self.assertFalse(self.backup.exists())

    def test_changed_source_refused(self):
        self.prepare()
        (self.source / "ui/app.py").write_bytes(b"unexpected")
        with self.assertRaises(ValueError):
            self.call("install")
        self.assertFalse(self.backup.exists())

    def test_different_target_refused(self):
        self.prepare()
        data = json.loads(self.plan.read_text())
        data["app"] = "elsewhere"
        self.plan.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.call("install")

    def test_incomplete_traversal_case_duplicate_refused(self):
        self.prepare()
        original = self.plan.read_text()
        for name in ("core/../outside", "core/CON.", "ui/APP.py", "elsewhere/a"):
            data = json.loads(original)
            data["files"][0]["path"] = name
            self.plan.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                self.call("install")
        self.assertFalse(self.backup.exists())

    def test_reordered_payload_refused(self):
        self.prepare()
        data = json.loads(self.plan.read_text())
        data["files"].reverse()
        self.plan.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.call("install")

    def test_partial_write_has_valid_backup(self):
        self.prepare()
        replace = upgrade.installer.replace
        count = 0
        def fail(source, target):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("simulated interruption")
            replace(source, target)
        with patch.object(upgrade.installer, "replace", side_effect=fail):
            with self.assertRaises(OSError):
                self.call("install")
        self.call("rollback")
        self.call("check")


class SourceTests(unittest.TestCase):
    def test_actual_source_is_complete_and_excludes_tests(self):
        names = upgrade.payload(ROOT)
        self.assertTrue(upgrade.REQUIRED <= set(names))
        self.assertFalse(upgrade.TESTS & set(names))
        self.assertEqual(names[-1], "core/version.py")
        self.assertIn("ui/studio/subscription_confirm.js", names)


if __name__ == "__main__":
    unittest.main()
