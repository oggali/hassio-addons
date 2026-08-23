"""Home Assistant Supervisor API client."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (base_url or os.environ.get("HA_URL") or "http://supervisor/core/api").rstrip("/")
        self.token = token or os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN") or ""
        self.timeout = timeout
        if not self.token:
            raise RuntimeError("No Home Assistant token (SUPERVISOR_TOKEN or HA_TOKEN)")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        resp = requests.get(
            f"{self.base_url}/states/{entity_id}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_states(self, entity_ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            try:
                state = self.get_state(entity_id)
            except requests.RequestException:
                continue
            if state:
                out[entity_id] = state
        return out

    def set_state(
        self,
        entity_id: str,
        state: str,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"state": state}
        if attributes is not None:
            payload["attributes"] = attributes
        resp = requests.post(
            f"{self.base_url}/states/{entity_id}",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def call_service(self, domain: str, service: str, data: dict[str, Any] | None = None) -> Any:
        resp = requests.post(
            f"{self.base_url}/services/{domain}/{service}",
            headers=self._headers(),
            json=data or {},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        if not resp.content:
            return None
        return resp.json()

    def get_history(
        self,
        entity_ids: list[str],
        start: datetime,
        end: datetime | None = None,
    ) -> list[list[dict[str, Any]]]:
        if not entity_ids:
            return []
        start_utc = start.astimezone(timezone.utc)
        params = {
            "filter_entity_id": ",".join(entity_ids),
            "minimal_response": "true",
            "significant_changes_only": "true",
        }
        if end is not None:
            params["end_time"] = end.astimezone(timezone.utc).isoformat()
        url = f"{self.base_url}/history/period/{quote(start_utc.isoformat())}"
        resp = requests.get(
            url,
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
