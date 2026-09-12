"""Home Assistant websocket client (helpers + Android notification actions)."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from typing import Any, Callable

from settings import Settings

try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore[assignment]


def _log(message: str) -> None:
    print(f"[training_coach] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def websocket_url(api_url: str) -> str:
    url = api_url.rstrip("/")
    if url.endswith("/api"):
        url = url[:-4] + "/websocket"
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    if url.startswith("ws://") or url.startswith("wss://"):
        return url
    return "ws://" + url


class HaWebsocket:
    """Short-lived authenticated websocket for Home Assistant commands."""

    def __init__(self, api_url: str, token: str, timeout: int = 20) -> None:
        self.api_url = api_url
        self.token = token
        self.timeout = timeout
        self._ws: Any = None
        self._msg_id = 1

    def connect(self) -> None:
        if websocket is None:
            raise RuntimeError("websocket-client not installed")
        self._ws = websocket.create_connection(websocket_url(self.api_url), timeout=self.timeout)
        hello = json.loads(self._ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected websocket hello: {hello}")
        self._ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth = json.loads(self._ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA websocket auth failed: {auth}")

    def command(self, command_type: str, data: dict[str, Any] | None = None) -> Any:
        if self._ws is None:
            raise RuntimeError("websocket not connected")
        msg_id = self._msg_id
        self._msg_id += 1
        payload: dict[str, Any] = {"id": msg_id, "type": command_type}
        if data:
            payload.update(data)
        self._ws.send(json.dumps(payload))
        while True:
            raw = self._ws.recv()
            if not raw:
                raise RuntimeError("websocket closed")
            msg = json.loads(raw)
            if msg.get("id") != msg_id or msg.get("type") != "result":
                continue
            if not msg.get("success"):
                err = msg.get("error") or {}
                raise RuntimeError(err.get("message") or str(err) or "websocket command failed")
            return msg.get("result")

    def close(self) -> None:
        if self._ws is None:
            return
        try:
            self._ws.close()
        except Exception:
            pass
        self._ws = None

    def __enter__(self) -> "HaWebsocket":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def run_action_listener(
    settings: Settings,
    token: str,
    api_url: str,
    on_event: Callable[[dict[str, Any]], None],
    stop: threading.Event,
) -> None:
    if websocket is None:
        _log("websocket-client not installed; Android actions disabled")
        return
    url = websocket_url(api_url)
    msg_id = 1

    while not stop.is_set():
        try:
            ws = websocket.create_connection(url, timeout=20)
        except Exception as exc:  # noqa: BLE001
            _log(f"HA websocket connect failed: {exc}")
            stop.wait(8)
            continue
        try:
            hello = json.loads(ws.recv())
            if hello.get("type") != "auth_required":
                _log(f"Unexpected websocket hello: {hello}")
            ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth = json.loads(ws.recv())
            if auth.get("type") != "auth_ok":
                _log(f"HA websocket auth failed: {auth}")
                ws.close()
                stop.wait(15)
                continue
            ws.send(
                json.dumps(
                    {
                        "id": msg_id,
                        "type": "subscribe_events",
                        "event_type": "mobile_app_notification_action",
                    }
                )
            )
            msg_id += 1
            _log("Subscribed to mobile_app_notification_action")
            ws.settimeout(5)
            while not stop.is_set():
                try:
                    raw = ws.recv()
                except Exception:
                    continue
                if not raw:
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") != "event":
                    continue
                event = payload.get("event") or {}
                data = event.get("data") or {}
                if not data:
                    continue
                try:
                    on_event(data)
                except Exception as exc:  # noqa: BLE001
                    _log(f"Action handler failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            _log(f"HA websocket error: {exc}")
        finally:
            try:
                ws.close()
            except Exception:
                pass
        stop.wait(5)


def parse_action_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
