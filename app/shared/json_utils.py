from __future__ import annotations

import json
from typing import Any


def parse_json_object(raw_text: str, *, empty_error: str, invalid_error: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError(empty_error)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(invalid_error)
