from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


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
