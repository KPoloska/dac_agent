from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import asdict, is_dataclass
from .util import sanitize_json
from jsonschema import Draft202012Validator


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "review_result.schema.json"


class SchemaValidationError(RuntimeError):
    pass


def validate_review_result(data: Any, schema_path: Optional[Path] = None) -> None:
    # Accept ReviewResult dataclass (and similar) directly.
    if hasattr(data, "to_dict") and callable(getattr(data, "to_dict")):
        data = data.to_dict()
    elif is_dataclass(data):
        data = asdict(data)
    # Make it JSON-safe (e.g., convert NaN/inf, Path objects, etc.)
    data = sanitize_json(data)
    sp = schema_path or DEFAULT_SCHEMA_PATH
    if not sp.exists():
        raise SchemaValidationError(f"Schema file not found: {sp}")

    schema = json.loads(sp.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = ["Review result JSON does not match schema:"]
        for e in errors[:25]:
            path = "$"
            for p in e.path:
                path += f"[{p!r}]" if isinstance(p, int) else f".{p}"
            lines.append(f"- {path}: {e.message}")
        if len(errors) > 25:
            lines.append(f"... and {len(errors) - 25} more errors")
        raise SchemaValidationError("\n".join(lines))
