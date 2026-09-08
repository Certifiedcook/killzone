"""Networking for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from engine.definitions import ENGINEER_BUILD_TYPES
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MAX_PLAYER_UNITS
from engine.definitions import MISSION_VARIANTS
from engine.definitions import NETWORK_PVP_BATTLEFIELDS
from engine.definitions import NETWORK_PVP_DEFAULT_ROSTER
from engine.definitions import NETWORK_UNIT_FIELDS
from engine.definitions import PLAYER_ROLE_ORDER
from engine.definitions import ROLES
from engine.definitions import STATIC_WEAPON_ROLES
from engine.models import Explosion
from engine.models import Impact
from engine.models import Tracer
from src.multiplayer_net import DEFAULT_SERVER_HOST
from src.multiplayer_net import DEFAULT_SERVER_PORT
from engine.simulation import RealTimeGame
import math


def sanitize_network_roster(roster):
    if not isinstance(roster, (list, tuple)):
        return list(NETWORK_PVP_DEFAULT_ROSTER)
    cleaned = [str(role) for role in roster if str(role) in PLAYER_ROLE_ORDER]
    if not cleaned:
        return list(NETWORK_PVP_DEFAULT_ROSTER)
    return cleaned[:MAX_PLAYER_UNITS]


def sanitize_network_battlefield(value):
    value = str(value or "farmland")
    return value if value in NETWORK_PVP_BATTLEFIELDS else "farmland"


def _network_disable_ai(self, _dt):
    return None


def _network_disable_noargs(self):
    return None


def _network_disable_objectives(self, _dt=None):
    return None


def network_pvp_winner(game):
    players = [
        unit
        for unit in game.living("player")
        if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    enemies = [
        unit
        for unit in game.living("enemy")
        if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    if not players and (not enemies):
        return "draw"
    if not players:
        return "enemy"
    if not enemies:
        return "player"
    return None


def _network_check_end(self):
    winner = network_pvp_winner(self)
    if winner == "player":
        self.victory = True
    elif winner == "enemy":
        self.defeat = True


class NetworkGame(RealTimeGame):
    """Authoritative human-versus-human rules over the shared simulation systems."""

    def __init__(self, seed, roster=None, battlefield="farmland"):
        from engine.rules import _operation_open_position
        from engine.rules import clamp

        roster = sanitize_network_roster(roster)
        battlefield = sanitize_network_battlefield(battlefield)
        super().__init__(
            seed=int(seed),
            difficulty="Hard",
            player_roster=roster,
            reserve_count=0,
            operation_config={
                "mission": "assault",
                "variant": battlefield,
                "weather": "auto",
                "enemy_strength": 1.0,
            },
        )
        self.units = [unit for unit in self.units if unit.faction == "player"]
        self._kz_rebuild_indexes()
        for role in roster:
            self.add_unit("enemy", role, MAP_W - 4, MAP_H // 2)
        for faction, units, x_values, facing in (
            ("player", self.living("player"), (3, 5, 7), 0),
            ("enemy", self.living("enemy"), (MAP_W - 4, MAP_W - 6, MAP_W - 8), 180),
        ):
            for index, unit in enumerate(units):
                desired_x = x_values[index % len(x_values)]
                desired_y = 3 + (index * 5 + index // 3) % (MAP_H - 6)
                position = _operation_open_position(
                    self, desired_x, desired_y, unit, radius=10
                )
                if position is not None:
                    unit.x, unit.y = position
                unit.facing = facing
                unit.path = []
                unit.waypoints = []
                unit.command_queue = []
                unit.order = "idle"
                unit.overwatch = False
                unit.fire_lane = False
                unit.hold_position = False
                unit.reserve_active = True
                unit.reserve = False
                unit.battle_role = "pvp"
                unit.plan_state = "human"
                unit.fallback_point = (
                    2 if faction == "player" else MAP_W - 3,
                    int(clamp(round(unit.y), 2, MAP_H - 3)),
                )
        self.network_pvp = True
        self.network_replica = False
        self.mission_type = "pvp"
        self.mission_title = f"PVP — {MISSION_VARIANTS[battlefield]['name']}"
        self.mission_brief = "Defeat the opposing player-controlled force."
        self.objectives = [
            {
                "title": "DEFEAT THE ENEMY FORCE",
                "desc": "Break the opposing commander's combat-effective force.",
                "pos": (MAP_W // 2, MAP_H // 2),
                "progress": 0.0,
                "state": "active",
            }
        ]
        self.objective_index = 0
        self.battle_stage = "PLAYER VERSUS PLAYER"
        self.paused = False
        self.victory = False
        self.defeat = False
        self.network_initial_cells = [
            [
                (cell.terrain, getattr(cell, "axis", None), getattr(cell, "hp", None))
                for cell in row
            ]
            for row in self.grid
        ]
        self.network_dynamic_cells = set()
        self._kz_rebuild_indexes()

    def update_ai(self, dt):
        """Orders come from the two connected players."""

    def update_enemy_builders(self):
        """Both players choose their own construction orders."""

    def update_objectives(self):
        """PVP has one elimination objective, with no campaign progression."""

    def update_mission_state(self, dt):
        self.notifications = [
            item for item in self.notifications if item["until"] > self.time
        ]

    def check_end(self):
        _network_check_end(self)


def create_network_pvp_game(seed, roster=None, battlefield="farmland"):
    """Compatibility factory for the explicit multiplayer game type."""
    return NetworkGame(seed, roster=roster, battlefield=battlefield)


def _network_json_value(value):
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_network_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _network_effect_observed(game, perspective, position, radius):
    from engine.rules import dist

    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return False
    return any(
        (
            unit.combat_effective and dist(unit.pos, position) <= radius
            for unit in game.living(perspective)
        )
    )


def _base_serialize_network_snapshot(game, perspective):
    units = []
    for unit in game.units:
        local = unit.faction == perspective
        visible = local or game.visible_to(perspective, unit)
        record = {
            "uid": unit.uid,
            "faction": "player" if local else "enemy",
            "role": unit.role,
            "visible": visible,
        }
        if local or visible:
            for field in NETWORK_UNIT_FIELDS:
                if hasattr(unit, field):
                    record[field] = _network_json_value(getattr(unit, field))
        else:
            record["casualty"] = unit.casualty if unit.casualty == "dead" else "healthy"
        units.append(record)
    cells = []
    for y, row in enumerate(game.grid):
        for x, cell in enumerate(row):
            baseline = game.network_initial_cells[y][x]
            changed = (
                cell.terrain != baseline[0]
                or getattr(cell, "axis", None) != baseline[1]
                or getattr(cell, "hp", None) != baseline[2]
                or (cell.smoke > 0.02)
                or (cell.fire > 0.02)
                or cell.mine_seen_player
                or cell.mine_seen_enemy
            )
            if changed:
                cells.append(
                    [
                        x,
                        y,
                        cell.terrain,
                        getattr(cell, "axis", None),
                        getattr(cell, "hp", None),
                        round(cell.smoke, 3),
                        round(cell.fire, 3),
                        bool(
                            cell.mine_seen_player
                            if perspective == "player"
                            else cell.mine_seen_enemy
                        ),
                    ]
                )
    contacts = []
    for uid, info, age in game.known_contacts(perspective, memory=10.0):
        contacts.append(
            {
                "uid": uid,
                "pos": [round(info["pos"][0], 3), round(info["pos"][1], 3)],
                "seen": round(game.time - age, 3),
                "role": info.get("role", "CONTACT"),
            }
        )
    winner = network_pvp_winner(game)
    return {
        "time": round(game.time, 4),
        "weather": game.weather,
        "wind": list(game.wind),
        "units": units,
        "cells": cells,
        "contacts": contacts,
        "tracers": [
            [
                list(tracer.a),
                list(tracer.b),
                round(tracer.life, 4),
                round(tracer.total, 4),
            ]
            for tracer in game.tracers[-96:]
            if _network_effect_observed(game, perspective, tracer.a, 16.0)
            or _network_effect_observed(game, perspective, tracer.b, 16.0)
        ],
        "impacts": [
            [round(impact.x, 3), round(impact.y, 3), impact.kind, round(impact.life, 4)]
            for impact in game.impacts[-96:]
            if _network_effect_observed(game, perspective, (impact.x, impact.y), 16.0)
        ],
        "explosions": [
            [
                round(explosion.x, 3),
                round(explosion.y, 3),
                round(explosion.timer, 4),
                round(explosion.radius, 3),
                round(explosion.damage, 3),
                round(explosion.suppression, 3),
                explosion.kind,
                explosion.faction,
            ]
            for explosion in game.explosions[-32:]
            if _network_effect_observed(
                game, perspective, (explosion.x, explosion.y), 24.0
            )
        ],
        "winner": winner,
    }


def _base_apply_network_snapshot(game, snapshot):
    game.time = float(snapshot.get("time", game.time))
    game.weather = str(snapshot.get("weather", game.weather))
    wind = snapshot.get("wind")
    if isinstance(wind, list) and len(wind) == 2:
        game.wind = (float(wind[0]), float(wind[1]))
    game.tracers = [
        Tracer(tuple(record[0]), tuple(record[1]), float(record[2]), float(record[3]))
        for record in snapshot.get("tracers", [])
        if isinstance(record, list) and len(record) >= 4
    ]
    game.impacts = [
        Impact(float(record[0]), float(record[1]), str(record[2]), float(record[3]))
        for record in snapshot.get("impacts", [])
        if isinstance(record, list) and len(record) >= 4
    ]
    game.explosions = [
        Explosion(
            float(record[0]),
            float(record[1]),
            float(record[2]),
            float(record[3]),
            float(record[4]),
            float(record[5]),
            str(record[6]),
            str(record[7]),
        )
        for record in snapshot.get("explosions", [])
        if isinstance(record, list) and len(record) >= 8
    ]
    terrain_before = {}
    for x, y in list(getattr(game, "network_dynamic_cells", set())):
        baseline = game.network_initial_cells[y][x]
        cell = game.grid[y][x]
        terrain_before[(x, y)] = (cell.terrain, cell.axis, cell.hp)
        cell.terrain, cell.axis, cell.hp = baseline
        cell.smoke = 0.0
        cell.fire = 0.0
    game.network_dynamic_cells = set()
    for record in snapshot.get("cells", []):
        if not isinstance(record, list) or len(record) < 8:
            continue
        x, y = (int(record[0]), int(record[1]))
        if not game.in_bounds(x, y):
            continue
        cell = game.grid[y][x]
        terrain_before.setdefault((x, y), (cell.terrain, cell.axis, cell.hp))
        cell.terrain = str(record[2])
        cell.axis = record[3]
        cell.hp = record[4]
        cell.smoke = float(record[5])
        cell.fire = float(record[6])
        cell.mine_seen_player = bool(record[7])
        game.network_dynamic_cells.add((x, y))
    if any(
        before != (game.grid[y][x].terrain, game.grid[y][x].axis, game.grid[y][x].hp)
        for (x, y), before in terrain_before.items()
    ):
        # Invalidate this world's caches once for an actual final-state change.
        game._terrain_state.value += 1
    known_ids = set()
    for record in snapshot.get("units", []):
        if not isinstance(record, dict):
            continue
        uid = int(record.get("uid", -1))
        role = str(record.get("role", "Rifleman"))
        faction = str(record.get("faction", "enemy"))
        if role not in ROLES or faction not in ("player", "enemy"):
            continue
        unit = game.get_unit(uid)
        if unit is None:
            unit = game.add_unit(faction, role, 1, 1)
            unit.uid = uid
            game.next_uid = max(game.next_uid, uid + 1)
        unit.faction = faction
        unit.role = role
        for field in NETWORK_UNIT_FIELDS:
            if field not in record or not hasattr(unit, field):
                continue
            value = record[field]
            if field in ("target_pos",):
                value = tuple(value) if isinstance(value, list) else value
            elif field in ("path", "waypoints") and isinstance(value, list):
                value = [tuple(item) for item in value]
            setattr(unit, field, value)
        visible = bool(record.get("visible", faction == "player"))
        unit.spotted_player_until = (
            game.time + 4.0 if faction == "enemy" and visible else 0.0
        )
        known_ids.add(uid)
    game.intel["player"] = {
        int(contact["uid"]): {
            "pos": tuple(contact["pos"]),
            "seen": float(contact["seen"]),
            "role": str(contact.get("role", "CONTACT")),
        }
        for contact in snapshot.get("contacts", [])
        if isinstance(contact, dict) and "uid" in contact and ("pos" in contact)
    }
    game.network_replica = True
    game._kz_rebuild_indexes()


def _network_owned_units(game, faction, ids):
    if (
        not isinstance(ids, list)
        or len(ids) > MAX_PLAYER_UNITS
        or any(type(uid) is not int or uid <= 0 for uid in ids)
    ):
        return []
    units = []
    for uid in dict.fromkeys(ids):
        unit = game.get_unit(uid)
        if unit is not None and unit.faction == faction and unit.combat_effective:
            units.append(unit)
    return units


def _network_position(game, value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(
        type(coordinate) not in (int, float)
        or (type(coordinate) is float and not math.isfinite(coordinate))
        for coordinate in value
    ):
        return None
    # Check the original coordinates before truncation, including negative fractions.
    if not (0 <= value[0] < MAP_W and 0 <= value[1] < MAP_H):
        return None
    x, y = (int(value[0]), int(value[1]))
    return (x, y) if game.in_bounds(x, y) else None


_POSITION_COMMANDS = frozenset(
    {
        "move",
        "grenade",
        "smoke",
        "rifle_grenade",
        "suppress",
        "overwatch",
        "mortar",
        "assault",
        "bound",
        "fallback",
        "build",
    }
)
_NETWORK_COMMANDS = _POSITION_COMMANDS | {
    "fire",
    "reload",
    "stance",
    "deploy",
    "fire_mode",
    "clear_jam",
    "barrel",
    "bayonet",
    "doctrine",
    "discipline",
    "priority",
    "autonomy",
    "hold",
}


def _validate_network_command(game, faction, message):
    """Validate the complete request before a command can mutate unit state."""
    if not isinstance(message, dict) or message.get("type") != "command":
        return "Expected a command object"
    if faction not in ("player", "enemy"):
        return "Invalid faction"
    action = message.get("action")
    if not isinstance(action, str) or action not in _NETWORK_COMMANDS:
        return "Unsupported command action"
    ids = message.get("units")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_PLAYER_UNITS:
        return f"Expected between 1 and {MAX_PLAYER_UNITS} unit IDs"
    if any(type(uid) is not int or uid <= 0 for uid in ids):
        return "Unit IDs must be positive integers"
    if "sequence" in message and (
        type(message["sequence"]) is not int or message["sequence"] < 0
    ):
        return "Sequence must be a nonnegative integer"
    if action in _POSITION_COMMANDS or "position" in message:
        if _network_position(game, message.get("position")) is None:
            return "Position must contain two finite coordinates inside the battlefield"
    if action == "fire" and (
        type(message.get("target")) is not int or message["target"] <= 0
    ):
        return "Target must be a positive unit ID"
    for field in ("append", "emergency", "enabled", "smoke"):
        if field in message and type(message[field]) is not bool:
            return f"{field.capitalize()} must be a boolean"
    if "cook" in message:
        cook = message["cook"]
        if (
            type(cook) not in (int, float)
            or (type(cook) is float and not math.isfinite(cook))
            or not 0 <= cook <= 1.8
        ):
            return "Grenade cook time must be finite and between 0 and 1.8 seconds"
    if "mode" in message:
        allowed = (
            ("fast", "safe", "manual")
            if action == "move"
            else ("aimed", "snap", "normal", "rapid")
        )
        if not isinstance(message["mode"], str) or message["mode"] not in allowed:
            return "Invalid movement mode" if action == "move" else "Invalid fire mode"
    if "formation" in message and message["formation"] not in (
        "wedge",
        "line",
        "column",
        "spread",
    ):
        return "Invalid formation"
    if action == "build":
        kind = message.get("kind")
        if not isinstance(kind, str) or kind not in ENGINEER_BUILD_TYPES:
            return "Invalid construction type"
    return None


def _base_apply_network_command(game, faction, message):
    from engine.rules import angle_to

    action = str(message.get("action", ""))
    units = _network_owned_units(game, faction, message.get("units", []))
    if not units:
        return (False, "No owned combat-effective units")
    position = _network_position(game, message.get("position"))
    append = bool(message.get("append", False))
    if action == "move" and position is not None:
        game.issue_move(
            units,
            position,
            append=append,
            mode=str(message.get("mode", units[0].move_mode)),
            formation=str(message.get("formation", "wedge")),
        )
    elif action == "fire":
        target = game.get_unit(int(message.get("target", -1)))
        if target is None or target.faction == faction or (not target.combat_effective):
            return (False, "Invalid target")
        if not game.visible_to(faction, target):
            return (False, "Target is not currently observed")
        for unit in units:
            game.issue_fire(unit, target, str(message.get("mode", unit.fire_mode)))
    elif action in ("grenade", "smoke", "rifle_grenade") and position is not None:
        for unit in units:
            game.throw_grenade(
                unit,
                position,
                smoke=action == "smoke",
                rifle=action == "rifle_grenade",
                cook=float(message.get("cook", 0.0)),
            )
    elif action == "suppress" and position is not None:
        for unit in units:
            game.suppress_area(unit, position)
    elif action == "overwatch" and position is not None:
        for unit in units:
            game.set_overwatch(unit, angle_to(unit, position), 90)
    elif action == "reload":
        for unit in units:
            game.start_reload(unit, emergency=bool(message.get("emergency", False)))
    elif action == "stance":
        for unit in units:
            game.cycle_stance(unit)
    elif action == "deploy":
        for unit in units:
            game.toggle_deploy(unit)
    elif action == "fire_mode":
        mode = str(message.get("mode", "normal"))
        if mode not in ("aimed", "snap", "normal", "rapid"):
            return (False, "Invalid fire mode")
        for unit in units:
            unit.fire_mode = mode
    elif action == "clear_jam":
        for unit in units:
            game.clear_jam(unit)
    elif action == "barrel":
        for unit in units:
            game.change_barrel(unit)
    elif action == "bayonet":
        for unit in units:
            game.bayonet_toggle(unit)
    elif action == "mortar" and position is not None:
        for unit in units:
            game.mortar_fire(unit, position, smoke=bool(message.get("smoke", False)))
    elif action == "assault" and position is not None:
        game.coordinated_advance(units, position)
    elif action == "bound" and position is not None:
        game.bounding_advance(units, position)
    elif action == "fallback" and position is not None:
        for unit in units:
            unit.fallback_point = position
        game.issue_move(units, position, mode="safe", formation="column")
    elif action == "build" and position is not None:
        kind = str(message.get("kind", ""))
        engineer, reason = game.queue_construction(
            faction,
            kind,
            position,
            preferred_engineers=[unit for unit in units if unit.role == "Engineer"],
        )
        if engineer is None:
            return (False, reason)
    elif action == "doctrine":
        game.cycle_squad_doctrine(units)
    elif action == "discipline":
        disciplines = ("hold", "return", "free", "confident")
        for unit in units:
            unit.fire_discipline = disciplines[
                (disciplines.index(unit.fire_discipline) + 1) % len(disciplines)
            ]
    elif action == "priority":
        priorities = ("nearest", "exposed", "specialist", "suppressed")
        for unit in units:
            unit.target_priority = priorities[
                (priorities.index(unit.target_priority) + 1) % len(priorities)
            ]
    elif action == "autonomy":
        enabled = bool(message.get("enabled", True))
        for unit in units:
            unit.auto_reload = enabled
            unit.auto_cover = enabled
            unit.auto_smoke = enabled
            unit.auto_medic = enabled
    elif action == "hold":
        enabled = bool(message.get("enabled", True))
        for unit in units:
            unit.hold_position = enabled
            if enabled:
                unit.path = []
                unit.waypoints = []
                unit.order = "idle"
    else:
        return (False, "Unsupported or incomplete command")
    return (True, "")


def _network_parse_address(value):
    value = str(value).strip()
    if not value:
        return (DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT)
    if ":" not in value:
        return (value, DEFAULT_SERVER_PORT)
    host, port = value.rsplit(":", 1)
    return (host.strip(), int(port))


def _network_normalize_client_factions(game, side):
    if side != "enemy":
        return
    for unit in game.units:
        unit.faction = "player" if unit.faction == "enemy" else "enemy"
    game._kz_rebuild_indexes()


def serialize_network_snapshot(game, perspective):
    snapshot = _base_serialize_network_snapshot(game, perspective)
    snapshot["polish_tracers"] = [
        [
            round(start_x, 3),
            round(start_y, 3),
            round(end_x, 3),
            round(end_y, 3),
            "player" if faction == perspective else "enemy",
            round(max(0.0, expires - game.time), 4),
        ]
        for start_x, start_y, end_x, end_y, faction, expires in getattr(
            game, "polish_recent_tracers", []
        )[-96:]
        if expires > game.time
        and (
            _network_effect_observed(game, perspective, (start_x, start_y), 16.0)
            or _network_effect_observed(game, perspective, (end_x, end_y), 16.0)
        )
    ]
    return snapshot


def apply_network_snapshot(game, snapshot):
    _base_apply_network_snapshot(game, snapshot)
    game.polish_recent_tracers = [
        (
            float(record[0]),
            float(record[1]),
            float(record[2]),
            float(record[3]),
            str(record[4]),
            game.time + float(record[5]),
        )
        for record in snapshot.get("polish_tracers", [])
        if isinstance(record, list) and len(record) >= 6
    ]


def apply_network_command(game, faction, message):
    reason = _validate_network_command(game, faction, message)
    if reason is not None:
        return (False, reason)
    accepted, reason = _base_apply_network_command(game, faction, message)
    if accepted and str(message.get("action", "")) in ("fire", "suppress"):
        units = _network_owned_units(game, faction, message.get("units", []))
        if units and all(
            (
                game.time < getattr(unit, "polish_lane_blocked_until", 0.0)
                for unit in units
            )
        ):
            return (False, "Friendly firing lane blocked")
    return (accepted, reason)
