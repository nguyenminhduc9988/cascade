"""Shared utility helpers."""

from __future__ import annotations

import json
from typing import Any

from ulid import ULID


def new_id() -> str:
    """Generate a new time-ordered, sortable 26-char ULID string."""
    return str(ULID())


def dumps(value: Any) -> str:
    """Serialise ``value`` to a compact JSON string (never raises on failure)."""
    return json.dumps(value, default=str, separators=(",", ":"))


def loads(value: str | None) -> Any:
    """Deserialise a JSON string, returning ``{}`` for ``None``/empty input."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
