"""Rules for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from engine.definitions import COMBAT2_CALLSIGNS
from engine.definitions import COMBAT2_FIRST_NAMES
from engine.definitions import COMBAT2_STATIC_ROLES
from engine.definitions import COMBAT2_SURNAMES
from engine.definitions import COMBAT2_WOUND_LABELS
from engine.definitions import COMBAT_POLISH_DEFAULT_PROFILE
from engine.definitions import COMBAT_POLISH_WEAPON_PROFILES
from engine.definitions import DEFENSE_BREACH_ROLES
from engine.definitions import DEFENSE_FIRE_SUPPORT_ROLES
from engine.definitions import DEFENSE_SUSTAINMENT_ROLES
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import OPERATION_DEFENSE_DURATIONS
from engine.definitions import OPERATION_ENEMY_STRENGTHS
from engine.definitions import OPERATION_MISSIONS
from engine.definitions import OPERATION_VARIANTS
from engine.definitions import OPERATION_WEATHER
from engine.definitions import SOLDIER_IDENTITY_COMBINATIONS
from engine.definitions import SQUAD_VISUAL_COLORS
from engine.definitions import TERRAIN
from engine.definitions import _SQUAD_GROUP_BY_ROLE
from engine.definitions import _SQUAD_TACTICAL_LABELS
import math
import random


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def dist(a, b) -> float:
    ax, ay = getattr(a, "pos", a)
    bx, by = getattr(b, "pos", b)
    return math.hypot(ax - bx, ay - by)


def angle_to(a, b) -> float:
    ax, ay = getattr(a, "pos", a)
    bx, by = getattr(b, "pos", b)
    return math.degrees(math.atan2(by - ay, bx - ax)) % 360


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _vs_sector_name(y):
    if y < MAP_H / 3:
        return "NORTH"
    if y > MAP_H * 2 / 3:
        return "SOUTH"
    return "CENTRE"


def squad_role_group(role):
    """Return the tactical group used only for automatic squad placement."""
    return _SQUAD_GROUP_BY_ROLE.get(role, "assault")


def squad_visual_color(squad_id):
    """Return the stable accent color for Squad A–I."""
    index = max(1, int(squad_id)) - 1
    return SQUAD_VISUAL_COLORS[index % len(SQUAD_VISUAL_COLORS)]


def squad_tactical_label(game, squad_id):
    counts = {}
    for unit in game.living("player"):
        if not unit.combat_effective or getattr(unit, "squad_id", 0) != squad_id:
            continue
        group = squad_role_group(unit.role)
        counts[group] = counts.get(group, 0) + 1
    if not counts:
        return "EMPTY"
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return "MIXED"
    return _SQUAD_TACTICAL_LABELS[ordered[0][0]]


def sector_stability_color(stability):
    """Return the UI color key for defensive line stability."""
    return "good" if stability > 65 else "contact" if stability > 30 else "danger"


def unit_is_firing_while_moving(unit):
    return bool(
        getattr(unit, "_moving_fire_active", False)
        or (unit.order == "move" and (unit.path or unit.waypoints))
    )


def default_operation_config():
    return {
        "mission": "assault",
        "variant": "auto",
        "weather": "auto",
        "enemy_strength": 1.0,
        "defense_duration": 300,
    }


def sanitize_operation_config(config=None):
    cleaned = default_operation_config()
    if config:
        cleaned.update(config)
    if cleaned["mission"] not in OPERATION_MISSIONS:
        cleaned["mission"] = "assault"
    if cleaned["variant"] not in OPERATION_VARIANTS:
        cleaned["variant"] = "auto"
    if cleaned["weather"] not in OPERATION_WEATHER:
        cleaned["weather"] = "auto"
    cleaned["enemy_strength"] = min(
        OPERATION_ENEMY_STRENGTHS,
        key=lambda value: abs(value - float(cleaned["enemy_strength"])),
    )
    cleaned["defense_duration"] = min(
        OPERATION_DEFENSE_DURATIONS,
        key=lambda value: abs(value - int(cleaned["defense_duration"])),
    )
    return cleaned


def _operation_open_position(game, desired_x, desired_y, unit, radius=8):
    desired_x = int(clamp(desired_x, 1, MAP_W - 2))
    desired_y = int(clamp(desired_y, 1, MAP_H - 2))
    occupied = {
        other.tile for other in game.units if other.alive and other.uid != unit.uid
    }
    choices = []
    for radius_now in range(radius + 1):
        for y in range(
            max(1, desired_y - radius_now), min(MAP_H - 1, desired_y + radius_now + 1)
        ):
            for x in range(
                max(1, desired_x - radius_now),
                min(MAP_W - 1, desired_x + radius_now + 1),
            ):
                if max(abs(x - desired_x), abs(y - desired_y)) != radius_now:
                    continue
                if (x, y) in occupied or not game.passable(x, y, unit):
                    continue
                cover = TERRAIN[game.grid[y][x].terrain]["cover"]
                choices.append((-cover, abs(x - desired_x) + abs(y - desired_y), x, y))
        if choices:
            break
    if not choices:
        return None
    choices.sort()
    return (choices[0][2], choices[0][3])


def _operation_defense_assignment_for_role(role):
    if role in DEFENSE_BREACH_ROLES:
        return "breach"
    if role in DEFENSE_FIRE_SUPPORT_ROLES:
        return "fire_support"
    if role in DEFENSE_SUSTAINMENT_ROLES:
        return "sustainment"
    return "assault"


def _operation_defense_sector_for_y(y):
    if y < MAP_H / 3:
        return "NORTH"
    if y >= MAP_H * 2 / 3:
        return "SOUTH"
    return "CENTRE"


def _operation_defense_sector_center(sector):
    return {
        "NORTH": max(4, MAP_H // 6),
        "CENTRE": MAP_H // 2,
        "SOUTH": min(MAP_H - 5, MAP_H * 5 // 6),
    }.get(sector, MAP_H // 2)


def filter_network_events(game, perspective, events):
    """Keep exact visible/local effects while coarsening audible-only combat."""
    from engine.networking import _network_effect_observed

    filtered = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type", ""))
        position = event.get("pos")
        local = event.get("faction") == perspective
        observed = local or _network_effect_observed(
            game, perspective, position, 22.0 if kind == "explosion" else 15.0
        )
        if observed or position is None:
            filtered.append(dict(event))
            continue
        audible_radius = (
            44.0 if kind == "explosion" else 34.0 if kind == "shot" else 18.0
        )
        if kind not in ("shot", "explosion") or not _network_effect_observed(
            game, perspective, position, audible_radius
        ):
            continue
        coarse = dict(event)
        coarse["pos"] = [
            round(float(position[0]) / 6.0) * 6,
            round(float(position[1]) / 6.0) * 6,
        ]
        coarse["audible_only"] = True
        filtered.append(coarse)
    return filtered


def presentation_weather_particles(weather, seed, clock, width, height, count=32):
    """Produce a deterministic frame of map-space atmospheric particles."""
    weather = str(weather)
    width = max(1, int(width))
    height = max(1, int(height))
    count = max(0, int(count))
    cadence = 11 if weather == "rain" else 3 if weather == "fog" else 2
    frame = int(max(0.0, float(clock)) * cadence)
    rng = random.Random(int(seed) * 1000003 ^ frame * 97409 ^ sum(map(ord, weather)))
    output = []
    for _ in range(count):
        x = rng.randrange(width)
        y = rng.randrange(height)
        if weather == "rain":
            length = rng.randint(7, 16)
            alpha = rng.randint(36, 94)
        elif weather == "fog":
            length = rng.randint(30, 92)
            alpha = rng.randint(9, 26)
        else:
            length = rng.randint(1, 3)
            alpha = rng.randint(14, 34)
        output.append((x, y, length, alpha))
    return output


def presentation_terrain_marks(terrain, x, y, seed, count=4):
    """Return stable normalized detail marks used by the terrain cache."""
    rng = random.Random(
        int(seed) * 83492791
        ^ int(x) * 73856093
        ^ int(y) * 19349663
        ^ sum(map(ord, str(terrain)))
    )
    return [
        (rng.random(), rng.random(), rng.random()) for _ in range(max(0, int(count)))
    ]


def generate_soldier_identity(seed, uid, faction="player", squad_id=1, slot=1):
    """Return a deterministic identity from a 1,600-combination name space."""
    total = SOLDIER_IDENTITY_COMBINATIONS
    faction_offset = 0 if faction == "player" else total // 2 + 17
    index = (int(seed) * 37 + int(uid) * 53 + faction_offset) % total
    first = COMBAT2_FIRST_NAMES[index // len(COMBAT2_SURNAMES)]
    surname = COMBAT2_SURNAMES[index % len(COMBAT2_SURNAMES)]
    callsign = COMBAT2_CALLSIGNS[
        (index * 7 + int(seed) + int(squad_id) * 3) % len(COMBAT2_CALLSIGNS)
    ]
    letter = chr(64 + min(26, max(1, int(squad_id))))
    compact = f"{letter}{max(1, int(slot))} {first} {surname}"
    return {
        "identity_index": index,
        "first_name": first,
        "surname": surname,
        "full_name": f"{first} {surname}",
        "callsign": callsign,
        "display_name": compact,
    }


def _combat2_initialize_unit(game, unit):
    unit.wound_head = float(getattr(unit, "wound_head", 0.0))
    unit.wound_torso = float(getattr(unit, "wound_torso", 0.0))
    unit.wound_arm = float(getattr(unit, "wound_arm", 0.0))
    unit.wound_leg = float(getattr(unit, "wound_leg", 0.0))
    unit.wound_treated = bool(getattr(unit, "wound_treated", False))
    unit.combat2_exposed_until = float(getattr(unit, "combat2_exposed_until", 0.0))
    unit.combat2_settle_until = float(getattr(unit, "combat2_settle_until", 0.0))
    unit.combat2_acquired_uid = getattr(unit, "combat2_acquired_uid", None)
    unit.combat2_ready_at = float(getattr(unit, "combat2_ready_at", 0.0))
    unit.combat2_assignment = getattr(unit, "combat2_assignment", "unassigned")
    unit.combat2_phase = getattr(unit, "combat2_phase", "contact")
    unit.combat2_plan_target = getattr(unit, "combat2_plan_target", None)
    unit.combat2_flank = getattr(unit, "combat2_flank", None)
    unit.combat2_decision_reason = getattr(unit, "combat2_decision_reason", "")
    unit.combat2_last_move_pos = getattr(unit, "combat2_last_move_pos", unit.pos)
    if unit.role in COMBAT2_STATIC_ROLES or getattr(unit, "is_emplacement", False):
        return unit
    squad_id = max(1, int(getattr(unit, "squad_id", 1)))
    slot = (
        sum(
            (
                other.faction == unit.faction
                and other.uid != unit.uid
                and (other.uid < unit.uid)
                and (getattr(other, "squad_id", 0) == squad_id)
                and (other.role not in COMBAT2_STATIC_ROLES)
                for other in game.units
            )
        )
        + 1
    )
    identity = generate_soldier_identity(
        game.seed, unit.uid, unit.faction, squad_id, slot
    )
    for key, value in identity.items():
        setattr(unit, key, value)
    return unit


def _combat2_wound_penalties(unit):
    arm = clamp(float(getattr(unit, "wound_arm", 0.0)), 0.0, 100.0)
    leg = clamp(float(getattr(unit, "wound_leg", 0.0)), 0.0, 100.0)
    head = clamp(float(getattr(unit, "wound_head", 0.0)), 0.0, 100.0)
    torso = clamp(float(getattr(unit, "wound_torso", 0.0)), 0.0, 100.0)
    return {
        "aim": arm * 0.15 + head * 0.2,
        "reload": 1.0 + arm * 0.009,
        "move": clamp(1.0 - leg * 0.0065 - torso * 0.0015, 0.48, 1.0),
        "reaction": head * 0.007 + torso * 0.002,
    }


def combat2_wound_summary(unit):
    wounds = []
    for location in ("head", "torso", "arm", "leg"):
        severity = float(getattr(unit, f"wound_{location}", 0.0))
        if severity >= 8:
            grade = (
                "severe"
                if severity >= 55
                else "moderate"
                if severity >= 28
                else "light"
            )
            wounds.append(f"{grade} {COMBAT2_WOUND_LABELS[location]}")
    return ", ".join(wounds) if wounds else "no localized wounds"


def _combat2_point_segment_distance(px, py, ax, ay, bx, by):
    vx, vy = (bx - ax, by - ay)
    denominator = vx * vx + vy * vy
    q = (
        0.0
        if denominator <= 1e-09
        else clamp(((px - ax) * vx + (py - ay) * vy) / denominator, 0.0, 1.0)
    )
    cx, cy = (ax + q * vx, ay + q * vy)
    return (math.hypot(px - cx, py - cy), q)


def _combat2_target_radius(game, target):
    radius = {"standing": 0.34, "crouched": 0.27, "prone": 0.19}.get(
        target.stance, 0.32
    )
    cover = float(TERRAIN[game.grid[target.tile[1]][target.tile[0]].terrain]["cover"])
    radius *= clamp(1.0 - cover * 0.075, 0.58, 1.0)
    if game.time < getattr(target, "combat2_exposed_until", 0.0):
        radius *= 1.32
    if target.order == "move":
        radius *= 1.12
    return radius


def _combat2_impact_kind(cell):
    if cell.terrain in ("wall", "building", "bunker", "bridge"):
        return "metal"
    if TERRAIN[cell.terrain]["cover"] >= 2:
        return "cover"
    return "dirt"


def combat_polish_weapon_profile(unit_or_weapon):
    """Return a copy of the cadence profile for a unit or weapon name."""
    weapon_name = (
        str(unit_or_weapon)
        if isinstance(unit_or_weapon, str)
        else str(getattr(unit_or_weapon, "weapon_name", ""))
    )
    return dict(
        COMBAT_POLISH_WEAPON_PROFILES.get(weapon_name, COMBAT_POLISH_DEFAULT_PROFILE)
    )


def _polish_initialize_unit(unit):
    unit.polish_burst_remaining = int(getattr(unit, "polish_burst_remaining", 0))
    unit.polish_burst_pause_until = float(
        getattr(unit, "polish_burst_pause_until", 0.0)
    )
    unit.polish_recoil = float(getattr(unit, "polish_recoil", 0.0))
    unit.polish_target_lock_until = float(
        getattr(unit, "polish_target_lock_until", 0.0)
    )
    unit.polish_plan_commit_until = float(
        getattr(unit, "polish_plan_commit_until", 0.0)
    )
    unit.polish_deploy_lock_until = float(
        getattr(unit, "polish_deploy_lock_until", 0.0)
    )
    unit.polish_reaction_until = float(getattr(unit, "polish_reaction_until", 0.0))
    unit.polish_reaction_kind = str(getattr(unit, "polish_reaction_kind", ""))
    unit.polish_reaction_stance = getattr(unit, "polish_reaction_stance", None)
    unit.polish_order_state = str(getattr(unit, "polish_order_state", "READY"))
    unit.polish_order_state_until = float(
        getattr(unit, "polish_order_state_until", 0.0)
    )
    unit.polish_lane_reason = str(getattr(unit, "polish_lane_reason", ""))
    unit.polish_lane_blocked_until = float(
        getattr(unit, "polish_lane_blocked_until", 0.0)
    )
    unit.polish_wait_reason = str(getattr(unit, "polish_wait_reason", ""))
    unit.polish_arrival_facing = float(
        getattr(unit, "polish_arrival_facing", unit.facing)
    )
    unit.polish_last_order_signature = getattr(
        unit, "polish_last_order_signature", None
    )
    unit.polish_last_order_at = float(getattr(unit, "polish_last_order_at", -99.0))
    unit.polish_last_progress_pos = tuple(
        getattr(unit, "polish_last_progress_pos", unit.pos)
    )
    unit.polish_last_progress_at = float(getattr(unit, "polish_last_progress_at", 0.0))
    return unit


def _polish_unit_clearance(unit):
    stance = getattr(unit, "stance", "standing")
    return 0.3 if stance == "prone" else 0.4 if stance == "crouched" else 0.5
