"""Combat Feel 2.1: cadence, readable danger, stable tactics, and presentation polish.

This deliberately extends Combat 2.0 instead of replacing it.  Physical
rounds remain authoritative (and can still hit a friendly who crosses a shot
after it is fired), while deliberate orders now reject an obviously occupied
friendly firing lane.  The rest of the pass focuses on rhythm and intent:
weapons use recognizable bursts, soldiers react to danger, and AI orders live
long enough to look like a plan rather than a sequence of corrections.
"""


COMBAT_POLISH_WEAPON_PROFILES = {
    "SMG": {"burst": (3, 5), "pause": (0.22, 0.42), "recoil": 3.0, "cadence": 0.92},
    "Carbine": {"burst": (2, 4), "pause": (0.26, 0.48), "recoil": 2.7, "cadence": 0.96},
    "Service Rifle": {"burst": (2, 3), "pause": (0.32, 0.58), "recoil": 3.1, "cadence": 1.02},
    "Automatic Rifle": {"burst": (3, 5), "pause": (0.30, 0.52), "recoil": 3.2, "cadence": 0.96},
    "Light Machine Gun": {"burst": (5, 8), "pause": (0.42, 0.72), "recoil": 2.4, "cadence": 0.94},
    "Heavy Machine Gun": {"burst": (6, 10), "pause": (0.48, 0.82), "recoil": 1.9, "cadence": 0.94},
    "Marksman Rifle": {"burst": (1, 2), "pause": (0.46, 0.78), "recoil": 4.0, "cadence": 1.06},
    "Scoped Rifle": {"burst": (1, 1), "pause": (0.70, 1.05), "recoil": 4.8, "cadence": 1.08},
}
COMBAT_POLISH_DEFAULT_PROFILE = {
    "burst": (2, 3), "pause": (0.30, 0.55), "recoil": 3.0, "cadence": 1.0,
}
COMBAT_POLISH_STATIC_ROLES = frozenset(globals().get("STATIC_WEAPON_ROLES", ()))
COMBAT_POLISH_COMMIT_ORDERS = frozenset(
    ("move", "fire", "suppress", "overwatch", "fire_lane", "deploy", "pack", "build")
)


def combat_polish_weapon_profile(unit_or_weapon):
    """Return a copy of the cadence profile for a unit or weapon name."""
    weapon_name = (
        str(unit_or_weapon)
        if isinstance(unit_or_weapon, str)
        else str(getattr(unit_or_weapon, "weapon_name", ""))
    )
    return dict(COMBAT_POLISH_WEAPON_PROFILES.get(weapon_name, COMBAT_POLISH_DEFAULT_PROFILE))


def _polish_initialize_unit(unit):
    unit.polish_burst_remaining = int(getattr(unit, "polish_burst_remaining", 0))
    unit.polish_burst_pause_until = float(getattr(unit, "polish_burst_pause_until", 0.0))
    unit.polish_recoil = float(getattr(unit, "polish_recoil", 0.0))
    unit.polish_target_lock_until = float(getattr(unit, "polish_target_lock_until", 0.0))
    unit.polish_plan_commit_until = float(getattr(unit, "polish_plan_commit_until", 0.0))
    unit.polish_deploy_lock_until = float(getattr(unit, "polish_deploy_lock_until", 0.0))
    unit.polish_reaction_until = float(getattr(unit, "polish_reaction_until", 0.0))
    unit.polish_reaction_kind = str(getattr(unit, "polish_reaction_kind", ""))
    unit.polish_reaction_stance = getattr(unit, "polish_reaction_stance", None)
    unit.polish_order_state = str(getattr(unit, "polish_order_state", "READY"))
    unit.polish_order_state_until = float(getattr(unit, "polish_order_state_until", 0.0))
    unit.polish_lane_reason = str(getattr(unit, "polish_lane_reason", ""))
    unit.polish_lane_blocked_until = float(getattr(unit, "polish_lane_blocked_until", 0.0))
    unit.polish_wait_reason = str(getattr(unit, "polish_wait_reason", ""))
    unit.polish_arrival_facing = float(getattr(unit, "polish_arrival_facing", unit.facing))
    unit.polish_last_order_signature = getattr(unit, "polish_last_order_signature", None)
    unit.polish_last_order_at = float(getattr(unit, "polish_last_order_at", -99.0))
    unit.polish_last_progress_pos = tuple(getattr(unit, "polish_last_progress_pos", unit.pos))
    unit.polish_last_progress_at = float(getattr(unit, "polish_last_progress_at", 0.0))
    return unit


_polish_previous_add_unit = RealTimeGame.add_unit


def _polish_add_unit(self, faction, role, x, y):
    return _polish_initialize_unit(_polish_previous_add_unit(self, faction, role, x, y))


RealTimeGame.add_unit = _polish_add_unit


_polish_previous_init = RealTimeGame.__init__


def _polish_init(self, *args, **kwargs):
    _polish_previous_init(self, *args, **kwargs)
    self.polish_preparation_until = 1.0
    self.polish_plan_commits = {}
    self.polish_engagement_state = "PREPARATION"
    self.polish_engagement_changed_at = 0.0
    self.polish_contact_pressure = 0.0
    self.polish_last_impact_event_at = -99.0
    self.polish_recent_tracers = []
    self.polish_peak_intensity = 0.0
    for unit in self.units:
        _polish_initialize_unit(unit)


RealTimeGame.__init__ = _polish_init


def _polish_unit_clearance(unit):
    stance = getattr(unit, "stance", "standing")
    return 0.30 if stance == "prone" else 0.40 if stance == "crouched" else 0.50


def _polish_firing_lane_risk(self, shooter, aim_position, target_uid=None):
    """Return the first friendly obstructing a deliberate firing lane."""
    ax, ay = shooter.pos
    bx, by = float(aim_position[0]), float(aim_position[1])
    if math.hypot(bx - ax, by - ay) < 0.75:
        return None
    risks = []
    for friendly in self.living(shooter.faction):
        if (
            friendly.uid == shooter.uid
            or friendly.uid == target_uid
            or not friendly.combat_effective
            or friendly.casualty in ("dead", "surrendered")
        ):
            continue
        clearance, along = _combat2_point_segment_distance(friendly.x, friendly.y, ax, ay, bx, by)
        if 0.07 < along < 0.94 and clearance < _polish_unit_clearance(friendly) + 0.18:
            risks.append((along, clearance, friendly))
    return min(risks, default=None, key=lambda item: item[0])


RealTimeGame.firing_lane_risk = _polish_firing_lane_risk


def _polish_mark_lane_blocked(self, unit, friendly):
    name = getattr(friendly, "display_name", friendly.role)
    unit.polish_lane_reason = f"FRIENDLY IN LANE — {name}"
    unit.polish_lane_blocked_until = self.time + 1.25
    unit.polish_wait_reason = "WAITING FOR CLEAR LANE"
    unit.polish_order_state = "UNABLE: FRIENDLY LANE"
    unit.polish_order_state_until = self.time + 1.25
    unit.next_shot = max(unit.next_shot, self.time + 0.18)


def _polish_clear_lane_state(self, unit):
    if self.time >= getattr(unit, "polish_lane_blocked_until", 0.0):
        unit.polish_lane_reason = ""
        if unit.polish_wait_reason == "WAITING FOR CLEAR LANE":
            unit.polish_wait_reason = ""


def _polish_smoke_blocks_support(self, thrower, position):
    """Avoid smoke that would blind a friendly support weapon's active lane."""
    px, py = float(position[0]), float(position[1])
    for support in self.living(thrower.faction):
        if support.uid == thrower.uid or support.role not in COMBAT2_SUPPORT_ROLES:
            continue
        if support.order not in ("fire", "suppress", "fire_lane", "overwatch"):
            continue
        target = self.get_unit(support.target_uid) if support.target_uid is not None else None
        aim = target.pos if target is not None else getattr(support, "target_pos", None)
        if aim is None and support.order in ("fire_lane", "overwatch"):
            radians = math.radians(support.facing)
            aim = (support.x + math.cos(radians) * 11, support.y + math.sin(radians) * 11)
        if aim is None:
            continue
        clearance, along = _combat2_point_segment_distance(px, py, support.x, support.y, aim[0], aim[1])
        if 0.10 < along < 0.92 and clearance < 1.7:
            return support
    return None


RealTimeGame.smoke_blocks_support = _polish_smoke_blocks_support


_polish_previous_throw_grenade = RealTimeGame.throw_grenade


def _polish_throw_grenade(self, unit, target, smoke=False, rifle=False, cook=0.0):
    if smoke:
        support = self.smoke_blocks_support(unit, target)
        if support is not None:
            unit.polish_wait_reason = "SMOKE WOULD MASK SUPPORT"
            unit.polish_order_state = "UNABLE: SUPPORT LANE"
            unit.polish_order_state_until = self.time + 1.5
            return False
    return _polish_previous_throw_grenade(self, unit, target, smoke=smoke, rifle=rifle, cook=cook)


RealTimeGame.throw_grenade = _polish_throw_grenade


def _polish_open_destination(self, unit, desired, reserved):
    desired = (
        int(clamp(round(desired[0]), 0, MAP_W - 1)),
        int(clamp(round(desired[1]), 0, MAP_H - 1)),
    )
    candidates = [desired]
    for radius in (1, 2):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) == radius:
                    candidates.append((desired[0] + dx, desired[1] + dy))
    best = None
    best_score = 9999.0
    for x, y in candidates:
        if not self.in_bounds(x, y) or (x, y) in reserved or not self.passable(x, y, unit):
            continue
        cell = self.grid[y][x]
        score = dist((x, y), desired) + self.tile_threat(unit.faction, x, y) * 0.08
        score -= TERRAIN[cell.terrain]["cover"] * 0.08
        if score < best_score:
            best, best_score = (x, y), score
    return best or desired


_polish_previous_issue_move = RealTimeGame.issue_move


def _polish_issue_move(self, units, dest, append=False, mode=None, formation="spread"):
    effective = [unit for unit in units if unit.combat_effective]
    offsets = self.formation_offsets(len(effective), formation)
    reserved = set()
    issued = []
    for unit, (offset_x, offset_y) in zip(effective, offsets):
        desired = (dest[0] + offset_x, dest[1] + offset_y)
        destination = _polish_open_destination(self, unit, desired, reserved)
        reserved.add(destination)
        signature = ("move", destination, mode or unit.move_mode, bool(append))
        same_active_order = (
            not append
            and unit.faction == "enemy"
            and signature == getattr(unit, "polish_last_order_signature", None)
            and self.time < getattr(unit, "polish_plan_commit_until", 0.0)
            and unit.order == "move"
            and (unit.path or unit.waypoints)
        )
        if same_active_order:
            unit.polish_order_state = "MOVING"
            issued.append(unit)
            continue
        _polish_previous_issue_move(
            self, [unit], destination, append=append, mode=mode, formation="line"
        )
        unit.polish_arrival_facing = angle_to(unit, dest)
        unit.polish_last_order_signature = signature
        unit.polish_last_order_at = self.time
        unit.polish_plan_commit_until = max(unit.polish_plan_commit_until, self.time + 1.15)
        unit.polish_order_state = "QUEUED" if append else "RECEIVED"
        unit.polish_order_state_until = self.time + 0.72
        unit.polish_wait_reason = ""
        issued.append(unit)
    return issued


RealTimeGame.issue_move = _polish_issue_move


_polish_previous_issue_fire = RealTimeGame.issue_fire


def _polish_issue_fire(self, unit, target, mode="normal"):
    if unit.faction == "enemy" and target.uid != getattr(unit, "target_uid", None):
        current = self.get_unit(getattr(unit, "target_uid", None))
        if (
            self.time < getattr(unit, "polish_target_lock_until", 0.0)
            and current is not None
            and current.combat_effective
            and self.can_see(unit, current)
            and dist(unit, current) <= unit.weapon["range"]
        ):
            target = current
    risk = self.firing_lane_risk(unit, target.pos, target.uid)
    if risk is not None and unit.faction == "enemy":
        enemy_faction = "player" if unit.faction == "enemy" else "enemy"
        alternatives = [
            candidate for candidate in self.living(enemy_faction)
            if candidate.uid != target.uid
            and candidate.combat_effective
            and dist(unit, candidate) <= unit.weapon["range"]
            and self.can_see(unit, candidate)
            and self.firing_lane_risk(unit, candidate.pos, candidate.uid) is None
        ]
        if alternatives:
            target = min(
                alternatives,
                key=lambda candidate: (
                    0 if candidate.role in COMBAT2_SUPPORT_ROLES else 1,
                    self.effective_cover(unit, candidate),
                    dist(unit, candidate),
                ),
            )
            risk = None
    if risk is not None:
        self._polish_mark_lane_blocked(unit, risk[2])
        return False
    result = _polish_previous_issue_fire(self, unit, target, mode)
    unit.polish_target_lock_until = self.time + (3.3 if unit.faction == "enemy" else 1.0)
    unit.polish_last_order_signature = ("fire", target.uid, mode)
    unit.polish_order_state = "ENGAGING"
    unit.polish_order_state_until = self.time + 0.8
    unit.polish_wait_reason = ""
    return result if result is not None else True


RealTimeGame.issue_fire = _polish_issue_fire


_polish_previous_suppress_area = RealTimeGame.suppress_area


def _polish_suppress_area(self, unit, position):
    risk = self.firing_lane_risk(unit, position)
    if risk is not None and unit.faction == "enemy":
        dx, dy = float(position[0]) - unit.x, float(position[1]) - unit.y
        length = max(0.001, math.hypot(dx, dy))
        normal = (-dy / length, dx / length)
        for side in (-1.0, 1.0):
            alternate = (
                clamp(float(position[0]) + normal[0] * side * 1.35, 0, MAP_W - 1),
                clamp(float(position[1]) + normal[1] * side * 1.35, 0, MAP_H - 1),
            )
            if self.firing_lane_risk(unit, alternate) is None:
                position, risk = alternate, None
                break
    if risk is not None:
        self._polish_mark_lane_blocked(unit, risk[2])
        return False
    result = _polish_previous_suppress_area(self, unit, position)
    unit.polish_last_order_signature = ("suppress", round(position[0], 1), round(position[1], 1))
    unit.polish_order_state = "SUPPRESSING"
    unit.polish_order_state_until = self.time + 0.8
    unit.polish_target_lock_until = self.time + 2.7
    return result if result is not None else True


RealTimeGame.suppress_area = _polish_suppress_area


_polish_previous_fire_interval = RealTimeGame.fire_interval


def _polish_fire_interval(self, unit):
    interval = _polish_previous_fire_interval(self, unit)
    return interval * combat_polish_weapon_profile(unit)["cadence"]


RealTimeGame.fire_interval = _polish_fire_interval


_polish_previous_hit_chance = RealTimeGame.hit_chance


def _polish_hit_chance(self, attacker, target, mode=None, reaction=False):
    chance = _polish_previous_hit_chance(self, attacker, target, mode=mode, reaction=reaction)
    if chance <= 0:
        return chance
    distance = dist(attacker, target)
    close_bonus = 8.0 if distance < 3.0 else 3.5 if distance < 5.5 else 0.0
    recoil_penalty = clamp(float(getattr(attacker, "polish_recoil", 0.0)), 0.0, 19.0)
    return clamp(chance + close_bonus - recoil_penalty, 2, 97)


RealTimeGame.hit_chance = _polish_hit_chance


def _polish_trigger_ready(self, unit, suppressive=False):
    if self.time < getattr(unit, "polish_burst_pause_until", 0.0):
        unit.next_shot = max(unit.next_shot, unit.polish_burst_pause_until)
        return False
    if getattr(unit, "polish_burst_remaining", 0) <= 0:
        profile = combat_polish_weapon_profile(unit)
        low, high = profile["burst"]
        if unit.fire_mode == "aimed":
            high = low = 1
        elif unit.fire_mode == "rapid":
            low, high = low + 1, high + 2
        if suppressive and unit.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman"):
            low, high = low + 1, high + 2
        unit.polish_burst_remaining = self.rng.randint(int(low), int(high))
    return True


RealTimeGame.polish_trigger_ready = _polish_trigger_ready


_polish_previous_commit_weapon_discharge = _combat2_commit_weapon_discharge


def _combat2_commit_weapon_discharge(self, attacker, reaction=False):
    _polish_previous_commit_weapon_discharge(self, attacker, reaction=reaction)
    profile = combat_polish_weapon_profile(attacker)
    attacker.polish_recoil = clamp(
        attacker.polish_recoil + profile["recoil"] * (0.72 if attacker.stance == "prone" else 1.0),
        0.0,
        24.0,
    )
    attacker.polish_burst_remaining = max(0, attacker.polish_burst_remaining - 1)
    if attacker.polish_burst_remaining == 0:
        low, high = profile["pause"]
        pause = self.rng.uniform(low, high)
        if attacker.fire_mode == "rapid":
            pause *= 0.76
        attacker.polish_burst_pause_until = self.time + pause
        attacker.next_shot = max(attacker.next_shot, attacker.polish_burst_pause_until)


_polish_previous_perform_shot = RealTimeGame.perform_shot


def _polish_perform_shot(self, attacker, target, reaction=False):
    risk = self.firing_lane_risk(attacker, target.pos, target.uid)
    if risk is not None:
        self._polish_mark_lane_blocked(attacker, risk[2])
        return
    if not self.polish_trigger_ready(attacker):
        return
    ammo_before = attacker.ammo
    result = _polish_previous_perform_shot(self, attacker, target, reaction=reaction)
    if attacker.ammo < ammo_before:
        attacker.polish_order_state = "FIRING"
        attacker.polish_order_state_until = self.time + 0.32
    return result


RealTimeGame.perform_shot = _polish_perform_shot


_polish_previous_perform_suppressive = RealTimeGame.perform_suppressive_shot


def _polish_perform_suppressive(self, unit):
    if unit.target_pos:
        risk = self.firing_lane_risk(unit, unit.target_pos)
        if risk is not None:
            self._polish_mark_lane_blocked(unit, risk[2])
            return
    if not self.polish_trigger_ready(unit, suppressive=True):
        return
    return _polish_previous_perform_suppressive(self, unit)


RealTimeGame.perform_suppressive_shot = _polish_perform_suppressive


_polish_previous_apply_near_miss = RealTimeGame._combat2_apply_near_miss


def _polish_apply_near_miss(self, projectile, unit, distance_to_path):
    already_suppressed = unit.uid in projectile.suppressed_uids
    result = _polish_previous_apply_near_miss(self, projectile, unit, distance_to_path)
    if already_suppressed:
        return result
    if unit.polish_reaction_stance is None:
        unit.polish_reaction_stance = unit.stance
    severity = clamp((0.92 - distance_to_path) / 0.92 + unit.suppression / 130.0, 0.0, 1.7)
    if severity >= 1.05 or unit.suppression >= 78:
        unit.polish_reaction_kind = "PINNED"
        unit.stance = "prone"
        duration = 1.15
        unit.combat2_exposed_until = min(unit.combat2_exposed_until, self.time + 0.12)
    elif severity >= 0.58:
        unit.polish_reaction_kind = "DUCK"
        if unit.stance == "standing":
            unit.stance = "crouched"
        duration = 0.72
    else:
        unit.polish_reaction_kind = "FLINCH"
        duration = 0.36
    unit.polish_reaction_until = max(unit.polish_reaction_until, self.time + duration)
    unit.command_delay_until = max(unit.command_delay_until, self.time + duration * 0.32)
    source = self.get_unit(projectile.shooter_uid)
    if source is not None:
        unit.facing = angle_to(unit, source)
    if distance_to_path <= 0.82:
        self.emit(
            "near_miss",
            pos=unit.pos,
            faction=projectile.faction,
            victim_faction=unit.faction,
            weapon=projectile.weapon_name,
            proximity=round(distance_to_path, 3),
        )
    return result


RealTimeGame._combat2_apply_near_miss = _polish_apply_near_miss


_polish_previous_apply_wound = RealTimeGame.apply_ballistic_wound


def _polish_apply_wound(self, target, damage, projectile):
    if projectile.traveled < 3.2:
        damage *= 1.14
    result = _polish_previous_apply_wound(self, target, damage, projectile)
    target.polish_reaction_kind = "HIT"
    target.polish_reaction_until = max(target.polish_reaction_until, self.time + 1.1)
    target.polish_order_state = "WOUNDED"
    target.polish_order_state_until = self.time + 1.5
    return result


RealTimeGame.apply_ballistic_wound = _polish_apply_wound


_polish_previous_terrain_collision = RealTimeGame.combat2_terrain_collision


def _polish_terrain_collision(self, projectile, x, y):
    impact_count = len(self.impacts)
    stopped = _polish_previous_terrain_collision(self, projectile, x, y)
    if len(self.impacts) > impact_count and self.time - self.polish_last_impact_event_at >= 0.035:
        self.polish_last_impact_event_at = self.time
        self.emit(
            "impact",
            pos=(projectile.x, projectile.y),
            faction=projectile.faction,
            material=self.impacts[-1].kind,
            weapon=projectile.weapon_name,
        )
    return stopped


RealTimeGame.combat2_terrain_collision = _polish_terrain_collision


_polish_previous_update_ballistics = RealTimeGame.update_ballistic_rounds


def _polish_update_ballistics(self, dt):
    before = {
        round_state.round_id: (round_state.x, round_state.y, round_state.faction)
        for round_state in self.ballistic_rounds
    }
    result = _polish_previous_update_ballistics(self, dt)
    now = self.time
    for round_state in self.ballistic_rounds:
        previous = before.get(round_state.round_id)
        if previous is None:
            continue
        start_x, start_y, faction = previous
        if dist((start_x, start_y), (round_state.x, round_state.y)) > 0.02:
            self.polish_recent_tracers.append(
                (start_x, start_y, round_state.x, round_state.y, faction, now + 0.14)
            )
    self.polish_recent_tracers = [segment for segment in self.polish_recent_tracers[-180:] if segment[5] > now]
    return result


RealTimeGame.update_ballistic_rounds = _polish_update_ballistics


_polish_previous_toggle_deploy = RealTimeGame.toggle_deploy


def _polish_toggle_deploy(self, unit):
    if unit.faction == "enemy" and self.time < unit.polish_deploy_lock_until:
        return False
    was_deployed = bool(unit.deployed)
    result = _polish_previous_toggle_deploy(self, unit)
    if bool(unit.deployed) != was_deployed or unit.order in ("deploy", "pack"):
        unit.polish_deploy_lock_until = self.time + 3.0
        unit.polish_plan_commit_until = max(unit.polish_plan_commit_until, self.time + 2.4)
        unit.polish_order_state = "DEPLOYING" if not was_deployed else "PACKING"
        unit.polish_order_state_until = self.time + 1.2
    return result


RealTimeGame.toggle_deploy = _polish_toggle_deploy


_polish_previous_plan_squads = RealTimeGame.plan_combat2_squads


def _polish_plan_squads(self, force=False):
    old_plans = dict(getattr(self, "combat2_tactical_plans", {}))
    result = _polish_previous_plan_squads(self, force=force)
    for squad_id, plan in list(self.combat2_tactical_plans.items()):
        old = old_plans.get(squad_id)
        committed_until = self.polish_plan_commits.get(squad_id, -1.0)
        if old and self.time < committed_until and old.get("phase") != plan.get("phase"):
            for key in ("phase", "flank", "target", "target_uid"):
                plan[key] = old.get(key, plan.get(key))
        elif old is None or old.get("phase") != plan.get("phase"):
            self.polish_plan_commits[squad_id] = self.time + 3.6
        # Give every squad a stable, slightly different lateral lane.  This is
        # deliberately small so the existing terrain-aware route remains king.
        if plan.get("offensive") and plan.get("flank"):
            flank_x, flank_y = plan["flank"]
            lane = ((int(squad_id) * 37) % 5 - 2) * 0.42
            plan["flank"] = (
                clamp(flank_x, 1, MAP_W - 2),
                clamp(flank_y + lane, 1, MAP_H - 2),
            )
        for unit in self.living("enemy"):
            if max(1, int(getattr(unit, "squad_id", 1))) == squad_id:
                unit.combat2_phase = plan.get("phase", unit.combat2_phase)
                unit.combat2_flank = plan.get("flank", unit.combat2_flank)
    return result


RealTimeGame.plan_combat2_squads = _polish_plan_squads


_polish_previous_ai_decide = RealTimeGame.ai_decide


def _polish_ai_decide(self, unit):
    preparation_crisis = (
        unit.suppression >= 75 or unit.morale < 32 or unit.jammed or unit.ammo <= 0
    )
    if (
        unit.faction == "enemy"
        and self.time < self.polish_preparation_until
        and not preparation_crisis
    ):
        unit.combat2_decision_reason = "holding during the preparation beat"
        return
    if unit.faction == "enemy":
        wound_load = max(
            float(getattr(unit, "wound_head", 0.0)),
            float(getattr(unit, "wound_torso", 0.0)),
            float(getattr(unit, "wound_arm", 0.0)),
            float(getattr(unit, "wound_leg", 0.0)),
        )
        depleted = unit.ammo <= 0 and not unit.magazines
        specialist = unit.role in COMBAT2_SUPPORT_ROLES or unit.role in COMBAT2_SUSTAINMENT_ROLES
        if specialist and (wound_load >= 58 or depleted) and unit.order != "move":
            destination = self.find_nearby_cover(unit, 6)
            if destination and destination != unit.tile:
                self.issue_move([unit], destination, mode="safe", formation="column")
                unit.combat2_decision_reason = "withdrawing a depleted specialist into cover"
                return
        crisis = unit.suppression >= 78 or unit.morale < 30 or unit.jammed or unit.ammo <= 0
        if (
            not crisis
            and self.time < unit.polish_plan_commit_until
            and unit.order in COMBAT_POLISH_COMMIT_ORDERS
            and (unit.order != "move" or unit.path or unit.waypoints)
        ):
            return
    before = (
        unit.order,
        tuple(unit.waypoints),
        unit.target_uid,
        bool(unit.deployed),
    )
    result = _polish_previous_ai_decide(self, unit)
    after = (
        unit.order,
        tuple(unit.waypoints),
        unit.target_uid,
        bool(unit.deployed),
    )
    if unit.faction == "enemy" and after != before:
        duration = 2.4 if unit.order in ("deploy", "pack") else 1.45 if unit.order == "move" else 0.92
        unit.polish_plan_commit_until = max(unit.polish_plan_commit_until, self.time + duration)
    return result


RealTimeGame.ai_decide = _polish_ai_decide


if hasattr(RealTimeGame, "update_defense_attack_orders"):
    _polish_previous_defense_orders = RealTimeGame.update_defense_attack_orders

    def _polish_update_defense_attack_orders(self, dt):
        if self.time < self.polish_preparation_until:
            return
        return _polish_previous_defense_orders(self, dt)

    RealTimeGame.update_defense_attack_orders = _polish_update_defense_attack_orders


def _polish_update_unit_state(self, unit, dt):
    recovery = 8.5 if unit.order in ("fire", "suppress") else 13.0
    if unit.stance == "prone":
        recovery *= 1.28
    unit.polish_recoil = max(0.0, unit.polish_recoil - recovery * dt)
    self._polish_clear_lane_state(unit)

    if self.time >= unit.polish_reaction_until and unit.polish_reaction_kind:
        if unit.polish_reaction_stance is not None and unit.suppression < 38 and unit.order != "fire":
            unit.stance = unit.polish_reaction_stance
        unit.polish_reaction_stance = None
        unit.polish_reaction_kind = ""

    if unit.order == "move":
        moved = dist(unit.pos, unit.polish_last_progress_pos)
        if moved >= 0.28:
            unit.polish_last_progress_pos = unit.pos
            unit.polish_last_progress_at = self.time
            unit.polish_order_state = "MOVING"
        elif self.time - unit.polish_last_progress_at > 4.8:
            unit.polish_wait_reason = "ROUTE BLOCKED"
            unit.polish_order_state = "DELAYED: ROUTE"
            if unit.faction == "enemy":
                unit.path = []
                unit.waypoints = []
                unit.order = "idle"
                unit.polish_plan_commit_until = 0.0
                unit.last_ai = -99.0
            unit.polish_last_progress_at = self.time
    elif unit.polish_order_state == "MOVING":
        unit.facing = unit.polish_arrival_facing
        unit.polish_order_state = "IN POSITION"
        unit.polish_order_state_until = self.time + 1.0
        unit.polish_wait_reason = ""

    if self.time >= unit.polish_order_state_until:
        if unit.order == "fire":
            unit.polish_order_state = "ENGAGING"
        elif unit.order == "suppress":
            unit.polish_order_state = "SUPPRESSING"
        elif unit.order == "move":
            unit.polish_order_state = "MOVING"
        elif not unit.polish_wait_reason:
            unit.polish_order_state = "READY"


RealTimeGame._polish_clear_lane_state = _polish_clear_lane_state
RealTimeGame._polish_mark_lane_blocked = _polish_mark_lane_blocked
RealTimeGame.update_polish_unit_state = _polish_update_unit_state


def _polish_update_engagement_state(self, dt):
    visible_contact = any(
        unit.combat_effective and self.visible_to("player", unit)
        for unit in self.living("enemy")
    )
    pressure = min(1.0, len(self.ballistic_rounds) / 10.0 + self.combat_intensity / 110.0)
    if visible_contact or pressure > 0.12:
        self.polish_contact_pressure = min(3.0, self.polish_contact_pressure + dt * (0.8 + pressure))
    else:
        self.polish_contact_pressure = max(0.0, self.polish_contact_pressure - dt * 0.7)
    self.polish_peak_intensity = max(self.polish_peak_intensity, self.combat_intensity)
    if self.time < self.polish_preparation_until:
        state = "PREPARATION"
    elif self.victory or self.defeat:
        state = "SECURED" if self.victory else "BROKEN"
    elif self.combat_intensity >= 52 or self.polish_contact_pressure >= 2.1:
        state = "ENGAGEMENT"
    elif self.polish_contact_pressure >= 0.72:
        state = "CONTACT"
    else:
        state = "MANOEUVRE"
    if state != self.polish_engagement_state:
        self.polish_engagement_state = state
        self.polish_engagement_changed_at = self.time


RealTimeGame.update_polish_engagement_state = _polish_update_engagement_state


_polish_previous_update = RealTimeGame.update


def _polish_update(self, dt):
    result = _polish_previous_update(self, dt)
    if getattr(self, "network_replica", False):
        return result
    if not self.paused:
        for unit in self.units:
            if unit.alive:
                self.update_polish_unit_state(unit, dt)
        self.update_polish_engagement_state(dt)
    return result


RealTimeGame.update = _polish_update


# Replicate only presentation-relevant intent.  Decision locks remain server
# internal; clients need the reaction/order state to draw the same battle.
if "NETWORK_UNIT_FIELDS" in globals():
    NETWORK_UNIT_FIELDS = tuple(NETWORK_UNIT_FIELDS) + tuple(
        field_name for field_name in (
            "polish_recoil", "polish_reaction_until", "polish_reaction_kind",
            "polish_order_state", "polish_order_state_until", "polish_lane_reason",
            "polish_lane_blocked_until", "polish_wait_reason", "polish_arrival_facing",
        ) if field_name not in NETWORK_UNIT_FIELDS
    )


if "serialize_network_snapshot" in globals():
    _polish_previous_serialize_snapshot = serialize_network_snapshot

    def serialize_network_snapshot(game, perspective):
        snapshot = _polish_previous_serialize_snapshot(game, perspective)
        snapshot["polish_tracers"] = [
            [
                round(start_x, 3), round(start_y, 3), round(end_x, 3), round(end_y, 3),
                "player" if faction == perspective else "enemy",
                round(max(0.0, expires - game.time), 4),
            ]
            for start_x, start_y, end_x, end_y, faction, expires
            in getattr(game, "polish_recent_tracers", [])[-96:]
            if expires > game.time and (
                _network_effect_observed(game, perspective, (start_x, start_y), 16.0)
                or _network_effect_observed(game, perspective, (end_x, end_y), 16.0)
            )
        ]
        return snapshot


    _polish_previous_apply_snapshot = apply_network_snapshot

    def apply_network_snapshot(game, snapshot):
        _polish_previous_apply_snapshot(game, snapshot)
        game.polish_recent_tracers = [
            (
                float(record[0]), float(record[1]), float(record[2]), float(record[3]),
                str(record[4]), game.time + float(record[5]),
            )
            for record in snapshot.get("polish_tracers", [])
            if isinstance(record, list) and len(record) >= 6
        ]


if "apply_network_command" in globals():
    _polish_previous_apply_network_command = apply_network_command

    def apply_network_command(game, faction, message):
        accepted, reason = _polish_previous_apply_network_command(game, faction, message)
        if accepted and str(message.get("action", "")) in ("fire", "suppress"):
            units = _network_owned_units(game, faction, message.get("units", []))
            if units and all(
                game.time < getattr(unit, "polish_lane_blocked_until", 0.0)
                for unit in units
            ):
                return False, "Friendly firing lane blocked"
        return accepted, reason


_polish_previous_audio_mix = presentation_audio_mix


def presentation_audio_mix(event, distance, intensity=0.0):
    layers = list(_polish_previous_audio_mix(event, distance, intensity))
    kind = str(event.get("type", ""))
    near = clamp(1.0 - float(distance) / 34.0, 0.0, 1.0)
    if kind == "near_miss":
        proximity = clamp(1.0 - float(event.get("proximity", 0.5)) / 0.92, 0.0, 1.0)
        layers.extend((("crack", 0.16 + proximity * 0.20), ("distant", 0.035 * near)))
    elif kind == "impact":
        material = str(event.get("material", "dirt"))
        if material == "metal":
            layers.extend((("mechanical", 0.13 * near), ("crack", 0.07 * near)))
        elif material in ("cover", "body"):
            layers.append(("debris", 0.12 * near))
        else:
            layers.append(("debris", 0.07 * near))
    # Stable micro-variation prevents stacked identical samples from phasing.
    position = event.get("pos") or (0.0, 0.0)
    variation = 0.94 + (abs(math.sin(float(position[0]) * 1.73 + float(position[1]) * 2.11)) * 0.10)
    combined = {}
    for name, volume in layers:
        combined[name] = clamp(combined.get(name, 0.0) + volume * variation, 0.0, 0.75)
    return [(name, volume) for name, volume in combined.items() if volume > 0.005]


_polish_previous_app_init = KillZoneApp.__init__


def _polish_app_init(self):
    self.camera_shake_enabled = True
    self.edge_scroll_enabled = True
    self.polish_camera_target = None
    self.polish_result_seen_at = None
    self.polish_result_game = None
    self.polish_last_frame_at = time.perf_counter()
    self._polish_shot_window = []
    _polish_previous_app_init(self)


KillZoneApp.__init__ = _polish_app_init


_polish_previous_start_battle = KillZoneApp.start_battle


def _polish_start_battle(self, *args, **kwargs):
    self.polish_camera_target = None
    self.polish_result_seen_at = None
    self.polish_result_game = None
    return _polish_previous_start_battle(self, *args, **kwargs)


KillZoneApp.start_battle = _polish_start_battle


if "PERSISTED_SETTING_DEFAULTS" in globals():
    PERSISTED_SETTING_DEFAULTS.update(
        {"camera_shake_enabled": True, "edge_scroll_enabled": True}
    )


_polish_previous_apply_settings = apply_user_settings


def apply_user_settings(app, values):
    changed = _polish_previous_apply_settings(app, values)
    if isinstance(values, dict):
        for key in ("camera_shake_enabled", "edge_scroll_enabled"):
            if isinstance(values.get(key), bool):
                setattr(app, key, values[key])
                changed = True
    return changed


_polish_previous_settings_rects = KillZoneApp.settings_rects


def _polish_settings_rects(self):
    rects = dict(_polish_previous_settings_rects(self))
    center = WINDOW_W // 2
    rects["shake"] = pygame.Rect(center - 190, 562, 380, 34)
    rects["edge"] = pygame.Rect(center - 190, 602, 380, 34)
    rects["back"] = pygame.Rect(center - 150, 676, 300, 42)
    return rects


KillZoneApp.settings_rects = _polish_settings_rects


_polish_previous_draw_settings = KillZoneApp.draw_settings


def _polish_draw_settings(self):
    _polish_previous_draw_settings(self)
    rects = self.settings_rects()
    self.button(
        rects["shake"],
        f"CAMERA SHAKE: {'ON' if self.camera_shake_enabled else 'OFF'}",
        self.mouse,
        accent=self.camera_shake_enabled,
    )
    self.button(
        rects["edge"],
        f"EDGE SCROLL: {'ON' if self.edge_scroll_enabled else 'OFF'}",
        self.mouse,
        accent=self.edge_scroll_enabled,
    )


KillZoneApp.draw_settings = _polish_draw_settings


_polish_previous_handle_settings = KillZoneApp.handle_settings_event


def _polish_handle_settings(self, event):
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        rects = self.settings_rects()
        if rects["shake"].collidepoint(event.pos):
            self.camera_shake_enabled = not self.camera_shake_enabled
            save_user_settings(self)
            return
        if rects["edge"].collidepoint(event.pos):
            self.edge_scroll_enabled = not self.edge_scroll_enabled
            save_user_settings(self)
            return
    return _polish_previous_handle_settings(self, event)


KillZoneApp.handle_settings_event = _polish_handle_settings


_polish_previous_focus_selected = KillZoneApp.focus_selected


def _polish_focus_selected(self):
    units = self.selected_units()
    if not units:
        return
    center_x = sum(unit.x for unit in units) / len(units)
    center_y = sum(unit.y for unit in units) / len(units)
    self.polish_camera_target = (
        center_x - (MAP_VIEW_W_PX / self.tile_px) / 2,
        center_y - (MAP_VIEW_H_PX / self.tile_px) / 2,
    )


KillZoneApp.focus_selected = _polish_focus_selected


def _polish_update_camera(self, dt):
    if self.state not in ("game", "deployment"):
        return
    keys = pygame.key.get_pressed()
    speed = 13 * dt / max(0.72, self.zoom)
    manual = False
    if keys[pygame.K_LEFT]:
        self.camera_x -= speed; manual = True
    if keys[pygame.K_RIGHT]:
        self.camera_x += speed; manual = True
    if keys[pygame.K_UP]:
        self.camera_y -= speed; manual = True
    if keys[pygame.K_DOWN]:
        self.camera_y += speed; manual = True
    mouse_x, mouse_y = self.mouse
    map_rect = self.map_view_rect()
    if self.edge_scroll_enabled and map_rect.collidepoint(self.mouse) and not self.drag_start:
        edge = 8
        if mouse_x < map_rect.left + edge:
            self.camera_x -= speed * 0.7; manual = True
        elif mouse_x > map_rect.right - edge:
            self.camera_x += speed * 0.7; manual = True
        if mouse_y < map_rect.top + edge:
            self.camera_y -= speed * 0.7; manual = True
        elif mouse_y > map_rect.bottom - edge:
            self.camera_y += speed * 0.7; manual = True
    if manual or self.camera_drag:
        self.polish_camera_target = None
    elif self.polish_camera_target is not None:
        target_x, target_y = self.polish_camera_target
        blend = 1.0 - math.exp(-max(0.0, dt) * 8.5)
        self.camera_x += (target_x - self.camera_x) * blend
        self.camera_y += (target_y - self.camera_y) * blend
        if abs(target_x - self.camera_x) + abs(target_y - self.camera_y) < 0.02:
            self.camera_x, self.camera_y = target_x, target_y
            self.polish_camera_target = None
    self.clamp_camera()


KillZoneApp.update_camera = _polish_update_camera


_polish_previous_play_event = KillZoneApp.play_event


def _polish_play_event(self, event):
    previous_shake = (self.shake_until, self.shake_strength)
    result = _polish_previous_play_event(self, event)
    if not self.camera_shake_enabled:
        self.shake_until, self.shake_strength = previous_shake
    now = time.perf_counter()
    if event.get("type") == "shot":
        self._polish_shot_window.append(now)
        self._polish_shot_window = [stamp for stamp in self._polish_shot_window if now - stamp <= 0.8]
        if len(self._polish_shot_window) >= 11:
            self._presentation_duck_until = max(self._presentation_duck_until, now + 0.16)
    return result


KillZoneApp.play_event = _polish_play_event


_polish_previous_issue_context = KillZoneApp.issue_context_command


def _polish_issue_context(self, cell, append=False):
    units = list(self.selected_units())
    result = _polish_previous_issue_context(self, cell, append=append)
    blocked = [
        unit for unit in units
        if self.game.time < getattr(unit, "polish_lane_blocked_until", 0.0)
    ]
    if blocked:
        _qol_notify(
            self,
            f"{len(blocked)} unit{'s' if len(blocked) != 1 else ''} waiting for a clear friendly lane",
            kind="danger",
            duration=2.0,
        )
    return result


KillZoneApp.issue_context_command = _polish_issue_context


_polish_previous_status_badge = battlefield_status_badge


def battlefield_status_badge(unit, game_time=0.0):
    if game_time < getattr(unit, "polish_lane_blocked_until", 0.0):
        return "LANE", "danger"
    reaction = getattr(unit, "polish_reaction_kind", "")
    if game_time < getattr(unit, "polish_reaction_until", 0.0) and reaction:
        return ("PIN" if reaction == "PINNED" else reaction), "suppression" if reaction != "HIT" else "danger"
    return _polish_previous_status_badge(unit, game_time)


_polish_previous_tooltip_lines = unit_card_tooltip_lines


def unit_card_tooltip_lines(unit):
    lines = list(_polish_previous_tooltip_lines(unit))
    state = str(getattr(unit, "polish_order_state", "READY"))
    lines.append(f"ORDER  {state}")
    lane = str(getattr(unit, "polish_lane_reason", ""))
    wait = str(getattr(unit, "polish_wait_reason", ""))
    if lane:
        lines.append(f"SAFETY  {lane}")
    elif wait:
        lines.append(f"WAIT  {wait}")
    return lines


_polish_previous_draw_unit = KillZoneApp.draw_unit


def _polish_draw_unit(self, unit):
    _polish_previous_draw_unit(self, unit)
    if not unit.combat_effective:
        return
    center = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(30, 30).collidepoint(center):
        return
    if self.game.time < getattr(unit, "polish_reaction_until", 0.0):
        radians = math.radians(unit.facing)
        direction = (math.cos(radians), math.sin(radians))
        base = (center[0] - round(direction[0] * 17), center[1] - round(direction[1] * 17))
        tip = (center[0] - round(direction[0] * 26), center[1] - round(direction[1] * 26))
        pygame.draw.line(self.screen, COLORS["suppression"], base, tip, 2)
    if unit.uid in self.selected and self.game.time < getattr(unit, "polish_lane_blocked_until", 0.0):
        radius = max(15, int(self.tile_px * 0.6))
        pygame.draw.circle(self.screen, COLORS["danger"], center, radius, 2)
        pygame.draw.line(
            self.screen, COLORS["danger"],
            (center[0] - radius + 3, center[1] + radius - 3),
            (center[0] + radius - 3, center[1] - radius + 3), 2,
        )


KillZoneApp.draw_unit = _polish_draw_unit


_polish_previous_draw_map = KillZoneApp.draw_map


def _polish_draw_map(self):
    _polish_previous_draw_map(self)
    if self.state not in ("game", "deployment"):
        return
    map_rect = self.map_view_rect()
    for start_x, start_y, end_x, end_y, faction, expires in getattr(self.game, "polish_recent_tracers", [])[-90:]:
        if expires <= self.game.time:
            continue
        start = self.world_to_screen(start_x, start_y)
        end = self.world_to_screen(end_x, end_y)
        clipped = map_rect.clipline(start, end)
        if clipped:
            color = (151, 220, 232) if faction == "player" else (238, 133, 72)
            pygame.draw.line(self.screen, color, clipped[0], clipped[1], 1)
    age = self.game.time - getattr(self.game, "polish_engagement_changed_at", -99.0)
    if 0 <= age <= 2.2:
        label = self.game.polish_engagement_state
        alpha_color = "danger" if label in ("ENGAGEMENT", "BROKEN") else "objective"
        surface = self.cached_text_surface(label, 11, alpha_color)
        panel = pygame.Rect(map_rect.centerx - surface.get_width() // 2 - 12, map_rect.top + 8, surface.get_width() + 24, 22)
        pygame.draw.rect(self.screen, (25, 28, 24), panel, border_radius=3)
        pygame.draw.rect(self.screen, COLORS[alpha_color], panel, 1, border_radius=3)
        self.screen.blit(surface, (panel.centerx - surface.get_width() // 2, panel.centery - surface.get_height() // 2))


KillZoneApp.draw_map = _polish_draw_map


_polish_previous_draw_after_action = KillZoneApp.draw_after_action


def _polish_draw_after_action(self):
    now = time.perf_counter()
    game_identity = id(self.game)
    if self.polish_result_game != game_identity:
        self.polish_result_game = game_identity
        self.polish_result_seen_at = None
    if self.polish_result_seen_at is None:
        self.polish_result_seen_at = now
    if now - self.polish_result_seen_at < 0.9:
        return
    result = _polish_previous_draw_after_action(self)
    width = 760
    x = MAP_X + (MAP_VIEW_W_PX - width) // 2
    y = MAP_Y + 35
    state = getattr(self.game, "polish_engagement_state", "COMPLETE")
    peak = getattr(self.game, "polish_peak_intensity", 0.0)
    self.text(f"FINAL STATE {state}   ·   PEAK COMBAT INTENSITY {peak:.0f}", (x + 24, y + 72), 9, "muted")
    return result


KillZoneApp.draw_after_action = _polish_draw_after_action
