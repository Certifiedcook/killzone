"""Canonical, non-executable representation of deterministic battle state.

Temporal LOS, threat and path memoization is behavioral state and is retained.
Only metrics and indexes that are rebuilt from primary objects are omitted.
"""

import hashlib
import json
import math
import random
from functools import lru_cache
from pathlib import Path
import sys

from engine import models
from engine.revisions import TerrainRevision
from engine.simulation import RealTimeGame
from engine.scenarios import Scenario
from engine.content import write_json

MODEL_TYPES = {
    cls.__name__: cls
    for cls in (
        models.Cell,
        models.Unit,
        models.Explosion,
        models.Tracer,
        models.Impact,
        models.BloodDecal,
        models.BoundingOrder,
        models.AssaultOrder,
        models.DustPuff,
        models.BallisticRound,
    )
}
TRANSIENT_FIELDS = frozenset(
    {"_perf", "profile_enabled", "_uid_index", "_living_cache", "_ballistic_spatial"}
)


class StateError(ValueError):
    pass


def encode_value(value, *, location="state", _active=None):
    """Encode only explicitly supported values; reject unknown objects and cycles."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise StateError(f"{location}: non-finite number")
        return value
    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        raise StateError(f"{location}: cyclic state is unsupported")
    active.add(identity)

    def encode(child, suffix):
        return encode_value(child, location=f"{location}.{suffix}", _active=active)

    try:
        if type(value) is list:
            return [encode(child, index) for index, child in enumerate(value)]
        if type(value) is dict:
            return {
                "$type": "dict",
                "items": [
                    [encode(key, "key"), encode(child, key)]
                    for key, child in value.items()
                ],
            }
        if type(value) in (tuple, set, frozenset):
            children = [encode(child, index) for index, child in enumerate(value)]
            if type(value) is not tuple:
                children.sort(key=canonical_json)
            return {"$type": type(value).__name__, "items": children}
        if type(value) is random.Random:
            return {"$type": "Random", "state": encode(value.getstate(), "rng")}
        if type(value) is TerrainRevision:
            if type(value.value) is not int or value.value < 0:
                raise StateError(
                    f"{location}: terrain revision must be a nonnegative integer"
                )
            return {"$type": "TerrainRevision", "value": value.value}
        if type(value) in MODEL_TYPES.values():
            fields = vars(value).copy()
            if type(value) is models.Cell:
                fields.pop("_revision_state", None)
            return {"$type": type(value).__name__, "fields": encode(fields, "fields")}
        raise StateError(f"{location}: unsupported object type {type(value).__name__}")
    finally:
        active.remove(identity)


def canonical_json(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def capture_state(game):
    """Read a local world without consuming RNG, rebuilding caches or mutating it."""
    if type(game) is not RealTimeGame:
        raise StateError("state: only local RealTimeGame worlds are supported")
    return encode_value(
        {key: value for key, value in vars(game).items() if key not in TRANSIENT_FIELDS}
    )


def state_fingerprint(game):
    return hashlib.sha256(
        canonical_json(capture_state(game)).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=1)
def engine_signature():
    """Fingerprint shipped simulation source, independent of path and line endings."""
    root = Path(__file__).resolve().parent
    sources = [
        root / name
        for name in (
            "simulation.py",
            "models.py",
            "definitions.py",
            "rules.py",
            "revisions.py",
            "spatial.py",
        )
    ]
    sources.extend(sorted((root / "systems").glob("*.py")))
    digest = hashlib.sha256()
    for path in sources:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_text(encoding="utf-8").encode("utf-8") + b"\0")
    return digest.hexdigest()


def export_checkpoint(game):
    """Export allowlisted JSON state with explicit source/runtime compatibility.

    No pickle, imports named by a file, or executable payloads are used.
    """
    payload = {
        "format": "killzone-battle",
        "schema_version": 1,
        "engine_signature": engine_signature(),
        "python_runtime": [
            sys.implementation.name,
            sys.version_info.major,
            sys.version_info.minor,
        ],
        "scenario": Scenario.from_game(game).to_dict(),
        "state": capture_state(game),
    }
    payload["sha256"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return payload


def save_checkpoint(game, path):
    write_json(path, export_checkpoint(game))
