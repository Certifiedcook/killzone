"""Systems / tactics for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _combat2_wound_penalties
from engine.rules import _operation_open_position
from engine.rules import _vs_sector_name
from engine.rules import angle_diff
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import dist
from engine.rules import squad_role_group
from engine.rules import unit_is_firing_while_moving
from engine.definitions import AUTO_SQUAD_LIMIT
from engine.definitions import AUTO_SQUAD_SIZE
from engine.definitions import COMBAT2_STATIC_ROLES
from engine.definitions import COMBAT2_SUPPORT_ROLES
from engine.definitions import COMBAT2_SUSTAINMENT_ROLES
from engine.definitions import COMBAT_POLISH_COMMIT_ORDERS
from engine.definitions import DIFFICULTY
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MOVING_FIRE_ACCURACY_PENALTY
from engine.definitions import ROLES
from engine.definitions import ROLE_CONTACT
from engine.definitions import SQUAD_DOCTRINES
from engine.definitions import STANCE
from engine.definitions import STATIC_WEAPON_ROLES
from engine.definitions import TERRAIN
from engine.definitions import _SQUAD_FALLBACK_AFFINITY
from engine.models import Unit
from typing import Tuple
import math
import time


class TacticsSystem:
    def _base_line_info(self, a, b) -> Tuple[bool, float, int, float]:
        """clear, smoke density, soft penetration cost, maximum intervening height."""
        smoke = 0.0
        soft_pen = 0
        max_h = -9
        cells = self.line_cells(a, b)
        for x, y in cells[1:-1]:
            c = self.grid[y][x]
            smoke += c.smoke
            if c.terrain == "hill":
                max_h = max(max_h, TERRAIN[c.terrain]["height"])
            if c.terrain == "door" and (not c.door_open):
                return (False, smoke, 99, max_h)
            if c.terrain in ("woods", "sandbags", "door", "woodwall", "window"):
                soft_pen += TERRAIN[c.terrain]["pen"]
            elif TERRAIN[c.terrain]["blocks"]:
                return (False, smoke, 99, max_h)
        sh = TERRAIN[self.grid[int(round(a[1]))][int(round(a[0]))].terrain]["height"]
        th = TERRAIN[self.grid[int(round(b[1]))][int(round(b[0]))].terrain]["height"]
        if max_h > max(sh, th) and len(cells) > 3:
            return (False, smoke, soft_pen, max_h)
        return (True, smoke, soft_pen, max_h)

    def _base_can_see(self, observer: Unit, target: Unit) -> bool:
        if not observer.combat_effective or not target.alive:
            return False
        d = dist(observer, target)
        oh = TERRAIN[self.grid[observer.tile[1]][observer.tile[0]].terrain]["height"]
        th = TERRAIN[self.grid[target.tile[1]][target.tile[0]].terrain]["height"]
        role_spot = (
            ROLES[observer.role]["spot"]
            + STANCE[observer.stance]["spot"]
            + max(0, oh - th) * 2.0
        )
        conceal = (
            TERRAIN[self.grid[target.tile[1]][target.tile[0]].terrain]["conceal"] / 10
        )
        if target.stance == "prone":
            conceal += 2.0
        if target.signature > 0:
            conceal -= min(3.0, target.signature / 18)
        if self.weather == "fog":
            role_spot -= 3.0
        if d > role_spot - conceal:
            return False
        clear, smoke, _, _ = self.line_info(observer.pos, target.pos)
        if not clear or smoke >= 2.1:
            return False
        if self.trench_corner_blocked(observer, target):
            return False
        return True

    def _base_update_spotting(self):
        for target in self.living():
            for faction in ("player", "enemy"):
                if target.faction == faction:
                    continue
                observers = [u for u in self.living(faction) if u.combat_effective]
                if any((self.can_see(o, target) for o in observers)):
                    if faction == "player":
                        target.spotted_player_until = self.time + 2.2
                    else:
                        target.spotted_enemy_until = self.time + 2.2
                    self.intel[faction][target.uid] = {
                        "pos": (target.x, target.y),
                        "seen": self.time,
                        "role": target.role,
                    }
        for u in self.living():
            if u.role not in ("Engineer", "Recon"):
                continue
            ux, uy = u.tile
            radius = 3 if u.role == "Engineer" else 2
            for y in range(max(0, uy - radius), min(MAP_H, uy + radius + 1)):
                for x in range(max(0, ux - radius), min(MAP_W, ux + radius + 1)):
                    if self.grid[y][x].mine and math.hypot(x - ux, y - uy) <= radius:
                        if u.faction == "player":
                            self.grid[y][x].mine_seen_player = True
                        else:
                            self.grid[y][x].mine_seen_enemy = True

    def known_contacts(self, faction: str, memory: float = 10.0):
        out = []
        stale = []
        for uid, info in self.intel[faction].items():
            age = self.time - info["seen"]
            if age > memory:
                stale.append(uid)
                continue
            out.append((uid, info, age))
        for uid in stale:
            self.intel[faction].pop(uid, None)
        return out

    def _base_tile_threat(self, faction: str, x: int, y: int) -> float:
        threat = 0.0
        enemy_faction = "enemy" if faction == "player" else "player"
        for e in self.living(enemy_faction):
            if not e.combat_effective:
                continue
            if faction == "player" and (not self.visible_to("player", e)):
                continue
            if faction == "enemy" and (not self.visible_to("enemy", e)):
                continue
            d = math.hypot(e.x - x, e.y - y)
            if d > e.weapon["range"] + 1.5:
                continue
            local = max(0.15, 1.25 - d / max(1.0, e.weapon["range"]))
            bearing = angle_to(e, (x, y))
            if (e.overwatch or e.fire_lane) and angle_diff(
                e.fire_lane_center, bearing
            ) <= e.arc_width / 2:
                local += 0.9
            if e.role in ("Machine Gunner", "HMG Crew"):
                local += 0.35
            threat += local
        return threat

    def _base_update_cohesion_and_morale(self, dt):
        for u in self.living():
            allies = [
                a
                for a in self.living(u.faction)
                if a.uid != u.uid and a.combat_effective
            ]
            near = sum((1 for a in allies if dist(a, u) <= 5))
            ux, uy = u.tile
            junction = 0
            if self.grid[uy][ux].terrain == "trench":
                junction = sum(
                    (
                        1
                        for nx, ny in (
                            (ux + 1, uy),
                            (ux - 1, uy),
                            (ux, uy + 1),
                            (ux, uy - 1),
                        )
                        if self.in_bounds(nx, ny)
                        and self.grid[ny][nx].terrain == "trench"
                    )
                )
            target = clamp(35 + near * 16 + (12 if junction >= 3 else 0), 20, 100)
            u.cohesion += (target - u.cohesion) * dt * 0.12
            if u.suppression < 20 and u.cohesion > 60:
                u.morale = clamp(u.morale + dt * 0.8, 0, 100)

    def _base_handle_break(self, u: Unit):
        enemies = self.living("enemy" if u.faction == "player" else "player")
        nearest = min((dist(u, e) for e in enemies), default=99)
        allies = sum(
            (
                1
                for a in self.living(u.faction)
                if a.uid != u.uid and dist(a, u) < 5 and a.combat_effective
            )
        )
        if nearest < 4 and allies == 0 and (u.morale < 12):
            u.casualty = "surrendered"
            u.order = "surrender"
            u.path = []
            u.waypoints = []
            self.add_log(f"{u.faction} {u.role} surrendered.")
            for ally in self.living(u.faction):
                if ally.uid != u.uid and dist(ally, u) < 6:
                    ally.morale = max(0, ally.morale - 10)
                    ally.suppression = clamp(ally.suppression + 6, 0, 100)
            return
        rx, ry = self.rally_points.get(
            u.faction,
            (
                1 if u.faction == "player" else MAP_W - 2,
                int(clamp(round(u.y), 1, MAP_H - 2)),
            ),
        )
        y = int(clamp(round((ry + u.y) / 2), 1, MAP_H - 2))
        x = rx
        u.move_mode = "safe"
        u.waypoints = [(x, y)]
        u.path = []
        u.order = "rout"
        u.stance = "standing"

    def choose_auto_target(self, u: Unit):
        enemies = []
        weapon_range = u.weapon["range"]
        for enemy in self.living("enemy" if u.faction == "player" else "player"):
            if not enemy.combat_effective or not self.visible_to(u.faction, enemy):
                continue
            distance = dist(u, enemy)
            if distance <= weapon_range and self.can_see(u, enemy):
                enemies.append((enemy, distance))
        if not enemies:
            return None
        if u.target_priority == "nearest":
            return min(enemies, key=lambda candidate: candidate[1])[0]
        if u.target_priority == "exposed":
            return min(
                enemies,
                key=lambda candidate: (
                    self.effective_cover(u, candidate[0]),
                    candidate[1],
                ),
            )[0]
        if u.target_priority == "suppressed":
            return max(
                enemies, key=lambda candidate: (candidate[0].suppression, -candidate[1])
            )[0]
        return min(
            enemies,
            key=lambda candidate: (
                0
                if candidate[0].role
                in ("Machine Gunner", "HMG Crew", "Sniper", "Medic", "Mortar Team")
                else 1,
                candidate[1],
            ),
        )[0]

    def _base_ai_decide(self, u: Unit):
        if u.jammed:
            self.clear_jam(u)
            return
        if u.ammo <= 0 and u.magazines:
            self.start_reload(u)
            return
        if (
            u.heat > 88
            and u.barrel_spares > 0
            and (u.role in ("Machine Gunner", "HMG Crew"))
        ):
            self.change_barrel(u)
            return
        cross = self.crossfire_pressure(u)
        if (u.suppression > 74 or u.morale < 34 or cross > 0.55) and u.order not in (
            "rout",
            "move",
        ):
            if (
                u.auto_smoke
                and u.smoke_grenades > 0
                and (self.grid[u.tile[1]][u.tile[0]].smoke < 1.0)
                and (self.difficulty == "Veteran" or u.suppression > 84)
            ):
                self.throw_grenade(u, u.pos, smoke=True)
                return
            dest = self.find_nearby_cover(u, 5)
            if dest and dest != u.tile:
                if u.deployed and u.role in ("Machine Gunner", "HMG Crew"):
                    self.toggle_deploy(u)
                    return
                self.issue_move([u], dest, mode="safe", formation="column")
                return
        if u.role == "Medic" and u.med_supplies > 0:
            wounded = [
                a
                for a in self.living("enemy")
                if a.uid != u.uid and a.casualty in ("wounded", "incapacitated")
            ]
            if wounded:
                t = min(wounded, key=lambda a: dist(u, a))
                if dist(u, t) <= 1.5:
                    self.medic_action(u, t)
                    return
                if dist(u, t) < 7:
                    self.issue_move([u], t.tile, mode="safe")
                    return
        visible = [
            p
            for p in self.living("player")
            if p.combat_effective and self.can_see(u, p)
        ]
        if visible:
            target = min(
                visible,
                key=lambda p: (
                    0 if p.role in ("Machine Gunner", "Sniper", "Medic") else 1,
                    dist(u, p),
                ),
            )
            d = dist(u, target)
            if u.smoke_grenades > 0 and u.suppression > 60 and (d < 6):
                self.throw_grenade(u, u.pos, smoke=True)
                return
            if u.grenades > 0 and d < 4.2 and (self.effective_cover(u, target) >= 2):
                self.throw_grenade(u, target.pos, cook=0.7)
                return
            if u.rifle_grenades > 0 and 4 < d < 7:
                self.throw_grenade(u, target.pos, rifle=True)
                return
            nearby_target_allies = sum(
                (
                    1
                    for a in self.living("player")
                    if a.uid != target.uid
                    and a.combat_effective
                    and (dist(a, target) < 4)
                )
            )
            if (
                u.role in ("Assault", "Rifleman")
                and target.x > MAP_W - 13
                and (target.suppression > 55)
                and (nearby_target_allies <= 1)
                and (d < 5)
            ):
                nx = int(clamp(round(target.x + 1.5), 1, MAP_W - 2))
                ny = int(clamp(round(target.y), 1, MAP_H - 2))
                if self.passable(nx, ny, u):
                    self.issue_move([u], (nx, ny), mode="safe", formation="column")
                    return
            if u.role in ("Machine Gunner", "HMG Crew"):
                if not u.deployed:
                    self.toggle_deploy(u)
                    return
                if target.suppression < 60:
                    self.suppress_area(u, target.pos)
                    return
            if u.role == "Sniper":
                self.issue_fire(u, target, "aimed")
                return
            if u.role == "Assault" and d < 3:
                self.issue_fire(u, target, "rapid")
                return
            if d <= u.weapon["range"]:
                mode = "aimed" if d > 7 and u.suppression < 35 else "normal"
                self.issue_fire(u, target, mode)
                return
        contacts = self.known_contacts("enemy", memory=9.0)
        if contacts:
            _, info, _ = min(
                contacts,
                key=lambda z: math.hypot(u.x - z[1]["pos"][0], u.y - z[1]["pos"][1]),
            )
            tx, ty = info["pos"]
            dx = tx - u.x
            dy = ty - u.y
            side = self.rng.choice([-1, 1])
            length = max(1, math.hypot(dx, dy))
            fx = int(clamp(tx + side * (-dy / length) * 4, 1, MAP_W - 2))
            fy = int(clamp(ty + side * (dx / length) * 4, 1, MAP_H - 2))
            if self.rng.random() < 0.55:
                self.issue_move([u], (fx, fy), mode="safe")
            else:
                self.set_overwatch(u, angle_to(u, (tx, ty)), 90)
        else:
            c = self.grid[u.tile[1]][u.tile[0]]
            if u.role in ("Machine Gunner", "HMG Crew") and c.cover_wear > 0.65:
                if u.deployed:
                    self.toggle_deploy(u)
                else:
                    dest = self.find_nearby_cover(u, 5)
                    if dest:
                        self.issue_move([u], dest, mode="safe", formation="column")
                return
            if u.role in ("Machine Gunner", "HMG Crew") and u.deployed:
                self.set_fire_lane(u, 180, 60)
            else:
                self.set_overwatch(u, 180, 120)

    def _kz_compute_threat_grid(self, faction):
        grid = [[0.0 for _ in range(MAP_W)] for _ in range(MAP_H)]
        enemy = "enemy" if faction == "player" else "player"
        for e in self.living(enemy):
            if not e.combat_effective or not self.visible_to(faction, e):
                continue
            r = int(math.ceil(e.weapon["range"] + 1.5))
            ex, ey = e.tile
            y0 = max(0, ey - r)
            y1 = min(MAP_H, ey + r + 1)
            x0 = max(0, ex - r)
            x1 = min(MAP_W, ex + r + 1)
            for y in range(y0, y1):
                dy = y - e.y
                for x in range(x0, x1):
                    d = math.hypot(x - e.x, dy)
                    if d > e.weapon["range"] + 1.5:
                        continue
                    local = max(0.15, 1.25 - d / max(1.0, e.weapon["range"]))
                    bearing = angle_to(e, (x, y))
                    if (e.overwatch or e.fire_lane) and angle_diff(
                        e.fire_lane_center, bearing
                    ) <= e.arc_width / 2:
                        local += 0.9
                    if e.role in ("Machine Gunner", "HMG Crew"):
                        local += 0.35
                    grid[y][x] += local
        self._threat_grids[faction] = grid

    def tile_threat(self, faction, x, y):
        if not self.in_bounds(x, y):
            return 99.0
        if self.time - getattr(
            self, "_threat_cache_time", -999
        ) > 0.35 or faction not in getattr(self, "_threat_grids", {}):
            self._threat_cache_time = self.time
            self._threat_grids = {}
            self._kz_compute_threat_grid("player")
            self._kz_compute_threat_grid("enemy")
        return self._threat_grids[faction][y][x]

    def _kz_can_see(self, observer, target):
        if (
            target.role == "Sniper"
            and target.prepared > 0.6
            and (target.signature < 10)
            and target.combat_effective
        ):
            d = dist(observer, target)
            if d > max(5.5, ROLES[observer.role]["spot"] * 0.7):
                return False
        return self._base_can_see(observer, target)

    def _kz_handle_break_ext(self, u):
        before = u.casualty
        self._base_handle_break(u)
        if before != "surrendered" and u.casualty == "surrendered":
            self.stats[u.faction]["surrendered"] += 1
            self._kz_event_record(
                "surrender", f"{u.faction} {u.role} surrendered", u.pos
            )

    def _kz_ai_decide(self, u):
        visible = [
            p
            for p in self.living("player")
            if p.combat_effective and self.can_see(u, p)
        ]
        if visible:
            target = min(
                visible,
                key=lambda p: (
                    0
                    if p.role in ("Machine Gunner", "HMG Crew", "Sniper", "Medic")
                    else 1,
                    dist(u, p),
                ),
            )
            mates = [
                a
                for a in self.living("enemy")
                if a.uid != u.uid
                and a.combat_effective
                and (getattr(a, "squad_id", 0) == getattr(u, "squad_id", -1))
            ]
            support_active = any((a.order == "suppress" or a.fire_lane for a in mates))
            tactics = DIFFICULTY[self.difficulty].get("tactics", 1)
            if (
                u.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman")
                and target.suppression < 65
            ):
                if u.role in ("Machine Gunner", "HMG Crew") and (not u.deployed):
                    self.toggle_deploy(u)
                    return
                self.suppress_area(u, target.pos)
                return
            if (
                support_active
                and u.role in ("Rifleman", "Assault", "Grenadier", "Engineer")
                and (dist(u, target) > 3)
                and (self.rng.random() < 0.32 * tactics)
            ):
                dx = target.x - u.x
                dy = target.y - u.y
                ln = max(1, math.hypot(dx, dy))
                side = -1 if getattr(u, "squad_id", 0) % 2 else 1
                fx = int(clamp(target.x + side * (-dy / ln) * 4.5, 1, MAP_W - 2))
                fy = int(clamp(target.y + side * (dx / ln) * 4.5, 1, MAP_H - 2))
                if (
                    self.tile_threat("enemy", fx, fy)
                    < self.tile_threat("enemy", *u.tile) + 0.8
                ):
                    if (
                        u.smoke_grenades > 0
                        and self.tile_threat("enemy", fx, fy) > 1.0
                        and (self.rng.random() < 0.35 * tactics)
                    ):
                        self.throw_grenade(
                            u, ((u.x + fx) / 2, (u.y + fy) / 2), smoke=True
                        )
                    self.issue_move([u], (fx, fy), mode="safe", formation="column")
                    return
        if (
            u.role == "Sniper"
            and getattr(u, "shots_recent", 0) >= 3
            and (u.signature > 12)
            and (u.order not in ("move", "rout"))
        ):
            dest = self.find_nearby_cover(u, 6)
            if dest and dest != u.tile:
                u.shots_recent = 0
                self.issue_move([u], dest, mode="safe", formation="column")
                return
        if (
            u.suppression > 74 or u.morale < 34 or self.crossfire_pressure(u) > 0.55
        ) and getattr(u, "fallback_point", None):
            fp = u.fallback_point
            if self.passable(*fp, u):
                if u.deployed and u.role in ("Machine Gunner", "HMG Crew"):
                    self.toggle_deploy(u)
                    return
                self.issue_move([u], fp, mode="safe", formation="column")
                return
        self._base_ai_decide(u)

    def _vs_update_spotting(self):
        self._base_update_spotting()
        for uid, info, age in self.known_contacts("player", memory=10):
            if age > 0.08:
                continue
            last = self._contact_last_report.get(uid, -999)
            if self.time - last < 8:
                continue
            self._contact_last_report[uid] = self.time
            role = ROLE_CONTACT.get(info.get("role", ""), "INFANTRY")
            sec = _vs_sector_name(info["pos"][1])
            self.notify(f"CONTACT — {role}, {sec}", kind="danger", duration=3.8)
            self._vs_event("contact", f"Contact: {role}, {sec}", info["pos"])

    def _vs_ai_decide(self, u):
        if u.faction == "enemy":
            role = getattr(u, "initial_battle_role", "forward")
            if role == "reserve" and (not getattr(u, "reserve_active", True)):
                if u.role in ("Machine Gunner", "HMG Crew") and (not u.deployed):
                    self.toggle_deploy(u)
                    return
                if u.order not in ("overwatch", "deploy"):
                    self.set_overwatch(u, 180, 105)
                return
            if getattr(u, "plan_state", "") == "counterattack" and getattr(
                u, "counterattack_point", None
            ):
                point = u.counterattack_point
                visible = [
                    p
                    for p in self.living("player")
                    if p.combat_effective and self.can_see(u, p)
                ]
                if (
                    not visible
                    and dist(u.pos, point) > 2.5
                    and (u.order in ("idle", "overwatch"))
                ):
                    self.issue_move([u], point, mode="safe", formation="column")
                    return
            if role == "command" and self.objective_index < 3:
                visible = [
                    p
                    for p in self.living("player")
                    if p.combat_effective and self.can_see(u, p)
                ]
                if not visible:
                    if u.order not in ("overwatch", "deploy"):
                        self.set_overwatch(u, 180, 120)
                    return
            if (
                getattr(u, "battle_sector", "") in self.collapsed_sectors
                and u.x < self.secondary_line_x - 0.5
                and (u.order not in ("move", "rout"))
            ):
                fp = (self.secondary_line_x, int(clamp(round(u.y), 2, MAP_H - 3)))
                if self.passable(*fp, u):
                    self.issue_move([u], fp, mode="safe", formation="column")
                    return
        self._kz_ai_decide(u)

    def _vs_shot_breakdown(self, a, t, mode=None, reaction=False):
        mode = mode or a.fire_mode
        w = a.weapon
        d = dist(a, t)
        mods = []
        clear, smoke, soft_pen, _ = self.line_info(a.pos, t.pos)
        if not clear:
            return {"chance": 0, "mods": [("LINE OF SIGHT", -999)]}
        base = float(w["acc"])
        mods.append(("weapon base", base))
        range_mod = -max(0, d - 2) * 2.8
        mods.append(("range", range_mod))
        cover_mod = -self.effective_cover(a, t) * 9
        mods.append(("cover", cover_mod))
        stance = STANCE[a.stance]["acc"] + STANCE[t.stance]["hit"]
        mods.append(("stance", stance))
        supp = -a.suppression * 0.32
        mods.append(("shooter suppression", supp))
        prep = a.prepared * 7
        mods.append(("prepared", prep))
        smoke_mod = -smoke * 19
        mods.append(("smoke", smoke_mod))
        pen = -soft_pen * 7
        mods.append(("intervening cover", pen))
        if mode == "snap":
            mods.append(("snap fire", -16))
        elif mode == "aimed":
            mods.append(("aimed fire", 18 + a.aim_progress * 10))
        elif mode == "rapid":
            mods.append(("rapid fire", -12))
        incoming = angle_to(t, a)
        flank = angle_diff(t.facing, incoming)
        if flank > 125:
            mods.append(("rear attack", 22))
        elif flank > 75:
            mods.append(("flank attack", 11))
        tc = self.grid[t.tile[1]][t.tile[0]]
        if tc.terrain in ("trench", "firing_step") and tc.axis:
            shot = angle_to(t, a)
            axis_deg = 0 if tc.axis == "H" else 90
            along = min(angle_diff(shot, axis_deg), angle_diff(shot, axis_deg + 180))
            if along < 28:
                mods.append(("enfilade", 12))
        if d <= 2.2 and a.role == "Assault":
            mods.append(("assault CQB", 18))
        if self.weather == "rain":
            mods.append(("rain", -3))
        elif self.weather == "fog":
            mods.append(("fog", -7))
        return {
            "chance": self.hit_chance(a, t, mode, reaction),
            "range": d,
            "smoke": smoke,
            "soft_pen": soft_pen,
            "mods": mods,
        }

    def choose_retreat_position(self, u, extra_rear=False):
        fp = getattr(u, "fallback_point", None)
        if fp and self.in_bounds(*fp) and self.passable(*fp, u):
            return fp
        ux, uy = u.tile
        direction = -1 if u.faction == "player" else 1
        best = None
        best_score = -1000000000.0
        radius = 11 if extra_rear else 8
        for y in range(max(1, uy - radius), min(MAP_H - 1, uy + radius + 1)):
            for x in range(max(1, ux - radius), min(MAP_W - 1, ux + radius + 1)):
                if not self.passable(x, y, u):
                    continue
                dx = (x - ux) * direction
                if dx < 1 and (not extra_rear):
                    continue
                d = math.hypot(x - ux, y - uy)
                if d < 2.0:
                    continue
                c = self.grid[y][x]
                cover = TERRAIN[c.terrain]["cover"]
                th = self.tile_threat(u.faction, x, y)
                terrain_bonus = (
                    3.5
                    if c.terrain in ("trench", "firing_step", "dugout", "bunker")
                    else 2.0
                    if c.terrain in ("foxhole", "sandbags", "crater", "woods")
                    else 0
                )
                score = (
                    cover * 3.0
                    + terrain_bonus
                    + dx * (0.45 if extra_rear else 0.28)
                    - th * 3.2
                    - c.ground_suppression * 0.035
                    - d * 0.2
                )
                if score > best_score:
                    best_score = score
                    best = (x, y)
        if best:
            return best
        return self.rally_points.get(
            u.faction,
            (2 if u.faction == "player" else MAP_W - 3, int(clamp(uy, 1, MAP_H - 2))),
        )

    def morale_breakdown(self, u):
        allies = [
            a
            for a in self.living(u.faction)
            if a.uid != u.uid and a.combat_effective and (dist(a, u) < 5)
        ]
        cross = self.crossfire_pressure(u)
        c = self.grid[u.tile[1]][u.tile[0]]
        cover = max(0, TERRAIN[c.terrain]["cover"] - c.cover_wear * 2.2)
        factors = [
            ("suppression", u.suppression * 0.34),
            ("cohesion loss", (100 - u.cohesion) * 0.2),
            ("recent casualty shock", getattr(u, "rally_shock", 0) * 0.7),
            ("crossfire", cross * 18),
        ]
        if not allies:
            factors.append(("isolated", 12))
        else:
            factors.append(("nearby squadmates", -min(18, len(allies) * 4.5)))
        if cover > 0:
            factors.append(("protected position", -cover * 3.0))
        sm = getattr(u, "squad_morale", 50)
        if sm >= 65:
            factors.append(("squad confidence", -8))
        elif sm < 35:
            factors.append(("squad shaken", 8))
        return factors

    def update_unit_morale_state(self, u):
        if u.casualty == "surrendered":
            state = "SURRENDERED"
        elif u.order == "rout":
            state = "ROUTING"
        elif getattr(u, "rallying", False):
            state = "RALLYING"
        elif u.suppression >= 80:
            state = "PINNED"
        elif u.morale < 24 or u.cohesion < 35:
            state = (
                "BREAKING"
                if u.low_morale_since is not None and self.time - u.low_morale_since > 3
                else "SHAKEN"
            )
        elif u.morale < 58 or u.cohesion < 58 or u.suppression >= 42:
            state = "SHAKEN"
        else:
            state = "STEADY"
        u.morale_state = state
        return state

    def line_info(self, a, b):
        tick = int(self.time * 10)
        key = (
            round(a[0], 1),
            round(a[1], 1),
            round(b[0], 1),
            round(b[1], 1),
            self.terrain_revision,
            tick,
        )
        cached = self._line_cache.get(key)
        prof = getattr(self, "profile_enabled", False)
        if cached is not None:
            if prof:
                self._perf["line_hits"] = self._perf.get("line_hits", 0) + 1
            return cached
        t0 = time.perf_counter() if prof else 0
        out = self._base_line_info(a, b)
        self._line_cache[key] = out
        if len(self._line_cache) > 900:
            self._line_cache.clear()
            self._line_cache[key] = out
        if prof:
            self._perf["line_calls"] = self._perf.get("line_calls", 0) + 1
            self._perf["los_ms"] = (
                self._perf.get("los_ms", 0) + (time.perf_counter() - t0) * 1000
            )
        return out

    def can_see(self, observer, target):
        if not observer.combat_effective or not target.alive:
            return False
        tick = int(self.time * 8)
        key = (
            observer.uid,
            target.uid,
            observer.tile,
            target.tile,
            observer.stance,
            target.stance,
            self.terrain_revision,
            tick,
        )
        cached = self._los_cache.get(key)
        prof = getattr(self, "profile_enabled", False)
        if cached is not None:
            if prof:
                self._perf["los_hits"] = self._perf.get("los_hits", 0) + 1
            return cached
        t0 = time.perf_counter() if prof else 0
        out = self._kz_can_see(observer, target)
        self._los_cache[key] = out
        if len(self._los_cache) > 700:
            self._los_cache.clear()
            self._los_cache[key] = out
        if prof:
            self._perf["los_calls"] = self._perf.get("los_calls", 0) + 1
            self._perf["los_ms"] = (
                self._perf.get("los_ms", 0) + (time.perf_counter() - t0) * 1000
            )
        return out

    def update_cohesion_and_morale(self, dt):
        self._base_update_cohesion_and_morale(dt)
        active = [u for u in self.units if u.alive and u.combat_effective]
        by_faction = {"player": [], "enemy": []}
        groups = {}
        for u in active:
            by_faction.setdefault(u.faction, []).append(u)
            groups.setdefault((u.faction, getattr(u, "squad_id", 0)), []).append(u)
        for members in groups.values():
            inv = 1.0 / max(1, len(members))
            squad = clamp(
                sum(
                    (
                        m.morale * 0.5
                        + m.cohesion * 0.35
                        + (100 - m.suppression) * 0.15
                        for m in members
                    )
                )
                * inv,
                0,
                100,
            )
            for u in members:
                u.squad_morale = squad
        for u in active:
            cell = self.grid[u.tile[1]][u.tile[0]]
            safe = (
                u.under_fire_until <= self.time
                and cell.ground_suppression < 18
                and (u.suppression < 38)
            )
            ux, uy = (u.x, u.y)
            near = 0
            for a in by_faction.get(u.faction, ()):
                if a.uid != u.uid:
                    dx = a.x - ux
                    dy = a.y - uy
                    if dx * dx + dy * dy < 25:
                        near += 1
            if safe:
                rec = dt * (
                    1.15
                    + min(4, TERRAIN[cell.terrain]["cover"]) * 0.18
                    + min(3, near) * 0.12
                )
                u.morale = clamp(u.morale + rec, 0, 100)
                u.cohesion = clamp(u.cohesion + dt * (0.45 + near * 0.1), 0, 100)
                if u.rally_shock > 0:
                    refund = min(u.rally_shock, dt * 0.95)
                    u.rally_shock -= refund
                    u.morale = clamp(u.morale + refund * 0.65, 0, 100)
            else:
                u.rally_shock = max(0, u.rally_shock - dt * 0.12)
            severe = u.morale < 24 and (u.suppression > 65 or u.cohesion < 45)
            if severe and u.low_morale_since is None:
                u.low_morale_since = self.time
            elif not severe and u.morale > 30 and (u.suppression < 68):
                u.low_morale_since = None
                u.breaking_since = None
            self.update_unit_morale_state(u)

    def handle_break(self, u):
        if not u.combat_effective:
            return
        now = self.time
        cross = self.crossfire_pressure(u)
        if u.suppression >= 88:
            u.morale_state = "PINNED"
            u.overwatch = False
            u.fire_lane = False
            u.stance = "prone"
            if u.order in ("overwatch", "fire_lane", "fire") and u.suppression >= 94:
                u.order = "idle"
                u.target_uid = None
                u.target_pos = None
            if (
                u.suppression >= 95
                and (not getattr(u, "hold_position", False))
                and u.auto_cover
                and (now >= getattr(u, "survival_react_at", 0))
            ):
                u.survival_react_at = now + 2.2
                dest = self.find_nearby_cover(u, 3)
                if dest and dest != u.tile:
                    self.issue_move([u], dest, mode="safe", formation="column")
        severe = u.morale < 16 and (
            u.cohesion < 48 or u.suppression > 86 or cross > 0.55
        )
        catastrophic = u.morale < 6 and u.cohesion < 28
        if not severe and (not catastrophic):
            return
        if u.low_morale_since is None:
            u.low_morale_since = now
        elapsed = now - u.low_morale_since
        allies = sum(
            (
                1
                for a in self.living(u.faction)
                if a.uid != u.uid and a.combat_effective and (dist(a, u) < 5)
            )
        )
        delay = 7.0
        if getattr(u, "squad_morale", 50) >= 60:
            delay += 2.0
        elif getattr(u, "squad_morale", 50) < 28:
            delay -= 1.2
        if allies == 0:
            delay -= 1.0
        if cross > 0.65:
            delay -= 0.8
        if getattr(u, "hold_position", False):
            delay += 3.5
        if catastrophic:
            delay = min(delay, 5.0 if getattr(u, "hold_position", False) else 3.5)
        u.breaking_since = u.low_morale_since
        u.morale_state = "BREAKING" if elapsed >= delay * 0.45 else "PINNED"
        if elapsed < delay:
            return
        enemies = [
            e
            for e in self.living("enemy" if u.faction == "player" else "player")
            if e.combat_effective
        ]
        nearest = min((dist(u, e) for e in enemies), default=99)
        if (
            nearest < 3.4
            and allies == 0
            and (u.morale < 7)
            and (not getattr(u, "hold_position", False))
        ):
            u.casualty = "surrendered"
            u.order = "surrender"
            self.cleanup_unit_state(u, "surrender")
            if hasattr(self, "stats"):
                self.stats[u.faction]["surrendered"] += 1
            self.add_log(f"{u.faction} {u.role} surrendered after isolation.")
            if hasattr(self, "_vs_event"):
                self._vs_event(
                    "surrender",
                    f"{getattr(u, 'display_name', u.role)} surrendered",
                    u.pos,
                )
            return
        dest = self.choose_retreat_position(
            u, extra_rear=u.role in ("Medic", "Mortar Team", "Sniper")
        )
        u.move_mode = "safe"
        u.waypoints = [dest]
        u.path = []
        u.order = "rout"
        u.rout_started_at = now
        u.rally_target = dest
        u.rallying = False
        u.rally_safe_since = None
        u.stance = "standing"
        u.overwatch = False
        u.fire_lane = False
        self.add_log(
            f"{getattr(u, 'display_name', u.role)} breaking — falling back to cover."
        )

    def _perf_ai_decide3(self, u):
        if u.faction == "enemy" and u.combat_effective:
            compromised = getattr(u, "battle_sector", "") in getattr(
                self, "collapsed_sectors", set()
            ) or getattr(u, "morale_state", "") in ("BREAKING", "ROUTING")
            if compromised and u.order not in ("rout", "move", "pack", "deploy"):
                if u.role in ("Machine Gunner", "HMG Crew") and u.deployed:
                    self.toggle_deploy(u)
                    return
                if u.role in ("Medic", "Mortar Team", "Sniper"):
                    dest = self.choose_retreat_position(u, extra_rear=True)
                    if dest and dest != u.tile:
                        self.issue_move([u], dest, mode="safe", formation="column")
                        return
        self._vs_ai_decide(u)

    def auto_squad_for(self, faction, role):
        desired = squad_role_group(role)
        existing = [unit for unit in self.units if unit.faction == faction]
        history = {squad_id: [] for squad_id in range(1, AUTO_SQUAD_LIMIT + 1)}
        active = {squad_id: [] for squad_id in range(1, AUTO_SQUAD_LIMIT + 1)}
        for unit in existing:
            squad_id = getattr(unit, "squad_id", 0)
            if squad_id not in history:
                continue
            history[squad_id].append(unit)
            if unit.combat_effective:
                active[squad_id].append(unit)
        available = [
            squad_id for squad_id in history if len(active[squad_id]) < AUTO_SQUAD_SIZE
        ]
        matching = []
        for squad_id in available:
            same = sum(
                (squad_role_group(unit.role) == desired for unit in history[squad_id])
            )
            if same:
                foreign = len(history[squad_id]) - same
                matching.append(
                    (same - foreign, len(active[squad_id]), -squad_id, squad_id)
                )
        if matching:
            return max(matching)[-1]
        unused = [squad_id for squad_id in available if not history[squad_id]]
        if unused:
            return unused[0]
        affinity = _SQUAD_FALLBACK_AFFINITY[desired]
        fallback = []
        for squad_id in available:
            group_counts = {}
            for unit in history[squad_id]:
                group = squad_role_group(unit.role)
                group_counts[group] = group_counts.get(group, 0) + 1
            dominant = max(group_counts, key=group_counts.get)
            priority = (
                len(affinity) - affinity.index(dominant) if dominant in affinity else 0
            )
            fallback.append((priority, -len(active[squad_id]), -squad_id, squad_id))
        if fallback:
            return max(fallback)[-1]
        return max((getattr(unit, "squad_id", 0) for unit in existing), default=0) + 1

    def update_spotting(self):
        active = [unit for unit in self.units if unit.alive]
        by_faction = {
            "player": [
                unit
                for unit in active
                if unit.faction == "player" and unit.combat_effective
            ],
            "enemy": [
                unit
                for unit in active
                if unit.faction == "enemy" and unit.combat_effective
            ],
        }
        targets_by_faction = {
            "player": [unit for unit in active if unit.faction == "player"],
            "enemy": [unit for unit in active if unit.faction == "enemy"],
        }
        for faction, targets in (
            ("player", targets_by_faction["enemy"]),
            ("enemy", targets_by_faction["player"]),
        ):
            observers = by_faction[faction]
            spotted_attribute = (
                "spotted_player_until" if faction == "player" else "spotted_enemy_until"
            )
            for target in targets:
                seen = False
                for observer in observers:
                    maximum = ROLES[observer.role]["spot"] + 8.0
                    dx = observer.x - target.x
                    dy = observer.y - target.y
                    if dx * dx + dy * dy > maximum * maximum:
                        continue
                    if self.can_see(observer, target):
                        seen = True
                        break
                if seen:
                    setattr(target, spotted_attribute, self.time + 2.2)
                    self.intel[faction][target.uid] = {
                        "pos": (target.x, target.y),
                        "seen": self.time,
                        "role": target.role,
                    }
        for unit in active:
            if not unit.combat_effective or unit.role not in ("Engineer", "Recon"):
                continue
            ux, uy = unit.tile
            radius = 3 if unit.role == "Engineer" else 2
            seen_attribute = (
                "mine_seen_player" if unit.faction == "player" else "mine_seen_enemy"
            )
            for y in range(max(0, uy - radius), min(MAP_H, uy + radius + 1)):
                for x in range(max(0, ux - radius), min(MAP_W, ux + radius + 1)):
                    if self.grid[y][x].mine and math.hypot(x - ux, y - uy) <= radius:
                        setattr(self.grid[y][x], seen_attribute, True)
        for uid, info, age in self.known_contacts("player", memory=10):
            if age > 0.08:
                continue
            last = self._contact_last_report.get(uid, -999)
            if self.time - last < 8:
                continue
            self._contact_last_report[uid] = self.time
            role = ROLE_CONTACT.get(info.get("role", ""), "INFANTRY")
            sector = _vs_sector_name(info["pos"][1])
            self.notify(f"CONTACT — {role}, {sector}", kind="danger", duration=3.8)
            self._vs_event("contact", f"Contact: {role}, {sector}", info["pos"])

    def moving_fire_target(self, unit):
        if unit.fire_discipline == "return":
            if unit.under_fire_until <= self.time or not unit.last_attacker_uid:
                return None
            candidate = self.get_unit(unit.last_attacker_uid)
            enemy_faction = "enemy" if unit.faction == "player" else "player"
            if (
                candidate is not None
                and candidate.faction == enemy_faction
                and candidate.combat_effective
                and self.visible_to(unit.faction, candidate)
                and self.can_see(unit, candidate)
                and (dist(unit, candidate) <= unit.weapon["range"])
            ):
                return candidate
            return None
        if unit.fire_discipline in ("free", "confident"):
            return self.choose_auto_target(unit)
        return None

    def _moving_fire_shot_breakdown(self, attacker, target, mode=None, reaction=False):
        breakdown = self._vs_shot_breakdown(
            attacker, target, mode=mode, reaction=reaction
        )
        if unit_is_firing_while_moving(attacker) and breakdown.get("chance", 0) > 0:
            breakdown.setdefault("mods", []).append(
                ("firing while moving", -MOVING_FIRE_ACCURACY_PENALTY)
            )
        return breakdown

    def cycle_squad_doctrine(self, units):
        squads = sorted(
            {
                (unit.faction, max(1, int(getattr(unit, "squad_id", 1))))
                for unit in units
                if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
            }
        )
        if not squads:
            return None
        current = self.squad_doctrine.get(squads[0], "balanced")
        new_value = SQUAD_DOCTRINES[
            (SQUAD_DOCTRINES.index(current) + 1) % len(SQUAD_DOCTRINES)
        ]
        for key in squads:
            self.squad_doctrine[key] = new_value
        self.add_log(f"Squad doctrine changed to {new_value}.")
        return new_value

    def defense_select_target(self, unit, visible):
        assignment = getattr(unit, "attack_assignment", "assault")
        claims = {}
        for attacker in self.living("enemy"):
            if attacker.target_uid is not None and attacker.order in (
                "fire",
                "suppress",
            ):
                claims[attacker.target_uid] = claims.get(attacker.target_uid, 0) + 1

        def target_score(target):
            distance = dist(unit, target)
            cluster = sum(
                (
                    other.combat_effective and dist(target, other) <= 2.4
                    for other in self.living("player")
                )
            )
            score = 34.0 - distance * 1.35 - claims.get(target.uid, 0) * 3.0
            score -= self.effective_cover(unit, target) * 1.4
            if target.role in STATIC_WEAPON_ROLES:
                score += 20 if assignment == "breach" else 13
            if target.role in ("Machine Gunner", "HMG Crew", "Sniper", "Marksman"):
                score += 11
            if target.role in ("Medic", "Engineer") and unit.role in (
                "Sniper",
                "Marksman",
            ):
                score += 10
            if assignment == "fire_support":
                score += cluster * 3.5
            if unit.role == "Grenadier":
                score += cluster * 4.0
            if target.casualty == "wounded":
                score -= 4
            return score

        return max(visible, key=target_score)

    def _operation_ai_decide(self, unit):
        if unit.role in STATIC_WEAPON_ROLES:
            return
        if self.mission_type != "defense" or unit.faction != "enemy":
            return self._perf_ai_decide3(unit)
        if not getattr(unit, "reserve_active", True):
            if unit.order not in ("idle", "overwatch"):
                unit.order = "idle"
            return
        if unit.jammed:
            self.clear_jam(unit)
            return
        if unit.ammo <= 0 and unit.magazines:
            self.start_reload(unit)
            return
        if unit.role == "Medic" and unit.med_supplies > 0:
            wounded = [
                ally
                for ally in self.living("enemy")
                if ally.uid != unit.uid
                and ally.casualty in ("wounded", "incapacitated")
                and getattr(ally, "reserve_active", True)
            ]
            if wounded:
                patient = min(wounded, key=lambda ally: dist(unit, ally))
                if dist(unit, patient) <= 1.5:
                    self.medic_action(unit, patient)
                    return
                approach = _operation_open_position(
                    self, patient.x, patient.y, unit, radius=2
                )
                if approach is not None and dist(unit, patient) < 10:
                    self.issue_move([unit], approach, mode="safe", formation="column")
                    return
        if unit.role == "Engineer" and unit.order == "build":
            return
        if (
            unit.role == "Engineer"
            and self.static_emplacement_count("enemy") < 4
            and (self.time >= getattr(unit, "next_builder_decision", 8.0))
            and self.enemy_builder_ready(unit)
        ):
            unit.order = "idle"
            unit.path = []
            unit.waypoints = []
            return
        visible = [
            target
            for target in self.living("player")
            if target.combat_effective and self.can_see(unit, target)
        ]
        if visible:
            target = self.defense_select_target(unit, visible)
            distance = dist(unit, target)
            assignment = getattr(unit, "attack_assignment", "assault")
            cluster = sum(
                (
                    other.combat_effective and dist(target, other) <= 2.4
                    for other in self.living("player")
                )
            )
            if (
                unit.smoke_grenades > 0
                and unit.suppression > 48
                and (assignment in ("breach", "assault"))
                and (distance < 9)
            ):
                self.throw_grenade(unit, unit.pos, smoke=True)
                return
            if (
                unit.grenades > 0
                and distance < 4.2
                and (cluster >= 2 or self.effective_cover(unit, target) >= 2)
            ):
                self.throw_grenade(unit, target.pos, cook=0.6)
                return
            if (
                unit.role == "Grenadier"
                and unit.rifle_grenades > 0
                and (4 < distance < 7)
            ):
                self.throw_grenade(unit, target.pos, rifle=True)
                return
            if unit.role in ("Machine Gunner", "HMG Crew"):
                if not unit.deployed:
                    self.toggle_deploy(unit)
                elif distance <= unit.weapon["range"]:
                    self.suppress_area(unit, target.pos)
                return
            if (
                unit.role == "Automatic Rifleman"
                and cluster >= 2
                and (distance <= unit.weapon["range"])
            ):
                self.suppress_area(unit, target.pos)
                return
            if (
                unit.role == "Mortar Team"
                and 5 <= distance <= 22
                and (unit.mortar_shells > 0)
            ):
                if not unit.deployed:
                    self.toggle_deploy(unit)
                else:
                    self.mortar_fire(unit, target.pos)
                return
            if unit.role in ("Sniper", "Marksman") and distance <= unit.weapon["range"]:
                self.issue_fire(unit, target, "aimed")
                return
            if distance <= unit.weapon["range"]:
                mode = "rapid" if assignment == "breach" and distance < 6 else "normal"
                self.issue_fire(unit, target, mode)
                return
        if unit.order in ("idle", "overwatch", "fire_lane") or (
            unit.order == "move" and (not unit.path) and (not unit.waypoints)
        ):
            self.issue_defense_tactical_order(unit)

    def shot_breakdown(self, attacker, target, mode=None, reaction=False):
        breakdown = self._moving_fire_shot_breakdown(
            attacker, target, mode=mode, reaction=reaction
        )
        if breakdown.get("chance", 0) <= 0:
            return breakdown
        penalties = _combat2_wound_penalties(attacker)
        if penalties["aim"] > 0.05:
            breakdown.setdefault("mods", []).append(
                ("localized wounds", -penalties["aim"])
            )
        if self.time < getattr(attacker, "combat2_settle_until", 0.0):
            breakdown.setdefault("mods", []).append(("weapon unsettled", -12.0))
        breakdown["chance"] = self.hit_chance(
            attacker, target, mode=mode, reaction=reaction
        )
        return breakdown

    def combat2_known_target_position(self):
        visible = [
            unit
            for unit in self.living("player")
            if unit.combat_effective and self.visible_to("enemy", unit)
        ]
        if visible:
            center_x = sum((unit.x for unit in visible)) / len(visible)
            center_y = sum((unit.y for unit in visible)) / len(visible)
            return ((center_x, center_y), visible)
        contacts = self.known_contacts("enemy", memory=12.0)
        if contacts:
            positions = [record[1]["pos"] for record in contacts]
            return (
                (
                    sum((position[0] for position in positions)) / len(positions),
                    sum((position[1] for position in positions)) / len(positions),
                ),
                [],
            )
        if getattr(self, "mission_type", "assault") == "defense":
            command = getattr(self, "map_features", {}).get(
                "command_post", (MAP_W - 5, MAP_H / 2)
            )
            return (tuple(command), [])
        return (
            (max(3.0, getattr(self, "primary_line_x", MAP_W - 10) - 10.0), MAP_H / 2),
            [],
        )

    def _combat2_plan_squads(self, force=False):
        if (
            getattr(self, "network_replica", False)
            or getattr(self, "mission_type", "assault") == "pvp"
        ):
            return
        if not force and self.time < self.combat2_next_plan_at:
            return
        tactics = DIFFICULTY[self.difficulty].get("tactics", 1.0)
        self.combat2_next_plan_at = self.time + max(0.55, 1.05 / max(0.5, tactics))
        target_position, visible = self.combat2_known_target_position()
        squads = {}
        for unit in self.living("enemy"):
            if unit.combat_effective and unit.role not in COMBAT2_STATIC_ROLES:
                squads.setdefault(max(1, int(getattr(unit, "squad_id", 1))), []).append(
                    unit
                )
        offensive = getattr(self, "mission_type", "assault") == "defense"
        plans = {}
        for squad_id, members in squads.items():
            center = (
                sum((unit.x for unit in members)) / len(members),
                sum((unit.y for unit in members)) / len(members),
            )
            local_targets = sorted(visible, key=lambda target: dist(target.pos, center))
            squad_target = local_targets[0].pos if local_targets else target_position
            target_unit = local_targets[0] if local_targets else None
            support = [unit for unit in members if unit.role in COMBAT2_SUPPORT_ROLES]
            sustainment = [
                unit for unit in members if unit.role in COMBAT2_SUSTAINMENT_ROLES
            ]
            maneuver = [
                unit
                for unit in members
                if unit not in support and unit not in sustainment
            ]
            if not maneuver:
                maneuver = [unit for unit in members if unit not in support]
            distance_to_target = dist(center, squad_target)
            tx, ty = (
                int(clamp(round(squad_target[0]), 0, MAP_W - 1)),
                int(clamp(round(squad_target[1]), 0, MAP_H - 1)),
            )
            target_suppression = (
                target_unit.suppression
                if target_unit is not None
                else self.grid[ty][tx].ground_suppression
            )
            support_active = any(
                (
                    unit.order in ("suppress", "fire", "fire_lane") and unit.ammo > 0
                    for unit in support
                )
            )
            if offensive:
                if target_suppression < 32 and support and (not support_active):
                    phase = "base_of_fire"
                elif distance_to_target > 4.2:
                    phase = "maneuver"
                else:
                    phase = "assault"
                side = -1 if squad_id % 2 else 1
                dx, dy = (squad_target[0] - center[0], squad_target[1] - center[1])
                length = max(1.0, math.hypot(dx, dy))
                flank = (
                    clamp(
                        squad_target[0]
                        + side * (-dy / length) * min(5.0, distance_to_target * 0.48),
                        1,
                        MAP_W - 2,
                    ),
                    clamp(
                        squad_target[1]
                        + side * (dx / length) * min(5.0, distance_to_target * 0.48),
                        1,
                        MAP_H - 2,
                    ),
                )
            else:
                enemy_strength = self.combat2_local_strength("player", center, 6.0)
                friendly_strength = self.combat2_local_strength("enemy", center, 6.0)
                threatened = enemy_strength > friendly_strength * 1.12
                counterattack = (
                    any(
                        (
                            target.suppression >= 62 and dist(target.pos, center) <= 5.0
                            for target in local_targets
                        )
                    )
                    and friendly_strength >= enemy_strength * 1.18
                )
                phase = (
                    "counterattack"
                    if counterattack
                    else "reposition"
                    if threatened
                    else "hold"
                )
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
                    assignment = (
                        "assault"
                        if offensive and phase == "assault"
                        else "maneuver"
                        if offensive
                        else "screen"
                    )
                unit.combat2_assignment = assignment
                unit.combat2_phase = phase
                unit.combat2_plan_target = tuple(squad_target)
                unit.combat2_flank = tuple(flank)
        self.combat2_tactical_plans = plans

    def _combat2_ai_decide(self, unit):
        if (
            unit.faction != "enemy"
            or unit.role in COMBAT2_STATIC_ROLES
            or getattr(self, "mission_type", "assault") == "pvp"
        ):
            return self._operation_ai_decide(unit)
        if (
            unit.jammed
            or (unit.ammo <= 0 and unit.magazines)
            or unit.suppression > 78
            or (unit.morale < 28)
        ):
            return self._operation_ai_decide(unit)
        if not getattr(unit, "reserve_active", True):
            return self._operation_ai_decide(unit)
        if (
            unit.order.startswith("eng_build")
            or unit.order in ("build", "medic", "rout", "surrender")
            or getattr(unit, "_construction_queued", False)
        ):
            return
        plan = self.combat2_tactical_plans.get(
            max(1, int(getattr(unit, "squad_id", 1)))
        )
        if plan is None:
            self.plan_combat2_squads(force=True)
            plan = self.combat2_tactical_plans.get(
                max(1, int(getattr(unit, "squad_id", 1)))
            )
        if plan is None:
            return self._operation_ai_decide(unit)
        target_position = plan["target"]
        visible = [
            target
            for target in self.living("player")
            if target.combat_effective and self.can_see(unit, target)
        ]
        target = (
            min(visible, key=lambda candidate: dist(unit, candidate))
            if visible
            else None
        )
        if (
            plan["offensive"]
            and target is None
            and (getattr(self, "mission_type", "assault") == "defense")
        ):
            unit.combat2_decision_reason = "advancing on the staged assault route"
            return self._operation_ai_decide(unit)
        assignment = unit.combat2_assignment
        phase = plan["phase"]
        if plan["offensive"]:
            if assignment == "support_by_fire":
                if (
                    target is None
                    and getattr(self, "mission_type", "assault") == "defense"
                ):
                    staging = self.defense_attack_destination(unit)
                    if dist(unit.pos, staging) > 2.4:
                        if unit.deployed and unit.role in (
                            "Machine Gunner",
                            "HMG Crew",
                        ):
                            self.toggle_deploy(unit)
                        elif unit.order != "move":
                            self.issue_move(
                                [unit], staging, mode="safe", formation="column"
                            )
                        unit.combat2_decision_reason = (
                            "advancing the base of fire by bounds"
                        )
                        return
                if unit.role in ("Machine Gunner", "HMG Crew") and (not unit.deployed):
                    unit.combat2_decision_reason = "deploying the squad base of fire"
                    self.toggle_deploy(unit)
                    return
                if (
                    unit.role == "Mortar Team"
                    and target is not None
                    and (5 <= dist(unit, target) <= 19)
                ):
                    if not unit.deployed:
                        self.toggle_deploy(unit)
                    elif unit.mortar_shells > 0:
                        self.mortar_fire(unit, target.pos)
                    unit.combat2_decision_reason = (
                        "supporting the assault with indirect fire"
                    )
                elif unit.role in (
                    "Machine Gunner",
                    "HMG Crew",
                    "Automatic Rifleman",
                ) and (target is not None or unit.order not in ("suppress", "fire")):
                    unit.combat2_decision_reason = (
                        "fixing the defence with sustained fire"
                    )
                    self.suppress_area(
                        unit, target.pos if target is not None else target_position
                    )
                elif target is not None:
                    self.issue_fire(unit, target, "aimed")
                    unit.combat2_decision_reason = "providing deliberate precision fire"
                elif unit.order not in ("overwatch", "fire"):
                    self.set_overwatch(unit, angle_to(unit, target_position), 90)
                return
            if assignment == "sustainment":
                if unit.role == "Medic":
                    return self._operation_ai_decide(unit)
                if (
                    phase == "assault"
                    and dist(unit.pos, target_position) > 5.0
                    and (unit.order not in ("move", "rout"))
                ):
                    follow = (
                        int(clamp(target_position[0] - 3.0, 1, MAP_W - 2)),
                        int(clamp(target_position[1], 1, MAP_H - 2)),
                    )
                    unit.combat2_decision_reason = (
                        "keeping engineer support behind the assault"
                    )
                    self.issue_move([unit], follow, mode="safe", formation="column")
                    return
                return self._operation_ai_decide(unit)
            if phase == "base_of_fire":
                if target is not None:
                    unit.combat2_decision_reason = (
                        "adding fire until the enemy is fixed"
                    )
                    self.issue_fire(unit, target, "normal")
                else:
                    self.set_overwatch(unit, angle_to(unit, target_position), 105)
                return
            if phase == "maneuver":
                flank = (
                    self.defense_attack_destination(unit)
                    if target is None
                    and getattr(self, "mission_type", "assault") == "defense"
                    else plan["flank"]
                )
                if dist(unit.pos, flank) > 1.8 and unit.order != "move":
                    if (
                        unit.smoke_grenades > 0
                        and self.tile_threat("enemy", *unit.tile) > 1.15
                    ):
                        midpoint = (
                            (unit.x + flank[0]) * 0.5,
                            (unit.y + flank[1]) * 0.5,
                        )
                        self.throw_grenade(unit, midpoint, smoke=True)
                        unit.combat2_decision_reason = (
                            "screening the maneuver route with smoke"
                        )
                    else:
                        self.issue_move(
                            [unit],
                            (int(flank[0]), int(flank[1])),
                            mode="safe",
                            formation="column",
                        )
                        unit.combat2_decision_reason = (
                            "maneuvering around the fixed defence"
                        )
                    return
                if target is not None:
                    self.issue_fire(unit, target, "normal")
                else:
                    self.set_overwatch(unit, angle_to(unit, target_position), 100)
                return
            if target is not None:
                distance = dist(unit, target)
                if (
                    unit.grenades > 0
                    and distance < 4.1
                    and (self.effective_cover(unit, target) >= 2)
                ):
                    self.throw_grenade(unit, target.pos, cook=0.6)
                    unit.combat2_decision_reason = (
                        "breaching covered defenders with a grenade"
                    )
                elif distance <= unit.weapon["range"]:
                    self.issue_fire(
                        unit,
                        target,
                        "rapid"
                        if unit.role == "Assault" or distance < 3.0
                        else "normal",
                    )
                    unit.combat2_decision_reason = (
                        "closing and clearing the assault objective"
                    )
                return
            if dist(unit.pos, target_position) > 1.6 and unit.order != "move":
                self.issue_move(
                    [unit],
                    (int(target_position[0]), int(target_position[1])),
                    mode="safe",
                    formation="wedge",
                )
                unit.combat2_decision_reason = "occupying the suppressed objective"
            return
        if assignment == "covered_lane":
            if unit.role in ("Machine Gunner", "HMG Crew") and (not unit.deployed):
                self.toggle_deploy(unit)
                unit.combat2_decision_reason = (
                    "deploying an interlocking defensive lane"
                )
            elif target is not None and unit.role in (
                "Machine Gunner",
                "HMG Crew",
                "Automatic Rifleman",
            ):
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
            return self._operation_ai_decide(unit)
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
                    self.issue_move(
                        [unit], destination, mode="safe", formation="column"
                    )
                unit.combat2_decision_reason = (
                    "trading a compromised position for depth"
                )
                return
        if phase == "counterattack" and target is not None:
            if dist(unit, target) <= unit.weapon["range"]:
                self.issue_fire(
                    unit, target, "rapid" if dist(unit, target) < 4 else "normal"
                )
            elif unit.order != "move":
                self.issue_move([unit], target.tile, mode="safe", formation="wedge")
            unit.combat2_decision_reason = "counterattacking a suppressed penetration"
            return
        if target is not None:
            self.issue_fire(
                unit, target, "aimed" if dist(unit, target) > 7 else "normal"
            )
            unit.combat2_decision_reason = "engaging from the prepared defence"
        elif unit.order not in ("overwatch", "fire_lane"):
            self.set_overwatch(unit, 180, 110)
            unit.combat2_decision_reason = "holding the defensive screen"

    def plan_combat2_squads(self, force=False):
        old_plans = dict(getattr(self, "combat2_tactical_plans", {}))
        result = self._combat2_plan_squads(force=force)
        for squad_id, plan in list(self.combat2_tactical_plans.items()):
            old = old_plans.get(squad_id)
            committed_until = self.polish_plan_commits.get(squad_id, -1.0)
            if (
                old
                and self.time < committed_until
                and (old.get("phase") != plan.get("phase"))
            ):
                for key in ("phase", "flank", "target", "target_uid"):
                    plan[key] = old.get(key, plan.get(key))
            elif old is None or old.get("phase") != plan.get("phase"):
                self.polish_plan_commits[squad_id] = self.time + 3.6
            if plan.get("offensive") and plan.get("flank"):
                flank_x, flank_y = plan["flank"]
                lane = (int(squad_id) * 37 % 5 - 2) * 0.42
                plan["flank"] = (
                    clamp(flank_x, 1, MAP_W - 2),
                    clamp(flank_y + lane, 1, MAP_H - 2),
                )
            for unit in self.living("enemy"):
                if max(1, int(getattr(unit, "squad_id", 1))) == squad_id:
                    unit.combat2_phase = plan.get("phase", unit.combat2_phase)
                    unit.combat2_flank = plan.get("flank", unit.combat2_flank)
        return result

    def ai_decide(self, unit):
        preparation_crisis = (
            unit.suppression >= 75
            or unit.morale < 32
            or unit.jammed
            or (unit.ammo <= 0)
        )
        if (
            unit.faction == "enemy"
            and self.time < self.polish_preparation_until
            and (not preparation_crisis)
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
            depleted = unit.ammo <= 0 and (not unit.magazines)
            specialist = (
                unit.role in COMBAT2_SUPPORT_ROLES
                or unit.role in COMBAT2_SUSTAINMENT_ROLES
            )
            if specialist and (wound_load >= 58 or depleted) and (unit.order != "move"):
                destination = self.find_nearby_cover(unit, 6)
                if destination and destination != unit.tile:
                    self.issue_move(
                        [unit], destination, mode="safe", formation="column"
                    )
                    unit.combat2_decision_reason = (
                        "withdrawing a depleted specialist into cover"
                    )
                    return
            crisis = (
                unit.suppression >= 78
                or unit.morale < 30
                or unit.jammed
                or (unit.ammo <= 0)
            )
            if (
                not crisis
                and self.time < unit.polish_plan_commit_until
                and (unit.order in COMBAT_POLISH_COMMIT_ORDERS)
                and (unit.order != "move" or unit.path or unit.waypoints)
            ):
                return
        before = (
            unit.order,
            tuple(unit.waypoints),
            unit.target_uid,
            bool(unit.deployed),
        )
        result = self._combat2_ai_decide(unit)
        after = (
            unit.order,
            tuple(unit.waypoints),
            unit.target_uid,
            bool(unit.deployed),
        )
        if unit.faction == "enemy" and after != before:
            duration = (
                2.4
                if unit.order in ("deploy", "pack")
                else 1.45
                if unit.order == "move"
                else 0.92
            )
            unit.polish_plan_commit_until = max(
                unit.polish_plan_commit_until, self.time + duration
            )
        return result
