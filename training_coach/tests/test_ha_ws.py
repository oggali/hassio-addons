"""Home Assistant websocket helper-create client."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import ha_ws  # noqa: E402
from ha_ws import HaWebsocket  # noqa: E402


class FakeConnection:
    def __init__(self, inbox: list) -> None:
        self.inbox = list(inbox)
        self.sent: list[dict] = []
        self.closed = False

    def recv(self) -> str:
        if not self.inbox:
            raise TimeoutError("no more websocket messages")
        item = self.inbox.pop(0)
        return item if isinstance(item, str) else json.dumps(item)

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def close(self) -> None:
        self.closed = True


class DummyWsModule:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def create_connection(self, url: str, timeout: int = 20):
        self.url = url
        self.timeout = timeout
        return self.conn


class HaWebsocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = ha_ws.websocket

    def tearDown(self) -> None:
        ha_ws.websocket = self._orig

    def test_command_success(self):
        conn = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"id": 1, "type": "event", "event": {}},
                {
                    "id": 1,
                    "type": "result",
                    "success": True,
                    "result": {"id": "training_coach_feeling"},
                },
            ]
        )
        ha_ws.websocket = DummyWsModule(conn)  # type: ignore[assignment]
        with HaWebsocket("http://supervisor/core/api", "tok") as session:
            result = session.command(
                "input_select/create",
                {"name": "Training coach feeling", "options": ["unset", "ok"]},
            )
        self.assertEqual(result, {"id": "training_coach_feeling"})
        self.assertEqual(conn.sent[0], {"type": "auth", "access_token": "tok"})
        self.assertEqual(conn.sent[1]["type"], "input_select/create")
        self.assertEqual(conn.sent[1]["name"], "Training coach feeling")
        self.assertTrue(conn.closed)

    def test_command_error_message(self):
        conn = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {
                    "id": 1,
                    "type": "result",
                    "success": False,
                    "error": {"code": "invalid_format", "message": "required key not provided"},
                },
            ]
        )
        ha_ws.websocket = DummyWsModule(conn)  # type: ignore[assignment]
        session = HaWebsocket("http://ha/api", "tok")
        session.connect()
        with self.assertRaisesRegex(RuntimeError, "required key not provided"):
            session.command("input_datetime/create", {"name": "x"})
        session.close()

    def test_auth_failure(self):
        conn = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_invalid", "message": "Invalid access token"},
            ]
        )
        ha_ws.websocket = DummyWsModule(conn)  # type: ignore[assignment]
        with self.assertRaisesRegex(RuntimeError, "auth failed"):
            HaWebsocket("http://ha/api", "bad").connect()


if __name__ == "__main__":
    unittest.main()
