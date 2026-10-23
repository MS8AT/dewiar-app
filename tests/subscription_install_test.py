"""Проверки установки и отката на временных синтетических приложениях.

Настоящий Dewiar не открывается; процессы и сеть не затрагиваются.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "tools" / "install_local_codex.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app, self.source, self.backup = root / "app", root / "source", root / "backup"
        for p in (self.app, self.source):
            (p / "core").mkdir(parents=True)
        (self.app / "core/a.py").write_bytes(b"before")
        (self.source / "core/a.py").write_bytes(b"after")
        (self.source / "core/b.py").write_bytes(b"new")
        (self.app / "settings.json").write_bytes(b"must not change")
        sha = lambda b: hashlib.sha256(b).hexdigest()
        self.files = [{"path": "core/a.py", "before": sha(b"before"), "after": sha(b"after")},
                      {"path": "core/b.py", "before": None, "after": sha(b"new")}]
        self.manifest = self.source / "manifest.json"
        self.manifest.write_text(json.dumps({"version": 1, "files": self.files}), encoding="utf-8")

    def call(self, mode):
        return installer.transfer(mode, self.app, self.backup, self.source, self.manifest)

    def test_check_does_not_write(self):
        self.assertEqual(self.call("check"), "base")
        self.assertFalse(self.backup.exists())
        self.assertEqual((self.app / "core/a.py").read_bytes(), b"before")

    def test_install_and_rollback_preserve_unlisted_files(self):
        self.assertEqual(self.call("install"), "installed")
        self.assertEqual(self.call("check"), "installed")
        self.assertEqual((self.app / "core/a.py").read_bytes(), b"after")
        self.assertTrue((self.app / "core/b.py").exists())
        self.assertEqual(self.call("rollback"), "base")
        self.assertEqual((self.app / "core/a.py").read_bytes(), b"before")
        self.assertFalse((self.app / "core/b.py").exists())
        self.assertEqual((self.app / "settings.json").read_bytes(), b"must not change")

    def test_changed_baseline_refuses_before_backup(self):
        (self.app / "core/a.py").write_bytes(b"user edit")
        with self.assertRaises(ValueError):
            self.call("install")
        self.assertFalse(self.backup.exists())

    def test_changed_payload_refuses_before_backup(self):
        (self.source / "core/b.py").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.call("install")
        self.assertFalse(self.backup.exists())

    def test_rollback_refuses_later_user_edits(self):
        self.call("install")
        (self.app / "core/b.py").write_bytes(b"user edit")
        with self.assertRaises(ValueError):
            self.call("rollback")
        self.assertEqual((self.app / "core/a.py").read_bytes(), b"after")

    def test_partial_install_is_recoverable(self):
        self.call("install")
        (self.app / "core/a.py").write_bytes(b"before")
        with self.assertRaises(ValueError):
            self.call("check")
        self.call("rollback")
        self.assertFalse((self.app / "core/b.py").exists())

    def test_manifest_traversal_and_duplicate_rejected(self):
        for name in ("core/../outside", "core//a.py", "C:/a.py", "../a.py", "core/a.py"):
            self.files[1]["path"] = name
            self.manifest.write_text(json.dumps({"version": 1, "files": self.files}))
            with self.assertRaises(ValueError):
                self.call("install")
            self.assertFalse(self.backup.exists())

    def test_corrupt_backup_refuses_before_writing(self):
        self.call("install")
        (self.backup / "core/a.py").write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.call("rollback")
        self.assertTrue((self.app / "core/b.py").exists())

    def test_new_file_cannot_replace_a_directory(self):
        (self.app / "core/b.py").mkdir()
        with self.assertRaises(ValueError):
            self.call("install")
        self.assertFalse(self.backup.exists())

    def test_published_manifest_matches_source_files(self):
        for item in installer.entries(ROOT / "tools/local_codex_manifest.json"):
            with self.subTest(path=item["path"]):
                self.assertEqual(installer.digest(ROOT / item["path"]), item["after"])

    def test_process_guard_excludes_own_pid_but_still_refuses_dewiar(self):
        # --app содержит путь Dewiar: сам установщик не является работающим ядром.
        with patch.object(installer.subprocess, "run") as run:
            run.return_value.returncode = 0
            installer.stopped()
            command = run.call_args.args[0][-1]
            self.assertIn(f"$_.ProcessId -ne {installer.os.getpid()}", command)
            self.assertIn("Get-CimInstance Win32_Process", command)
            run.return_value.returncode = 2
            with self.assertRaises(ValueError):
                installer.stopped()


if __name__ == "__main__":
    unittest.main()
