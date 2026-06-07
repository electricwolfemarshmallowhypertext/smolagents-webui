from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


REDACTED_VALUE = "[redacted]"
SECRET_KEY_FRAGMENTS = (
    "api_key",
    "token",
    "secret",
    "password",
    "authorization",
    "bearer",
)


def to_json_compatible(value: Any, *, max_depth: int = 6) -> Any:
    """Convert arbitrary Python values into JSON-safe structures."""

    if max_depth < 0:
        return "<max-depth-reached>"

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    if is_dataclass(value):
        return to_json_compatible(asdict(value), max_depth=max_depth - 1)

    if isinstance(value, Mapping):
        return {str(key): to_json_compatible(item, max_depth=max_depth - 1) for key, item in value.items()}

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_compatible(item, max_depth=max_depth - 1) for item in value]

    if hasattr(value, "dict") and callable(value.dict):
        try:
            return to_json_compatible(value.dict(), max_depth=max_depth - 1)
        except Exception:
            return str(value)

    return str(value)


def is_secret_key(key: Any) -> bool:
    normalized = str(key).lower()
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_secrets(value: Any, *, max_depth: int = 6) -> Any:
    """Convert values to JSON-safe structures while redacting secret-bearing keys."""

    json_value = to_json_compatible(value, max_depth=max_depth)
    return _redact_json_compatible(json_value, max_depth=max_depth)


def _redact_json_compatible(value: Any, *, max_depth: int) -> Any:
    if max_depth < 0:
        return "<max-depth-reached>"

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if is_secret_key(text_key):
                redacted[text_key] = REDACTED_VALUE
            else:
                redacted[text_key] = _redact_json_compatible(item, max_depth=max_depth - 1)
        return redacted

    if isinstance(value, list):
        return [_redact_json_compatible(item, max_depth=max_depth - 1) for item in value]

    return value
