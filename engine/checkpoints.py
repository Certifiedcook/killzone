"""Validated reconstruction of versioned local battle checkpoints."""

from dataclasses import fields
import hashlib
import math
import random
import sys
import types
from typing import Union, get_args, get_origin, get_type_hints

from engine import models
from engine.content import load_json
from engine.definitions import MAP_H, MAP_W, ROLES, STANCE, TERRAIN, WEAPONS
from engine.revisions import TerrainRevision
from engine.scenarios import Scenario
from engine.simulation import RealTimeGame
from engine.state import (
    MODEL_TYPES,
    TRANSIENT_FIELDS,
    StateError,
    canonical_json,
    engine_signature,
)
from engine.state_fields import GAME_FIELDS, UNIT_FIELDS, UNIT_DYNAMIC_TYPES
from engine.state_shapes import WORLD_SHAPES


def _require(condition, location, message):
    if not condition:
        raise StateError(f"{location}: {message}")


def _field_names(values, allowed, required, location):
    _require(type(values) is dict, location, "expected attribute dictionary")
    _require(
        all(type(name) is str for name in values),
        location,
        "attribute names must be strings",
    )
    _require(
        not (values.keys() - allowed),
        location,
        f"unknown attributes {sorted(values.keys() - allowed)!r}",
    )
    _require(
        not (required - values.keys()),
        location,
        f"missing attributes {sorted(required - values.keys())!r}",
    )


def _matches(value, hint):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Union, types.UnionType):
        return any(_matches(value, choice) for choice in args)
    if hint is float:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    if hint in (str, int, bool, type(None)):
        return type(value) is hint
    if origin is list:
        return type(value) is list and all(_matches(item, args[0]) for item in value)
    if origin is tuple:
        return (
            type(value) is tuple
            and len(value) == len(args)
            and all(_matches(item, kind) for item, kind in zip(value, args))
        )
    if hint is set:
        return type(value) is set
    return True


def _validate_model(value, location):
    cls = type(value)
    declared = {field.name for field in fields(cls)} - {"_revision_state"}
    allowed = UNIT_FIELDS if cls is models.Unit else declared
    attributes = vars(value)
    _field_names(attributes, allowed, declared, location)
    for name, hint in get_type_hints(cls).items():
        if name in attributes:
            _require(
                _matches(attributes[name], hint),
                f"{location}.{name}",
                "invalid field type or shape",
            )
    if cls is models.Cell:
        _require(value.terrain in TERRAIN, location, "unknown terrain")
        _require(value.axis in (None, "H", "V"), location, "invalid terrain axis")
    if cls is models.Unit:
        for name, specification in UNIT_DYNAMIC_TYPES.items():
            if name in attributes:
                _require(
                    _matches_spec(attributes[name], specification),
                    f"{location}.{name}",
                    "invalid dynamic field type or shape",
                )
        _require(value.uid > 0, location, "unit ID must be positive")
        _require(value.faction in ("player", "enemy"), location, "unknown faction")
        _require(
            value.role in ROLES and value.weapon_name in WEAPONS,
            location,
            "unknown role or weapon",
        )
        _require(value.stance in STANCE, location, "unknown stance")
        _require(
            value.casualty
            in ("healthy", "wounded", "incapacitated", "dead", "surrendered"),
            location,
            "unknown casualty state",
        )
        _require(
            0 <= value.x <= MAP_W - 1 and 0 <= value.y <= MAP_H - 1,
            location,
            "unit position is outside map",
        )
        for name in ("path", "waypoints", "route_preview"):
            _require(
                all(0 <= x < MAP_W and 0 <= y < MAP_H for x, y in getattr(value, name)),
                f"{location}.{name}",
                "coordinate outside map",
            )
        for command, argument in value.command_queue:
            valid = command == "move" and _matches(argument, tuple[int, int])
            valid = valid or (command == "fire" and _matches(argument, tuple[int, str]))
            _require(valid, f"{location}.command_queue", "invalid queued order")
    if cls is models.BallisticRound:
        _require(
            value.round_id > 0 and value.shooter_uid > 0,
            location,
            "invalid projectile IDs",
        )
        _require(
            value.faction in ("player", "enemy") and value.weapon_name in WEAPONS,
            location,
            "invalid projectile faction or weapon",
        )
        _require(
            all(_matches(tile, tuple[int, int]) for tile in value.visited_cells),
            location,
            "invalid projectile cell history",
        )
        _require(
            all(type(uid) is int and uid > 0 for uid in value.suppressed_uids),
            location,
            "invalid suppressed unit IDs",
        )


def _matches_spec(value, specification):
    if type(specification) is str:
        if specification in ("positive_int", "nonnegative_int"):
            return type(value) is int and value >= (
                1 if specification == "positive_int" else 0
            )
        if specification in ("nonnegative", "unit_interval"):
            return (
                _matches(value, float)
                and value >= 0
                and (specification != "unit_interval" or value <= 1)
            )
        if specification in ("tile", "pos", "map_pos"):
            valid = _matches(
                value,
                tuple[int, int] if specification == "tile" else tuple[float, float],
            )
            return valid and (
                specification == "pos"
                or 0 <= value[0] < MAP_W
                and 0 <= value[1] < MAP_H
            )
        if specification == "threat_grid":
            return (
                type(value) is list
                and len(value) == MAP_H
                and all(
                    type(row) is list
                    and len(row) == MAP_W
                    and all(_matches_spec(cell, "nonnegative") for cell in row)
                    for row in value
                )
            )
        return _matches(
            value,
            {"number": float, "int": int, "bool": bool, "str": str, "null": type(None)}[
                specification
            ],
        )
    if "enum" in specification:
        return any(
            type(value) is type(option) and value == option
            for option in specification["enum"]
        )
    if "list" in specification or "tuple_of" in specification:
        kind, key = (list, "list") if "list" in specification else (tuple, "tuple_of")
        return type(value) is kind and all(
            _matches_spec(item, specification[key]) for item in value
        )
    if "mapping" in specification:
        key_type, item_type = specification["mapping"]
        return type(value) is dict and all(
            _matches_spec(key, key_type) and _matches_spec(item, item_type)
            for key, item in value.items()
        )
    if "record" in specification:
        record = specification["record"]
        return (
            type(value) is dict
            and set(value) == set(record)
            and all(
                _matches_spec(value[key], expected) for key, expected in record.items()
            )
        )
    if "one_of" in specification:
        return any(_matches_spec(value, option) for option in specification["one_of"])
    if "literal" in specification:
        return (
            type(value) is type(specification["literal"])
            and value == specification["literal"]
        )
    shape = specification["tuple"]
    return (
        type(value) is tuple
        and len(value) == len(shape)
        and all(_matches_spec(item, expected) for item, expected in zip(value, shape))
    )


class _Decoder:
    def __init__(self):
        self.nodes = 0

    def decode(self, value, location="state", depth=0):
        self.nodes += 1
        _require(
            depth <= 64 and self.nodes <= 2_000_000,
            location,
            "state exceeds decoding limits",
        )
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float:
            _require(math.isfinite(value), location, "non-finite number")
            return value

        def decode(child, suffix):
            return self.decode(child, f"{location}.{suffix}", depth + 1)

        if type(value) is list:
            return [decode(child, index) for index, child in enumerate(value)]
        _require(type(value) is dict, location, "expected a tagged JSON object")
        tag = value.get("$type")
        _require(type(tag) is str, location, "missing type tag")
        if tag in ("dict", "tuple", "set", "frozenset"):
            _require(
                set(value) == {"$type", "items"} and type(value["items"]) is list,
                location,
                "invalid container tag",
            )
            if tag == "dict":
                result = {}
                for index, pair in enumerate(value["items"]):
                    _require(
                        type(pair) is list and len(pair) == 2,
                        location,
                        "invalid dictionary entry",
                    )
                    key, item = decode(pair[0], f"key[{index}]"), decode(pair[1], index)
                    try:
                        _require(
                            key not in result,
                            location,
                            "duplicate decoded dictionary key",
                        )
                        result[key] = item
                    except TypeError as error:
                        raise StateError(
                            f"{location}: unhashable dictionary key"
                        ) from error
                return result
            items = [decode(child, index) for index, child in enumerate(value["items"])]
            try:
                result = {"tuple": tuple, "set": set, "frozenset": frozenset}[tag](
                    items
                )
                _require(
                    tag == "tuple" or len(result) == len(items),
                    location,
                    "duplicate decoded set member",
                )
                return result
            except TypeError as error:
                raise StateError(f"{location}: unhashable set member") from error
        if tag == "Random":
            _require(set(value) == {"$type", "state"}, location, "invalid RNG tag")
            state = decode(value["state"], "rng")
            _require(
                type(state) is tuple
                and len(state) == 3
                and type(state[0]) is int
                and state[0] == 3,
                location,
                "unsupported RNG state",
            )
            words = state[1]
            _require(
                type(words) is tuple
                and len(words) == 625
                and all(
                    type(word) is int and 0 <= word <= 0xFFFFFFFF for word in words[:-1]
                )
                and type(words[-1]) is int
                and 0 <= words[-1] <= 624,
                location,
                "invalid RNG words",
            )
            _require(
                state[2] is None or _matches(state[2], float),
                location,
                "invalid RNG Gaussian cache",
            )
            rng = random.Random(0)
            rng.setstate(state)
            return rng
        if tag == "TerrainRevision":
            _require(
                set(value) == {"$type", "value"}
                and type(value["value"]) is int
                and value["value"] >= 0,
                location,
                "invalid terrain revision",
            )
            return TerrainRevision(value["value"])
        _require(tag in MODEL_TYPES, location, f"unknown type {tag!r}")
        _require(set(value) == {"$type", "fields"}, location, "invalid model tag")
        attributes = decode(value["fields"], "fields")
        cls = MODEL_TYPES[tag]
        declared = {field.name for field in fields(cls)} - {"_revision_state"}
        _field_names(
            attributes,
            UNIT_FIELDS if cls is models.Unit else declared,
            declared,
            location,
        )
        model = object.__new__(cls)
        vars(model).update(attributes)
        _validate_model(model, location)
        return model


def _validate_world(state, template):
    required = vars(template).keys() - TRANSIENT_FIELDS
    _field_names(state, GAME_FIELDS, required, "state")
    for name, specification in WORLD_SHAPES.items():
        _require(
            _matches_spec(state[name], specification),
            f"state.{name}",
            "invalid nested state shape",
        )
    for name, initial in vars(template).items():
        if name in TRANSIENT_FIELDS or initial is None:
            continue
        actual = state[name]
        expected = type(initial)
        valid = (
            _matches(actual, float) if expected is float else type(actual) is expected
        )
        _require(valid, f"state.{name}", "invalid field type")
    grid, units = state["grid"], state["units"]
    _require(
        len(state["objectives"]) > 0
        and type(state["objective_index"]) is int
        and 0 <= state["objective_index"] <= len(state["objectives"]),
        "state.objective_index",
        "invalid objective collection or index",
    )
    _require(
        all(
            key == plan["squad_id"]
            for key, plan in state["combat2_tactical_plans"].items()
        ),
        "state.combat2_tactical_plans",
        "plan squad ID differs from its key",
    )
    _require(
        len(grid) == MAP_H
        and all(
            type(row) is list
            and len(row) == MAP_W
            and all(type(cell) is models.Cell for cell in row)
            for row in grid
        ),
        "state.grid",
        "invalid grid dimensions or cell types",
    )
    collections = {
        "units": models.Unit,
        "explosions": models.Explosion,
        "tracers": models.Tracer,
        "impacts": models.Impact,
        "blood": models.BloodDecal,
        "dust": models.DustPuff,
        "bounding_orders": models.BoundingOrder,
        "assault_orders": models.AssaultOrder,
        "ballistic_rounds": models.BallisticRound,
    }
    for name, kind in collections.items():
        _require(
            type(state[name]) is list
            and all(type(item) is kind for item in state[name]),
            f"state.{name}",
            "invalid model collection",
        )
    for name, collection, key in (
        ("next_uid", units, "uid"),
        ("next_ballistic_round_id", state["ballistic_rounds"], "round_id"),
    ):
        ids = [getattr(item, key) for item in collection]
        _require(len(ids) == len(set(ids)), f"state.{name}", "duplicate IDs")
        _require(
            type(state[name]) is int and state[name] > max(ids, default=0),
            f"state.{name}",
            "next ID must exceed existing IDs",
        )
    _require(
        type(state["rng"]) is random.Random
        and type(state["_terrain_state"]) is TerrainRevision,
        "state",
        "invalid RNG or terrain tracker",
    )
    _require(state["time"] >= 0, "state.time", "negative simulation time")
    _require(
        _matches(state["wind"], tuple[int, int])
        and state["wind"] in ((1, 0), (-1, 0), (0, 1), (0, -1)),
        "state.wind",
        "invalid wind vector",
    )
    _require(
        all(type(text) is str for text in state["log"]),
        "state.log",
        "invalid log entries",
    )
    for name in ("notifications", "battle_events", "events", "objectives"):
        _require(
            all(type(item) is dict for item in state[name]),
            f"state.{name}",
            "expected object entries",
        )
    for notice in state["notifications"]:
        _require(
            set(notice) == {"text", "kind", "born", "until"}
            and all(type(notice[key]) is str for key in ("text", "kind"))
            and all(_matches(notice[key], float) for key in ("born", "until")),
            "state.notifications",
            "invalid notification",
        )
    for event in state["battle_events"]:
        _require(
            set(event) == {"time", "kind", "text", "pos"}
            and _matches(event["time"], float)
            and type(event["kind"]) is str
            and type(event["text"]) is str
            and _matches(event["pos"], tuple[float, float] | None),
            "state.battle_events",
            "invalid battle event",
        )
    for event in state["events"]:
        _require(type(event.get("type")) is str, "state.events", "missing event type")
    _require(
        state.get("network_replica", False) is False,
        "state.network_replica",
        "network replicas cannot be restored as local battles",
    )
    for tile, uid in state["_occupancy"].items():
        _require(
            _matches(tile, tuple[int, int]) and type(uid) is int,
            "state._occupancy",
            "invalid occupancy entry",
        )


def restore_checkpoint(payload):
    """Validate completely and create a new world; never mutate an existing game."""
    _require(type(payload) is dict, "checkpoint", "expected an object")
    expected = {
        "format",
        "schema_version",
        "engine_signature",
        "python_runtime",
        "scenario",
        "state",
        "sha256",
    }
    _require(set(payload) == expected, "checkpoint", "invalid envelope fields")
    _require(
        payload["format"] == "killzone-battle"
        and type(payload["schema_version"]) is int
        and payload["schema_version"] == 1,
        "checkpoint.schema_version",
        "unsupported format or version",
    )
    _require(
        payload["engine_signature"] == engine_signature(),
        "checkpoint.engine_signature",
        "simulation source differs from saved battle",
    )
    _require(
        payload["python_runtime"]
        == [sys.implementation.name, sys.version_info.major, sys.version_info.minor],
        "checkpoint.python_runtime",
        "Python runtime differs from saved battle",
    )
    unsigned = {key: value for key, value in payload.items() if key != "sha256"}
    try:
        encoded = canonical_json(unsigned).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as error:
        raise StateError("checkpoint: invalid JSON payload") from error
    _require(len(encoded) <= 32 * 1024 * 1024, "checkpoint", "state exceeds size limit")
    _require(
        type(payload["sha256"]) is str
        and hashlib.sha256(encoded).hexdigest() == payload["sha256"],
        "checkpoint.sha256",
        "integrity check failed",
    )
    scenario = Scenario.from_dict(payload["scenario"])
    state = _Decoder().decode(payload["state"])
    template = scenario.create_game()
    _validate_world(state, template)
    game = object.__new__(RealTimeGame)
    vars(game).update(state)
    try:
        saved_scenario = Scenario.from_dict(
            {
                "schema_version": 1,
                "seed": game.seed,
                "difficulty": game.difficulty,
                "player_roster": game.player_roster,
                "reserve_count": game.reserve_count,
                "operation": game.operation_config,
            }
        )
    except ValueError as error:
        raise StateError(f"checkpoint.scenario: {error}") from error
    _require(
        saved_scenario == scenario,
        "checkpoint.scenario",
        "settings do not match saved state",
    )
    game._perf = dict(template._perf)
    game.profile_enabled = False
    game._uid_index = {unit.uid: unit for unit in game.units}
    game._living_cache = {
        faction: game.living(faction) for faction in ("player", "enemy")
    }
    for row in game.grid:
        for cell in row:
            cell._revision_state = game._terrain_state
    return game


def load_checkpoint(path):
    return restore_checkpoint(load_json(path))
