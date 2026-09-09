"""Bounded, strict JSON loading shared by engine content formats."""

import json
import math
from pathlib import Path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        _constant(value)
    return number


def load_json(path, *, max_bytes=32 * 1024 * 1024):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    with Path(path).open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"JSON file exceeds {max_bytes} bytes")
    try:
        result = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    except RecursionError as error:
        raise ValueError("JSON nesting is too deep") from error
    pending = [(result, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            raise ValueError("JSON nesting exceeds 64 levels")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
    return result


def write_json(path, payload):
    text = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
