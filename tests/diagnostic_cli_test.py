"""CLI и ограниченный API на fake WebSocket: без токена пользователя и без сервера."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import diagnostic_cli as cli
from bridge import Bridge


class Socket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def send(self, msg): self.sent.append(json.loads(msg))
    def recv(self, **kw): return json.dumps(self.incoming.pop(0))


class CliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.token = Path(temp.name) / "token"
        self.token.write_text("a" * 64)

    def test_scoped_handshake_and_only_diagnostic_command(self):
        socket = Socket([{"type": "hello", "data": {"limited": True, "scope": "diagnostics"}},
                         {"type": "reply", "id": 1, "ok": True, "data": {"schema": 1, "action": "sli"}}])
        def connect(url, **kwargs):
            self.assertEqual(url, "ws://127.0.0.1:8765")
            self.assertIsNone(kwargs["proxy"])
            return socket
        self.assertEqual(cli.request("sli", self.token, connect=connect)["action"], "sli")
        self.assertEqual(socket.sent[0]["scope"], "diagnostics")
        self.assertEqual(socket.sent[1]["cmd"], "diagnostics_read")

    def test_old_full_hello_is_not_returned_or_followed(self):
        socket = Socket([{"type": "hello", "data": {"settings": {"api_key": "SECRET"}}}])
        with self.assertRaisesRegex(ValueError, "scope_unavailable"):
            cli.request("status", self.token, connect=lambda *a, **kw: socket)
        self.assertEqual(len(socket.sent), 1)

    def test_server_error_payload_is_not_exposed(self):
        socket = Socket([{"type": "hello", "data": {"limited": True, "scope": "diagnostics"}},
                         {"type": "reply", "id": 1, "ok": False, "error": "SECRET"}])
        with self.assertRaisesRegex(ValueError, "diagnostic_request_failed"):
            cli.request("status", self.token, connect=lambda *a, **kw: socket)

    def test_invalid_command_and_port_fail_before_connect(self):
        for action, port in (("quit", 8765), ("status", 0), ("status", True), ("status", 65536)):
            with self.assertRaises(ValueError):
                cli.request(action, self.token, port, connect=lambda *a, **kw: self.fail("connection forbidden"))

    def test_oversized_token_refused(self):
        self.token.write_text("s" * 1025)
        with self.assertRaises(ValueError): cli.read_token(self.token)

    def test_api_and_smoke_do_not_read_auth_or_connect(self):
        for action in ("api", "test"):
            with patch.object(cli, "request", side_effect=AssertionError), patch.object(cli, "read_token", side_effect=AssertionError):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): self.assertEqual(cli.main([action]), 0)
                self.assertIsInstance(json.loads(out.getvalue()), dict)

    def test_cli_error_is_redacted_and_nonzero(self):
        with patch.object(cli, "request", side_effect=RuntimeError("SECRET")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["status", "--token-file", str(self.token)]), 2)
            self.assertNotIn("SECRET", out.getvalue())

    def test_optimized_python_cannot_skip_offline_checks(self):
        code = f"import sys; sys.path.insert(0, {str(ROOT / 'core')!r}); import brain_routes, diagnostic_cli; brain_routes.needs_probe=lambda *a: True; diagnostic_cli.selftest()"
        result = subprocess.run([sys.executable, "-O", "-B", "-c", code], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("offline_check_failed", result.stderr)

    def test_windows_launcher_packaging(self):
        # CMD не должен зависеть от текущей кодовой страницы Windows.
        launcher = (ROOT / "core/dewiar-cli.cmd").read_bytes()
        launcher.decode("ascii")
        self.assertNotIn(b"\n", launcher.replace(b"\r\n", b""))
        self.assertTrue(launcher.endswith(b"\r\n"))
        self.assertIn(b"*.cmd   text eol=crlf", (ROOT / ".gitattributes").read_bytes())


class AsyncSocket:
    def __init__(self, messages): self.messages, self.sent, self.closed = list(messages), [], None
    async def recv(self): return json.dumps(self.messages.pop(0))
    async def send(self, text): self.sent.append(json.loads(text))
    async def close(self, **kw): self.closed = kw
    def __aiter__(self): return self
    async def __anext__(self):
        if not self.messages: raise StopAsyncIteration
        return json.dumps(self.messages.pop(0))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge("a" * 64)
        self.addCleanup(self.bridge.pool.shutdown, wait=True)
        self.bridge.loop = asyncio.get_running_loop()
        self.calls = []
        self.bridge.handler = lambda cmd, args: self.calls.append(cmd) or {"schema": 1, "action": "status"}

    async def test_scope_skips_snapshot_and_broadcasts(self):
        ws = AsyncSocket([{"token": "a" * 64, "scope": "diagnostics"},
                          {"id": 1, "cmd": "diagnostics_read", "args": {"action": "status"}}])
        await self.bridge._client(ws)
        for _ in range(30):
            if len(ws.sent) == 2: break
            await asyncio.sleep(.01)
        self.assertEqual(self.calls, ["diagnostics_read"])
        self.assertEqual(ws.sent[0], {"type": "hello", "data": {"limited": True, "scope": "diagnostics"}})
        self.assertEqual(len(ws.sent), 2)
        self.assertFalse(self.bridge.clients or self.bridge.limited_ws or self.bridge.seen)

    async def test_scope_rejects_commands_and_wrong_token(self):
        for token in ("a" * 64, "wrong"):
            ws = AsyncSocket([{"token": token, "scope": "diagnostics"}, {"id": 2, "cmd": "task_create"}])
            await self.bridge._client(ws)
            self.assertEqual(self.calls, [])
            if token == "wrong": self.assertEqual(ws.closed["code"], 4001)
            else: self.assertFalse(ws.sent[-1]["ok"])

    async def test_call_scoped_token_cannot_upgrade_to_diagnostics(self):
        self.bridge.allow("call-token", {"call_end"})
        ws = AsyncSocket([{"token": "call-token", "scope": "diagnostics"}])
        await self.bridge._client(ws)
        self.assertEqual(ws.closed["code"], 4001)
        self.assertEqual(self.calls, [])


if __name__ == "__main__": unittest.main()
