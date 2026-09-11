"""Compatibility shim — decisions now live in DuckDB via store.CoachStore."""

from __future__ import annotations

# Kept so older imports do not break; prefer CoachStore.upsert_decision.
