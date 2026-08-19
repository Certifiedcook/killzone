"""Combat 2.0: physical small-arms fire, persistent wounds, squad tactics and identities.

This extension deliberately sits at the end of the assembled game source.  It
keeps the mature command, operations and networking layers intact while making
their firefights spatial: every small-arms shot now travels through the map,
can strike unintended soldiers, interacts with material, and suppresses anyone
close to its actual path.
"""


COMBAT2_FIRST_NAMES = (
    "Aidan", "Alex", "Arthur", "Ben", "Callum", "Charlie", "Conor", "Daniel",
    "Darragh", "Declan", "Elliot", "Eoin", "Evan", "Finn", "George", "Harry",
    "Hugo", "Isaac", "Jack", "James", "Jamie", "Joseph", "Kieran", "Leo",
    "Liam", "Lucas", "Max", "Michael", "Nathan", "Noah", "Oliver", "Oscar",
    "Patrick", "Ronan", "Sam", "Sean", "Theo", "Thomas", "William", "Zach",
)

COMBAT2_SURNAMES = (
    "Adams", "Baker", "Bell", "Bennett", "Brennan", "Brown", "Burke", "Byrne",
    "Campbell", "Clarke", "Collins", "Cooper", "Daly", "Doyle", "Duffy", "Evans",
    "Farrell", "Fitzgerald", "Flynn", "Foster", "Gallagher", "Graham", "Grant", "Hayes",
    "Hughes", "Kelly", "Kennedy", "Lynch", "Martin", "McCarthy", "McDonnell", "Miller",
    "Moore", "Morgan", "Murphy", "Murray", "Nolan", "O'Brien", "O'Connor", "O'Neill",
)

COMBAT2_CALLSIGNS = (
    "Badger", "Bishop", "Bolt", "Brass", "Comet", "Crow", "Echo", "Flint",
    "Fox", "Ghost", "Hawkeye", "Iceman", "Kestrel", "Mako", "Nomad", "Rook",
    "Scout", "Slate", "Sparrow", "Torch", "Viper", "Wolf", "Wren", "Zero",
)

SOLDIER_IDENTITY_COMBINATIONS = len(COMBAT2_FIRST_NAMES) * len(COMBAT2_SURNAMES)
COMBAT2_STATIC_ROLES = frozenset(globals().get("STATIC_WEAPON_ROLES", ()))
COMBAT2_SUPPORT_ROLES = frozenset(
    ("Machine Gunner", "HMG Crew", "Automatic Rifleman", "Marksman", "Sniper", "Mortar Team")
)
COMBAT2_ASSAULT_ROLES = frozenset(("Assault", "Rifleman", "Grenadier", "Recon"))
COMBAT2_SUSTAINMENT_ROLES = frozenset(("Medic", "Engineer"))
COMBAT2_WOUND_LABELS = {
    "head": "head trauma",
    "torso": "torso wound",
    "arm": "arm wound",
    "leg": "leg wound",
}


@dataclass
class BallisticRound:
    round_id: int
    shooter_uid: int
    faction: str
    weapon_name: str
    x: float
    y: float
    vx: float
    vy: float
    remaining: float
    damage: float
    penetration: float
    suppression: float
    intended_uid: Optional[int] = None
    reaction: bool = False
    suppressive: bool = False
    traveled: float = 0.0
    visited_cells: set = field(default_factory=set)
    suppressed_uids: set = field(default_factory=set)


def generate_soldier_identity(seed, uid, faction="player", squad_id=1, slot=1):
    """Return a deterministic identity from a 1,600-combination name space."""
    total = SOLDIER_IDENTITY_COMBINATIONS
    faction_offset = 0 if faction == "player" else total // 2 + 17
    # 53 is coprime with 1,600, so sequential unit ids traverse the whole pool
    # without repeats before wrapping.
    index = (int(seed) * 37 + int(uid) * 53 + faction_offset) % total
    first = COMBAT2_FIRST_NAMES[index // len(COMBAT2_SURNAMES)]
    surname = COMBAT2_SURNAMES[index % len(COMBAT2_SURNAMES)]
    callsign = COMBAT2_CALLSIGNS[(index * 7 + int(seed) + int(squad_id) * 3) % len(COMBAT2_CALLSIGNS)]
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
    slot = sum(
        other.faction == unit.faction
        and other.uid != unit.uid
        and other.uid < unit.uid
        and getattr(other, "squad_id", 0) == squad_id
        and other.role not in COMBAT2_STATIC_ROLES
        for other in game.units
    ) + 1
    identity = generate_soldier_identity(game.seed, unit.uid, unit.faction, squad_id, slot)
    for key, value in identity.items():
        setattr(unit, key, value)
    return unit


_combat2_previous_add_unit = RealTimeGame.add_unit


def _combat2_add_unit(self, faction, role, x, y):
    unit = _combat2_previous_add_unit(self, faction, role, x, y)
    return _combat2_initialize_unit(self, unit)


RealTimeGame.add_unit = _combat2_add_unit


_combat2_previous_init = RealTimeGame.__init__


def _combat2_init(self, *args, **kwargs):
    _combat2_previous_init(self, *args, **kwargs)
    self.ballistic_rounds = []
    self.next_ballistic_round_id = 1
    self.combat2_tactical_plans = {}
    self.combat2_next_plan_at = 0.0
    self.combat2_last_projectile_count = 0
    for unit in self.units:
        _combat2_initialize_unit(self, unit)


RealTimeGame.__init__ = _combat2_init


def _combat2_wound_penalties(unit):
    arm = clamp(float(getattr(unit, "wound_arm", 0.0)), 0.0, 100.0)
    leg = clamp(float(getattr(unit, "wound_leg", 0.0)), 0.0, 100.0)
    head = clamp(float(getattr(unit, "wound_head", 0.0)), 0.0, 100.0)
    torso = clamp(float(getattr(unit, "wound_torso", 0.0)), 0.0, 100.0)
    return {
        "aim": arm * 0.15 + head * 0.20,
        "reload": 1.0 + arm * 0.009,
        "move": clamp(1.0 - leg * 0.0065 - torso * 0.0015, 0.48, 1.0),
        "reaction": head * 0.007 + torso * 0.002,
    }


def combat2_wound_summary(unit):
    wounds = []
    for location in ("head", "torso", "arm", "leg"):
        severity = float(getattr(unit, f"wound_{location}", 0.0))
        if severity >= 8:
            grade = "severe" if severity >= 55 else "moderate" if severity >= 28 else "light"
            wounds.append(f"{grade} {COMBAT2_WOUND_LABELS[location]}")
    return ", ".join(wounds) if wounds else "no localized wounds"


_combat2_previous_hit_chance = RealTimeGame.hit_chance


def _combat2_hit_chance(self, attacker, target, mode=None, reaction=False):
    chance = _combat2_previous_hit_chance(self, attacker, target, mode=mode, reaction=reaction)
    if chance <= 0:
        return chance
    penalty = _combat2_wound_penalties(attacker)["aim"]
    if self.time < getattr(attacker, "combat2_settle_until", 0.0):
        penalty += 12.0
    # Reacquisition is a temporal delay; once the weapon is ready it does not
    # also pay a hidden accuracy tax.
    return clamp(chance - penalty, 2, 96)


RealTimeGame.hit_chance = _combat2_hit_chance


_combat2_previous_shot_breakdown = RealTimeGame.shot_breakdown


def _combat2_shot_breakdown(self, attacker, target, mode=None, reaction=False):
    breakdown = _combat2_previous_shot_breakdown(self, attacker, target, mode=mode, reaction=reaction)
    if breakdown.get("chance", 0) <= 0:
        return breakdown
    penalties = _combat2_wound_penalties(attacker)
    if penalties["aim"] > 0.05:
        breakdown.setdefault("mods", []).append(("localized wounds", -penalties["aim"]))
    if self.time < getattr(attacker, "combat2_settle_until", 0.0):
        breakdown.setdefault("mods", []).append(("weapon unsettled", -12.0))
    # Several older presentation layers build their modifier list separately.
    # The authoritative number always comes from the final hit-chance pipeline.
    breakdown["chance"] = self.hit_chance(attacker, target, mode=mode, reaction=reaction)
    return breakdown


RealTimeGame.shot_breakdown = _combat2_shot_breakdown


_combat2_previous_issue_fire = RealTimeGame.issue_fire


def _combat2_issue_fire(self, unit, target, mode="normal"):
    changed = getattr(unit, "combat2_acquired_uid", None) != target.uid
    _combat2_previous_issue_fire(self, unit, target, mode)
    if changed:
        unit.combat2_acquired_uid = target.uid
        delay = self.reaction_delay(unit, target) * (0.66 if mode == "snap" else 0.88)
        unit.combat2_ready_at = max(unit.combat2_ready_at, self.time + delay)
        unit.next_shot = max(unit.next_shot, unit.combat2_ready_at)


RealTimeGame.issue_fire = _combat2_issue_fire


def _combat2_spawn_round(self, attacker, aim_position, intended_uid=None, reaction=False, suppressive=False):
    ax, ay = attacker.pos
    tx, ty = aim_position
    dx, dy = tx - ax, ty - ay
    length = max(0.001, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    speed = {
        "SMG": 42.0,
        "Carbine": 48.0,
        "Service Rifle": 56.0,
        "Automatic Rifle": 54.0,
        "Light Machine Gun": 57.0,
        "Heavy Machine Gun": 62.0,
        "Marksman Rifle": 64.0,
        "Scoped Rifle": 67.0,
    }.get(attacker.weapon_name, 52.0)
    weapon = attacker.weapon
    round_state = BallisticRound(
        self.next_ballistic_round_id,
        attacker.uid,
        attacker.faction,
        attacker.weapon_name,
        ax + ux * 0.22,
        ay + uy * 0.22,
        ux * speed,
        uy * speed,
        weapon["range"] * (1.04 if suppressive else 1.0),
        float(weapon["damage"]),
        float(weapon["pen"]),
        float(weapon["supp"]),
        intended_uid,
        reaction,
        suppressive,
    )
    self.next_ballistic_round_id += 1
    self.ballistic_rounds.append(round_state)
    if len(self.ballistic_rounds) > 360:
        self.ballistic_rounds = self.ballistic_rounds[-320:]
    return round_state


RealTimeGame.spawn_ballistic_round = _combat2_spawn_round


def _combat2_commit_weapon_discharge(self, attacker, reaction=False):
    weapon = attacker.weapon
    attacker.ammo -= 1
    attacker.next_shot = self.time + self.fire_interval(attacker)
    attacker.signature = max(attacker.signature, 55 if attacker.role in ("Machine Gunner", "HMG Crew") else 32)
    attacker.aim_progress = max(0, attacker.aim_progress - 0.35)
    attacker.combat2_exposed_until = self.time + (0.75 if attacker.stance == "prone" else 1.05)
    heat_add = weapon["heat"] * (1.35 if attacker.fire_mode == "rapid" else 1.0)
    attacker.heat += heat_add
    jam_probability = 0.002 + max(0, attacker.heat - 75) * 0.0015
    if self.rng.random() < jam_probability:
        attacker.jammed = True
        self.add_log(f"{getattr(attacker, 'display_name', attacker.role)} weapon jammed.")
    if hasattr(self, "stats"):
        self.stats[attacker.faction]["shots"] += 1
    attacker.shots_recent = getattr(attacker, "shots_recent", 0) + 1
    attacker.last_shot_time = self.time
    self.emit("shot", weapon=attacker.weapon_name, pos=attacker.pos, faction=attacker.faction)


def _combat2_perform_shot(self, attacker, target, reaction=False):
    if not attacker.combat_effective or not target.combat_effective:
        return
    if attacker.jammed or attacker.reload_timer > 0 or attacker.carrying_uid is not None:
        return
    if self.time < attacker.command_delay_until or self.time < attacker.traverse_ready_at:
        return
    if attacker.heat >= 100:
        attacker.order = "idle"
        self.add_log(f"{getattr(attacker, 'display_name', attacker.role)} overheated; fire stopped.")
        return
    if attacker.ammo <= 0:
        self.start_reload(attacker)
        return
    distance = dist(attacker, target)
    if distance > attacker.weapon["range"]:
        return
    if getattr(attacker, "combat2_acquired_uid", None) != target.uid:
        attacker.combat2_acquired_uid = target.uid
        acquisition = 0.0 if getattr(attacker, "_moving_fire_active", False) else self.reaction_delay(attacker, target) * 0.42
        attacker.combat2_ready_at = self.time + acquisition
        attacker.next_shot = max(attacker.next_shot, attacker.combat2_ready_at)
        if acquisition > 0:
            return
    if self.time < getattr(attacker, "combat2_ready_at", 0.0):
        attacker.next_shot = max(attacker.next_shot, attacker.combat2_ready_at)
        return
    chance = self.hit_chance(attacker, target, reaction=reaction)
    if chance <= 0:
        return
    attacker.facing = angle_to(attacker, target)
    dx, dy = target.x - attacker.x, target.y - attacker.y
    length = max(0.001, math.hypot(dx, dy))
    normal = (-dy / length, dx / length)
    hit_solution = self.rng.uniform(0, 100) <= chance
    if hit_solution:
        lateral = self.rng.gauss(0, 0.075 + distance * 0.0035)
        depth = self.rng.gauss(0, 0.055)
    else:
        miss_width = 0.36 + (100 - chance) * 0.014 + distance * 0.012
        lateral = self.rng.choice((-1.0, 1.0)) * self.rng.uniform(0.34, miss_width)
        depth = self.rng.uniform(-0.22, 0.45)
    aim = (
        target.x + normal[0] * lateral + (dx / length) * depth,
        target.y + normal[1] * lateral + (dy / length) * depth,
    )
    _combat2_commit_weapon_discharge(self, attacker, reaction=reaction)
    self.spawn_ballistic_round(attacker, aim, target.uid, reaction=reaction)


RealTimeGame.perform_shot = _combat2_perform_shot


def _combat2_perform_suppressive_shot(self, unit):
    if not unit.combat_effective or unit.jammed or unit.reload_timer > 0 or unit.carrying_uid is not None:
        return
    if unit.ammo <= 0:
        self.start_reload(unit)
        return
    if not unit.target_pos or self.time < unit.command_delay_until or self.time < unit.traverse_ready_at:
        return
    tx, ty = unit.target_pos
    distance = dist(unit.pos, (tx, ty))
    if distance > unit.weapon["range"] * 1.05:
        return
    spread = 0.35 + distance * 0.035
    aim = (tx + self.rng.gauss(0, spread), ty + self.rng.gauss(0, spread * 0.72))
    unit.facing = angle_to(unit, aim)
    _combat2_commit_weapon_discharge(self, unit)
    unit.next_shot = self.time + self.fire_interval(unit) * 0.65
    unit.heat += unit.weapon["heat"] * 0.2
    self.spawn_ballistic_round(unit, aim, suppressive=True)


RealTimeGame.perform_suppressive_shot = _combat2_perform_suppressive_shot


def _combat2_point_segment_distance(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    denominator = vx * vx + vy * vy
    q = 0.0 if denominator <= 1e-9 else clamp(((px - ax) * vx + (py - ay) * vy) / denominator, 0.0, 1.0)
    cx, cy = ax + q * vx, ay + q * vy
    return math.hypot(px - cx, py - cy), q


def _combat2_target_radius(game, target):
    radius = {"standing": 0.34, "crouched": 0.27, "prone": 0.19}.get(target.stance, 0.32)
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


def _combat2_terrain_collision(self, projectile, x, y):
    cell = self.grid[y][x]
    terrain = TERRAIN[cell.terrain]
    cover = float(terrain["cover"])
    resistance = float(terrain["pen"])
    closed_door = cell.terrain == "door" and not cell.door_open
    hard = bool(terrain["blocks"] or closed_door or cell.terrain in ("wall", "building"))
    material = hard or cell.terrain in ("woods", "sandbags", "bunker", "woodwall", "window", "door", "dugout")
    if not material:
        return False
    intercept = 1.0 if hard else clamp(0.12 + cover * 0.105, 0.18, 0.72)
    if self.rng.random() > intercept:
        return False
    penetrates = projectile.penetration >= max(1.0, resistance) and (
        not hard or projectile.penetration > resistance or self.rng.random() < 0.35
    )
    power = projectile.damage * (0.42 if penetrates else 0.7)
    self.degrade_cover((x, y), power, int(max(0, projectile.penetration)))
    if cell.hp is not None and power > 10:
        cell.hp -= power * 0.08
    if penetrates:
        projectile.damage *= clamp(0.82 - resistance * 0.12, 0.34, 0.78)
        projectile.penetration = max(0.0, projectile.penetration - max(0.65, resistance))
        self.impacts.append(Impact(projectile.x, projectile.y, _combat2_impact_kind(cell), 0.16))
        return False
    self.impacts.append(Impact(projectile.x, projectile.y, _combat2_impact_kind(cell), 0.22))
    return True


RealTimeGame.combat2_terrain_collision = _combat2_terrain_collision


def _combat2_apply_wound(self, target, damage, projectile):
    roll = self.rng.random()
    if target.stance == "prone":
        thresholds = (0.15, 0.57, 0.78)
    else:
        thresholds = (0.11, 0.53, 0.77)
    if roll < thresholds[0]:
        location, multiplier = "head", 1.55
    elif roll < thresholds[1]:
        location, multiplier = "torso", 1.0
    elif roll < thresholds[2]:
        location, multiplier = "arm", 0.67
    else:
        location, multiplier = "leg", 0.76
    final_damage = damage * multiplier * self.rng.uniform(0.88, 1.12)
    severity_gain = clamp(final_damage * (0.86 if location == "torso" else 1.0), 4.0, 72.0)
    attr = f"wound_{location}"
    setattr(target, attr, clamp(float(getattr(target, attr, 0.0)) + severity_gain, 0.0, 100.0))
    target.wound_treated = False
    if location == "head":
        target.disoriented_until = max(target.disoriented_until, self.time + 1.4 + severity_gain * 0.045)
    elif location == "torso":
        target.bleed = max(target.bleed, 9.0 + severity_gain * 0.28)
    elif location == "arm":
        target.aim_progress = 0.0
    elif location == "leg":
        target.stamina = max(0.0, target.stamina - severity_gain * 0.45)
    source = self.get_unit(projectile.shooter_uid)
    self.apply_damage(target, final_damage, source, f"{location} gunshot")
    if target.casualty == "healthy" and severity_gain >= 8:
        target.casualty = "wounded"
    self.impacts.append(Impact(target.x, target.y, "body", 0.20))
    if hasattr(self, "stats"):
        self.stats[projectile.faction]["hits"] += 1
    if source is not None:
        source.momentum = clamp(source.momentum + 10, 0, 100)
    return location, final_damage


RealTimeGame.apply_ballistic_wound = _combat2_apply_wound


def _combat2_apply_near_miss(self, projectile, unit, distance_to_path):
    if unit.uid in projectile.suppressed_uids:
        return
    projectile.suppressed_uids.add(unit.uid)
    proximity = clamp(1.0 - distance_to_path / 0.92, 0.0, 1.0)
    gain = projectile.suppression * (0.13 + proximity * 0.47)
    if projectile.suppressive:
        gain *= 1.28
    unit.suppression = clamp(unit.suppression + gain, 0, 100)
    unit.morale = clamp(unit.morale - gain * 0.12, 0, 100)
    unit.under_fire_until = self.time + 2.8
    unit.last_attacker_uid = projectile.shooter_uid
    source = self.get_unit(projectile.shooter_uid)
    if source is not None:
        unit.incoming_bearings.append((angle_to(unit, source), self.time))
    tx, ty = unit.tile
    self.grid[ty][tx].ground_suppression = clamp(
        self.grid[ty][tx].ground_suppression + gain * 0.42,
        0,
        100,
    )


RealTimeGame._combat2_apply_near_miss = _combat2_apply_near_miss


def _combat2_update_ballistics(self, dt):
    if not self.ballistic_rounds:
        self.combat2_last_projectile_count = 0
        return
    max_step = 0.18
    for projectile in list(self.ballistic_rounds):
        speed = max(0.001, math.hypot(projectile.vx, projectile.vy))
        travel = min(projectile.remaining, speed * dt)
        steps = max(1, int(math.ceil(travel / max_step)))
        step_distance = travel / steps
        ux, uy = projectile.vx / speed, projectile.vy / speed
        alive = True
        for _ in range(steps):
            ax, ay = projectile.x, projectile.y
            bx, by = ax + ux * step_distance, ay + uy * step_distance
            projectile.x, projectile.y = bx, by
            projectile.remaining -= step_distance
            projectile.traveled += step_distance
            if not (0 <= bx < MAP_W and 0 <= by < MAP_H):
                alive = False
                break
            cell_pos = (int(round(bx)), int(round(by)))
            if not self.in_bounds(*cell_pos):
                alive = False
                break
            if cell_pos not in projectile.visited_cells:
                projectile.visited_cells.add(cell_pos)
                if self.combat2_terrain_collision(projectile, *cell_pos):
                    alive = False
                    break
            candidates = []
            if projectile.traveled > 0.30:
                for unit in self.living():
                    if unit.uid == projectile.shooter_uid or not unit.combat_effective:
                        continue
                    distance_to_path, position = _combat2_point_segment_distance(unit.x, unit.y, ax, ay, bx, by)
                    if distance_to_path <= 0.92:
                        candidates.append((position, distance_to_path, unit))
            hit = None
            for _position, distance_to_path, unit in sorted(candidates, key=lambda record: record[0]):
                radius = _combat2_target_radius(self, unit)
                if distance_to_path <= radius:
                    hit = unit
                    break
                self._combat2_apply_near_miss(projectile, unit, distance_to_path)
            if hit is not None:
                self._combat2_apply_near_miss(projectile, hit, 0.0)
                self.apply_ballistic_wound(hit, projectile.damage, projectile)
                alive = False
                break
            if projectile.remaining <= 0:
                alive = False
                self.impacts.append(Impact(bx, by, "dirt", 0.16))
                break
        self.tracers.append(Tracer((projectile.x - ux * min(travel, 0.75), projectile.y - uy * min(travel, 0.75)), (projectile.x, projectile.y), 0.12, 0.12))
        if not alive and projectile in self.ballistic_rounds:
            self.ballistic_rounds.remove(projectile)
    if len(self.tracers) > 260:
        self.tracers = self.tracers[-220:]
    if len(self.impacts) > 220:
        self.impacts = self.impacts[-180:]
    self.combat2_last_projectile_count = len(self.ballistic_rounds)


RealTimeGame.update_ballistic_rounds = _combat2_update_ballistics


_combat2_previous_start_reload = RealTimeGame.start_reload


def _combat2_start_reload(self, unit, emergency=False):
    before = unit.reload_timer
    result = _combat2_previous_start_reload(self, unit, emergency=emergency)
    if unit.reload_timer > max(0.0, before):
        unit.reload_timer *= _combat2_wound_penalties(unit)["reload"]
    return result


RealTimeGame.start_reload = _combat2_start_reload


_combat2_previous_complete_action = RealTimeGame.complete_action


def _combat2_complete_action(self, unit):
    medic_target = self.get_unit(unit.target_uid) if unit.order == "medic" else None
    result = _combat2_previous_complete_action(self, unit)
    if medic_target is not None and medic_target.alive:
        for location in ("head", "torso", "arm", "leg"):
            attr = f"wound_{location}"
            setattr(medic_target, attr, float(getattr(medic_target, attr, 0.0)) * 0.58)
        medic_target.wound_treated = True
    return result


RealTimeGame.complete_action = _combat2_complete_action


_combat2_previous_update_movement = RealTimeGame.update_movement


def _combat2_update_movement(self, unit, dt):
    before = unit.pos
    penalties = _combat2_wound_penalties(unit)
    # Scaling dt preserves path and occupancy semantics while making leg wounds
    # materially slow the distance covered by the existing movement integrator.
    result = _combat2_previous_update_movement(self, unit, dt * penalties["move"])
    if dist(before, unit.pos) > 1e-6:
        unit.combat2_settle_until = max(unit.combat2_settle_until, self.time + 0.34 + unit.suppression * 0.002)
        unit.combat2_exposed_until = max(unit.combat2_exposed_until, self.time + 0.30)
        unit.combat2_last_move_pos = unit.pos
    return result


RealTimeGame.update_movement = _combat2_update_movement


def _combat2_known_target_position(self):
    visible = [
        unit for unit in self.living("player")
        if unit.combat_effective and self.visible_to("enemy", unit)
    ]
    if visible:
        center_x = sum(unit.x for unit in visible) / len(visible)
        center_y = sum(unit.y for unit in visible) / len(visible)
        return (center_x, center_y), visible
    contacts = self.known_contacts("enemy", memory=12.0)
    if contacts:
        positions = [record[1]["pos"] for record in contacts]
        return (
            sum(position[0] for position in positions) / len(positions),
            sum(position[1] for position in positions) / len(positions),
        ), []
    if getattr(self, "mission_type", "assault") == "defense":
        command = getattr(self, "map_features", {}).get("command_post", (MAP_W - 5, MAP_H / 2))
        return tuple(command), []
    return (max(3.0, getattr(self, "primary_line_x", MAP_W - 10) - 10.0), MAP_H / 2), []


RealTimeGame.combat2_known_target_position = _combat2_known_target_position


def _combat2_local_strength(self, faction, position, radius=5.5):
    return sum(
        1.35 if unit.role in COMBAT2_SUPPORT_ROLES else 1.0
        for unit in self.living(faction)
        if unit.combat_effective and dist(unit.pos, position) <= radius
    )


RealTimeGame.combat2_local_strength = _combat2_local_strength


def _combat2_plan_squads(self, force=False):
    if getattr(self, "network_replica", False) or getattr(self, "mission_type", "assault") == "pvp":
        return
    if not force and self.time < self.combat2_next_plan_at:
        return
    tactics = DIFFICULTY[self.difficulty].get("tactics", 1.0)
    self.combat2_next_plan_at = self.time + max(0.55, 1.05 / max(0.5, tactics))
    target_position, visible = self.combat2_known_target_position()
    squads = {}
    for unit in self.living("enemy"):
        if unit.combat_effective and unit.role not in COMBAT2_STATIC_ROLES:
            squads.setdefault(max(1, int(getattr(unit, "squad_id", 1))), []).append(unit)
    offensive = getattr(self, "mission_type", "assault") == "defense"
    plans = {}
    for squad_id, members in squads.items():
        center = (
            sum(unit.x for unit in members) / len(members),
            sum(unit.y for unit in members) / len(members),
        )
        local_targets = sorted(visible, key=lambda target: dist(target.pos, center))
        squad_target = local_targets[0].pos if local_targets else target_position
        target_unit = local_targets[0] if local_targets else None
        support = [unit for unit in members if unit.role in COMBAT2_SUPPORT_ROLES]
        sustainment = [unit for unit in members if unit.role in COMBAT2_SUSTAINMENT_ROLES]
        maneuver = [unit for unit in members if unit not in support and unit not in sustainment]
        if not maneuver:
            maneuver = [unit for unit in members if unit not in support]
        distance_to_target = dist(center, squad_target)
        tx, ty = int(clamp(round(squad_target[0]), 0, MAP_W - 1)), int(clamp(round(squad_target[1]), 0, MAP_H - 1))
        target_suppression = target_unit.suppression if target_unit is not None else self.grid[ty][tx].ground_suppression
        support_active = any(
            unit.order in ("suppress", "fire", "fire_lane") and unit.ammo > 0
            for unit in support
        )
        if offensive:
            if target_suppression < 32 and support and not support_active:
                phase = "base_of_fire"
            elif distance_to_target > 4.2:
                phase = "maneuver"
            else:
                phase = "assault"
            side = -1 if squad_id % 2 else 1
            dx, dy = squad_target[0] - center[0], squad_target[1] - center[1]
            length = max(1.0, math.hypot(dx, dy))
            flank = (
                clamp(squad_target[0] + side * (-dy / length) * min(5.0, distance_to_target * 0.48), 1, MAP_W - 2),
                clamp(squad_target[1] + side * (dx / length) * min(5.0, distance_to_target * 0.48), 1, MAP_H - 2),
            )
        else:
            enemy_strength = self.combat2_local_strength("player", center, 6.0)
            friendly_strength = self.combat2_local_strength("enemy", center, 6.0)
            threatened = enemy_strength > friendly_strength * 1.12
            counterattack = any(
                target.suppression >= 62 and dist(target.pos, center) <= 5.0
                for target in local_targets
            ) and friendly_strength >= enemy_strength * 1.18
            phase = "counterattack" if counterattack else "reposition" if threatened else "hold"
            flank = center
        plan = {
            "squad_id": squad_id,
            "offensive": offensive,
            "phase": phase,
            "target": tuple(squad_target),
            "target_uid": target_unit.uid if target_unit is not None else None,
            "flank": tuple(flank),
            "support_active": support_active,
            "created": self.time,
        }
        plans[squad_id] = plan
        for unit in members:
            if unit in support:
                assignment = "support_by_fire" if offensive else "covered_lane"
            elif unit in sustainment:
                assignment = "sustainment"
            elif not offensive and members.index(unit) >= max(1, len(members) - 2):
                assignment = "reserve"
            else:
                assignment = "assault" if offensive and phase == "assault" else "maneuver" if offensive else "screen"
            unit.combat2_assignment = assignment
            unit.combat2_phase = phase
            unit.combat2_plan_target = tuple(squad_target)
            unit.combat2_flank = tuple(flank)
    self.combat2_tactical_plans = plans


RealTimeGame.plan_combat2_squads = _combat2_plan_squads


_combat2_previous_ai_decide = RealTimeGame.ai_decide


def _combat2_ai_decide(self, unit):
    if unit.faction != "enemy" or unit.role in COMBAT2_STATIC_ROLES or getattr(self, "mission_type", "assault") == "pvp":
        return _combat2_previous_ai_decide(self, unit)
    if unit.jammed or (unit.ammo <= 0 and unit.magazines) or unit.suppression > 78 or unit.morale < 28:
        return _combat2_previous_ai_decide(self, unit)
    if not getattr(unit, "reserve_active", True):
        return _combat2_previous_ai_decide(self, unit)
    if (
        unit.order.startswith("eng_build")
        or unit.order in ("build", "medic", "rout", "surrender")
        or getattr(unit, "_construction_queued", False)
    ):
        return
    plan = self.combat2_tactical_plans.get(max(1, int(getattr(unit, "squad_id", 1))))
    if plan is None:
        self.plan_combat2_squads(force=True)
        plan = self.combat2_tactical_plans.get(max(1, int(getattr(unit, "squad_id", 1))))
    if plan is None:
        return _combat2_previous_ai_decide(self, unit)
    target_position = plan["target"]
    visible = [
        target for target in self.living("player")
        if target.combat_effective and self.can_see(unit, target)
    ]
    target = min(visible, key=lambda candidate: dist(unit, candidate)) if visible else None
    # The operations layer already owns terrain-aware, staged approach
    # waypoints for the reverse-map defence mission. Preserve that navigation
    # until contact, then let the new squad plan control the firefight.
    if plan["offensive"] and target is None and getattr(self, "mission_type", "assault") == "defense":
        unit.combat2_decision_reason = "advancing on the staged assault route"
        return _combat2_previous_ai_decide(self, unit)
    assignment = unit.combat2_assignment
    phase = plan["phase"]
    if plan["offensive"]:
        if assignment == "support_by_fire":
            if target is None and getattr(self, "mission_type", "assault") == "defense":
                staging = self.defense_attack_destination(unit)
                if dist(unit.pos, staging) > 2.4:
                    if unit.deployed and unit.role in ("Machine Gunner", "HMG Crew"):
                        self.toggle_deploy(unit)
                    elif unit.order != "move":
                        self.issue_move([unit], staging, mode="safe", formation="column")
                    unit.combat2_decision_reason = "advancing the base of fire by bounds"
                    return
            if unit.role in ("Machine Gunner", "HMG Crew") and not unit.deployed:
                unit.combat2_decision_reason = "deploying the squad base of fire"
                self.toggle_deploy(unit)
                return
            if unit.role == "Mortar Team" and target is not None and 5 <= dist(unit, target) <= 19:
                if not unit.deployed:
                    self.toggle_deploy(unit)
                elif unit.mortar_shells > 0:
                    self.mortar_fire(unit, target.pos)
                unit.combat2_decision_reason = "supporting the assault with indirect fire"
            elif unit.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman") and (
                target is not None or unit.order not in ("suppress", "fire")
            ):
                unit.combat2_decision_reason = "fixing the defence with sustained fire"
                self.suppress_area(unit, target.pos if target is not None else target_position)
            elif target is not None:
                self.issue_fire(unit, target, "aimed")
                unit.combat2_decision_reason = "providing deliberate precision fire"
            elif unit.order not in ("overwatch", "fire"):
                self.set_overwatch(unit, angle_to(unit, target_position), 90)
            return
        if assignment == "sustainment":
            if unit.role == "Medic":
                return _combat2_previous_ai_decide(self, unit)
            if phase == "assault" and dist(unit.pos, target_position) > 5.0 and unit.order not in ("move", "rout"):
                follow = (int(clamp(target_position[0] - 3.0, 1, MAP_W - 2)), int(clamp(target_position[1], 1, MAP_H - 2)))
                unit.combat2_decision_reason = "keeping engineer support behind the assault"
                self.issue_move([unit], follow, mode="safe", formation="column")
                return
            return _combat2_previous_ai_decide(self, unit)
        if phase == "base_of_fire":
            if target is not None:
                unit.combat2_decision_reason = "adding fire until the enemy is fixed"
                self.issue_fire(unit, target, "normal")
            else:
                self.set_overwatch(unit, angle_to(unit, target_position), 105)
            return
        if phase == "maneuver":
            flank = (
                self.defense_attack_destination(unit)
                if target is None and getattr(self, "mission_type", "assault") == "defense"
                else plan["flank"]
            )
            if dist(unit.pos, flank) > 1.8 and unit.order != "move":
                if unit.smoke_grenades > 0 and self.tile_threat("enemy", *unit.tile) > 1.15:
                    midpoint = ((unit.x + flank[0]) * 0.5, (unit.y + flank[1]) * 0.5)
                    self.throw_grenade(unit, midpoint, smoke=True)
                    unit.combat2_decision_reason = "screening the maneuver route with smoke"
                else:
                    self.issue_move([unit], (int(flank[0]), int(flank[1])), mode="safe", formation="column")
                    unit.combat2_decision_reason = "maneuvering around the fixed defence"
                return
            if target is not None:
                self.issue_fire(unit, target, "normal")
            else:
                self.set_overwatch(unit, angle_to(unit, target_position), 100)
            return
        if target is not None:
            distance = dist(unit, target)
            if unit.grenades > 0 and distance < 4.1 and self.effective_cover(unit, target) >= 2:
                self.throw_grenade(unit, target.pos, cook=0.6)
                unit.combat2_decision_reason = "breaching covered defenders with a grenade"
            elif distance <= unit.weapon["range"]:
                self.issue_fire(unit, target, "rapid" if unit.role == "Assault" or distance < 3.0 else "normal")
                unit.combat2_decision_reason = "closing and clearing the assault objective"
            return
        if dist(unit.pos, target_position) > 1.6 and unit.order != "move":
            self.issue_move([unit], (int(target_position[0]), int(target_position[1])), mode="safe", formation="wedge")
            unit.combat2_decision_reason = "occupying the suppressed objective"
        return
    # Defensive doctrine: weapons establish interlocking lanes, the screen
    # trades ground when locally outmatched, and a small reserve only commits
    # against a genuinely suppressed incursion.
    if assignment == "covered_lane":
        if unit.role in ("Machine Gunner", "HMG Crew") and not unit.deployed:
            self.toggle_deploy(unit)
            unit.combat2_decision_reason = "deploying an interlocking defensive lane"
        elif target is not None and unit.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman"):
            self.suppress_area(unit, target.pos)
            unit.combat2_decision_reason = "denying the enemy approach"
        elif target is not None:
            self.issue_fire(unit, target, "aimed")
            unit.combat2_decision_reason = "engaging through the covered lane"
        elif unit.role not in ("Machine Gunner", "HMG Crew"):
            self.set_overwatch(unit, 180, 90)
            unit.combat2_decision_reason = "observing the assigned defensive lane"
        else:
            self.set_fire_lane(unit, 180, 75)
            unit.combat2_decision_reason = "covering the assigned sector"
        return
    if assignment == "sustainment":
        return _combat2_previous_ai_decide(self, unit)
    if assignment == "reserve" and phase != "counterattack":
        if unit.order not in ("overwatch", "fire"):
            self.set_overwatch(unit, 180, 120)
        unit.combat2_decision_reason = "remaining concealed as the local reserve"
        return
    if phase == "reposition" and unit.order != "move":
        destination = self.find_nearby_cover(unit, 5)
        if destination and destination != unit.tile:
            if unit.deployed and unit.role in ("Machine Gunner", "HMG Crew"):
                self.toggle_deploy(unit)
            else:
                self.issue_move([unit], destination, mode="safe", formation="column")
            unit.combat2_decision_reason = "trading a compromised position for depth"
            return
    if phase == "counterattack" and target is not None:
        if dist(unit, target) <= unit.weapon["range"]:
            self.issue_fire(unit, target, "rapid" if dist(unit, target) < 4 else "normal")
        elif unit.order != "move":
            self.issue_move([unit], target.tile, mode="safe", formation="wedge")
        unit.combat2_decision_reason = "counterattacking a suppressed penetration"
        return
    if target is not None:
        self.issue_fire(unit, target, "aimed" if dist(unit, target) > 7 else "normal")
        unit.combat2_decision_reason = "engaging from the prepared defence"
    elif unit.order not in ("overwatch", "fire_lane"):
        self.set_overwatch(unit, 180, 110)
        unit.combat2_decision_reason = "holding the defensive screen"


RealTimeGame.ai_decide = _combat2_ai_decide


_combat2_previous_update = RealTimeGame.update


def _combat2_update(self, dt):
    if getattr(self, "network_replica", False):
        return _combat2_previous_update(self, dt)
    active = not self.paused and not (self.victory or self.defeat)
    if active:
        self.plan_combat2_squads()
    result = _combat2_previous_update(self, dt)
    if active:
        self.update_ballistic_rounds(dt)
    return result


RealTimeGame.update = _combat2_update


# New state travels through the existing authoritative multiplayer snapshots.
if "NETWORK_UNIT_FIELDS" in globals():
    NETWORK_UNIT_FIELDS = tuple(NETWORK_UNIT_FIELDS) + tuple(
        field_name for field_name in (
            "identity_index", "first_name", "surname", "full_name", "callsign",
            "wound_head", "wound_torso", "wound_arm", "wound_leg", "wound_treated",
            "combat2_exposed_until", "combat2_settle_until", "combat2_assignment",
            "combat2_phase", "combat2_plan_target", "combat2_decision_reason",
        ) if field_name not in NETWORK_UNIT_FIELDS
    )


_combat2_previous_tooltip_lines = unit_card_tooltip_lines


def unit_card_tooltip_lines(unit):
    lines = list(_combat2_previous_tooltip_lines(unit))
    if unit.role not in COMBAT2_STATIC_ROLES:
        identity = f"{getattr(unit, 'full_name', getattr(unit, 'display_name', unit.role))}  ·  {unit.role}  ·  callsign {getattr(unit, 'callsign', '—')}"
        if lines:
            lines[0] = identity
        wounds = combat2_wound_summary(unit)
        if wounds != "no localized wounds":
            lines.append(f"TRAUMA  {wounds.upper()}")
        assignment = str(getattr(unit, "combat2_assignment", "unassigned")).replace("_", " ").upper()
        phase = str(getattr(unit, "combat2_phase", "contact")).replace("_", " ").upper()
        if unit.faction == "enemy" and assignment != "UNASSIGNED":
            lines.append(f"TACTICS  {assignment} · {phase}")
    return lines


_combat2_previous_draw_unit = KillZoneApp.draw_unit


def _combat2_draw_unit(self, unit):
    _combat2_previous_draw_unit(self, unit)
    if not unit.alive or unit.role in COMBAT2_STATIC_ROLES:
        return
    wound_load = max(
        float(getattr(unit, "wound_head", 0.0)),
        float(getattr(unit, "wound_torso", 0.0)),
        float(getattr(unit, "wound_arm", 0.0)),
        float(getattr(unit, "wound_leg", 0.0)),
    )
    if wound_load < 18:
        return
    center = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(30, 30).collidepoint(center):
        return
    radius = max(14, int(self.tile_px * 0.58))
    color = COLORS["danger"] if wound_load >= 55 else COLORS["contact"]
    pygame.draw.line(self.screen, color, (center[0] + radius - 5, center[1] - radius), (center[0] + radius, center[1] - radius), 2)
    pygame.draw.line(self.screen, color, (center[0] + radius, center[1] - radius), (center[0] + radius, center[1] - radius + 5), 2)


KillZoneApp.draw_unit = _combat2_draw_unit
