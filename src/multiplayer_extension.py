# =============================================================================
# MULTIPLAYER — AUTHORITATIVE SERVER + DESKTOP CLIENT
# =============================================================================

import types
import socket

from src.multiplayer_net import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    NetworkClient,
    PROTOCOL_VERSION,
)


NETWORK_PVP_BATTLEFIELDS = ("farmland", "wooded_ridge", "ruined_village", "hill_line")
NETWORK_PVP_DEFAULT_ROSTER = (
    "Rifleman",
    "Rifleman",
    "Machine Gunner",
    "Marksman",
    "Medic",
    "Engineer",
    "Recon",
    "Grenadier",
    "Assault",
    "Automatic Rifleman",
)
NETWORK_UNIT_FIELDS = (
    "x",
    "y",
    "hp",
    "max_hp",
    "casualty",
    "bleed",
    "suppression",
    "morale",
    "morale_state",
    "cohesion",
    "squad_morale",
    "ammo",
    "magazines",
    "grenades",
    "smoke_grenades",
    "rifle_grenades",
    "satchel",
    "med_supplies",
    "tools",
    "mortar_shells",
    "artillery_shells",
    "order",
    "stance",
    "move_mode",
    "fire_mode",
    "fire_discipline",
    "target_priority",
    "facing",
    "deployed",
    "overwatch",
    "fire_lane",
    "fire_lane_center",
    "arc_width",
    "arc_range",
    "hold_position",
    "target_uid",
    "target_pos",
    "path",
    "waypoints",
    "action_timer",
    "reload_timer",
    "heat",
    "jammed",
    "stamina",
    "momentum",
    "prepared",
    "bayonet",
    "assistant_alive",
    "crew",
    "squad_id",
    "display_name",
    "is_emplacement",
)


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


def _network_disable_objectives(self, _dt):
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
    if not players and not enemies:
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


def create_network_pvp_game(seed, roster=None, battlefield="farmland"):
    roster = sanitize_network_roster(roster)
    battlefield = sanitize_network_battlefield(battlefield)
    game = RealTimeGame(
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
    game.units = [unit for unit in game.units if unit.faction == "player"]
    _kz_rebuild_indexes(game)
    for role in roster:
        game.add_unit("enemy", role, MAP_W - 4, MAP_H // 2)

    for faction, units, x_values, facing in (
        ("player", game.living("player"), (3, 5, 7), 0),
        ("enemy", game.living("enemy"), (MAP_W - 4, MAP_W - 6, MAP_W - 8), 180),
    ):
        for index, unit in enumerate(units):
            desired_x = x_values[index % len(x_values)]
            desired_y = 3 + ((index * 5 + index // 3) % (MAP_H - 6))
            position = _operation_open_position(game, desired_x, desired_y, unit, radius=10)
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

    game.network_pvp = True
    game.network_replica = False
    game.mission_type = "pvp"
    game.mission_title = f"PVP — {MISSION_VARIANTS[battlefield]['name']}"
    game.mission_brief = "Defeat the opposing player-controlled force."
    game.objectives = [
        {
            "title": "DEFEAT THE ENEMY FORCE",
            "desc": "Break the opposing commander's combat-effective force.",
            "pos": (MAP_W // 2, MAP_H // 2),
            "progress": 0.0,
            "state": "active",
        }
    ]
    game.objective_index = 0
    game.battle_stage = "PLAYER VERSUS PLAYER"
    game.paused = False
    game.victory = False
    game.defeat = False
    game.update_ai = types.MethodType(_network_disable_ai, game)
    game.update_enemy_builders = types.MethodType(_network_disable_noargs, game)
    game.update_objectives = types.MethodType(_network_disable_objectives, game)
    game.check_end = types.MethodType(_network_check_end, game)
    game.network_initial_cells = [
        [
            (
                cell.terrain,
                getattr(cell, "axis", None),
                getattr(cell, "hp", None),
            )
            for cell in row
        ]
        for row in game.grid
    ]
    game.network_dynamic_cells = set()
    _kz_rebuild_indexes(game)
    return game


def _network_json_value(value):
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_network_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _network_effect_observed(game, perspective, position, radius):
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return False
    return any(
        unit.combat_effective and dist(unit.pos, position) <= radius
        for unit in game.living(perspective)
    )


def filter_network_events(game, perspective, events):
    """Keep exact visible/local effects while coarsening audible-only combat."""
    filtered = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type", ""))
        position = event.get("pos")
        local = event.get("faction") == perspective
        observed = local or _network_effect_observed(
            game,
            perspective,
            position,
            22.0 if kind == "explosion" else 15.0,
        )
        if observed or position is None:
            filtered.append(dict(event))
            continue
        audible_radius = 44.0 if kind == "explosion" else 34.0 if kind == "shot" else 18.0
        if kind not in ("shot", "explosion") or not _network_effect_observed(
            game, perspective, position, audible_radius
        ):
            continue
        coarse = dict(event)
        coarse["pos"] = [round(float(position[0]) / 6.0) * 6, round(float(position[1]) / 6.0) * 6]
        coarse["audible_only"] = True
        filtered.append(coarse)
    return filtered


def serialize_network_snapshot(game, perspective):
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
                or cell.smoke > 0.02
                or cell.fire > 0.02
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
                        bool(cell.mine_seen_player if perspective == "player" else cell.mine_seen_enemy),
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
            [list(tracer.a), list(tracer.b), round(tracer.life, 4), round(tracer.total, 4)]
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
            if _network_effect_observed(game, perspective, (explosion.x, explosion.y), 24.0)
        ],
        "winner": winner,
    }


def apply_network_snapshot(game, snapshot):
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

    for x, y in list(getattr(game, "network_dynamic_cells", set())):
        baseline = game.network_initial_cells[y][x]
        cell = game.grid[y][x]
        cell.terrain, cell.axis, cell.hp = baseline
        cell.smoke = 0.0
        cell.fire = 0.0
    game.network_dynamic_cells = set()
    for record in snapshot.get("cells", []):
        if not isinstance(record, list) or len(record) < 8:
            continue
        x, y = int(record[0]), int(record[1])
        if not game.in_bounds(x, y):
            continue
        cell = game.grid[y][x]
        cell.terrain = str(record[2])
        cell.axis = record[3]
        cell.hp = record[4]
        cell.smoke = float(record[5])
        cell.fire = float(record[6])
        cell.mine_seen_player = bool(record[7])
        game.network_dynamic_cells.add((x, y))

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
        unit.spotted_player_until = game.time + 4.0 if faction == "enemy" and visible else 0.0
        known_ids.add(uid)

    game.intel["player"] = {
        int(contact["uid"]): {
            "pos": tuple(contact["pos"]),
            "seen": float(contact["seen"]),
            "role": str(contact.get("role", "CONTACT")),
        }
        for contact in snapshot.get("contacts", [])
        if isinstance(contact, dict) and "uid" in contact and "pos" in contact
    }
    game.network_replica = True
    _kz_rebuild_indexes(game)


def _network_owned_units(game, faction, ids):
    if not isinstance(ids, list) or len(ids) > MAX_PLAYER_UNITS:
        return []
    units = []
    for uid in dict.fromkeys(ids):
        unit = game.get_unit(int(uid))
        if unit is not None and unit.faction == faction and unit.combat_effective:
            units.append(unit)
    return units


def _network_position(game, value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = int(value[0]), int(value[1])
    return (x, y) if game.in_bounds(x, y) else None


def apply_network_command(game, faction, message):
    action = str(message.get("action", ""))
    units = _network_owned_units(game, faction, message.get("units", []))
    if not units:
        return False, "No owned combat-effective units"
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
        if target is None or target.faction == faction or not target.combat_effective:
            return False, "Invalid target"
        if not game.visible_to(faction, target):
            return False, "Target is not currently observed"
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
            return False, "Invalid fire mode"
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
            return False, reason
    elif action == "doctrine":
        game.cycle_squad_doctrine(units)
    elif action == "discipline":
        disciplines = ("hold", "return", "free", "confident")
        for unit in units:
            unit.fire_discipline = disciplines[(disciplines.index(unit.fire_discipline) + 1) % len(disciplines)]
    elif action == "priority":
        priorities = ("nearest", "exposed", "specialist", "suppressed")
        for unit in units:
            unit.target_priority = priorities[(priorities.index(unit.target_priority) + 1) % len(priorities)]
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
        return False, "Unsupported or incomplete command"
    return True, ""


_network_previous_game_update = RealTimeGame.update


def _network_game_update(self, dt):
    if getattr(self, "network_replica", False):
        return
    return _network_previous_game_update(self, dt)


RealTimeGame.update = _network_game_update


# ------------------------------ desktop UI ---------------------------------
_network_previous_app_init = KillZoneApp.__init__


def _network_app_init(self):
    _network_previous_app_init(self)
    self.network = NetworkClient()
    self.network_server_address = f"{DEFAULT_SERVER_HOST}:{DEFAULT_SERVER_PORT}"
    hostname = socket.gethostname().split(".", 1)[0]
    self.network_player_name = (hostname or "Player")[:20]
    self.network_input = None
    self.network_status = "OFFLINE"
    self.network_rooms = []
    self.network_online = 0
    self.network_lobby = None
    self.network_connection_id = None
    self.network_pending_action = None
    self.network_side = None
    self.network_match_active = False
    self.network_match_result = None
    self.network_sequence = 0


KillZoneApp.__init__ = _network_app_init


def _network_parse_address(value):
    value = str(value).strip()
    if not value:
        return DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT
    if ":" not in value:
        return value, DEFAULT_SERVER_PORT
    host, port = value.rsplit(":", 1)
    return host.strip(), int(port)


def _network_multiplayer_menu_rect(self):
    return pygame.Rect(WINDOW_W // 2 + 180, 292, 270, 54)


def _network_browser_rects(self):
    left = 190
    width = WINDOW_W - left * 2
    rects = {
        "address": pygame.Rect(left, 145, 520, 44),
        "name": pygame.Rect(left, 209, 360, 44),
        "connect": pygame.Rect(left + 540, 145, 180, 44),
        "refresh": pygame.Rect(left + 740, 145, 180, 44),
        "create": pygame.Rect(left + width - 250, 209, 250, 44),
        "back": pygame.Rect(left, 705, 210, 44),
    }
    for index in range(6):
        rects[f"room:{index}"] = pygame.Rect(left, 310 + index * 58, width, 48)
    return rects


def _network_lobby_rects(self):
    return {
        "ready": pygame.Rect(WINDOW_W // 2 - 270, 635, 250, 50),
        "leave": pygame.Rect(WINDOW_W // 2 + 20, 635, 250, 50),
    }


KillZoneApp.multiplayer_menu_rect = _network_multiplayer_menu_rect
KillZoneApp.network_browser_rects = _network_browser_rects
KillZoneApp.network_lobby_rects = _network_lobby_rects


def _network_connect(self, pending=None):
    try:
        host, port = _network_parse_address(self.network_server_address)
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
    except (TypeError, ValueError) as exc:
        self.network_status = f"INVALID ADDRESS — {exc}"
        return False
    if self.network.connected:
        self.network.send("list_rooms")
        return True
    if self.network.connecting:
        return False
    self.network_pending_action = pending
    self.network_status = f"CONNECTING TO {host}:{port}..."
    return self.network.connect(host, port, self.network_player_name)


def _network_create_room(self):
    roster = self.current_setup_roster() or list(NETWORK_PVP_DEFAULT_ROSTER)
    battlefield = self.setup_variant if self.setup_variant in NETWORK_PVP_BATTLEFIELDS else "farmland"
    self.network.send(
        "create_room",
        name=f"{self.network_player_name}'s battle",
        seed=random.randint(1, 999_999_999),
        roster=roster,
        battlefield=battlefield,
    )


def _network_send_command(self, action, units=None, **payload):
    if not getattr(self, "network_match_active", False) or not getattr(
        getattr(self, "network", None), "connected", False
    ):
        return False
    unit_ids = [unit.uid for unit in (self.selected_units() if units is None else units)]
    if not unit_ids:
        _qol_notify(self, "Select one or more units first", kind="danger", duration=1.5)
        return False
    self.network_sequence += 1
    self.network.send(
        "command",
        sequence=self.network_sequence,
        action=action,
        units=unit_ids,
        **payload,
    )
    return True


KillZoneApp.connect_multiplayer = _network_connect
KillZoneApp.create_multiplayer_room = _network_create_room
KillZoneApp.send_network_command = _network_send_command


def _network_normalize_client_factions(game, side):
    if side != "enemy":
        return
    for unit in game.units:
        unit.faction = "player" if unit.faction == "enemy" else "enemy"
    _kz_rebuild_indexes(game)


def _network_process_messages(self):
    if not hasattr(self, "network"):
        return
    for message in self.network.poll():
        message_type = message.get("type")
        if message_type == "network_connected":
            self.network_status = "CONNECTED — NEGOTIATING"
        elif message_type == "hello_ack":
            if int(message.get("protocol", -1)) != PROTOCOL_VERSION:
                self.network_status = "PROTOCOL MISMATCH"
                self.network.close("protocol mismatch")
                continue
            self.network_connection_id = message.get("connection_id")
            self.network_status = f"ONLINE · SERVER {message.get('service_version', '?')}"
            if self.network_pending_action == "create":
                self.create_multiplayer_room()
            else:
                self.network.send("list_rooms")
            self.network_pending_action = None
        elif message_type == "server_list":
            self.network_rooms = list(message.get("rooms", []))[:6]
            self.network_online = int(message.get("online", self.network_online or 0))
        elif message_type == "room_joined":
            self.state = "multiplayer_lobby"
            self.network_match_result = None
        elif message_type == "lobby_state":
            self.network_lobby = message.get("room")
            if self.network_lobby and self.network_lobby.get("status") == "lobby":
                self.state = "multiplayer_lobby"
        elif message_type == "room_left":
            self.network_lobby = None
            self.network_match_active = False
            self.state = "multiplayer"
            self.network.send("list_rooms")
        elif message_type == "match_start":
            side = str(message.get("side", "player"))
            game = create_network_pvp_game(
                seed=int(message.get("seed", 1)),
                roster=message.get("roster"),
                battlefield=message.get("battlefield", "farmland"),
            )
            _network_normalize_client_factions(game, side)
            game.network_replica = True
            initial_snapshot = message.get("snapshot", {})
            apply_network_snapshot(game, initial_snapshot)
            for event in initial_snapshot.get("events", []):
                if isinstance(event, dict):
                    self.play_event(event)
            self.game = game
            self.network_side = side
            self.network_match_active = True
            self.network_match_result = None
            self.battle_active = True
            self.state = "game"
            self.selected = []
            self.command_mode = "normal"
            self.show_help = False
            self.build_menu_open = False
            self.control_groups = {index: [] for index in range(1, 10)}
            if side == "enemy":
                self.camera_x = MAP_W
                self.camera_y = MAP_H // 2
                self.clamp_camera()
        elif message_type == "snapshot" and getattr(self, "network_match_active", False):
            state = message.get("state", {})
            apply_network_snapshot(self.game, state)
            for event in state.get("events", []):
                if isinstance(event, dict):
                    self.play_event(event)
        elif message_type == "match_end":
            self.network_match_active = False
            self.network_match_result = str(message.get("result", "defeat"))
            self.game.victory = self.network_match_result == "victory"
            self.game.defeat = self.network_match_result != "victory"
            _qol_notify(
                self,
                f"PVP {self.network_match_result.upper()} — {message.get('reason', 'match ended')}",
                kind="good" if self.game.victory else "danger",
                duration=6.0,
            )
        elif message_type == "command_rejected":
            _qol_notify(self, str(message.get("reason", "Command rejected")), kind="danger", duration=1.8)
        elif message_type == "error":
            self.network_status = f"ERROR — {message.get('message', 'server error')}"
            _qol_notify(self, str(message.get("message", "Server error")), kind="danger", duration=2.5)
        elif message_type == "network_error":
            self.network_status = f"CONNECTION FAILED — {message.get('message', 'unknown error')}"
        elif message_type == "network_disconnected":
            self.network_status = "DISCONNECTED"
            if getattr(self, "network_match_active", False):
                self.network_match_active = False
                self.network_match_result = "disconnected"


KillZoneApp.process_network_messages = _network_process_messages


_network_previous_draw_main_menu = KillZoneApp.draw_main_menu


def _network_draw_main_menu(self):
    _network_previous_draw_main_menu(self)
    self.button(self.multiplayer_menu_rect(), "MULTIPLAYER", self.mouse, accent=False)


KillZoneApp.draw_main_menu = _network_draw_main_menu


def _network_draw_browser(self):
    self.draw_menu_background()
    rects = self.network_browser_rects()
    title = self.get_font(48).render("MULTIPLAYER", True, COLORS["white"])
    self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 52))
    self.text("AUTHORITATIVE KILL ZONE SERVER", (190, 113), 13, "select")

    for field, label, value in (
        ("address", "SERVER ADDRESS", self.network_server_address),
        ("name", "PLAYER NAME", self.network_player_name),
    ):
        rect = rects[field]
        pygame.draw.rect(self.screen, COLORS["panel"], rect, border_radius=4)
        pygame.draw.rect(
            self.screen,
            COLORS["select"] if self.network_input == field else COLORS["muted"],
            rect,
            2 if self.network_input == field else 1,
            border_radius=4,
        )
        self.text(label, (rect.x, rect.y - 18), 10, "muted")
        self.text(value + ("_" if self.network_input == field else ""), (rect.x + 12, rect.y + 13), 14, "white")
    self.button(rects["connect"], "CONNECT", self.mouse, accent=self.network.connected)
    self.button(rects["refresh"], "REFRESH", self.mouse, enabled=self.network.connected)
    self.button(rects["create"], "CREATE BATTLE", self.mouse, accent=self.network.connected)
    self.text(self.network_status[:90], (190, 270), 13, "good" if self.network.connected else "contact")
    self.text(f"{self.network_online} PLAYER(S) ONLINE", (WINDOW_W - 410, 270), 12, "muted")
    self.text("AVAILABLE BATTLES", (190, 286), 14, "white")

    if not self.network_rooms:
        self.text("No public battles found. Connect, refresh, or create one.", (210, 340), 14, "muted")
    for index, room in enumerate(self.network_rooms[:6]):
        rect = rects[f"room:{index}"]
        available = room.get("status") == "lobby" and int(room.get("players", 0)) < 2
        pygame.draw.rect(self.screen, COLORS["panel"], rect, border_radius=4)
        pygame.draw.rect(self.screen, COLORS["select"] if available else COLORS["muted"], rect, 1, border_radius=4)
        lock = "LOCKED" if room.get("locked") else "OPEN"
        self.text(str(room.get("name", "Battle"))[:38], (rect.x + 14, rect.y + 8), 14, "white")
        self.text(
            f"{room.get('players', 0)}/2 · {str(room.get('battlefield', 'field')).upper()} · {lock} · {str(room.get('status', 'lobby')).upper()}",
            (rect.x + 14, rect.y + 27),
            10,
            "muted",
        )
        self.button(
            pygame.Rect(rect.right - 138, rect.y + 7, 124, 34),
            "JOIN" if available else "UNAVAILABLE",
            self.mouse,
            enabled=available,
            accent=available,
        )
    self.button(rects["back"], "BACK", self.mouse)
    self.text("Matches are server-authoritative; neither player can pause or change speed.", (190, 765), 11, "muted")


def _network_draw_lobby(self):
    self.draw_menu_background()
    room = self.network_lobby or {}
    rects = self.network_lobby_rects()
    title = self.get_font(48).render("PVP LOBBY", True, COLORS["white"])
    self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 65))
    self.text(f"ROOM {room.get('id', '------')} · {room.get('name', 'Battle')}", (WINDOW_W // 2 - 320, 150), 18, "select")
    self.text(
        f"MAP {str(room.get('battlefield', 'farmland')).upper()} · SEED {room.get('seed', '-')}",
        (WINDOW_W // 2 - 320, 183),
        13,
        "muted",
    )
    players = room.get("players", [])
    for slot in range(2):
        panel = pygame.Rect(WINDOW_W // 2 - 390 + slot * 410, 255, 370, 245)
        pygame.draw.rect(self.screen, COLORS["panel"], panel, border_radius=6)
        pygame.draw.rect(self.screen, COLORS["nato_friend"] if slot == 0 else COLORS["nato_hostile"], panel, 2, border_radius=6)
        player = next((item for item in players if int(item.get("slot", -1)) == slot), None)
        self.text("BLUE FORCE" if slot == 0 else "RED FORCE", (panel.x + 20, panel.y + 20), 18, "white")
        if player:
            self.text(str(player.get("name", "Player")), (panel.x + 20, panel.y + 78), 24, "select")
            self.text("READY" if player.get("ready") else "NOT READY", (panel.x + 20, panel.y + 132), 16, "good" if player.get("ready") else "contact")
        else:
            self.text("WAITING FOR PLAYER...", (panel.x + 20, panel.y + 92), 16, "muted")
    me = next((item for item in players if item.get("id") == self.network_connection_id), None)
    ready = bool(me and me.get("ready"))
    self.button(rects["ready"], "UNREADY" if ready else "READY", self.mouse, accent=not ready)
    self.button(rects["leave"], "LEAVE LOBBY", self.mouse)
    self.text("The battle begins automatically when both commanders are ready.", (WINDOW_W // 2 - 290, 555), 14, "muted")


KillZoneApp.draw_multiplayer_browser = _network_draw_browser
KillZoneApp.draw_multiplayer_lobby = _network_draw_lobby


def _network_edit_input(self, event):
    if event.key == pygame.K_BACKSPACE:
        if self.network_input == "address":
            self.network_server_address = self.network_server_address[:-1]
        elif self.network_input == "name":
            self.network_player_name = self.network_player_name[:-1]
        return
    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        self.network_input = None
        return
    text = getattr(event, "unicode", "")
    if not text or not text.isprintable():
        return
    if self.network_input == "address" and len(self.network_server_address) < 64:
        if text.isalnum() or text in ".:-_":
            self.network_server_address += text
    elif self.network_input == "name" and len(self.network_player_name) < 24:
        self.network_player_name += text


def _network_handle_browser(self, event):
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_F11:
            self.toggle_fullscreen()
        elif event.key == pygame.K_ESCAPE:
            self.state = "menu"
            self.network_input = None
        elif self.network_input:
            self._edit_network_input(event)
        return
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return
    rects = self.network_browser_rects()
    if rects["address"].collidepoint(event.pos):
        self.network_input = "address"
    elif rects["name"].collidepoint(event.pos):
        self.network_input = "name"
    else:
        self.network_input = None
    if rects["connect"].collidepoint(event.pos):
        self.connect_multiplayer()
    elif rects["refresh"].collidepoint(event.pos) and self.network.connected:
        self.network.send("list_rooms")
    elif rects["create"].collidepoint(event.pos):
        if self.network.connected:
            self.create_multiplayer_room()
        else:
            self.connect_multiplayer(pending="create")
    elif rects["back"].collidepoint(event.pos):
        self.state = "menu"
    for index, room in enumerate(self.network_rooms[:6]):
        rect = rects[f"room:{index}"]
        join_rect = pygame.Rect(rect.right - 138, rect.y + 7, 124, 34)
        if join_rect.collidepoint(event.pos) and room.get("status") == "lobby":
            self.network.send("join_room", room_id=room.get("id"), password="")
            return


def _network_handle_lobby(self, event):
    if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,):
        self.network.send("leave_room")
        return
    if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
        self.toggle_fullscreen()
        return
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return
    rects = self.network_lobby_rects()
    if rects["leave"].collidepoint(event.pos):
        self.network.send("leave_room")
    elif rects["ready"].collidepoint(event.pos):
        players = (self.network_lobby or {}).get("players", [])
        me = next((item for item in players if item.get("id") == self.network_connection_id), None)
        self.network.send("ready", ready=not bool(me and me.get("ready")))


KillZoneApp._edit_network_input = _network_edit_input
KillZoneApp.handle_multiplayer_browser = _network_handle_browser
KillZoneApp.handle_multiplayer_lobby = _network_handle_lobby


_network_previous_handle_event = KillZoneApp.handle_event


def _network_handle_event(self, event):
    event = self.normalize_event_pos(event)
    if event.type == pygame.MOUSEMOTION:
        self.mouse = event.pos
    if event.type == pygame.QUIT:
        self.network.close("game closed")
    if self.state == "menu" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if self.multiplayer_menu_rect().collidepoint(event.pos):
            self.state = "multiplayer"
            self.network_status = "ONLINE" if self.network.connected else "OFFLINE"
            return
    if self.state == "multiplayer":
        return self.handle_multiplayer_browser(event)
    if self.state == "multiplayer_lobby":
        return self.handle_multiplayer_lobby(event)
    if self.state == "game" and getattr(self, "network_match_result", None) and event.type == pygame.KEYDOWN:
        if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
            self.network.send("leave_room")
            self.network_lobby = None
            self.state = "multiplayer"
            return
    if self.state == "game" and getattr(self, "network_match_active", False) and event.type == pygame.KEYDOWN:
        mods = getattr(event, "mod", pygame.key.get_mods())
        if event.key == pygame.K_d and mods & pygame.KMOD_SHIFT:
            self.send_network_command("doctrine")
            return
    return _network_previous_handle_event(self, event)


KillZoneApp.handle_event = _network_handle_event


_network_previous_issue_context = KillZoneApp.issue_context_command


def _network_issue_context(self, cell, append=False):
    if not getattr(self, "network_match_active", False):
        return _network_previous_issue_context(self, cell, append=append)
    units = self.selected_units()
    if not units:
        return
    target = self.game.unit_at(*cell)
    if target is not None and target.faction == "enemy" and self.game.visible_to("player", target):
        self.send_network_command("fire", units, target=target.uid, mode=units[0].fire_mode)
        return
    mode = self.command_mode
    payload = {"position": list(cell), "append": bool(append), "formation": self.formation}
    if mode.startswith("build:"):
        self.send_network_command("build", units, kind=mode.split(":", 1)[1], position=list(cell))
    elif mode in ("grenade", "smoke", "rifle_grenade"):
        self.send_network_command(mode, units, position=list(cell), cook=self.cook)
    elif mode in ("suppress", "overwatch", "assault", "bound", "fallback"):
        self.send_network_command(mode, units, position=list(cell))
    elif mode == "mortar":
        self.send_network_command("mortar", units, position=list(cell), smoke=False)
    elif mode == "mortar_smoke":
        self.send_network_command("mortar", units, position=list(cell), smoke=True)
    elif mode == "normal":
        self.send_network_command("move", units, **payload)
    else:
        _qol_notify(self, f"{mode.upper()} is not network-enabled yet", kind="danger", duration=1.8)
        return
    self.command_mode = "normal"


KillZoneApp.issue_context_command = _network_issue_context


_network_previous_handle_command_bar = KillZoneApp.handle_command_bar


def _network_handle_command_bar(self, pos):
    if not getattr(self, "network_match_active", False):
        return _network_previous_handle_command_bar(self, pos)
    clicked = next((name for name, rect in self.command_bar_rects().items() if rect.collidepoint(pos)), None)
    if clicked is None:
        return False
    units = self.selected_units()
    if not units:
        return True
    if clicked in QOL_TARGET_MODES:
        self.command_mode = QOL_TARGET_MODES[clicked]
    elif clicked == "RELOAD":
        self.send_network_command("reload", units)
    elif clicked == "STANCE":
        self.send_network_command("stance", units)
    elif clicked == "FORMATION":
        self.cycle_formation()
    elif clicked == "DISCIPLINE":
        self.send_network_command("discipline", units)
    elif clicked == "PRIORITY":
        self.send_network_command("priority", units)
    elif clicked == "AUTO":
        enabled = not all(unit.auto_reload and unit.auto_cover and unit.auto_smoke and unit.auto_medic for unit in units)
        self.send_network_command("autonomy", units, enabled=enabled)
    elif clicked == "HOLD":
        self.send_network_command("hold", units, enabled=not all(unit.hold_position for unit in units))
    else:
        return _network_previous_handle_command_bar(self, pos)
    return True


KillZoneApp.handle_command_bar = _network_handle_command_bar


_network_previous_handle_key = KillZoneApp.handle_key


def _network_handle_key(self, key, mods):
    if not getattr(self, "network_match_active", False):
        return _network_previous_handle_key(self, key, mods)
    units = self.selected_units()
    if key == pygame.K_SPACE:
        _qol_notify(self, "Multiplayer matches cannot be paused", kind="danger", duration=1.5)
    elif key == pygame.K_F1:
        self.show_help = not self.show_help
    elif key == pygame.K_TAB:
        self.show_threat = not self.show_threat
    elif pygame.K_1 <= key <= pygame.K_9:
        return _network_previous_handle_key(self, key, mods)
    elif key == pygame.K_F4:
        self.cycle_formation()
    elif key == pygame.K_F7:
        self.send_network_command("discipline", units)
    elif key == pygame.K_F8:
        self.send_network_command("priority", units)
    elif key == pygame.K_z:
        self.send_network_command("stance", units)
    elif key == pygame.K_a:
        self.send_network_command("fire_mode", units, mode="aimed")
    elif key == pygame.K_f:
        self.send_network_command("fire_mode", units, mode="snap")
    elif key == pygame.K_w and not (mods & pygame.KMOD_SHIFT):
        self.send_network_command("fire_mode", units, mode="rapid")
    elif key == pygame.K_r:
        self.send_network_command("reload", units, emergency=bool(mods & pygame.KMOD_SHIFT))
    elif key == pygame.K_j:
        self.send_network_command("clear_jam", units)
    elif key == pygame.K_b and not (mods & pygame.KMOD_SHIFT):
        self.send_network_command("barrel", units)
    elif key == pygame.K_d and not (mods & pygame.KMOD_SHIFT):
        self.send_network_command("deploy", units)
    elif key == pygame.K_v:
        self.send_network_command("bayonet", units)
    elif key == pygame.K_g:
        self.command_mode = "grenade"
        self.cook = 0
    elif key == pygame.K_s:
        self.command_mode = "smoke"
    elif key == pygame.K_l:
        self.command_mode = "rifle_grenade"
    elif key == pygame.K_q:
        self.command_mode = "suppress"
    elif key == pygame.K_m:
        self.command_mode = "mortar"
    elif key == pygame.K_n:
        self.command_mode = "mortar_smoke"
    elif key == pygame.K_o:
        self.command_mode = "overwatch"
    elif key == pygame.K_c:
        self.command_mode = "assault"
    elif key == pygame.K_ESCAPE:
        if self.show_help:
            self.show_help = False
        elif self.command_mode != "normal":
            self.command_mode = "normal"
        else:
            _qol_notify(self, "Finish the match or disconnect from the PvP browser", duration=1.6)


KillZoneApp.handle_key = _network_handle_key


_network_previous_draw = KillZoneApp.draw


def _network_draw(self):
    self.process_network_messages()
    if self.state == "multiplayer":
        self.screen.fill(COLORS["bg"])
        self.draw_multiplayer_browser()
        self.present()
        return
    if self.state == "multiplayer_lobby":
        self.screen.fill(COLORS["bg"])
        self.draw_multiplayer_lobby()
        self.present()
        return
    result = _network_previous_draw(self)
    network_match_active = getattr(self, "network_match_active", False)
    network_match_result = getattr(self, "network_match_result", None)
    if self.state == "game" and (network_match_active or network_match_result):
        status = "LIVE" if network_match_active else str(network_match_result).upper()
        label = f"MULTIPLAYER · {str(self.network_side or '?').upper()} · {status}"
        panel = pygame.Rect(WINDOW_W // 2 - 190, 8, 380, 30)
        pygame.draw.rect(self.screen, COLORS["panel2"], panel, border_radius=3)
        pygame.draw.rect(self.screen, COLORS["select"] if network_match_active else COLORS["contact"], panel, 1, border_radius=3)
        surface = self.cached_text_surface(label, 11, "white")
        self.screen.blit(surface, (panel.centerx - surface.get_width() // 2, panel.centery - surface.get_height() // 2))
        if network_match_result:
            overlay = pygame.Rect(WINDOW_W // 2 - 260, WINDOW_H // 2 - 95, 520, 190)
            pygame.draw.rect(self.screen, COLORS["panel"], overlay, border_radius=6)
            pygame.draw.rect(self.screen, COLORS["select"] if self.game.victory else COLORS["danger"], overlay, 2, border_radius=6)
            self.text(f"PVP {str(network_match_result).upper()}", (overlay.x + 115, overlay.y + 42), 32, "white")
            self.text("Press Enter to return to the server browser", (overlay.x + 86, overlay.y + 112), 14, "muted")
        self.present()
    return result


KillZoneApp.draw = _network_draw
