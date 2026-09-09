"""Explicit schemas for nested tactical state retained by checkpoints."""

from engine.definitions import ENGINEER_BUILD_TYPES, ROLES, STANCE

FACTION = {"enum": ("player", "enemy")}
WORLD_SHAPES = {
    "_line_cache": {
        "mapping": [
            {
                "tuple": [
                    "number",
                    "number",
                    "number",
                    "number",
                    "nonnegative_int",
                    "nonnegative_int",
                ]
            },
            {"tuple": ["bool", "nonnegative", "nonnegative_int", "number"]},
        ]
    },
    "_los_cache": {
        "mapping": [
            {
                "tuple": [
                    "positive_int",
                    "positive_int",
                    "tile",
                    "tile",
                    {"enum": tuple(STANCE)},
                    {"enum": tuple(STANCE)},
                    "nonnegative_int",
                    "nonnegative_int",
                ]
            },
            "bool",
        ]
    },
    "_path_cache": {
        "mapping": [
            {
                "tuple": [
                    "tile",
                    "tile",
                    {"enum": ("fast", "safe", "manual")},
                    FACTION,
                    "nonnegative_int",
                ]
            },
            {"tuple_of": "tile"},
        ]
    },
    "_threat_grids": {"mapping": [FACTION, "threat_grid"]},
    "_mortar_solutions": {
        "mapping": [
            {"tuple": ["positive_int", "int", "int", "bool"]},
            {"enum": (1, 2, 3)},
        ]
    },
    "intel": {
        "record": {
            faction: {
                "mapping": [
                    "positive_int",
                    {
                        "record": {
                            "pos": "pos",
                            "seen": "nonnegative",
                            "role": {"enum": tuple(ROLES)},
                        }
                    },
                ]
            }
            for faction in ("player", "enemy")
        }
    },
    "objectives": {
        "list": {
            "record": {
                "title": "str",
                "desc": "str",
                "pos": "map_pos",
                "progress": "unit_interval",
                "state": {"enum": ("active", "locked", "complete")},
            }
        }
    },
    "construction_reservations": {
        "mapping": [
            "tile",
            {"tuple": ["positive_int", {"enum": tuple(ENGINEER_BUILD_TYPES)}, FACTION]},
        ]
    },
    "combat2_tactical_plans": {
        "mapping": [
            "positive_int",
            {
                "record": {
                    "squad_id": "positive_int",
                    "offensive": "bool",
                    "phase": {
                        "enum": (
                            "base_of_fire",
                            "maneuver",
                            "assault",
                            "counterattack",
                            "reposition",
                            "hold",
                        )
                    },
                    "target": "pos",
                    "target_uid": {"one_of": ["positive_int", "null"]},
                    "flank": "pos",
                    "support_active": "bool",
                    "created": "nonnegative",
                }
            },
        ]
    },
    "defense_attack_plan": {
        "mapping": [
            "positive_int",
            {
                "record": {
                    "assignment": {
                        "enum": ("breach", "assault", "fire_support", "sustainment")
                    },
                    "sector": {"enum": ("NORTH", "CENTRE", "SOUTH")},
                    "wave": {"enum": (1, 2, 3)},
                    "revision": "positive_int",
                }
            },
        ]
    },
    "polish_recent_tracers": {
        "list": {"tuple": ["number", "number", "number", "number", FACTION, "number"]}
    },
    "rally_points": {"record": {"player": "map_pos", "enemy": "map_pos"}},
}
