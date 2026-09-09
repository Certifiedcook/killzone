"""Systems / movement for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _combat2_wound_penalties
from engine.rules import _operation_defense_assignment_for_role
from engine.rules import _operation_defense_sector_center
from engine.rules import _operation_open_position
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import dist
from engine.definitions import Coord
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import ROLES
from engine.definitions import STANCE
from engine.definitions import STATIC_WEAPON_ROLES
from engine.definitions import TERRAIN
from engine.models import Unit
from typing import Dict
from typing import List
from typing import Optional
import heapq
import math
import time


class MovementSystem:
    def passable(self, x: int, y: int, unit: Optional[Unit] = None) -> bool:
        if not self.in_bounds(x, y):
            return False
        c = self.grid[y][x]
        if c.terrain == "door" and (not c.door_open):
            return False
        if TERRAIN[c.terrain]["move"] >= 999:
            return False
        other = self.unit_at(x, y)
        if other and (unit is None or other.uid != unit.uid) and other.combat_effective:
            return False
        return True

    def _base_find_path(
        self, unit: Unit, dest: Coord, mode: Optional[str] = None
    ) -> List[Coord]:
        mode = mode or unit.move_mode
        start = unit.tile
        if not self.passable(*dest, unit):
            return []
        pq = [(0.0, start)]
        came: Dict[Coord, Optional[Coord]] = {start: None}
        cost = {start: 0.0}
        while pq:
            _, cur = heapq.heappop(pq)
            if cur == dest:
                break
            x, y = cur
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not self.passable(nx, ny, unit):
                    continue
                cell = self.grid[ny][nx]
                step = TERRAIN[cell.terrain]["move"]
                if cell.terrain == "trench" and self.grid[y][x].terrain == "trench":
                    step *= 0.62
                if mode == "safe":
                    step += self.tile_threat(unit.faction, nx, ny) * 2.45
                    step += cell.ground_suppression * 0.025
                    step = max(
                        0.18, step - min(0.72, TERRAIN[cell.terrain]["cover"] * 0.12)
                    )
                elif mode == "fast":
                    step *= 0.8
                ncost = cost[cur] + step
                if (nx, ny) not in cost or ncost < cost[nx, ny]:
                    cost[nx, ny] = ncost
                    h = abs(dest[0] - nx) + abs(dest[1] - ny)
                    heapq.heappush(pq, (ncost + h * 0.4, (nx, ny)))
                    came[nx, ny] = cur
        if dest not in came:
            return []
        out = []
        cur = dest
        while cur != start:
            out.append(cur)
            cur = came[cur]
        out.reverse()
        return out

    def _base_issue_move(
        self,
        units: List[Unit],
        dest: Coord,
        append=False,
        mode=None,
        formation="spread",
    ):
        effective = [u for u in units if u.combat_effective]
        offsets = self.formation_offsets(len(effective), formation)
        for u, (ox, oy) in zip(effective, offsets):
            d = (
                int(clamp(round(dest[0] + ox), 0, MAP_W - 1)),
                int(clamp(round(dest[1] + oy), 0, MAP_H - 1)),
            )
            if not self.passable(*d, u):
                d = dest
            if mode:
                u.move_mode = mode
            if append:
                u.command_queue.append(("move", d))
                continue
            u.waypoints = [d]
            u.path = []
            u.order = "move"
            u.command_delay_until = max(
                u.command_delay_until,
                self.time + u.suppression * 0.006 + self.crossfire_pressure(u) * 0.35,
            )
            u.target_uid = None
            u.overwatch = False
            u.fire_lane = False

    def _base_update_movement(self, u: Unit, dt: float):
        if u.deployed and u.role in ("Machine Gunner", "HMG Crew", "Mortar Team"):
            return
        if not u.path:
            if u.waypoints:
                dest = u.waypoints[0]
                u.path = self.find_path(u, dest, u.move_mode)
                if not u.path:
                    u.waypoints.pop(0)
                    return
            else:
                u.order = "idle"
                return
        nx, ny = u.path[0]
        if not self.passable(nx, ny, u):
            u.path = []
            return
        cell = self.grid[ny][nx]
        terrain_mult = TERRAIN[cell.terrain]["move"]
        base = ROLES[u.role]["speed"] * STANCE[u.stance]["speed"]
        wound = max(0, 1 - u.hp / max(1, u.max_hp))
        if u.casualty == "wounded":
            base *= clamp(1 - wound * 0.42, 0.58, 0.92)
        base *= 0.68 + 0.32 * (u.stamina / 100)
        if u.suppression >= 50:
            base *= 0.78
        if u.suppression >= 80:
            base *= 0.55
        if u.dragging_uid is not None:
            base *= 0.48
        if u.carrying_uid is not None:
            base *= 0.62
        speed = base / max(0.55, terrain_mult)
        vx, vy = (nx - u.x, ny - u.y)
        vl = math.hypot(vx, vy)
        if vl < speed * dt or vl < 1e-06:
            oldx, oldy = (u.x, u.y)
            u.x, u.y = (nx, ny)
            u.path.pop(0)
            if vl > 1e-06:
                u.facing = math.degrees(math.atan2(ny - oldy, nx - oldx)) % 360
            self.on_enter_tile(u, nx, ny)
            if not u.path and u.waypoints and (u.waypoints[0] == (nx, ny)):
                u.waypoints.pop(0)
        else:
            step = speed * dt / vl
            u.x += vx * step
            u.y += vy * step
            u.facing = math.degrees(math.atan2(vy, vx)) % 360
            u.signature = max(u.signature, 10 if u.stance != "prone" else 4)
        if u.dragging_uid:
            t = self.get_unit(u.dragging_uid)
            if t and t.casualty == "incapacitated":
                t.x = u.x - 0.25 * math.cos(math.radians(u.facing))
                t.y = u.y - 0.25 * math.sin(math.radians(u.facing))
            else:
                u.dragging_uid = None
        if u.carrying_uid:
            t = self.get_unit(u.carrying_uid)
            if t and t.casualty == "incapacitated":
                t.x = u.x
                t.y = u.y
            else:
                u.carrying_uid = None

    def _kz_find_path(self, unit, dest, mode=None):
        t0 = time.perf_counter()
        mode = mode or unit.move_mode
        start = unit.tile
        key = (
            start,
            dest,
            mode,
            unit.faction,
            getattr(self, "_terrain_revision", 0) // 8,
        )
        cached = self._path_cache.get(key)
        if cached is not None:
            out = list(cached)
            self._perf["path_ms"] += (time.perf_counter() - t0) * 1000
            return out
        if not self.passable(*dest, unit):
            return []
        pq = [(0.0, start)]
        came = {start: None}
        cost = {start: 0.0}
        expanded = 0
        while pq and expanded < MAP_W * MAP_H:
            _, cur = heapq.heappop(pq)
            expanded += 1
            if cur == dest:
                break
            x, y = cur
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not self.passable(nx, ny, unit):
                    continue
                c = self.grid[ny][nx]
                step = TERRAIN[c.terrain]["move"]
                if c.terrain == "trench" and self.grid[y][x].terrain == "trench":
                    step *= 0.62
                if mode == "safe":
                    step += (
                        self.tile_threat(unit.faction, nx, ny) * 2.25
                        + c.ground_suppression * 0.022
                    )
                    step = max(
                        0.18, step - min(0.68, TERRAIN[c.terrain]["cover"] * 0.11)
                    )
                elif mode == "fast":
                    step *= 0.8
                nc = cost[cur] + step
                if (nx, ny) not in cost or nc < cost[nx, ny]:
                    cost[nx, ny] = nc
                    h = abs(dest[0] - nx) + abs(dest[1] - ny)
                    heapq.heappush(pq, (nc + h * 0.42, (nx, ny)))
                    came[nx, ny] = cur
        if dest not in came:
            out = []
        else:
            out = []
            cur = dest
            while cur != start:
                out.append(cur)
                cur = came[cur]
            out.reverse()
        if len(self._path_cache) > 512:
            self._path_cache.clear()
        self._path_cache[key] = tuple(out)
        self._perf["paths"] += 1
        self._perf["path_ms"] += (time.perf_counter() - t0) * 1000
        return out

    def _kz_issue_move(self, units, dest, append=False, mode=None, formation="spread"):
        effective = [u for u in units if u.combat_effective]
        if self.in_bounds(*dest) and self.grid[dest[1]][dest[0]].terrain in (
            "trench",
            "firing_step",
            "dugout",
        ):
            formation = "column"
        elif len(effective) >= 4:
            cx = sum((u.x for u in effective)) / len(effective)
            cy = sum((u.y for u in effective)) / len(effective)
            corridor = self.line_cells((cx, cy), dest)
            if any(
                (
                    self.grid[y][x].terrain
                    in ("trench", "firing_step", "door", "bridge")
                    for x, y in corridor
                    if self.in_bounds(x, y)
                )
            ):
                formation = "column"
        self._base_issue_move(
            units, dest, append=append, mode=mode, formation=formation
        )
        for i, u in enumerate([x for x in units if x.combat_effective]):
            u.path_ready_at = self.time + i * 0.008

    def _kz_update_movement(self, u, dt):
        if self.time < getattr(u, "wait_until", 0):
            return
        if not u.path and u.waypoints:
            if self.time < getattr(u, "path_ready_at", 0):
                return
            if self._path_budget <= 0:
                return
            self._path_budget -= 1
        if u.path:
            nxt = u.path[0]
            occ = self._occupancy.get(nxt)
            if occ and occ != u.uid:
                other = self.get_unit(occ)
                if other and other.faction == u.faction and other.combat_effective:
                    if not getattr(u, "blocked_since", 0):
                        u.blocked_since = self.time
                    u.wait_until = self.time + self.rng.uniform(0.05, 0.13)
                    if self.time - u.blocked_since > 0.65:
                        u.path = []
                        u.blocked_since = 0
                    return
            u.blocked_since = 0
        old_tile = u.tile
        self._base_update_movement(u, dt)
        new_tile = u.tile
        if new_tile != old_tile:
            if self._occupancy.get(old_tile) == u.uid:
                self._occupancy.pop(old_tile, None)
            self._occupancy[new_tile] = u.uid
        if self.grid[new_tile[1]][new_tile[0]].terrain not in (
            "trench",
            "firing_step",
            "dugout",
        ):
            for a in self.living(u.faction):
                if a.uid == u.uid or not a.combat_effective:
                    continue
                dx = u.x - a.x
                dy = u.y - a.y
                d2 = dx * dx + dy * dy
                if 1e-05 < d2 < 0.2:
                    d = math.sqrt(d2)
                    push = min(0.025, (0.46 - d) * 0.06)
                    u.x = clamp(u.x + dx / d * push, 0.2, MAP_W - 0.2)
                    u.y = clamp(u.y + dy / d * push, 0.2, MAP_H - 0.2)

    def find_path(self, unit, dest, mode=None):
        started = time.perf_counter()
        mode = mode or unit.move_mode
        start = unit.tile
        dest = (int(dest[0]), int(dest[1]))
        visual_revision = self.terrain_revision
        if getattr(self, "_maintenance_visual_revision", None) != visual_revision:
            self._maintenance_visual_revision = visual_revision
            self._path_cache.clear()
        occupied = {
            other.tile
            for other in self.units
            if other.uid != unit.uid and other.combat_effective
        }
        key = (start, dest, mode, unit.faction, self._terrain_revision)
        cached = self._path_cache.get(key)
        if cached is not None and all((tile not in occupied for tile in cached)):
            path = list(cached)
            self._perf["path_ms"] += (time.perf_counter() - started) * 1000
            return path

        def terrain_passable(x, y):
            if not (0 <= x < MAP_W and 0 <= y < MAP_H) or (x, y) in occupied:
                return False
            cell = self.grid[y][x]
            return (
                not (cell.terrain == "door" and (not cell.door_open))
                and TERRAIN[cell.terrain]["move"] < 999
            )

        if not terrain_passable(*dest):
            return []
        threat_grid = None
        if mode == "safe":
            self.tile_threat(unit.faction, start[0], start[1])
            threat_grid = self._threat_grids[unit.faction]
        queue = [(0.0, 0.0, start)]
        came = {start: None}
        costs = {start: 0.0}
        closed = set()
        grid = self.grid
        terrain_data = TERRAIN
        heuristic_scale = 1.5
        while queue:
            _, queued_cost, current = heapq.heappop(queue)
            if current in closed or queued_cost != costs.get(current):
                continue
            if current == dest:
                break
            closed.add(current)
            x, y = current
            current_terrain = grid[y][x].terrain
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not terrain_passable(nx, ny):
                    continue
                cell = grid[ny][nx]
                step_cost = terrain_data[cell.terrain]["move"]
                if cell.terrain == "trench" and current_terrain == "trench":
                    step_cost *= 0.62
                if mode == "safe":
                    step_cost += (
                        threat_grid[ny][nx] * 2.25 + cell.ground_suppression * 0.022
                    )
                    step_cost = max(
                        0.18,
                        step_cost
                        - min(0.68, terrain_data[cell.terrain]["cover"] * 0.11),
                    )
                elif mode == "fast":
                    step_cost *= 0.8
                new_cost = queued_cost + step_cost
                position = (nx, ny)
                if new_cost >= costs.get(position, float("inf")):
                    continue
                costs[position] = new_cost
                came[position] = current
                heuristic = (abs(dest[0] - nx) + abs(dest[1] - ny)) * heuristic_scale
                heapq.heappush(queue, (new_cost + heuristic, new_cost, position))
        if dest not in came:
            path = []
        else:
            path = []
            current = dest
            while current != start:
                path.append(current)
                current = came[current]
            path.reverse()
        if path:
            if len(self._path_cache) > 512:
                self._path_cache.clear()
            self._path_cache[key] = tuple(path)
        self._perf["paths"] += 1
        self._perf["path_ms"] += (time.perf_counter() - started) * 1000
        return path

    def _maintenance_update_movement(self, unit, dt):
        needs_path = (
            not unit.path
            and bool(unit.waypoints)
            and (self.time >= getattr(unit, "path_ready_at", 0))
            and (self.time >= getattr(unit, "wait_until", 0))
            and (
                not (
                    unit.deployed
                    and unit.role in ("Machine Gunner", "HMG Crew", "Mortar Team")
                )
            )
        )
        if needs_path:
            if getattr(self, "_maintenance_paths_started", 0) >= 1:
                return
            self._maintenance_paths_started = (
                getattr(self, "_maintenance_paths_started", 0) + 1
            )
        return self._kz_update_movement(unit, dt)

    def _operation_issue_move(
        self, units, dest, append=False, mode=None, formation="spread"
    ):
        movable = [unit for unit in units if unit.role not in STATIC_WEAPON_ROLES]
        if mode is None and movable:
            doctrines = {self.doctrine_for(unit) for unit in movable}
            if doctrines == {"cautious"}:
                mode = "safe"
            elif doctrines == {"aggressive"}:
                mode = "fast"
        return self._kz_issue_move(
            movable, dest, append=append, mode=mode, formation=formation
        )

    def defense_attack_destination(self, unit):
        """Return a role-aware, open waypoint for the coordinated assault."""
        assignment = getattr(
            unit, "attack_assignment", _operation_defense_assignment_for_role(unit.role)
        )
        sector = getattr(unit, "attack_sector", self.defense_main_effort)
        primary = self.primary_line_x
        secondary = self.secondary_line_x
        command = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
        front_x = self.defense_sector_front(sector)
        progress_x = (
            front_x if assignment in ("fire_support", "sustainment") else unit.x
        )
        if progress_x < primary - 4.5:
            target_x = primary - 4
        elif progress_x < primary + 1.5:
            target_x = primary + 1
        elif progress_x < secondary - 2.5:
            target_x = secondary - 2
        else:
            target_x = command[0]
        if assignment == "fire_support":
            target_x = min(target_x - 4, max(unit.x, front_x - 5))
        elif assignment == "sustainment":
            target_x = min(target_x - 2, max(unit.x, front_x - 3))
        sector_center = _operation_defense_sector_center(sector)
        lane_offset = unit.uid * 3 % 7 - 3
        if unit.role == "Recon":
            lane_offset += -4 if unit.uid % 2 else 4
        target_y = int(clamp(sector_center + lane_offset, 2, MAP_H - 3))
        if target_x >= command[0] - 1:
            target_y = int(clamp(command[1] + lane_offset // 2, 2, MAP_H - 3))
        destination = _operation_open_position(self, target_x, target_y, unit, radius=5)
        return destination or (int(clamp(target_x, 1, MAP_W - 2)), target_y)

    def update_movement(self, unit, dt):
        before = unit.pos
        penalties = _combat2_wound_penalties(unit)
        result = self._maintenance_update_movement(unit, dt * penalties["move"])
        if dist(before, unit.pos) > 1e-06:
            unit.combat2_settle_until = max(
                unit.combat2_settle_until, self.time + 0.34 + unit.suppression * 0.002
            )
            unit.combat2_exposed_until = max(
                unit.combat2_exposed_until, self.time + 0.3
            )
            unit.combat2_last_move_pos = unit.pos
        return result

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
            if (
                not self.in_bounds(x, y)
                or (x, y) in reserved
                or (not self.passable(x, y, unit))
            ):
                continue
            cell = self.grid[y][x]
            score = dist((x, y), desired) + self.tile_threat(unit.faction, x, y) * 0.08
            score -= TERRAIN[cell.terrain]["cover"] * 0.08
            if score < best_score:
                best, best_score = ((x, y), score)
        return best or desired

    def issue_move(self, units, dest, append=False, mode=None, formation="spread"):
        effective = [unit for unit in units if unit.combat_effective]
        offsets = self.formation_offsets(len(effective), formation)
        reserved = set()
        issued = []
        for unit, (offset_x, offset_y) in zip(effective, offsets):
            desired = (dest[0] + offset_x, dest[1] + offset_y)
            destination = self._polish_open_destination(unit, desired, reserved)
            reserved.add(destination)
            signature = ("move", destination, mode or unit.move_mode, bool(append))
            same_active_order = (
                not append
                and unit.faction == "enemy"
                and (signature == getattr(unit, "polish_last_order_signature", None))
                and (self.time < getattr(unit, "polish_plan_commit_until", 0.0))
                and (unit.order == "move")
                and (unit.path or unit.waypoints)
            )
            if same_active_order:
                unit.polish_order_state = "MOVING"
                issued.append(unit)
                continue
            self._operation_issue_move(
                [unit], destination, append=append, mode=mode, formation="line"
            )
            unit.polish_arrival_facing = angle_to(unit, dest)
            unit.polish_last_order_signature = signature
            unit.polish_last_order_at = self.time
            unit.polish_plan_commit_until = max(
                unit.polish_plan_commit_until, self.time + 1.15
            )
            unit.polish_order_state = "QUEUED" if append else "RECEIVED"
            unit.polish_order_state_until = self.time + 0.72
            unit.polish_wait_reason = ""
            issued.append(unit)
        return issued
