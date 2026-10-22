"""Upstream не заменяет форк: fake manifest, ни скачивания, ни запуска установщика."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import types
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from updater import Updater
from fork_update_policy import status


class ForkPolicyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.up = Updater(None, "0.39.2", self.root, source_managed=True)

    def test_unconfigured_is_not_auto_update_ready(self):
        state = self.up.public()["fork"]
        self.assertEqual(state["state"], "unconfigured")
        self.assertFalse(state["auto_download"] or state["auto_install"])
        self.assertIn("trusted_release_feed", state["blockers"])

    def test_new_upstream_is_discovery_only_even_with_download_true(self):
        m = {"version": "0.40.0", "exe": "x.exe", "deb": "x.deb", "sha256": "a" * 64, "notes": "new"}
        with patch.object(self.up, "_fetch", return_value=({**m, "windows": m}, "https://synthetic.invalid/")), patch.object(self.up, "_download") as dl:
            self.assertIsNone(self.up.check(download=True))
            dl.assert_not_called()
        self.assertEqual(self.up.public()["upstream"]["version"], "0.40.0")
        self.assertTrue(self.up.public()["upstream"]["newer"])
        self.assertIsNone(self.up.public()["available"])

    def test_direct_download_refused_before_http(self):
        with self.assertRaises(ValueError): self.up._download({})
        self.assertFalse(list(self.root.iterdir()))

    def test_malformed_version_cannot_stop_discovery(self):
        for version in ("9" * 5000, "latest", "1.2.3-secret"):
            m = {"version": version, "exe": "x.exe", "deb": "x.deb"}
            with patch.object(self.up, "_fetch", return_value=({**m, "windows": m}, "https://synthetic.invalid/")):
                self.up.check()
            self.assertEqual(self.up.public()["upstream"]["version"], "")
            self.assertFalse(self.up.public()["upstream"]["newer"])

    def test_failed_check_marks_cached_discovery_stale_without_raw_error(self):
        self.up.upstream_info = {"version": "0.40.0", "checked_at": 1}
        with patch.object(self.up, "_fetch", side_effect=ValueError("SECRET")):
            self.up.check()
        out = self.up.public()
        self.assertFalse(out["fork"]["discovery"]["ok"])
        self.assertEqual(out["fork"]["discovery"]["error"], "network_or_manifest_error")
        self.assertEqual(out["upstream"]["checked_at"], 1)
        self.assertNotIn("SECRET", json.dumps(out))

    def test_nonobject_manifest_cannot_stop_discovery(self):
        for manifest in ([], {"windows": []}):
            with patch.object(self.up, "_fetch", return_value=(manifest, "https://synthetic.invalid/")):
                self.assertIsNone(self.up.check())
            self.assertFalse(self.up.public()["fork"]["discovery"]["ok"])

    def test_status_hides_old_installer_paths(self):
        self.up.failed = {"path": "old.exe"}
        self.up.available = {"path": "old.exe"}
        out = self.up.public()
        self.assertIsNone(out["available"])
        self.assertIsNone(out["failed"])

    def test_ui_install_paths_refuse_before_any_launch(self):
        tree = ast.parse((ROOT / "ui/app.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Api")
        funcs = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {"install_update", "_install_update_win", "run_installer"}]
        ns = {}; exec(compile(ast.Module(body=funcs, type_ignores=[]), "update-guard-fixture", "exec"), ns)
        host = types.SimpleNamespace(_fork_managed=True)
        for fn in funcs:
            args = (None, None) if fn.name == "_install_update_win" else (None,)
            self.assertFalse(ns[fn.name](host, *args)["ok"])

    def test_existing_nonmanaged_updater_contract_preserved(self):
        other = Updater(None, "0.39.2", self.root)
        self.assertNotIn("fork", other.public())

    def test_voice_reports_unconfigured_not_network_failure(self):
        tree = ast.parse((ROOT / "core/engine_answer.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_direct_update")
        ns = {"threading": threading}; exec(compile(ast.Module(body=[fn], type_ignores=[]), "voice-update-fixture", "exec"), ns)
        said, done = [], threading.Event()
        def speak(msg, *a): said.append(msg); done.set()
        host = types.SimpleNamespace(updater=self.up, _say_quick=speak)
        with patch.object(self.up, "check", return_value=None), patch.dict(sys.modules, {"engine_base": types.SimpleNamespace(UPDATE_RX=types.SimpleNamespace(match=lambda x: True))}):
            self.assertTrue(ns["_direct_update"](host, "Обновись"))
            self.assertTrue(done.wait(2))
        self.assertIn("не настроен", said[0])
        self.assertNotIn("сайт не ответил", said[0])


if __name__ == "__main__": unittest.main()
