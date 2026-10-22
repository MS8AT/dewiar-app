"""Синтетические проверки DPAPI, ACL и мьютекса.

Хранилище настоящих сеансов не читается и не создаётся.
"""
import unittest
import os
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import windows_store
from windows_store import crypt, api, current_sid, descriptor, secure_subdirectories, check_acl


@unittest.skipUnless(os.name == "nt", "DPAPI и SID доступны только в Windows")
class DPAPITest(unittest.TestCase):
    def test_roundtrip(self):
        payload = b"synthetic-not-a-credential-20261022"
        encrypted = crypt(payload)
        self.assertNotIn(payload, encrypted)
        self.assertEqual(crypt(encrypted, decrypt=True), payload)

    def test_tampering_rejected(self):
        encrypted = bytearray(crypt(b"synthetic-test"))
        encrypted[-1] ^= 1
        with self.assertRaises(RuntimeError):
            crypt(bytes(encrypted), decrypt=True)

    def test_protected_directories_and_unsafe_existing_acl(self):
        k, a = api()
        sid = current_sid(k, a)
        sd, sa = descriptor(a, sid)
        try:
            with tempfile.TemporaryDirectory(prefix="siwc-synthetic-acl-") as directory:
                root = Path(directory)
                protected = secure_subdirectories(root, k, a, sid, sa)
                check_acl(protected, k, a, sid)
                self.assertEqual(secure_subdirectories(root, k, a, sid, sa), protected)
                with self.assertRaises(RuntimeError):
                    check_acl(root, k, a, sid)
        finally:
            k.LocalFree(sd)

    def test_cross_process_mutex_and_release(self):
        # Подменяем только создание хранилища в тестовых процессах.
        # Настоящий профиль, SDK, токены, вход и модель не задействованы.
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import windows_store as m; "
                "m.storage=lambda *args: 'SYNTHETIC_STORE_NOT_USED'; sys.exit(m.guard())")
        args = [sys.executable, "-I", "-B", "-c", code, str(Path(windows_store.__file__).parent)]
        options = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        first = subprocess.Popen(args, **options)
        try:
            self.assertTrue(json.loads(first.stdout.readline())["ready"])
            second = subprocess.run(args, input=b"", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(json.loads(second.stdout)["code"], "busy")
        finally:
            first.stdin.close()
            first.wait(timeout=10)
            first.stdout.close()
        third = subprocess.run(args, input=b"", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertTrue(json.loads(third.stdout)["ready"])


if __name__ == "__main__":
    unittest.main()
