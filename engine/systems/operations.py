"""Systems / operations for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _operation_defense_assignment_for_role
from engine.rules import _operation_defense_sector_center
from engine.rules import _operation_defense_sector_for_y
from engine.rules import _operation_open_position
from engine.rules import _vs_sector_name
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import dist
from engine.definitions import Coord
from engine.definitions import DEFENSE_ATTACK_SECTORS
from engine.definitions import DIFFICULTY
from engine.definitions import ENGINEER_BUILD_TYPES
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MISSION_VARIANTS
from engine.definitions import STATIC_WEAPON_ROLES
from engine.models import AssaultOrder
from engine.models import Explosion
from engine.models import Unit
import math


class OperationsSystem:
    def _base_toggle_deploy(self, u: Unit):
        if u.role not in ("Machine Gunner", "HMG Crew", "Mortar Team"):
            return
        u.action_timer = 2.0 if not u.deployed else 1.2
        u.order = "deploy" if not u.deployed else "pack"

    def trench_assault(self, u: Unit, target: Unit):
        if not u.combat_effective or not target.combat_effective:
            return
        if dist(u, target) > 1.45:
            return
        ux, uy = u.tile
        tx, ty = target.tile
        if (
            self.grid[uy][ux].terrain != "trench"
            or self.grid[ty][tx].terrain != "trench"
        ):
            return
        chance = (
            45
            + (u.morale - target.morale) * 0.25
            + u.momentum * 0.15
            + (18 if u.bayonet else 0)
            + (20 if target.suppression >= 50 else 0)
        )
        if u.role == "Assault":
            chance += 20
        if self.rng.uniform(0, 100) < clamp(chance, 10, 95):
            self.apply_damage(target, self.rng.uniform(55, 100), u, "trench assault")
            target.suppression = 100
        else:
            u.suppression = clamp(u.suppression + 40, 0, 100)
        u.action_timer = 1.8

    def engineer_action(self, u: Unit, pos: Coord, kind: str):
        if u.role != "Engineer" or dist(u.pos, pos) > 1.6:
            return
        x, y = pos
        c = self.grid[y][x]
        if kind == "cut" and c.terrain == "wire" and (u.tools > 0):
            u.tools -= 1
            u.action_timer = 2.5
            u.order = "eng_cut"
            u.target_pos = pos
        elif kind == "bangalore" and c.terrain == "wire" and (u.satchel > 0):
            u.satchel -= 1
            u.action_timer = 2.0
            self.explosions.append(Explosion(x, y, 2.0, 2.4, 95, 80, "HE", u.faction))
        elif kind == "clear_mine" and c.mine and (u.tools > 0):
            u.tools -= 1
            u.action_timer = 2.2
            u.order = "eng_mine"
            u.target_pos = pos
        elif (
            kind == "fortify"
            and c.terrain in ("open", "crater", "mud", "rubble")
            and (u.tools > 0)
        ):
            u.tools -= 1
            u.action_timer = 5.0
            u.order = "eng_fort"
            u.target_pos = pos
        elif kind == "trench" and c.terrain in ("open", "mud") and (u.tools > 0):
            u.tools -= 1
            u.action_timer = 8.0
            u.order = "eng_trench"
            u.target_pos = pos
        elif (
            kind == "wire" and c.terrain in ("open", "mud", "rubble") and (u.tools > 0)
        ):
            u.tools -= 1
            u.action_timer = 4.5
            u.order = "eng_wire"
            u.target_pos = pos

    def _base_check_end(self):
        p = [u for u in self.living("player") if u.combat_effective]
        e = [u for u in self.living("enemy") if u.combat_effective]
        if not e:
            self.victory = True
        if not p:
            self.defeat = True

    def _kz_rebuild_indexes(self):
        self._uid_index = {u.uid: u for u in self.units}
        occ = {}
        for u in self.units:
            if u.alive:
                occ[u.tile] = u.uid
        self._occupancy = occ
        self._living_cache = {
            "player": [u for u in self.units if u.alive and u.faction == "player"],
            "enemy": [u for u in self.units if u.alive and u.faction == "enemy"],
        }

    def assault_position(self, units, dest, target_uid=None):
        us = [u for u in units if u.combat_effective]
        if not us:
            return
        support = [
            u
            for u in us
            if u.role
            in (
                "Machine Gunner",
                "HMG Crew",
                "Automatic Rifleman",
                "Marksman",
                "Sniper",
                "Mortar Team",
            )
        ]
        assault = [u for u in us if u not in support]
        if not assault:
            assault = us[::2]
            support = [u for u in us if u not in assault]
        if not support and len(assault) > 1:
            support = [assault.pop()]
        ao = AssaultOrder(
            [u.uid for u in support], [u.uid for u in assault], dest, target_uid, 0, 0.0
        )
        self.assault_orders.append(ao)
        self._kz_event_record("assault", "Assault order initiated", dest)
        for u in support:
            if u.role in ("Machine Gunner", "HMG Crew") and (not u.deployed):
                self.toggle_deploy(u)
            self.suppress_area(u, dest)
        smoker = next((u for u in assault if u.smoke_grenades > 0), None)
        if smoker:
            mid = ((smoker.x + dest[0]) * 0.55, (smoker.y + dest[1]) * 0.55)
            self.throw_grenade(smoker, mid, smoke=True)
        self.add_log(
            "Assault: support element suppressing; assault element standing by."
        )

    def update_assault_orders(self, dt):
        for ao in list(self.assault_orders):
            ao.timer += dt
            support = [self.get_unit(i) for i in ao.support]
            assault = [self.get_unit(i) for i in ao.assault]
            support = [u for u in support if u and u.combat_effective]
            assault = [u for u in assault if u and u.combat_effective]
            if not assault:
                self.assault_orders.remove(ao)
                continue
            dx, dy = ao.dest
            ground = self.grid[int(clamp(dy, 0, MAP_H - 1))][
                int(clamp(dx, 0, MAP_W - 1))
            ].ground_suppression
            target = self.get_unit(ao.target_uid) if ao.target_uid else None
            target_supp = (
                target.suppression if target and target.combat_effective else 0
            )
            if ao.phase == 0 and (ao.timer > 2.2 or ground > 24 or target_supp > 45):
                for u in assault:
                    u.move_mode = (
                        "fast"
                        if self.grid[int(clamp(dy, 0, MAP_H - 1))][
                            int(clamp(dx, 0, MAP_W - 1))
                        ].smoke
                        > 1.0
                        else "safe"
                    )
                self.issue_move(
                    assault, ao.dest, mode=assault[0].move_mode, formation="spread"
                )
                ao.phase = 1
                ao.timer = 0
                self.add_log("Assault element moving under supporting fire.")
            elif ao.phase == 1:
                for u in support:
                    if u.order in ("idle", "overwatch") and u.ammo > 0:
                        self.suppress_area(u, ao.dest)
                if any((dist(u.pos, ao.dest) < 2.2 for u in assault)) or ao.timer > 11:
                    ao.phase = 2
                    ao.timer = 0
                    for u in assault:
                        enemies = [
                            e
                            for e in self.living(
                                "enemy" if u.faction == "player" else "player"
                            )
                            if e.combat_effective and dist(e, u) < u.weapon["range"]
                        ]
                        if enemies:
                            self.issue_fire(
                                u,
                                min(enemies, key=lambda e: dist(e, u)),
                                "rapid" if u.role == "Assault" else "normal",
                            )
            elif ao.phase == 2 and (
                ao.timer > 5 or all((dist(u.pos, ao.dest) < 3 for u in assault))
            ):
                self._kz_event_record("assault", "Assault reached objective", ao.dest)
                self.assault_orders.remove(ao)

    def _kz_deploy_reserves(self):
        if not self.player_reserves:
            return []
        roles = list(self.player_reserves)
        self.player_reserves = []
        new = []
        base_y = int(clamp(self.rally_points["player"][1], 3, MAP_H - 4))
        for i, role in enumerate(roles):
            x = 2 + i % 3
            y = int(clamp(base_y + i // 3 * 2 - len(roles) // 3, 2, MAP_H - 3))
            while self.unit_at(x, y) and y < MAP_H - 3:
                y += 1
            u = self.add_unit("player", role, x, y)
            u.reserve = True
            new.append(u)
        self.stats["player"]["reserves"] += len(new)
        self._kz_rebuild_indexes()
        self.add_log(f"{len(new)} reserve unit(s) entered from the west.")
        self._kz_event_record("reserve", f"{len(new)} reserves committed", (2, base_y))
        return new

    @property
    def current_objective(self):
        if 0 <= self.objective_index < len(self.objectives):
            return self.objectives[self.objective_index]
        return None

    def activate_enemy_reserves(self, reason="Line 1 compromised"):
        if self._reserves_activated:
            return
        units = [
            u
            for u in self.living("enemy")
            if getattr(u, "initial_battle_role", "") == "reserve"
        ]
        if not units:
            return
        self._reserves_activated = True
        for u in units:
            u.reserve_active = True
            u.plan_state = "reinforce"
            if u.role in ("Machine Gunner", "HMG Crew"):
                u.fallback_point = (
                    self.secondary_line_x,
                    int(clamp(round(u.y), 2, MAP_H - 3)),
                )
        self.notify("ENEMY RESERVES COMMITTED", kind="danger", duration=5)
        self._vs_event(
            "reserve",
            f"Enemy reserves committed — {reason}",
            (self.secondary_line_x, MAP_H // 2),
        )

    def complete_objective(self):
        if not 0 <= self.objective_index < len(self.objectives):
            return
        obj = self.objectives[self.objective_index]
        obj["state"] = "complete"
        obj["progress"] = 1.0
        self.notify(f"OBJECTIVE COMPLETE — {obj['title']}", kind="good", duration=5)
        self._vs_event("objective", f"Objective complete — {obj['title']}", obj["pos"])
        done = self.objective_index
        self.objective_index += 1
        if done == 0:
            self.activate_enemy_reserves("forward line breached")
        if done == 1:
            self.launch_counterattack()
        if self.objective_index < len(self.objectives):
            self.objectives[self.objective_index]["state"] = "active"
            nxt = self.objectives[self.objective_index]
            self.notify(f"NEW OBJECTIVE — {nxt['title']}", kind="objective", duration=5)
        else:
            self.victory = True
            if not self._mission_complete_recorded:
                self._mission_complete_recorded = True
                self._vs_event(
                    "victory",
                    "Enemy defensive system collapsed",
                    self.map_features["command_post"],
                )

    def _vs_update_local_surrenders(self):
        for u in list(self.living("enemy")):
            if not u.combat_effective or u.casualty == "surrendered":
                continue
            if u.morale > 23 or u.suppression < 82:
                continue
            friends = [
                a
                for a in self.living("enemy")
                if a.uid != u.uid and a.combat_effective and (dist(a, u) < 5)
            ]
            attackers = [
                a
                for a in self.living("player")
                if a.combat_effective and dist(a, u) < 3.2
            ]
            rear_cut = any((a.x > u.x + 0.5 for a in attackers))
            if attackers and len(friends) <= 1 and (rear_cut or u.morale < 12):
                score = (
                    24
                    - u.morale
                    + (u.suppression - 80) * 0.35
                    + len(attackers) * 3
                    - len(friends) * 4
                )
                if score >= 18:
                    u.casualty = "surrendered"
                    u.order = "surrender"
                    u.path = []
                    u.waypoints = []
                    u.command_queue = []
                    self.stats["enemy"]["surrendered"] += 1
                    self.notify(
                        f"ENEMY SECTION SURRENDERS — {u.battle_sector}",
                        kind="good",
                        duration=4,
                    )
                    self._vs_event("surrender", f"{u.display_name} surrendered", u.pos)

    def update_objectives(self):
        if self.victory or self.defeat:
            return
        p = self.primary_line_x
        s = self.secondary_line_x
        players = [u for u in self.living("player") if u.combat_effective]
        enemies = [u for u in self.living("enemy") if u.combat_effective]
        if not players:
            self.defeat = True
            return
        idx = self.objective_index
        if idx >= len(self.objectives):
            self.victory = True
            return
        obj = self.objectives[idx]
        if idx == 0:
            crossers = [u for u in players if u.x >= p - 1]
            forward = [
                u for u in enemies if getattr(u, "initial_battle_role", "") == "forward"
            ]
            rem = len(forward) / max(1, self.initial_role_counts["forward"])
            obj["progress"] = clamp(
                0.55 * min(1, len(crossers) / 2) + 0.45 * (1 - rem), 0, 1
            )
            if len(crossers) >= 2 and (rem <= 0.58 or self.collapsed_sectors):
                self.complete_objective()
        elif idx == 1:
            pos = obj["pos"]
            near_p = [u for u in players if dist(u.pos, pos) <= 2.4]
            near_e = [u for u in enemies if dist(u.pos, pos) <= 4.0]
            closest = min((dist(u.pos, pos) for u in players), default=99)
            obj["progress"] = clamp(1 - closest / 12, 0, 0.82 if near_e else 1)
            if near_p and (not near_e):
                self.complete_objective()
        elif idx == 2:
            crossers = [u for u in players if u.x >= s - 1]
            reserve = [
                u
                for u in enemies
                if getattr(u, "initial_battle_role", "") in ("reserve", "forward")
                and u.x >= p
            ]
            obj["progress"] = clamp(
                0.6 * min(1, len(crossers) / 2)
                + 0.4
                * (
                    1
                    - len(reserve)
                    / max(
                        1,
                        self.initial_role_counts["forward"]
                        + self.initial_role_counts["reserve"],
                    )
                ),
                0,
                1,
            )
            if len(crossers) >= 2 and (
                len(reserve) <= max(2, self.initial_enemy_total // 4)
                or len(self.collapsed_sectors) >= 2
            ):
                self.complete_objective()
        else:
            pos = obj["pos"]
            near_p = [u for u in players if dist(u.pos, pos) <= 2.7]
            near_e = [u for u in enemies if dist(u.pos, pos) <= 4.3]
            enemy_ratio = len(enemies) / max(1, self.initial_enemy_total)
            closest = min((dist(u.pos, pos) for u in players), default=99)
            obj["progress"] = max(
                clamp(1 - closest / 15, 0, 1), clamp(1 - enemy_ratio, 0, 1)
            )
            if near_p and (not near_e) or enemy_ratio <= 0.2:
                self.complete_objective()

    def _vs_update_mission(self, dt):
        self._mission_timer += dt
        self._stability_timer += dt
        self.update_battle_stage(dt)
        if self._stability_timer >= 0.5:
            self._stability_timer = 0
            self.update_sector_stability()
            self.update_local_surrenders()
            self.update_objectives()
            forward = [
                u
                for u in self.living("enemy")
                if getattr(u, "initial_battle_role", "") == "forward"
            ]
            ratio = len(forward) / max(1, self.initial_role_counts["forward"])
            trigger = (
                0.5
                if self.difficulty == "Easy"
                else 0.68
                if self.difficulty == "Hard"
                else 0.8
            )
            if not self._reserves_activated and ratio < trigger:
                self.activate_enemy_reserves("forward casualties")
        self.notifications = [n for n in self.notifications if n["until"] > self.time]

    def update_local_surrenders(self):
        for u in list(self.living("enemy")):
            if not u.combat_effective or u.casualty == "surrendered":
                continue
            if u.morale > 20 or u.suppression < 86:
                continue
            low_for = (
                self.time - u.low_morale_since if u.low_morale_since is not None else 0
            )
            if low_for < 5.0:
                continue
            friends = [
                a
                for a in self.living("enemy")
                if a.uid != u.uid and a.combat_effective and (dist(a, u) < 5)
            ]
            attackers = [
                a
                for a in self.living("player")
                if a.combat_effective and dist(a, u) < 3.2
            ]
            rear_cut = any((a.x > u.x + 0.5 for a in attackers))
            score = (
                22
                - u.morale
                + (u.suppression - 84) * 0.3
                + len(attackers) * 3
                - len(friends) * 4
            )
            if (
                attackers
                and len(friends) <= 1
                and (rear_cut or u.morale < 8)
                and (score >= 18)
            ):
                u.casualty = "surrendered"
                u.order = "surrender"
                self.cleanup_unit_state(u, "local surrender")
                self.stats["enemy"]["surrendered"] += 1
                self.notify(
                    f"ENEMY SECTION SURRENDERS — {u.battle_sector}",
                    kind="good",
                    duration=4,
                )
                self._vs_event("surrender", f"{u.display_name} surrendered", u.pos)

    def generate_map(self):
        requested = getattr(self, "operation_variant", "auto")
        if requested == "auto":
            return self._vs_generate_map()
        original_seed = self.seed
        variants = list(MISSION_VARIANTS)
        self.seed = (
            original_seed - original_seed % len(variants) + variants.index(requested)
        )
        try:
            self._vs_generate_map()
        finally:
            self.seed = original_seed
        self.battle_variant = requested
        self.map_features["variant"] = requested

    def _operation_scale_enemy_force(self):
        enemies = [unit for unit in self.units if unit.faction == "enemy"]
        target = max(4, int(round(len(enemies) * self.operation_enemy_strength)))
        if target < len(enemies):
            remove_ids = {
                unit.uid
                for unit in sorted(enemies, key=lambda item: item.uid, reverse=True)[
                    : len(enemies) - target
                ]
            }
            self.units = [unit for unit in self.units if unit.uid not in remove_ids]
        elif target > len(enemies):
            pool = (
                "Rifleman",
                "Assault",
                "Automatic Rifleman",
                "Grenadier",
                "Machine Gunner",
                "Engineer",
                "Medic",
                "Marksman",
            )
            for index in range(target - len(enemies)):
                role = pool[(len(enemies) + index) % len(pool)]
                self.add_unit(
                    "enemy", role, self.primary_line_x, 3 + index % (MAP_H - 6)
                )
        self._kz_rebuild_indexes()

    def _operation_place_force(self, units, x_values, facing):
        for index, unit in enumerate(units):
            desired_x = x_values[index % len(x_values)]
            desired_y = 2 + (index * 5 + index // 3) % (MAP_H - 4)
            placed = _operation_open_position(self, desired_x, desired_y, unit)
            if placed:
                unit.x, unit.y = placed
            unit.facing = facing
            unit.path = []
            unit.waypoints = []
            unit.command_queue = []
            unit.order = "idle"
            unit.overwatch = False
            unit.fire_lane = False

    def _operation_configure_defense(self):
        players = [unit for unit in self.units if unit.faction == "player"]
        enemies = [unit for unit in self.units if unit.faction == "enemy"]
        self.deployment_zone_side = "east"
        self.defense_deployment_x = max(self.primary_line_x - 3, MAP_W - 18)
        self.rally_points = {
            "player": self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2)),
            "enemy": (2, MAP_H // 2),
        }
        self._operation_place_force(
            players,
            (self.primary_line_x, self.primary_line_x + 1, self.secondary_line_x),
            180,
        )
        self._operation_place_force(enemies, (3, 5, 7, 9), 0)
        ordered = sorted(enemies, key=lambda unit: unit.uid)
        first = max(1, int(math.ceil(len(ordered) * 0.46)))
        second = max(first + 1, int(math.ceil(len(ordered) * 0.74)))
        for index, unit in enumerate(ordered):
            wave = 1 if index < first else 2 if index < second else 3
            unit.attack_wave = wave
            unit.initial_battle_role = f"wave{wave}"
            unit.battle_role = "assault"
            unit.plan_state = "attack" if wave == 1 else "reserve"
            unit.reserve_active = wave == 1
            unit.battle_sector = _vs_sector_name(unit.y)
            unit.fallback_point = (2, int(clamp(round(unit.y), 2, MAP_H - 3)))
        command_post = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
        strongpoint = self.map_features.get(
            "strongpoint", (self.primary_line_x + 2, MAP_H // 2)
        )
        self.objectives = [
            {
                "title": "HOLD THE FORWARD LINE",
                "desc": "Deny the eastern trench line through the opening assault.",
                "pos": (self.primary_line_x, MAP_H // 2),
                "progress": 0.0,
                "state": "active",
            },
            {
                "title": "HOLD THE STRONGPOINT",
                "desc": "Prevent the second wave from overrunning the central bunker.",
                "pos": strongpoint,
                "progress": 0.0,
                "state": "locked",
            },
            {
                "title": "PROTECT THE COMMAND POST",
                "desc": "Survive the final assault and retain the rear command bunker.",
                "pos": command_post,
                "progress": 0.0,
                "state": "locked",
            },
        ]
        self.objective_index = 0
        self.defense_elapsed = 0.0
        self.defense_capture_progress = 0.0
        self.defense_wave_announced = {1}
        self._defense_last_minute = int(math.ceil(self.defense_time_limit / 60))
        self.battle_stage = "PREPARATION"
        self.mission_title = (
            f"DEFENSE — {MISSION_VARIANTS[self.battle_variant]['name']}"
        )
        self.mission_brief = "Hold the eastern defensive system against three escalating enemy waves. Engineers can improve the position before and during contact."
        self.notifications = []
        self.battle_events = [
            event for event in self.battle_events if event.get("kind") != "mission"
        ]
        self.notify("MISSION — Hold the defensive line", kind="objective", duration=5.0)
        self._vs_event("mission", self.mission_title, (self.primary_line_x, MAP_H // 2))
        self._kz_rebuild_indexes()
        self.plan_defense_attack(force=True)

    def _operation_refresh_force_counts(self):
        enemies = [unit for unit in self.units if unit.faction == "enemy"]
        self.initial_enemy_total = max(1, len(enemies))
        self.initial_mobile_enemy_total = max(
            1, len([unit for unit in enemies if unit.role not in STATIC_WEAPON_ROLES])
        )
        self.initial_role_counts = {
            role: max(
                1,
                len(
                    [
                        unit
                        for unit in enemies
                        if getattr(unit, "initial_battle_role", "") == role
                    ]
                ),
            )
            for role in ("forward", "reserve", "command", "wave1", "wave2", "wave3")
        }
        self.initial_sector_counts = {
            sector: max(
                1,
                len(
                    [
                        unit
                        for unit in enemies
                        if getattr(unit, "battle_sector", "") == sector
                        and (
                            self.mission_type == "defense"
                            or getattr(unit, "initial_battle_role", "") == "forward"
                        )
                    ]
                ),
            )
            for sector in ("NORTH", "CENTRE", "SOUTH")
        }
        estimate = len(enemies)
        self.enemy_estimate = (max(1, estimate - 2), estimate + 2)

    def doctrine_for(self, unit):
        key = (unit.faction, max(1, int(getattr(unit, "squad_id", 1))))
        return self.squad_doctrine.get(key, "balanced")

    def update_auto_behaviors(self):
        aggressive = []
        for unit in self.living("player"):
            if self.doctrine_for(unit) == "aggressive" and unit.auto_cover:
                aggressive.append(unit)
                unit.auto_cover = False
        try:
            self._base_update_auto_behaviors()
        finally:
            for unit in aggressive:
                unit.auto_cover = True
        for unit in self.living("player"):
            if not unit.combat_effective or self.doctrine_for(unit) != "cautious":
                continue
            if unit.order not in ("idle", "overwatch", "fire_lane", "fire"):
                continue
            if unit.auto_smoke and unit.smoke_grenades > 0 and (unit.suppression > 62):
                if self.grid[unit.tile[1]][unit.tile[0]].smoke < 1.0:
                    self.throw_grenade(unit, unit.pos, smoke=True)
                    continue
            if unit.auto_cover and unit.suppression > 66:
                destination = self.find_nearby_cover(unit, 4)
                if destination and destination != unit.tile:
                    self.issue_move(
                        [unit], destination, mode="safe", formation="column"
                    )

    def static_emplacement_count(self, faction):
        return sum(
            (
                unit.faction == faction
                and unit.combat_effective
                and (unit.role in STATIC_WEAPON_ROLES)
                for unit in self.units
            )
        )

    def validate_build_site(self, faction, kind, pos, include_reservations=True):
        if kind not in ENGINEER_BUILD_TYPES:
            return (False, "Unknown construction")
        if not self.in_bounds(*pos):
            return (False, "Choose a tile inside the battlefield")
        pos = (int(pos[0]), int(pos[1]))
        if include_reservations and pos in self.construction_reservations:
            return (False, "Another construction is already planned there")
        cell = self.grid[pos[1]][pos[0]]
        if self.unit_at(*pos) is not None:
            return (False, "Construction tile is occupied")
        definition = ENGINEER_BUILD_TYPES[kind]
        queued_emplacements = sum(
            (
                ENGINEER_BUILD_TYPES[reservation[1]].get("role") is not None
                for reservation in self.construction_reservations.values()
                if reservation[2] == faction
            )
        )
        if (
            "role" in definition
            and self.static_emplacement_count(faction) + queued_emplacements >= 6
        ):
            return (False, "Temporary emplacement cap reached (6)")
        if "role" in definition and cell.terrain not in (
            "open",
            "mud",
            "rubble",
            "crater",
            "foxhole",
            "trench",
            "sandbags",
            "hill",
        ):
            return (False, "Static weapons require firm, open ground")
        if "terrain" in definition and cell.terrain not in (
            "open",
            "mud",
            "rubble",
            "crater",
            "foxhole",
        ):
            return (False, "Defenses require clear ground")
        return (True, "")

    def can_build(self, engineer, kind, pos):
        if engineer.role != "Engineer" or not engineer.combat_effective:
            return (False, "No combat-effective engineer is available")
        if engineer.action_timer > 0 or engineer.order == "build":
            return (False, "Engineer is already occupied")
        if not self.in_bounds(*pos) or dist(engineer.pos, pos) > 2.2:
            return (False, "Engineer has not reached the construction site")
        return self.validate_build_site(
            engineer.faction, kind, pos, include_reservations=False
        )

    def builder_staging_position(self, engineer, pos):
        choices = []
        px, py = pos
        for radius in (1, 2):
            for y in range(max(1, py - radius), min(MAP_H - 1, py + radius + 1)):
                for x in range(max(1, px - radius), min(MAP_W - 1, px + radius + 1)):
                    if max(abs(x - px), abs(y - py)) != radius:
                        continue
                    if not self.passable(x, y, engineer):
                        continue
                    choices.append((math.hypot(x - engineer.x, y - engineer.y), x, y))
            if choices:
                break
        if not choices:
            return None
        choices.sort()
        return (choices[0][1], choices[0][2])

    def queue_construction(self, faction, kind, pos, preferred_engineers=None):
        pos = (int(pos[0]), int(pos[1]))
        valid, reason = self.validate_build_site(faction, kind, pos)
        if not valid:
            return (None, reason)
        engineers = [
            unit
            for unit in self.living(faction)
            if unit.role == "Engineer"
            and unit.combat_effective
            and (unit.action_timer <= 0)
            and (not getattr(unit, "_construction_queued", False))
            and (unit.order != "build")
        ]
        if not engineers:
            return (None, "No available engineer can take this project")
        preferred_ids = {unit.uid for unit in preferred_engineers or []}
        engineers.sort(
            key=lambda unit: (
                0 if unit.uid in preferred_ids else 1,
                dist(unit.pos, pos),
            )
        )
        assignment = None
        for engineer in engineers:
            staging = self.builder_staging_position(engineer, pos)
            if staging is None:
                continue
            path = (
                self.find_path(engineer, staging, "safe")
                if engineer.tile != staging
                else []
            )
            if engineer.tile != staging and (not path):
                continue
            assignment = (engineer, staging)
            break
        if assignment is None:
            return (None, "No engineer can reach an adjacent build position")
        engineer, staging = assignment
        engineer._construction_queued = True
        engineer._construction_kind = kind
        engineer._construction_pos = pos
        engineer._construction_staging = staging
        engineer.target_pos = pos
        engineer.command_queue = []
        self.construction_reservations[pos] = (engineer.uid, kind, faction)
        self.issue_move([engineer], staging, mode="safe", formation="column")
        self.notify(
            f"ENGINEER EN ROUTE — {ENGINEER_BUILD_TYPES[kind]['label']}",
            kind="good" if faction == "player" else "danger",
            duration=3.0,
        )
        return (engineer, "")

    def cancel_construction_assignment(self, engineer, reason=None):
        pos = getattr(engineer, "_construction_pos", None)
        if pos is not None:
            reservation = self.construction_reservations.get(pos)
            if reservation and reservation[0] == engineer.uid:
                self.construction_reservations.pop(pos, None)
        engineer._construction_queued = False
        engineer._construction_kind = None
        engineer._construction_pos = None
        engineer._construction_staging = None
        engineer.target_pos = None
        if reason and engineer.faction == "player":
            self.notify(reason, kind="danger", duration=2.5)

    def update_engineer_assignments(self):
        for engineer in list(self.units):
            if not getattr(engineer, "_construction_queued", False):
                continue
            if not engineer.combat_effective:
                self.cancel_construction_assignment(
                    engineer, "Construction cancelled — engineer unavailable"
                )
                continue
            kind = getattr(engineer, "_construction_kind", None)
            pos = getattr(engineer, "_construction_pos", None)
            if kind not in ENGINEER_BUILD_TYPES or pos is None:
                self.cancel_construction_assignment(engineer)
                continue
            valid, reason = self.validate_build_site(
                engineer.faction, kind, pos, include_reservations=False
            )
            if not valid:
                self.cancel_construction_assignment(
                    engineer, f"Construction cancelled — {reason.lower()}"
                )
                continue
            if dist(engineer.pos, pos) <= 2.2:
                engineer._construction_queued = False
                started, reason = self.begin_construction(engineer, kind, pos)
                if not started:
                    self.cancel_construction_assignment(
                        engineer, f"Construction delayed — {reason.lower()}"
                    )
                continue
            if engineer.order == "move" and (engineer.path or engineer.waypoints):
                continue
            staging = self.builder_staging_position(engineer, pos)
            if staging is None:
                self.cancel_construction_assignment(
                    engineer, "Construction cancelled — site cannot be approached"
                )
                continue
            engineer._construction_staging = staging
            self.issue_move([engineer], staging, mode="safe", formation="column")

    def begin_construction(self, engineer, kind, pos):
        valid, reason = self.can_build(engineer, kind, pos)
        if not valid:
            return (False, reason)
        definition = ENGINEER_BUILD_TYPES[kind]
        engineer._construction_kind = kind
        engineer._construction_pos = (int(pos[0]), int(pos[1]))
        engineer.action_timer = float(definition["seconds"])
        engineer.order = "build"
        engineer.target_pos = engineer._construction_pos
        engineer.path = []
        engineer.waypoints = []
        self.notify(
            f"{engineer.faction.upper()} ENGINEER — building {definition['label']}",
            kind="info" if engineer.faction == "player" else "danger",
            duration=2.5,
        )
        return (True, "")

    def finish_construction(self, engineer):
        kind = getattr(engineer, "_construction_kind", None)
        pos = getattr(engineer, "_construction_pos", None)
        if kind not in ENGINEER_BUILD_TYPES or pos is None:
            self.cancel_construction_assignment(engineer)
            engineer.order = "idle"
            return None
        definition = ENGINEER_BUILD_TYPES[kind]
        built = None
        if self.unit_at(*pos) is None:
            if "terrain" in definition:
                self.set_cell(
                    pos[0],
                    pos[1],
                    definition["terrain"],
                    "H" if kind == "trench" else None,
                )
                built = pos
            else:
                built = self.add_unit(
                    engineer.faction, definition["role"], pos[0], pos[1]
                )
                built.is_emplacement = True
                built.built_by_uid = engineer.uid
                built.squad_id = 0
                built.display_name = definition["label"]
                built.deployed = True
                built.order = "emplaced"
                built.hold_position = True
                built.facing = engineer.facing
                built.artillery_shells = 12 if built.role == "Artillery Battery" else 0
                built.next_artillery_shot = self.time + 3.0
                self._kz_rebuild_indexes()
        engineer.order = "idle"
        engineer.target_pos = None
        reservation = self.construction_reservations.get(pos)
        if reservation and reservation[0] == engineer.uid:
            self.construction_reservations.pop(pos, None)
        engineer._construction_queued = False
        engineer._construction_kind = None
        engineer._construction_pos = None
        engineer._construction_staging = None
        if built is not None:
            self.notify(
                f"{definition['label']} COMPLETE",
                kind="good" if engineer.faction == "player" else "danger",
                duration=3.2,
            )
            self._vs_event(
                "construction",
                f"{engineer.faction.title()} built {definition['label']}",
                pos,
            )
        return built

    def _operation_complete_action(self, unit):
        finishing_build = unit.order == "build"
        self._base_complete_action(unit)
        if finishing_build:
            self.finish_construction(unit)

    def update_emplacements(self):
        for unit in list(self.living()):
            if unit.role not in STATIC_WEAPON_ROLES or not unit.combat_effective:
                continue
            unit.is_emplacement = True
            unit.deployed = True
            unit.hold_position = True
            if unit.jammed and unit.action_timer <= 0:
                self.clear_jam(unit)
                continue
            if unit.action_timer > 0 or unit.reload_timer > 0 or unit.jammed:
                continue
            unit.order = "emplaced"
            if unit.role == "Artillery Battery":
                if getattr(unit, "artillery_shells", 0) <= 0 or self.time < getattr(
                    unit, "next_artillery_shot", 0
                ):
                    continue
                enemy_faction = "enemy" if unit.faction == "player" else "player"
                targets = [
                    target
                    for target in self.living(enemy_faction)
                    if target.combat_effective
                    and target.role not in STATIC_WEAPON_ROLES
                    and self.visible_to(unit.faction, target)
                    and (5.0 <= dist(unit, target) <= 30.0)
                ]
                if not targets:
                    continue
                target = max(
                    targets,
                    key=lambda item: (
                        item.role in ("Machine Gunner", "HMG Crew", "Engineer"),
                        -dist(unit, item),
                    ),
                )
                scatter = 0.75 if unit.suppression < 35 else 1.6
                impact = (
                    clamp(target.x + self.rng.gauss(0, scatter), 0, MAP_W - 1),
                    clamp(target.y + self.rng.gauss(0, scatter), 0, MAP_H - 1),
                )
                self.explosions.append(
                    Explosion(
                        impact[0], impact[1], 2.4, 3.0, 112, 92, "HE", unit.faction
                    )
                )
                unit.artillery_shells -= 1
                unit.next_artillery_shot = self.time + self.rng.uniform(9.0, 12.5)
                unit.signature = max(unit.signature, 18)
                self.emit("shot", pos=unit.pos, weapon="artillery")
                continue
            if self.time < unit.next_shot:
                continue
            target = self.choose_auto_target(unit)
            if target is not None:
                self.perform_shot(unit, target)

    def enemy_builder_position(self, engineer):
        candidates = []
        ex, ey = engineer.tile
        sector = getattr(
            engineer, "attack_sector", getattr(self, "defense_main_effort", "CENTRE")
        )
        sector_y = _operation_defense_sector_center(sector)
        for y in range(max(1, ey - 2), min(MAP_H - 1, ey + 3)):
            for x in range(max(1, ex - 2), min(MAP_W - 1, ex + 3)):
                if (x, y) == engineer.tile or self.unit_at(x, y) is not None:
                    continue
                if self.grid[y][x].terrain not in (
                    "open",
                    "mud",
                    "rubble",
                    "crater",
                    "foxhole",
                    "hill",
                ):
                    continue
                candidates.append(
                    (
                        self.tile_threat("enemy", x, y),
                        abs(y - sector_y),
                        -x,
                        abs(x - ex) + abs(y - ey),
                        x,
                        y,
                    )
                )
        if not candidates:
            return None
        candidates.sort()
        return (candidates[0][-2], candidates[0][-1])

    def enemy_builder_ready(self, engineer):
        if self.mission_type != "defense":
            return True
        existing = self.static_emplacement_count("enemy")
        staging_offset = 20 if existing == 0 else 14 if existing == 1 else 7
        return engineer.x >= self.primary_line_x - staging_offset

    def update_enemy_builders(self):
        if self.time - self._last_engineer_builder_update < 0.75:
            return
        self._last_engineer_builder_update = self.time
        if self.static_emplacement_count("enemy") >= 4:
            return
        engineers = [
            unit
            for unit in self.living("enemy")
            if unit.role == "Engineer"
            and unit.combat_effective
            and getattr(unit, "reserve_active", True)
            and (unit.order in ("idle", "overwatch"))
            and (unit.action_timer <= 0)
            and self.enemy_builder_ready(unit)
            and (self.time >= getattr(unit, "next_builder_decision", 8.0))
        ]
        for engineer in engineers[:1]:
            position = self.enemy_builder_position(engineer)
            if position is None:
                engineer.next_builder_decision = self.time + 12.0
                continue
            existing = self.static_emplacement_count("enemy")
            if self.mission_type == "defense":
                kind = (
                    "field_gun"
                    if existing % 3 == 0
                    else "artillery"
                    if existing % 3 == 1
                    else "mg_nest"
                )
            else:
                kind = "mg_nest" if existing % 3 != 2 else "field_gun"
            built, _reason = self.begin_construction(engineer, kind, position)
            engineer.next_builder_decision = self.time + (24.0 if built else 10.0)

    def activate_defense_wave(self, wave):
        units = [
            unit
            for unit in self.living("enemy")
            if getattr(unit, "attack_wave", 1) == wave
            and (not getattr(unit, "reserve_active", True))
        ]
        if not units:
            return
        for unit in units:
            unit.reserve_active = True
            unit.plan_state = "attack"
            unit.order = "idle"
        self.defense_wave_announced.add(wave)
        self.notify(f"ENEMY WAVE {wave} COMMITTED", kind="danger", duration=5.0)
        self._vs_event(
            "reserve", f"Enemy assault wave {wave} committed", (5, MAP_H // 2)
        )
        self.plan_defense_attack(force=True)

    def plan_defense_attack(self, force=False):
        if self.mission_type != "defense":
            return False
        if not force and self.time < self._defense_next_plan_time:
            return False
        tactics = max(0.45, DIFFICULTY[self.difficulty].get("tactics", 1.0))
        self._defense_next_plan_time = self.time + max(2.4, 5.5 / tactics)
        pressure = {sector: 0.0 for sector in DEFENSE_ATTACK_SECTORS}
        contact_weights = {
            "MG Emplacement": 4.6,
            "Field Gun": 4.2,
            "Artillery Battery": 3.7,
            "Machine Gunner": 2.7,
            "HMG Crew": 3.2,
            "Sniper": 2.1,
            "Marksman": 1.9,
            "Engineer": 1.7,
            "Grenadier": 1.5,
        }
        for _uid, info, age in self.known_contacts("enemy", memory=22.0):
            x, y = info["pos"]
            if x < self.primary_line_x - 10:
                continue
            sector = _operation_defense_sector_for_y(y)
            freshness = clamp(1.0 - age / 28.0, 0.35, 1.0)
            pressure[sector] += contact_weights.get(info.get("role"), 1.0) * freshness
        for y in range(1, MAP_H - 1):
            sector = _operation_defense_sector_for_y(y)
            for x in range(max(1, self.primary_line_x - 2), MAP_W - 1):
                terrain = self.grid[y][x].terrain
                if terrain == "trench":
                    pressure[sector] += 0.12
                elif terrain == "sandbags":
                    pressure[sector] += 0.24
                elif terrain == "wire":
                    pressure[sector] += 0.17
        ranked = sorted(
            DEFENSE_ATTACK_SECTORS,
            key=lambda sector: (pressure[sector], DEFENSE_ATTACK_SECTORS.index(sector)),
        )
        previous_effort = self.defense_main_effort
        self.defense_main_effort = ranked[0]
        self.defense_sector_pressure = {
            sector: round(value, 2) for sector, value in pressure.items()
        }
        self.defense_plan_revision += 1
        active = [
            unit
            for unit in self.living("enemy")
            if unit.combat_effective
            and unit.role not in STATIC_WEAPON_ROLES
            and getattr(unit, "reserve_active", True)
        ]
        maneuver = []
        assault_slot = 0
        for unit in sorted(active, key=lambda item: item.uid):
            assignment = _operation_defense_assignment_for_role(unit.role)
            if assignment == "breach":
                sector = ranked[0]
            elif assignment == "assault":
                sector_pattern = (ranked[0], ranked[1], ranked[0], ranked[0], ranked[2])
                sector = sector_pattern[assault_slot % len(sector_pattern)]
                assault_slot += 1
            else:
                sector = ranked[0]
            unit.attack_assignment = assignment
            unit.attack_sector = sector
            unit.plan_state = f"{assignment}:{sector.lower()}"
            self.defense_attack_plan[unit.uid] = {
                "assignment": assignment,
                "sector": sector,
                "wave": getattr(unit, "attack_wave", 1),
                "revision": self.defense_plan_revision,
            }
            if assignment in ("breach", "assault"):
                maneuver.append(unit)
        for unit in active:
            if (
                unit.attack_assignment not in ("fire_support", "sustainment")
                or not maneuver
            ):
                continue
            lead = min(maneuver, key=lambda item: abs(item.y - unit.y))
            unit.attack_sector = lead.attack_sector
            unit.plan_state = f"{unit.attack_assignment}:{unit.attack_sector.lower()}"
            self.defense_attack_plan[unit.uid]["sector"] = unit.attack_sector
        live_ids = {unit.uid for unit in active}
        self.defense_attack_plan = {
            uid: plan
            for uid, plan in self.defense_attack_plan.items()
            if uid in live_ids
        }
        if previous_effort != self.defense_main_effort and self.time > 1:
            self.add_log(
                f"Enemy assault shifted toward the {self.defense_main_effort.lower()} sector."
            )
        return True

    def defense_sector_front(self, sector):
        maneuver = [
            unit.x
            for unit in self.living("enemy")
            if unit.combat_effective
            and getattr(unit, "reserve_active", True)
            and (getattr(unit, "attack_sector", self.defense_main_effort) == sector)
            and (getattr(unit, "attack_assignment", "assault") in ("breach", "assault"))
        ]
        if maneuver:
            return max(maneuver)
        fallback = [
            unit.x
            for unit in self.living("enemy")
            if unit.combat_effective
            and getattr(unit, "reserve_active", True)
            and (getattr(unit, "attack_assignment", "assault") in ("breach", "assault"))
        ]
        return max(fallback, default=7.0)

    def issue_defense_tactical_order(self, unit):
        destination = self.defense_attack_destination(unit)
        assignment = getattr(unit, "attack_assignment", "assault")
        distance = dist(unit.pos, destination)
        if assignment == "fire_support" and distance <= 2.6:
            facing = angle_to(
                unit, (MAP_W - 2, _operation_defense_sector_center(unit.attack_sector))
            )
            if unit.role in ("Machine Gunner", "HMG Crew"):
                if not unit.deployed:
                    self.toggle_deploy(unit)
                else:
                    self.set_fire_lane(unit, facing, 82)
            else:
                self.set_overwatch(unit, facing, 105)
            return
        if assignment == "sustainment" and distance <= 2.3:
            self.set_overwatch(unit, angle_to(unit, destination), 120)
            return
        if distance > 2.2:
            if unit.role in ("Machine Gunner", "HMG Crew") and unit.deployed:
                self.toggle_deploy(unit)
                return
            mode = (
                "safe"
                if assignment in ("fire_support", "sustainment")
                or unit.suppression > 45
                else "fast"
            )
            formation = "wedge" if assignment in ("breach", "assault") else "column"
            self.issue_move([unit], destination, mode=mode, formation=formation)
        else:
            self.set_overwatch(unit, angle_to(unit, (MAP_W - 2, destination[1])), 110)

    def _operation_update_defense_attack_orders(self, dt):
        if self.mission_type != "defense":
            return
        self._defense_attack_order_timer += dt
        if self._defense_attack_order_timer < 0.75:
            return
        self._defense_attack_order_timer = 0.0
        self.plan_defense_attack()
        for unit in self.living("enemy"):
            if (
                not unit.combat_effective
                or unit.role in STATIC_WEAPON_ROLES
                or (not getattr(unit, "reserve_active", True))
                or (unit.action_timer > 0)
                or (
                    unit.order
                    in ("build", "rout", "medic", "deploy", "pack", "clear_jam")
                )
                or getattr(unit, "_construction_queued", False)
            ):
                continue
            visible = any(
                (
                    target.combat_effective and self.can_see(unit, target)
                    for target in self.living("player")
                )
            )
            if visible:
                continue
            stalled = unit.order in ("idle", "overwatch", "fire_lane") or (
                unit.order == "move" and (not unit.path) and (not unit.waypoints)
            )
            if not stalled:
                continue
            self.issue_defense_tactical_order(unit)

    def _operation_update_defense_stage(self):
        remaining = max(0.0, self.defense_time_limit - self.defense_elapsed)
        if remaining <= 60:
            stage = "FINAL ASSAULT"
        elif self.defense_elapsed >= self.defense_time_limit / 3:
            stage = "HOLD"
        elif self.combat_intensity > 4 or any(
            (self.visible_to("player", unit) for unit in self.living("enemy"))
        ):
            stage = "CONTACT"
        else:
            stage = "PREPARATION"
        if stage != self.battle_stage:
            self.battle_stage = stage
            self.notify(
                stage,
                kind="danger" if stage in ("CONTACT", "FINAL ASSAULT") else "objective",
                duration=4.0,
            )

    def update_defense_mission(self, dt):
        self.defense_elapsed += dt
        self._mission_timer += dt
        self._stability_timer += dt
        self._operation_update_defense_stage()
        if (
            self.defense_elapsed >= self.defense_time_limit * 0.28
            and 2 not in self.defense_wave_announced
        ):
            self.activate_defense_wave(2)
        if (
            self.defense_elapsed >= self.defense_time_limit * 0.62
            and 3 not in self.defense_wave_announced
        ):
            self.activate_defense_wave(3)
        segment = self.defense_time_limit / len(self.objectives)
        active_index = min(
            len(self.objectives) - 1, int(self.defense_elapsed / max(1.0, segment))
        )
        for index, objective in enumerate(self.objectives):
            if index < active_index:
                objective["progress"] = 1.0
                objective["state"] = "complete"
            elif index == active_index:
                objective["progress"] = clamp(
                    (self.defense_elapsed - index * segment) / segment, 0, 1
                )
                objective["state"] = "active"
            else:
                objective["progress"] = 0.0
                objective["state"] = "locked"
        if active_index != self.objective_index:
            self.objective_index = active_index
            self.notify(
                f"NEW OBJECTIVE — {self.objectives[active_index]['title']}",
                kind="objective",
                duration=5.0,
            )
        if self._stability_timer >= 0.5:
            self._stability_timer = 0.0
            for sector in ("NORTH", "CENTRE", "SOUTH"):
                defenders = [
                    unit
                    for unit in self.living("player")
                    if unit.combat_effective
                    and unit.role not in STATIC_WEAPON_ROLES
                    and (_vs_sector_name(unit.y) == sector)
                ]
                attackers = [
                    unit
                    for unit in self.living("enemy")
                    if unit.combat_effective
                    and getattr(unit, "reserve_active", True)
                    and (_vs_sector_name(unit.y) == sector)
                    and (unit.x >= self.primary_line_x - 6)
                ]
                average_suppression = sum(
                    (unit.suppression for unit in defenders)
                ) / max(1, len(defenders))
                self.sector_stability[sector] = clamp(
                    100
                    - len(attackers) * 14
                    - average_suppression * 0.38
                    - max(0, 2 - len(defenders)) * 13,
                    0,
                    100,
                )
        command = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
        attackers = [
            unit
            for unit in self.living("enemy")
            if unit.combat_effective
            and unit.role not in STATIC_WEAPON_ROLES
            and (dist(unit.pos, command) <= 2.7)
        ]
        defenders = [
            unit
            for unit in self.living("player")
            if unit.combat_effective
            and unit.role not in STATIC_WEAPON_ROLES
            and (dist(unit.pos, command) <= 4.2)
        ]
        if attackers and (not defenders):
            self.defense_capture_progress = min(
                18.0, self.defense_capture_progress + dt
            )
        else:
            self.defense_capture_progress = max(
                0.0, self.defense_capture_progress - dt * 1.7
            )
        mobile_player = [
            unit
            for unit in self.living("player")
            if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
        ]
        mobile_enemy = [
            unit
            for unit in self.living("enemy")
            if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
        ]
        if not mobile_player or self.defense_capture_progress >= 18.0:
            self.defeat = True
            self._vs_event("defeat", "The defensive position was overrun", command)
        elif self.defense_elapsed >= self.defense_time_limit or (
            self.defense_elapsed >= 60
            and len(mobile_enemy) <= max(1, int(self.initial_mobile_enemy_total * 0.12))
        ):
            for objective in self.objectives:
                objective["progress"] = 1.0
                objective["state"] = "complete"
            self.objective_index = len(self.objectives)
            self.victory = True
            self._vs_event("victory", "The defensive line held", command)
        remaining_seconds = max(
            0, int(math.ceil(self.defense_time_limit - self.defense_elapsed))
        )
        remaining_minutes = int(math.ceil(remaining_seconds / 60))
        if remaining_seconds > 0 and remaining_minutes != self._defense_last_minute:
            self._defense_last_minute = remaining_minutes
            self.notify(
                f"HOLD FOR {remaining_minutes} MORE MINUTE{('S' if remaining_minutes != 1 else '')}",
                kind="objective",
                duration=3.0,
            )
        self.notifications = [
            item for item in self.notifications if item["until"] > self.time
        ]

    def update_mission_state(self, dt):
        if self.mission_type == "defense":
            return self.update_defense_mission(dt)
        return self._perf_mission_update(dt)

    def check_end(self):
        if self.mission_type != "defense":
            return self._base_check_end()
        players = [
            unit
            for unit in self.living("player")
            if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
        ]
        enemies = [
            unit
            for unit in self.living("enemy")
            if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
        ]
        if not enemies:
            self.victory = True
        if not players:
            self.defeat = True

    def deploy_player_reserves(self):
        if self.mission_type != "defense":
            return self._kz_deploy_reserves()
        if not self.player_reserves:
            return []
        roles = list(self.player_reserves)
        self.player_reserves = []
        new_units = []
        base_y = int(clamp(self.rally_points["player"][1], 3, MAP_H - 4))
        for index, role in enumerate(roles):
            unit = self.add_unit("player", role, MAP_W - 3, base_y)
            desired_y = int(
                clamp(base_y + index // 3 * 2 - len(roles) // 3, 2, MAP_H - 3)
            )
            position = _operation_open_position(
                self, MAP_W - 3 - index % 3, desired_y, unit, radius=6
            )
            if position:
                unit.x, unit.y = position
            unit.facing = 180
            unit.reserve = True
            new_units.append(unit)
            key = ("player", max(1, int(getattr(unit, "squad_id", 1))))
            self.squad_doctrine.setdefault(key, "balanced")
        self.stats["player"]["reserves"] += len(new_units)
        self._kz_rebuild_indexes()
        self.add_log(f"{len(new_units)} reserve unit(s) entered from the east.")
        self._kz_event_record(
            "reserve", f"{len(new_units)} reserves committed", (MAP_W - 3, base_y)
        )
        return new_units

    def toggle_deploy(self, unit):
        if unit.faction == "enemy" and self.time < unit.polish_deploy_lock_until:
            return False
        was_deployed = bool(unit.deployed)
        result = self._base_toggle_deploy(unit)
        if bool(unit.deployed) != was_deployed or unit.order in ("deploy", "pack"):
            unit.polish_deploy_lock_until = self.time + 3.0
            unit.polish_plan_commit_until = max(
                unit.polish_plan_commit_until, self.time + 2.4
            )
            unit.polish_order_state = "DEPLOYING" if not was_deployed else "PACKING"
            unit.polish_order_state_until = self.time + 1.2
        return result
