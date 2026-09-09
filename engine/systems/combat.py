"""Systems / combat for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _combat2_point_segment_distance
from engine.rules import _combat2_target_radius
from engine.rules import _combat2_wound_penalties
from engine.rules import _polish_unit_clearance
from engine.rules import angle_diff
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import combat_polish_weapon_profile
from engine.rules import dist
from engine.rules import unit_is_firing_while_moving
from engine.spatial import SpatialGrid
from engine.definitions import COMBAT2_SUPPORT_ROLES
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MOVING_FIRE_ACCURACY_PENALTY
from engine.definitions import MOVING_FIRE_EXCLUDED_ROLES
from engine.definitions import TERRAIN
from engine.models import BallisticRound
from engine.models import BloodDecal
from engine.models import DustPuff
from engine.models import Explosion
from engine.models import Impact
from engine.models import Tracer
from engine.models import Unit
from typing import Optional
from typing import Tuple
import math


class CombatSystem:
    def crossfire_pressure(self, target: Unit) -> float:
        """0..1 pressure from recent fire arriving from meaningfully different bearings."""
        target.incoming_bearings = [
            (a, t) for a, t in target.incoming_bearings if self.time - t <= 3.2
        ]
        if len(target.incoming_bearings) < 2:
            return 0.0
        angles = [a for a, _ in target.incoming_bearings]
        spread = max((angle_diff(a, b) for a in angles for b in angles), default=0.0)
        if spread < 45:
            return 0.0
        return clamp((spread - 45) / 105, 0, 1)

    def queue_fire(self, u: Unit, target_uid: int, mode: str = "normal"):
        u.command_queue.append(("fire", (target_uid, mode)))

    def _base_fire_interval(self, u: Unit) -> float:
        rpm = u.weapon["rpm"]
        factor = 1.0
        if u.fire_mode == "rapid":
            factor = 0.62
        elif u.fire_mode == "snap":
            factor = 0.78
        elif u.fire_mode == "aimed":
            factor = 1.45
        return 60.0 / rpm * factor

    def _base_issue_fire(self, unit: Unit, target: Unit, mode="normal"):
        if not unit.combat_effective:
            return
        unit.order = "fire"
        unit.target_uid = target.uid
        unit.fire_mode = mode
        unit.overwatch = False
        unit.fire_lane = False
        unit.command_delay_until = max(
            unit.command_delay_until, self.time + unit.suppression * 0.005
        )
        unit.traverse_ready_at = max(
            unit.traverse_ready_at, self.time + self.traverse_delay(unit, target)
        )
        if mode == "aimed":
            unit.aim_progress = 0.0

    def _base_perform_shot(self, attacker: Unit, target: Unit, reaction=False):
        if not attacker.combat_effective or not target.combat_effective:
            return
        if (
            attacker.jammed
            or attacker.reload_timer > 0
            or attacker.carrying_uid is not None
        ):
            return
        if (
            self.time < attacker.command_delay_until
            or self.time < attacker.traverse_ready_at
        ):
            return
        if attacker.heat >= 100:
            attacker.order = "idle"
            self.add_log(f"{attacker.role} overheated; fire stopped.")
            return
        if attacker.ammo <= 0:
            self.start_reload(attacker)
            return
        w = attacker.weapon
        d = dist(attacker, target)
        if d > w["range"]:
            return
        attacker.facing = angle_to(attacker, target)
        chance = self.hit_chance(attacker, target, reaction=reaction)
        if chance <= 0:
            return
        attacker.ammo -= 1
        attacker.next_shot = self.time + self.fire_interval(attacker)
        attacker.signature = max(
            attacker.signature,
            55 if attacker.role in ("Machine Gunner", "HMG Crew") else 32,
        )
        attacker.aim_progress = max(0, attacker.aim_progress - 0.35)
        heat_add = w["heat"] * (1.35 if attacker.fire_mode == "rapid" else 1.0)
        attacker.heat += heat_add
        jam_p = 0.002 + max(0, attacker.heat - 75) * 0.0015
        if self.rng.random() < jam_p:
            attacker.jammed = True
            self.add_log(f"{attacker.role} weapon jammed.")
        ax, ay = attacker.pos
        bx, by = target.pos
        self.tracers.append(Tracer((ax, ay), (bx, by)))
        self.emit(
            "shot",
            weapon=attacker.weapon_name,
            pos=attacker.pos,
            faction=attacker.faction,
        )
        target.under_fire_until = self.time + 3.4
        target.last_attacker_uid = attacker.uid
        target.incoming_bearings.append((angle_to(target, attacker), self.time))
        roll = self.rng.uniform(0, 100)
        hit = roll <= chance
        supp = w["supp"] * (1.08 if hit else 0.72)
        if attacker.role in ("Machine Gunner", "HMG Crew") and attacker.deployed:
            supp *= 1.35
        cover = self.effective_cover(attacker, target)
        supp *= max(0.82, 1 - cover * 0.035)
        cross = self.crossfire_pressure(target)
        supp *= 1.0 + cross * 0.48
        target.suppression = clamp(target.suppression + supp, 0, 100)
        target.morale = clamp(target.morale - supp * (0.15 + cross * 0.08), 0, 100)
        tc = self.grid[target.tile[1]][target.tile[0]]
        tc.ground_suppression = clamp(tc.ground_suppression + supp * 0.55, 0, 100)
        self.degrade_cover(target.pos, w["damage"] * (0.34 if hit else 0.2), w["pen"])
        if hit:
            close_mult = 1.0 + max(0, 4 - d) * 0.08
            dmg = w["damage"] * close_mult * self.rng.uniform(0.8, 1.18)
            if target.casualty == "wounded":
                dmg *= 1.08
            self.apply_damage(target, dmg, attacker, "gunfire")
            self.impacts.append(Impact(target.x, target.y, "body", 0.2))
            attacker.momentum = clamp(attacker.momentum + 12, 0, 100)
            attacker.prepared = max(0, attacker.prepared - 0.32)
            if target.suppression >= 50:
                for ally in self.living(attacker.faction):
                    if dist(ally, attacker) <= 6:
                        ally.momentum = clamp(ally.momentum + 3, 0, 100)
        else:
            terrain = self.grid[target.tile[1]][target.tile[0]].terrain
            kind = (
                "metal"
                if terrain in ("wall", "bunker", "wire")
                else "cover"
                if TERRAIN[terrain]["cover"] >= 2
                else "dirt"
            )
            self.impacts.append(
                Impact(
                    target.x + self.rng.uniform(-0.25, 0.25),
                    target.y + self.rng.uniform(-0.25, 0.25),
                    kind,
                    0.18,
                )
            )
            for other in self.living(target.faction):
                if other.uid == target.uid:
                    continue
                px, py = other.pos
                vx = bx - ax
                vy = by - ay
                den = vx * vx + vy * vy
                q = (
                    0
                    if den <= 1e-08
                    else clamp(((px - ax) * vx + (py - ay) * vy) / den, 0, 1)
                )
                dd = math.hypot(px - (ax + q * vx), py - (ay + q * vy))
                if dd <= 0.75:
                    other.suppression = clamp(
                        other.suppression + supp * (0.34 if dd < 0.35 else 0.2), 0, 100
                    )
                    other.under_fire_until = self.time + 2.2
                    other.last_attacker_uid = attacker.uid

    def _base_apply_damage(
        self, target: Unit, damage: float, source: Optional[Unit], cause: str
    ):
        if not target.alive:
            return
        target.hp -= damage
        target.morale = clamp(target.morale - damage * 0.35, 0, 100)
        target.under_fire_until = self.time + 3.5
        if source:
            target.last_attacker_uid = source.uid
        self.emit("hurt", pos=target.pos, damage=damage, cause=cause)
        if damage >= 12:
            self.blood.append(
                BloodDecal(
                    target.x + self.rng.uniform(-0.18, 0.18),
                    target.y + self.rng.uniform(-0.18, 0.18),
                    clamp(damage / 85, 0.12, 0.65),
                    self.rng.randint(0, 999999),
                    1.0,
                )
            )
            self.blood = self.blood[-180:]
        if (
            target.assistant_alive
            and damage >= 30
            and (self.rng.random() < min(0.45, damage / 180))
        ):
            target.assistant_alive = False
            target.crew = max(1, target.crew - 1)
            target.morale = max(0, target.morale - 12)
            self.add_log(f"{target.faction} {target.role} lost its assistant gunner.")
        if target.hp <= 0:
            lethality = clamp((damage - 25) / 75, 0.12, 0.7)
            if self.rng.random() < lethality:
                target.casualty = "dead"
                target.hp = 0
                target.bleed = 0
                self.blood.append(
                    BloodDecal(
                        target.x,
                        target.y,
                        self.rng.uniform(0.55, 0.95),
                        self.rng.randint(0, 999999),
                        1.0,
                    )
                )
                self.emit("death", pos=target.pos, cause=cause)
                self.add_log(f"{target.faction} {target.role} killed ({cause}).")
            else:
                target.casualty = "incapacitated"
                target.hp = 0
                target.bleed = self.rng.uniform(12, 28)
                self.add_log(f"{target.faction} {target.role} incapacitated.")
            target.order = "idle"
            target.path = []
            target.waypoints = []
            for ally in self.living(target.faction):
                if ally.uid != target.uid and dist(ally, target) < 5:
                    ally.morale = max(0, ally.morale - 12)
                    ally.suppression = clamp(ally.suppression + 8, 0, 100)
        elif target.hp < target.max_hp * 0.72 and target.casualty == "healthy":
            target.casualty = "wounded"
            target.bleed = self.rng.uniform(5, 12)

    def _base_start_reload(self, u: Unit, emergency=False):
        if u.reload_timer > 0 or not u.magazines:
            return
        speed = 1.0
        if u.role in ("Machine Gunner", "HMG Crew") and u.assistant_alive:
            speed = 0.72
        wound = max(0, 1 - u.hp / max(1, u.max_hp))
        speed *= 1.0 + wound * 0.55
        if u.suppression > 60:
            speed *= 1.18
        if emergency:
            speed *= 0.68
        u.reload_emergency = emergency
        u.reload_timer = u.weapon["reload"] * speed
        u.order = "reload"

    def finish_reload(self, u: Unit, emergency=None):
        if not u.magazines:
            return
        if emergency is None:
            emergency = u.reload_emergency
        old = u.ammo
        new = u.magazines.pop(0)
        if old > 0 and (not emergency):
            u.magazines.append(old)
        u.ammo = new
        u.reload_timer = 0
        u.reload_emergency = False
        u.order = "idle"

    def should_auto_reload(self, u: Unit) -> bool:
        if (
            not u.auto_reload
            or not u.magazines
            or u.reload_timer > 0
            or (u.action_timer > 0)
            or u.jammed
        ):
            return False
        if (
            u.order
            in ("move", "rout", "medic", "deploy", "pack", "barrel", "clear_jam")
            or u.carrying_uid is not None
        ):
            return False
        if u.ammo <= 0:
            return True
        if u.role in (
            "Machine Gunner",
            "HMG Crew",
            "Automatic Rifleman",
        ) and u.order in ("idle", "overwatch", "fire_lane"):
            return u.ammo <= max(4, int(u.weapon["mag"] * 0.12))
        return False

    def set_fire_lane(self, u: Unit, center: float, width=45):
        if u.role not in ("Machine Gunner", "HMG Crew"):
            return
        if not u.deployed:
            self.toggle_deploy(u)
            return
        u.fire_lane = True
        u.overwatch = False
        u.fire_lane_center = center
        u.arc_width = width
        u.arc_range = u.weapon["range"]
        u.order = "fire_lane"

    def _base_suppress_area(self, u: Unit, pos: Tuple[float, float]):
        if u.role not in ("Machine Gunner", "HMG Crew", "Automatic Rifleman"):
            return
        u.order = "suppress"
        u.target_pos = pos
        u.target_uid = None

    def _base_throw_grenade(
        self, u: Unit, pos: Tuple[float, float], smoke=False, cook=0.0, rifle=False
    ):
        if dist(u.pos, pos) > (7 if rifle else 4.5):
            return
        if smoke:
            if u.smoke_grenades <= 0:
                return
            u.smoke_grenades -= 1
            fuse = max(0.5, 1.5 - cook)
            self.explosions.append(
                Explosion(pos[0], pos[1], fuse, 2.3, 0, 0, "SMOKE", u.faction)
            )
        elif rifle:
            if u.rifle_grenades <= 0:
                return
            u.rifle_grenades -= 1
            fuse = 0.8
            self.explosions.append(
                Explosion(pos[0], pos[1], fuse, 2.0, 62, 58, "HE", u.faction)
            )
        else:
            if u.grenades <= 0:
                return
            u.grenades -= 1
            fuse = max(0.35, 2.4 - cook)
            self.explosions.append(
                Explosion(pos[0], pos[1], fuse, 2.0, 72, 68, "HE", u.faction)
            )
        u.action_timer = 0.8
        u.signature = max(u.signature, 10)
        self.grenade_reaction(pos, u.faction)

    def grenade_reaction(self, pos, faction):
        for u in self.living():
            if not u.combat_effective or dist(u.pos, pos) > 2.5:
                continue
            if u.suppression >= 80 or u.action_timer > 0:
                continue
            if self.rng.random() < 0.68:
                ux, uy = u.tile
                candidates = []
                for nx, ny in ((ux + 1, uy), (ux - 1, uy), (ux, uy + 1), (ux, uy - 1)):
                    if self.passable(nx, ny, u):
                        candidates.append((dist((nx, ny), pos), (nx, ny)))
                if candidates:
                    _, best = max(candidates)
                    u.waypoints = [best]
                    u.path = []
                    u.order = "move"
                    u.stance = "prone"

    def _base_mortar_fire(self, u: Unit, pos: Tuple[float, float], smoke=False):
        if u.role != "Mortar Team" or not u.deployed or u.mortar_shells <= 0:
            return
        if dist(u.pos, pos) < 5 or dist(u.pos, pos) > 22:
            return
        u.mortar_shells -= 1
        u.action_timer = 3.0
        flight = 2.8 + self.rng.uniform(-0.3, 0.4)
        scatter = 1.4 if u.suppression < 40 else 2.5
        px = clamp(pos[0] + self.rng.gauss(0, scatter * 0.35), 0, MAP_W - 1)
        py = clamp(pos[1] + self.rng.gauss(0, scatter * 0.35), 0, MAP_H - 1)
        if smoke:
            self.explosions.append(
                Explosion(px, py, flight, 3.0, 0, 0, "SMOKE", u.faction)
            )
        else:
            self.explosions.append(
                Explosion(px, py, flight, 2.8, 92, 82, "HE", u.faction)
            )

    def _base_resolve_explosion(self, e: Explosion):
        self.emit("explosion", pos=(e.x, e.y), kind=e.kind, radius=e.radius)
        if e.kind == "SMOKE":
            for y in range(
                max(0, int(e.y - e.radius)), min(MAP_H, int(e.y + e.radius) + 1)
            ):
                for x in range(
                    max(0, int(e.x - e.radius)), min(MAP_W, int(e.x + e.radius) + 1)
                ):
                    d = math.hypot(x - e.x, y - e.y)
                    if d <= e.radius:
                        add = max(0, 2.9 - d * 0.34)
                        self.grid[y][x].smoke = clamp(
                            self.grid[y][x].smoke + add, 0, 5.0
                        )
            return
        for u in self.living():
            d = dist(u.pos, (e.x, e.y))
            if d <= e.radius:
                c = self.grid[u.tile[1]][u.tile[0]]
                confined = (
                    1.22 if c.terrain in ("trench", "bunker", "building") else 1.0
                )
                dmg = max(0, e.damage * (1 - d / e.radius) * confined)
                if u.stance == "prone":
                    dmg *= 0.78
                self.apply_damage(u, dmg, None, "blast")
                shock = e.suppression * (1 - d / e.radius) * confined
                u.suppression = clamp(u.suppression + shock, 0, 100)
                u.morale = clamp(u.morale - shock * 0.12, 0, 100)
                if d <= e.radius * 0.85:
                    u.disoriented_until = max(
                        u.disoriented_until, self.time + 0.7 + (1 - d / e.radius) * 1.6
                    )
                self.grid[u.tile[1]][u.tile[0]].ground_suppression = clamp(
                    self.grid[u.tile[1]][u.tile[0]].ground_suppression + shock * 0.7,
                    0,
                    100,
                )
        for y in range(
            max(0, int(e.y - e.radius)), min(MAP_H, int(e.y + e.radius) + 1)
        ):
            for x in range(
                max(0, int(e.x - e.radius)), min(MAP_W, int(e.x + e.radius) + 1)
            ):
                d = math.hypot(x - e.x, y - e.y)
                if d > e.radius:
                    continue
                c = self.grid[y][x]
                power = e.damage * (1 - d / e.radius)
                if c.hp is not None:
                    c.hp -= power
                    if c.hp <= 0:
                        if c.terrain in (
                            "wall",
                            "building",
                            "woodwall",
                            "window",
                            "bunker",
                            "sandbags",
                            "door",
                        ):
                            c.reset_terrain("rubble")
                        elif c.terrain == "wire":
                            c.reset_terrain("open")
                        elif c.terrain == "bridge":
                            c.reset_terrain("water")
                        elif c.terrain == "woods":
                            c.reset_terrain("open")
                if power > 65 and c.terrain in ("open", "mud", "road"):
                    c.reset_terrain("crater")
                if power > 105 and c.terrain == "trench" and (self.rng.random() < 0.42):
                    c.reset_terrain("rubble")
                if (
                    power > 45
                    and c.terrain in ("woods", "building")
                    and (self.rng.random() < 0.3)
                ):
                    c.fire = max(c.fire, 4.0)

    def _base_perform_suppressive_shot(self, u: Unit):
        if u.ammo <= 0:
            self.start_reload(u)
            return
        if not u.target_pos:
            return
        u.ammo -= 1
        u.next_shot = self.time + self.fire_interval(u) * 0.65
        u.heat += u.weapon["heat"] * 1.2
        u.signature = 55
        tx, ty = u.target_pos
        self.tracers.append(Tracer(u.pos, (tx, ty)))
        cx, cy = (int(round(tx)), int(round(ty)))
        if self.in_bounds(cx, cy):
            self.grid[cy][cx].ground_suppression = clamp(
                self.grid[cy][cx].ground_suppression + u.weapon["supp"] * 0.85, 0, 100
            )
            self.degrade_cover((tx, ty), u.weapon["damage"] * 0.24, u.weapon["pen"])
        for target in self.living("enemy" if u.faction == "player" else "player"):
            if dist(target.pos, (tx, ty)) <= 2.2:
                target.incoming_bearings.append((angle_to(target, u), self.time))
                cross = self.crossfire_pressure(target)
                gain = u.weapon["supp"] * (0.78 + cross * 0.32)
                target.suppression = clamp(target.suppression + gain, 0, 100)
                target.morale = clamp(
                    target.morale - u.weapon["supp"] * (0.09 + cross * 0.05), 0, 100
                )

    def update_reaction_fire(self):
        living = self.living()
        factions = {
            "player": [unit for unit in living if unit.faction == "player"],
            "enemy": [unit for unit in living if unit.faction == "enemy"],
        }
        for shooter in living:
            if (
                not shooter.combat_effective
                or shooter.jammed
                or shooter.reload_timer > 0
                or (self.time < shooter.next_shot)
            ):
                continue
            if not (shooter.overwatch or shooter.fire_lane):
                continue
            enemies = factions["enemy" if shooter.faction == "player" else "player"]
            target = None
            nearest = math.inf
            range_squared = shooter.arc_range * shooter.arc_range
            for t in enemies:
                if not t.combat_effective:
                    continue
                if not (t.order == "move" or t.signature > 6):
                    continue
                distance_squared = (shooter.x - t.x) ** 2 + (shooter.y - t.y) ** 2
                if distance_squared > range_squared:
                    continue
                if (
                    angle_diff(shooter.fire_lane_center, angle_to(shooter, t))
                    > shooter.arc_width / 2
                ):
                    continue
                if not self.can_see(shooter, t):
                    continue
                if distance_squared < nearest:
                    nearest, target = (distance_squared, t)
            if target is not None:
                if shooter.reaction_target_uid != target.uid:
                    shooter.reaction_target_uid = target.uid
                    shooter.reaction_ready_at = self.time + self.reaction_delay(
                        shooter, target
                    )
                    shooter.traverse_ready_at = max(
                        shooter.traverse_ready_at,
                        self.time + self.traverse_delay(shooter, target),
                    )
                    continue
                if (
                    self.time < shooter.reaction_ready_at
                    or self.time < shooter.traverse_ready_at
                ):
                    continue
                old = shooter.fire_mode
                shooter.fire_mode = "rapid" if shooter.fire_lane else "snap"
                self.perform_shot(shooter, target, reaction=True)
                shooter.fire_mode = old
                shooter.reaction_ready_at = (
                    self.time + self.reaction_delay(shooter, target) * 0.55
                )

    def update_explosions(self, dt):
        for e in list(self.explosions):
            e.timer -= dt
            if e.timer <= 0:
                self.resolve_explosion(e)
                self.explosions.remove(e)

    def update_autofire(self):
        for u in self.living("player"):
            if (
                not u.combat_effective
                or u.order not in ("idle", "overwatch")
                or u.jammed
                or (u.reload_timer > 0)
                or (self.time < u.next_shot)
            ):
                continue
            if u.fire_discipline == "hold":
                continue
            t = None
            if (
                u.fire_discipline == "return"
                and u.under_fire_until > self.time
                and u.last_attacker_uid
            ):
                cand = self.get_unit(u.last_attacker_uid)
                if (
                    cand
                    and cand.combat_effective
                    and self.visible_to("player", cand)
                    and self.can_see(u, cand)
                ):
                    t = cand
            elif u.fire_discipline in ("free", "confident"):
                t = self.choose_auto_target(u)
            if t:
                if u.fire_discipline == "confident" and self.hit_chance(u, t) < 60:
                    continue
                self.perform_shot(u, t, reaction=True)

    def _kz_perform_shot(self, attacker, target, reaction=False):
        before_hp = target.hp
        before_ammo = attacker.ammo
        self._base_perform_shot(attacker, target, reaction=reaction)
        if attacker.ammo < before_ammo:
            self.stats[attacker.faction]["shots"] += 1
            attacker.shots_recent = getattr(attacker, "shots_recent", 0) + 1
            attacker.last_shot_time = self.time
            if target.hp < before_hp:
                self.stats[attacker.faction]["hits"] += 1
            if len(self.tracers) > 260:
                self.tracers = self.tracers[-220:]
            if len(self.impacts) > 220:
                self.impacts = self.impacts[-180:]

    def _kz_apply_damage(self, target, damage, source, cause):
        before = target.casualty
        self._base_apply_damage(target, damage, source, cause)
        if before not in ("dead", "surrendered") and target.casualty in (
            "dead",
            "incapacitated",
        ):
            self.stats[target.faction]["casualties"] += 1
            if source:
                self.stats[source.faction]["kills"] += 1
            self._kz_event_record(
                "casualty",
                f"{target.faction} {target.role} {target.casualty}",
                target.pos,
            )

    def _kz_throw_grenade(self, u, pos, smoke=False, cook=0.0, rifle=False):
        gb = u.grenades
        sb = u.smoke_grenades
        rb = u.rifle_grenades
        self._base_throw_grenade(u, pos, smoke=smoke, cook=cook, rifle=rifle)
        if u.grenades < gb or u.rifle_grenades < rb:
            self.stats[u.faction]["grenades"] += 1
        if u.smoke_grenades < sb:
            self.stats[u.faction]["smoke"] += 1

    def resolve_explosion(self, e):
        self._base_resolve_explosion(e)
        self._kz_event_record("explosion", f"{e.kind} detonation", (e.x, e.y))
        if e.kind == "HE":
            for _ in range(min(12, max(4, int(e.radius * 4)))):
                a = self.rng.random() * math.tau
                r = self.rng.random() * e.radius * 0.75
                self.dust.append(
                    DustPuff(
                        e.x + math.cos(a) * r,
                        e.y + math.sin(a) * r,
                        self.rng.uniform(0.18, 0.48),
                        self.rng.uniform(0.35, 0.8),
                        0.8,
                    )
                )
            self.dust = self.dust[-100:]
        if e.kind == "HE":
            cx, cy = (int(round(e.x)), int(round(e.y)))
            for y in range(
                max(0, cy - int(e.radius)), min(MAP_H, cy + int(e.radius) + 1)
            ):
                for x in range(
                    max(0, cx - int(e.radius)), min(MAP_W, cx + int(e.radius) + 1)
                ):
                    if math.hypot(x - e.x, y - e.y) > e.radius:
                        continue
                    c = self.grid[y][x]
                    if (
                        c.terrain == "woods"
                        and e.damage > 55
                        and (self.rng.random() < 0.45)
                    ):
                        c.reset_terrain("open")
                    elif (
                        c.terrain in ("wall", "building", "woodwall")
                        and c.hp is not None
                        and (c.hp <= 0)
                    ):
                        c.reset_terrain("rubble")
                    elif (
                        c.terrain in ("sandbags", "firing_step")
                        and c.cover_wear > 0.82
                        and (self.rng.random() < 0.5)
                    ):
                        c.reset_terrain("rubble")

    def recrew_weapon(self, helper, crew):
        if not helper.combat_effective or dist(helper, crew) > 1.6:
            return False
        if (
            crew.role in ("Machine Gunner", "HMG Crew")
            and crew.combat_effective
            and (not crew.assistant_alive)
        ):
            crew.assistant_alive = True
            crew.crew = max(2, crew.crew)
            helper.action_timer = 1.5
            helper.order = "idle"
            self.add_log(f"{helper.role} joined {crew.role} as assistant gunner.")
            return True
        if crew.role == "HMG Crew" and crew.casualty == "incapacitated":
            helper.role = "HMG Crew"
            helper.weapon_name = "Heavy Machine Gun"
            helper.ammo = max(helper.ammo, crew.ammo)
            helper.deployed = False
            helper.assistant_alive = False
            helper.action_timer = 2.2
            self.add_log(f"{helper.faction} infantry re-crewed an abandoned HMG.")
            return True
        return False

    def mortar_fire(self, u, pos, smoke=False):
        d = dist(u, pos)
        if d < 5.0:
            self.add_log("Mortar target inside minimum range.")
            return
        if d > 19.0:
            self.add_log("Mortar target beyond effective range.")
            return
        if not u.deployed or u.mortar_shells <= 0:
            return
        key = (u.uid, int(pos[0] // 2), int(pos[1] // 2), bool(smoke))
        ranged = self._mortar_solutions.get(key, 0)
        observers = [
            a
            for a in self.living(u.faction)
            if a.role in ("Recon", "Marksman")
            and a.combat_effective
            and (dist(a, pos) < 15)
        ]
        observed = any((self.line_info(a.pos, pos)[0] for a in observers))
        sigma = max(0.35, 1.45 - ranged * 0.32 - (0.38 if observed else 0))
        aim = (
            clamp(pos[0] + self.rng.gauss(0, sigma), 1, MAP_W - 2),
            clamp(pos[1] + self.rng.gauss(0, sigma), 1, MAP_H - 2),
        )
        self._mortar_solutions[key] = min(3, ranged + 1)
        self._base_mortar_fire(u, aim, smoke=smoke)
        self._kz_event_record(
            "mortar", f"Mortar {('smoke' if smoke else 'HE')} ranging {ranged + 1}", aim
        )

    def apply_damage(self, target, damage, source, cause):
        before = target.casualty
        self._kz_apply_damage(target, damage, source, cause)
        if before != target.casualty and target.casualty in ("dead", "incapacitated"):
            self.cleanup_unit_state(target, target.casualty)
            for ally in self.living(target.faction):
                if (
                    ally.uid != target.uid
                    and ally.combat_effective
                    and (dist(ally, target) < 5)
                ):
                    ally.rally_shock = clamp(
                        getattr(ally, "rally_shock", 0) + 12, 0, 40
                    )

    def _moving_fire_can_attempt(self, unit):
        morale_state = getattr(unit, "morale_state", "STEADY")
        return bool(
            unit.combat_effective
            and unit.order == "move"
            and (unit.role not in MOVING_FIRE_EXCLUDED_ROLES)
            and (unit.fire_discipline != "hold")
            and (unit.ammo > 0)
            and (not unit.jammed)
            and (unit.reload_timer <= 0)
            and (unit.action_timer <= 0)
            and (unit.carrying_uid is None)
            and (unit.dragging_uid is None)
            and (unit.suppression < 80)
            and (morale_state not in ("PINNED", "BREAKING", "ROUTING"))
            and (unit.heat < 100)
            and (self.time >= unit.next_shot)
            and (self.time >= unit.command_delay_until)
        )

    def try_moving_fire(self, unit):
        if not self.can_attempt_moving_fire(unit):
            return False
        unit._moving_fire_active = True
        previous_mode = unit.fire_mode
        try:
            target = self.moving_fire_target(unit)
            if target is None:
                return False
            unit.fire_mode = "normal"
            if (
                unit.fire_discipline == "confident"
                and self.hit_chance(unit, target) < 60
            ):
                return False
            ammunition_before = unit.ammo
            self.perform_shot(unit, target)
            return unit.ammo < ammunition_before
        finally:
            unit.fire_mode = previous_mode
            unit._moving_fire_active = False

    def _moving_fire_hit_chance(self, attacker, target, mode=None, reaction=False):
        chance = self._kz_hit_chance(attacker, target, mode=mode, reaction=reaction)
        if chance <= 0 or not unit_is_firing_while_moving(attacker):
            return chance
        return clamp(chance - MOVING_FIRE_ACCURACY_PENALTY, 2, 96)

    def update_unit(self, unit, dt):
        moving_before = unit.order == "move"
        position_before = unit.pos
        self._perf_update_unit(unit, dt)
        if (
            moving_before
            and unit.order == "move"
            and unit.jammed
            and unit.combat_effective
            and (unit.pos == position_before)
        ):
            self.update_movement(unit, dt)
        moved = dist(position_before, unit.pos) > 1e-06
        if moving_before and moved and (unit.order == "move"):
            self.try_moving_fire(unit)

    def can_attempt_moving_fire(self, unit):
        if not self._moving_fire_can_attempt(unit):
            return False
        doctrine = self.doctrine_for(unit)
        if doctrine == "cautious":
            return unit.under_fire_until > self.time
        if doctrine == "aggressive" and unit.suppression < 86:
            return True
        return unit.suppression < 80

    def _combat2_issue_fire(self, unit, target, mode="normal"):
        changed = getattr(unit, "combat2_acquired_uid", None) != target.uid
        self._base_issue_fire(unit, target, mode)
        if changed:
            unit.combat2_acquired_uid = target.uid
            delay = self.reaction_delay(unit, target) * (
                0.66 if mode == "snap" else 0.88
            )
            unit.combat2_ready_at = max(unit.combat2_ready_at, self.time + delay)
            unit.next_shot = max(unit.next_shot, unit.combat2_ready_at)

    def spawn_ballistic_round(
        self,
        attacker,
        aim_position,
        intended_uid=None,
        reaction=False,
        suppressive=False,
    ):
        ax, ay = attacker.pos
        tx, ty = aim_position
        dx, dy = (tx - ax, ty - ay)
        length = max(0.001, math.hypot(dx, dy))
        ux, uy = (dx / length, dy / length)
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

    def _combat2_commit_weapon_discharge(self, attacker, reaction=False):
        weapon = attacker.weapon
        attacker.ammo -= 1
        attacker.next_shot = self.time + self.fire_interval(attacker)
        attacker.signature = max(
            attacker.signature,
            55 if attacker.role in ("Machine Gunner", "HMG Crew") else 32,
        )
        attacker.aim_progress = max(0, attacker.aim_progress - 0.35)
        attacker.combat2_exposed_until = self.time + (
            0.75 if attacker.stance == "prone" else 1.05
        )
        heat_add = weapon["heat"] * (1.35 if attacker.fire_mode == "rapid" else 1.0)
        attacker.heat += heat_add
        jam_probability = 0.002 + max(0, attacker.heat - 75) * 0.0015
        if self.rng.random() < jam_probability:
            attacker.jammed = True
            self.add_log(
                f"{getattr(attacker, 'display_name', attacker.role)} weapon jammed."
            )
        if hasattr(self, "stats"):
            self.stats[attacker.faction]["shots"] += 1
        attacker.shots_recent = getattr(attacker, "shots_recent", 0) + 1
        attacker.last_shot_time = self.time
        self.emit(
            "shot",
            weapon=attacker.weapon_name,
            pos=attacker.pos,
            faction=attacker.faction,
        )

    def _combat2_perform_shot(self, attacker, target, reaction=False):
        if not attacker.combat_effective or not target.combat_effective:
            return
        if (
            attacker.jammed
            or attacker.reload_timer > 0
            or attacker.carrying_uid is not None
        ):
            return
        if (
            self.time < attacker.command_delay_until
            or self.time < attacker.traverse_ready_at
        ):
            return
        if attacker.heat >= 100:
            attacker.order = "idle"
            self.add_log(
                f"{getattr(attacker, 'display_name', attacker.role)} overheated; fire stopped."
            )
            return
        if attacker.ammo <= 0:
            self.start_reload(attacker)
            return
        distance = dist(attacker, target)
        if distance > attacker.weapon["range"]:
            return
        if getattr(attacker, "combat2_acquired_uid", None) != target.uid:
            attacker.combat2_acquired_uid = target.uid
            acquisition = (
                0.0
                if getattr(attacker, "_moving_fire_active", False)
                else self.reaction_delay(attacker, target) * 0.42
            )
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
        dx, dy = (target.x - attacker.x, target.y - attacker.y)
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
            target.x + normal[0] * lateral + dx / length * depth,
            target.y + normal[1] * lateral + dy / length * depth,
        )
        self._combat2_commit_weapon_discharge_2(attacker, reaction=reaction)
        self.spawn_ballistic_round(attacker, aim, target.uid, reaction=reaction)

    def _combat2_perform_suppressive_shot(self, unit):
        if (
            not unit.combat_effective
            or unit.jammed
            or unit.reload_timer > 0
            or (unit.carrying_uid is not None)
        ):
            return
        if unit.ammo <= 0:
            self.start_reload(unit)
            return
        if (
            not unit.target_pos
            or self.time < unit.command_delay_until
            or self.time < unit.traverse_ready_at
        ):
            return
        tx, ty = unit.target_pos
        distance = dist(unit.pos, (tx, ty))
        if distance > unit.weapon["range"] * 1.05:
            return
        spread = 0.35 + distance * 0.035
        aim = (tx + self.rng.gauss(0, spread), ty + self.rng.gauss(0, spread * 0.72))
        unit.facing = angle_to(unit, aim)
        self._combat2_commit_weapon_discharge_2(unit)
        unit.next_shot = self.time + self.fire_interval(unit) * 0.65
        unit.heat += unit.weapon["heat"] * 0.2
        self.spawn_ballistic_round(unit, aim, suppressive=True)

    def _combat2_apply_wound(self, target, damage, projectile):
        roll = self.rng.random()
        if target.stance == "prone":
            thresholds = (0.15, 0.57, 0.78)
        else:
            thresholds = (0.11, 0.53, 0.77)
        if roll < thresholds[0]:
            location, multiplier = ("head", 1.55)
        elif roll < thresholds[1]:
            location, multiplier = ("torso", 1.0)
        elif roll < thresholds[2]:
            location, multiplier = ("arm", 0.67)
        else:
            location, multiplier = ("leg", 0.76)
        final_damage = damage * multiplier * self.rng.uniform(0.88, 1.12)
        severity_gain = clamp(
            final_damage * (0.86 if location == "torso" else 1.0), 4.0, 72.0
        )
        attr = f"wound_{location}"
        setattr(
            target,
            attr,
            clamp(float(getattr(target, attr, 0.0)) + severity_gain, 0.0, 100.0),
        )
        target.wound_treated = False
        if location == "head":
            target.disoriented_until = max(
                target.disoriented_until, self.time + 1.4 + severity_gain * 0.045
            )
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
        self.impacts.append(Impact(target.x, target.y, "body", 0.2))
        if hasattr(self, "stats"):
            self.stats[projectile.faction]["hits"] += 1
        if source is not None:
            source.momentum = clamp(source.momentum + 10, 0, 100)
        return (location, final_damage)

    def _combat2_update_ballistics(self, dt):
        if not self.ballistic_rounds:
            self.combat2_last_projectile_count = 0
            return
        if not hasattr(self, "_ballistic_spatial"):
            self._ballistic_spatial = SpatialGrid()
        self._ballistic_spatial.rebuild(self.living())
        max_step = 0.18
        for projectile in list(self.ballistic_rounds):
            speed = max(0.001, math.hypot(projectile.vx, projectile.vy))
            travel = min(projectile.remaining, speed * dt)
            steps = max(1, int(math.ceil(travel / max_step)))
            step_distance = travel / steps
            ux, uy = (projectile.vx / speed, projectile.vy / speed)
            end_x = projectile.x + ux * travel
            end_y = projectile.y + uy * travel
            nearby_units = self._ballistic_spatial.query_aabb(
                min(projectile.x, end_x) - 0.92,
                min(projectile.y, end_y) - 0.92,
                max(projectile.x, end_x) + 0.92,
                max(projectile.y, end_y) + 0.92,
            )
            alive = True
            for _ in range(steps):
                ax, ay = (projectile.x, projectile.y)
                bx, by = (ax + ux * step_distance, ay + uy * step_distance)
                projectile.x, projectile.y = (bx, by)
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
                if projectile.traveled > 0.3:
                    for unit in nearby_units:
                        if (
                            unit.uid == projectile.shooter_uid
                            or not unit.combat_effective
                        ):
                            continue
                        distance_to_path, position = _combat2_point_segment_distance(
                            unit.x, unit.y, ax, ay, bx, by
                        )
                        if distance_to_path <= 0.92:
                            candidates.append((position, distance_to_path, unit))
                hit = None
                for _position, distance_to_path, unit in sorted(
                    candidates, key=lambda record: record[0]
                ):
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
            self.tracers.append(
                Tracer(
                    (
                        projectile.x - ux * min(travel, 0.75),
                        projectile.y - uy * min(travel, 0.75),
                    ),
                    (projectile.x, projectile.y),
                    0.12,
                    0.12,
                )
            )
            if not alive and projectile in self.ballistic_rounds:
                self.ballistic_rounds.remove(projectile)
        if len(self.tracers) > 260:
            self.tracers = self.tracers[-220:]
        if len(self.impacts) > 220:
            self.impacts = self.impacts[-180:]
        self.combat2_last_projectile_count = len(self.ballistic_rounds)

    def start_reload(self, unit, emergency=False):
        before = unit.reload_timer
        result = self._base_start_reload(unit, emergency=emergency)
        if unit.reload_timer > max(0.0, before):
            unit.reload_timer *= _combat2_wound_penalties(unit)["reload"]
        return result

    def firing_lane_risk(self, shooter, aim_position, target_uid=None):
        """Return the first friendly obstructing a deliberate firing lane."""
        ax, ay = shooter.pos
        bx, by = (float(aim_position[0]), float(aim_position[1]))
        if math.hypot(bx - ax, by - ay) < 0.75:
            return None
        risks = []
        for friendly in self.living(shooter.faction):
            if (
                friendly.uid == shooter.uid
                or friendly.uid == target_uid
                or (not friendly.combat_effective)
                or (friendly.casualty in ("dead", "surrendered"))
            ):
                continue
            clearance, along = _combat2_point_segment_distance(
                friendly.x, friendly.y, ax, ay, bx, by
            )
            if (
                0.07 < along < 0.94
                and clearance < _polish_unit_clearance(friendly) + 0.18
            ):
                risks.append((along, clearance, friendly))
        return min(risks, default=None, key=lambda item: item[0])

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

    def throw_grenade(self, unit, target, smoke=False, rifle=False, cook=0.0):
        if smoke:
            support = self.smoke_blocks_support(unit, target)
            if support is not None:
                unit.polish_wait_reason = "SMOKE WOULD MASK SUPPORT"
                unit.polish_order_state = "UNABLE: SUPPORT LANE"
                unit.polish_order_state_until = self.time + 1.5
                return False
        return self._kz_throw_grenade(unit, target, smoke=smoke, rifle=rifle, cook=cook)

    def issue_fire(self, unit, target, mode="normal"):
        if unit.faction == "enemy" and target.uid != getattr(unit, "target_uid", None):
            current = self.get_unit(getattr(unit, "target_uid", None))
            if (
                self.time < getattr(unit, "polish_target_lock_until", 0.0)
                and current is not None
                and current.combat_effective
                and self.can_see(unit, current)
                and (dist(unit, current) <= unit.weapon["range"])
            ):
                target = current
        risk = self.firing_lane_risk(unit, target.pos, target.uid)
        if risk is not None and unit.faction == "enemy":
            enemy_faction = "player" if unit.faction == "enemy" else "enemy"
            alternatives = [
                candidate
                for candidate in self.living(enemy_faction)
                if candidate.uid != target.uid
                and candidate.combat_effective
                and (dist(unit, candidate) <= unit.weapon["range"])
                and self.can_see(unit, candidate)
                and (self.firing_lane_risk(unit, candidate.pos, candidate.uid) is None)
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
        result = self._combat2_issue_fire(unit, target, mode)
        unit.polish_target_lock_until = self.time + (
            3.3 if unit.faction == "enemy" else 1.0
        )
        unit.polish_last_order_signature = ("fire", target.uid, mode)
        unit.polish_order_state = "ENGAGING"
        unit.polish_order_state_until = self.time + 0.8
        unit.polish_wait_reason = ""
        return result if result is not None else True

    def suppress_area(self, unit, position):
        risk = self.firing_lane_risk(unit, position)
        if risk is not None and unit.faction == "enemy":
            dx, dy = (float(position[0]) - unit.x, float(position[1]) - unit.y)
            length = max(0.001, math.hypot(dx, dy))
            normal = (-dy / length, dx / length)
            for side in (-1.0, 1.0):
                alternate = (
                    clamp(float(position[0]) + normal[0] * side * 1.35, 0, MAP_W - 1),
                    clamp(float(position[1]) + normal[1] * side * 1.35, 0, MAP_H - 1),
                )
                if self.firing_lane_risk(unit, alternate) is None:
                    position, risk = (alternate, None)
                    break
        if risk is not None:
            self._polish_mark_lane_blocked(unit, risk[2])
            return False
        result = self._base_suppress_area(unit, position)
        unit.polish_last_order_signature = (
            "suppress",
            round(position[0], 1),
            round(position[1], 1),
        )
        unit.polish_order_state = "SUPPRESSING"
        unit.polish_order_state_until = self.time + 0.8
        unit.polish_target_lock_until = self.time + 2.7
        return result if result is not None else True

    def fire_interval(self, unit):
        interval = self._base_fire_interval(unit)
        return interval * combat_polish_weapon_profile(unit)["cadence"]

    def _combat2_commit_weapon_discharge_2(self, attacker, reaction=False):
        self._combat2_commit_weapon_discharge(attacker, reaction=reaction)
        profile = combat_polish_weapon_profile(attacker)
        attacker.polish_recoil = clamp(
            attacker.polish_recoil
            + profile["recoil"] * (0.72 if attacker.stance == "prone" else 1.0),
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
            attacker.next_shot = max(
                attacker.next_shot, attacker.polish_burst_pause_until
            )

    def perform_shot(self, attacker, target, reaction=False):
        risk = self.firing_lane_risk(attacker, target.pos, target.uid)
        if risk is not None:
            self._polish_mark_lane_blocked(attacker, risk[2])
            return
        if not self.polish_trigger_ready(attacker):
            return
        ammo_before = attacker.ammo
        result = self._combat2_perform_shot(attacker, target, reaction=reaction)
        if attacker.ammo < ammo_before:
            attacker.polish_order_state = "FIRING"
            attacker.polish_order_state_until = self.time + 0.32
        return result

    def perform_suppressive_shot(self, unit):
        if unit.target_pos:
            risk = self.firing_lane_risk(unit, unit.target_pos)
            if risk is not None:
                self._polish_mark_lane_blocked(unit, risk[2])
                return
        if not self.polish_trigger_ready(unit, suppressive=True):
            return
        return self._combat2_perform_suppressive_shot(unit)

    def apply_ballistic_wound(self, target, damage, projectile):
        if projectile.traveled < 3.2:
            damage *= 1.14
        result = self._combat2_apply_wound(target, damage, projectile)
        target.polish_reaction_kind = "HIT"
        target.polish_reaction_until = max(
            target.polish_reaction_until, self.time + 1.1
        )
        target.polish_order_state = "WOUNDED"
        target.polish_order_state_until = self.time + 1.5
        return result

    def update_ballistic_rounds(self, dt):
        before = {
            round_state.round_id: (round_state.x, round_state.y, round_state.faction)
            for round_state in self.ballistic_rounds
        }
        result = self._combat2_update_ballistics(dt)
        now = self.time
        for round_state in self.ballistic_rounds:
            previous = before.get(round_state.round_id)
            if previous is None:
                continue
            start_x, start_y, faction = previous
            if dist((start_x, start_y), (round_state.x, round_state.y)) > 0.02:
                self.polish_recent_tracers.append(
                    (
                        start_x,
                        start_y,
                        round_state.x,
                        round_state.y,
                        faction,
                        now + 0.14,
                    )
                )
        self.polish_recent_tracers = [
            segment for segment in self.polish_recent_tracers[-180:] if segment[5] > now
        ]
        return result

    def update_polish_engagement_state(self, dt):
        visible_contact = any(
            (
                unit.combat_effective and self.visible_to("player", unit)
                for unit in self.living("enemy")
            )
        )
        pressure = min(
            1.0, len(self.ballistic_rounds) / 10.0 + self.combat_intensity / 110.0
        )
        if visible_contact or pressure > 0.12:
            self.polish_contact_pressure = min(
                3.0, self.polish_contact_pressure + dt * (0.8 + pressure)
            )
        else:
            self.polish_contact_pressure = max(
                0.0, self.polish_contact_pressure - dt * 0.7
            )
        self.polish_peak_intensity = max(
            self.polish_peak_intensity, self.combat_intensity
        )
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
