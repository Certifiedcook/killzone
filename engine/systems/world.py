"""Systems / world for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _combat2_impact_kind
from engine.rules import _combat2_initialize_unit
from engine.rules import _combat2_point_segment_distance
from engine.rules import _combat2_wound_penalties
from engine.rules import _polish_initialize_unit
from engine.rules import _vs_sector_name
from engine.rules import angle_diff
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import combat_polish_weapon_profile
from engine.rules import dist
from engine.revisions import TerrainRevision
from engine.definitions import COMBAT2_SUPPORT_ROLES
from engine.definitions import Coord
from engine.definitions import DEFAULT_PLAYER_ROSTER
from engine.definitions import DIFFICULTY
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MAX_PLAYER_UNITS
from engine.definitions import MISSION_VARIANTS
from engine.definitions import PLAYER_SURNAMES
from engine.definitions import ROLES
from engine.definitions import ROLE_CONTACT
from engine.definitions import STANCE
from engine.definitions import TERRAIN
from engine.definitions import WEAPONS
from engine.models import BloodDecal
from engine.models import BoundingOrder
from engine.models import Cell
from engine.models import Explosion
from engine.models import Impact
from engine.models import Tracer
from engine.models import Unit
from typing import List
from typing import Optional
from typing import Tuple
import math
import random
import time


class WorldSystem:
    @property
    def terrain_revision(self):
        """Changes immediately when this world's terrain or doors change."""
        return self._terrain_state.value

    def _base_init(
        self,
        seed: Optional[int] = None,
        difficulty: str = "Hard",
        player_roster: Optional[List[str]] = None,
    ):
        self.seed = seed if seed is not None else random.randint(100000, 999999)
        cleaned_roster = [
            r for r in player_roster or DEFAULT_PLAYER_ROSTER if r in ROLES
        ][:MAX_PLAYER_UNITS]
        self.player_roster = cleaned_roster or ["Rifleman"]
        self.rng = random.Random(self.seed)
        self.difficulty = difficulty
        self.time = 0.0
        self._terrain_state = TerrainRevision()
        self.grid = [
            [Cell(_revision_state=self._terrain_state) for _ in range(MAP_W)]
            for _ in range(MAP_H)
        ]
        self.units: List[Unit] = []
        self.explosions: List[Explosion] = []
        self.tracers: List[Tracer] = []
        self.impacts: List[Impact] = []
        self.blood: List[BloodDecal] = []
        self.events: List[dict] = []
        self.bounding_orders: List[BoundingOrder] = []
        self.intel = {"player": {}, "enemy": {}}
        self.log: List[str] = []
        self.next_uid = 1
        self.weather = self.rng.choice(["clear", "clear", "rain", "fog"])
        self.wind = self.rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        self.support = {
            "player_HE": 2,
            "player_SMOKE": 2,
            "enemy_HE": 1,
            "enemy_SMOKE": 1,
        }
        self.victory = False
        self.defeat = False
        self.paused = False
        self._spot_timer = 0.0
        self._world_timer = 0.0
        self._cohesion_timer = 0.0
        self.generate_map()
        self.rally_points = {
            "player": (3, MAP_H // 2),
            "enemy": (MAP_W - 4, MAP_H // 2),
        }
        self.spawn_default_forces()
        self.add_log(
            f"Realtime battle started. Seed {self.seed}. Weather: {self.weather}."
        )

    def _base_set_cell(self, x: int, y: int, terrain: str, axis: Optional[str] = None):
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            self.grid[y][x].reset_terrain(terrain, axis)
            if terrain == "door":
                self.grid[y][x].door_open = False

    def _base_generate_map(self):
        for y in range(MAP_H):
            for x in range(MAP_W):
                self.set_cell(x, y, "open")
        road_y = self.rng.randint(5, MAP_H - 6)
        for x in range(MAP_W):
            if self.rng.random() < 0.94:
                self.set_cell(x, road_y, "road")
        tx = MAP_W - 10
        for y in range(2, MAP_H - 2):
            self.set_cell(tx, y, "trench", "V")
        for x in range(tx - 5, MAP_W - 2):
            for y in (5, MAP_H // 2, MAP_H - 6):
                self.set_cell(x, y, "trench", "H")
        cx, cy = (tx, MAP_H // 2)
        for i in range(7):
            self.set_cell(cx - i, cy + i // 3, "trench", "H")
        for y in range(4, MAP_H - 4, 5):
            side = -1 if y // 5 % 2 else 1
            self.set_cell(tx + side, y, "trench", "H")
            self.set_cell(tx + side, y + 1, "firing_step", "V")
            if self.in_bounds(tx + 2 * side, y + 1):
                self.set_cell(tx + 2 * side, y + 1, "dugout")
            if self.in_bounds(tx - side, y):
                self.set_cell(tx - side, y, "sandbags")
        for y in (5, MAP_H // 2, MAP_H - 6):
            self.set_cell(tx + 2, y, "bunker")
            for dy in (-1, 1):
                if 0 <= y + dy < MAP_H:
                    self.set_cell(tx - 1, y + dy, "sandbags")
        wx = tx - 5
        gaps = {road_y, MAP_H // 2 + 1, self.rng.randint(2, MAP_H - 3)}
        for y in range(1, MAP_H - 1):
            if y not in gaps:
                self.set_cell(wx, y, "wire")
        for _ in range(28):
            x = self.rng.randint(wx - 2, tx - 1)
            y = self.rng.randint(2, MAP_H - 3)
            if self.grid[y][x].terrain in ("open", "mud", "road"):
                self.grid[y][x].mine = True
        for _ in range(55):
            x = self.rng.randint(8, wx - 2)
            y = self.rng.randint(1, MAP_H - 2)
            if self.grid[y][x].terrain == "open":
                self.set_cell(
                    x, y, self.rng.choice(["crater", "crater", "mud", "foxhole"])
                )
        for _ in range(6):
            cx = self.rng.randint(4, wx - 2)
            cy = self.rng.randint(2, MAP_H - 3)
            for _ in range(self.rng.randint(7, 14)):
                x = int(clamp(cx + self.rng.randint(-2, 2), 1, MAP_W - 2))
                y = int(clamp(cy + self.rng.randint(-2, 2), 1, MAP_H - 2))
                if self.grid[y][x].terrain == "open":
                    self.set_cell(x, y, self.rng.choice(["woods", "woods", "hill"]))
        bx, by = (self.rng.randint(11, 16), self.rng.randint(3, MAP_H - 8))
        for x in range(bx, bx + 5):
            for y in (by, by + 4):
                self.set_cell(x, y, "building")
        for y in range(by, by + 5):
            for x in (bx, bx + 4):
                self.set_cell(x, y, "building")
        self.set_cell(bx + 2, by + 4, "door")
        self.set_cell(bx + 1, by, "window")
        self.set_cell(bx + 3, by, "window")
        hx, hy = (bx + 7, max(2, by - 1))
        if hx + 3 < MAP_W - 2:
            for xx in range(hx, hx + 4):
                self.set_cell(xx, hy, "woodwall")
                self.set_cell(xx, hy + 3, "woodwall")
            for yy in range(hy, hy + 4):
                self.set_cell(hx, yy, "woodwall")
                self.set_cell(hx + 3, yy, "woodwall")
            self.set_cell(hx + 1, hy + 3, "door")
            self.set_cell(hx + 2, hy, "window")
        if self.rng.random() < 0.55:
            sx = self.rng.randint(18, 23)
            bridge_ys = {road_y, self.rng.randint(4, MAP_H - 5)}
            for y in range(MAP_H):
                self.set_cell(sx, y, "bridge" if y in bridge_ys else "water")
        for _ in range(12):
            x = self.rng.randint(tx - 2, MAP_W - 3)
            y = self.rng.randint(2, MAP_H - 3)
            if self.grid[y][x].terrain == "open":
                self.set_cell(x, y, "wall")

    def _base_add_unit(self, faction: str, role: str, x: float, y: float) -> Unit:
        d = ROLES[role]
        weapon = d["weapon"]
        mag = WEAPONS[weapon]["mag"]
        u = Unit(
            uid=self.next_uid,
            faction=faction,
            role=role,
            x=x,
            y=y,
            hp=float(d["hp"]),
            max_hp=float(d["hp"]),
            weapon_name=weapon,
            ammo=mag,
            magazines=[mag for _ in range(max(0, d.get("mags", 4) - 1))],
            grenades=d.get("grenades", 0),
            smoke_grenades=d.get("smoke", 0),
            rifle_grenades=d.get("rifle_grenades", 0),
            satchel=d.get("satchel", 0),
            med_supplies=d.get("med", 0),
            tools=d.get("tools", 0),
            mortar_shells=d.get("mortar", 0),
            crew=d.get("crew", 1),
            assistant_alive=role in ("Machine Gunner", "HMG Crew"),
            barrel_spares=2 if role in ("Machine Gunner", "HMG Crew") else 0,
            facing=0 if faction == "player" else 180,
        )
        self.next_uid += 1
        self.units.append(u)
        return u

    def _base_spawn_default_forces(self):
        player_roles = list(self.player_roster)
        slots = [(2 + i % 4, 3 + i // 4 * 5 + i % 2) for i in range(len(player_roles))]
        for role, (x, y) in zip(player_roles, slots):
            self.add_unit("player", role, x, min(y, MAP_H - 2))
        enemy_pool = [
            "Rifleman",
            "Rifleman",
            "Machine Gunner",
            "Marksman",
            "Assault",
            "Grenadier",
            "Engineer",
            "Medic",
            "Automatic Rifleman",
            "HMG Crew",
        ]
        n = DIFFICULTY[self.difficulty]["enemy"]
        spots = []
        tx = MAP_W - 10
        for y in range(2, MAP_H - 2):
            if self.grid[y][tx].terrain in ("trench", "firing_step"):
                spots.append((tx, y))
        self.rng.shuffle(spots)
        for i in range(n):
            role = enemy_pool[i % len(enemy_pool)]
            x, y = spots[i % len(spots)]
            if self.unit_at(x, y) is not None:
                y = int(clamp(y + 1, 1, MAP_H - 2))
            u = self.add_unit("enemy", role, x, y)
            if role in ("Machine Gunner", "HMG Crew"):
                u.deployed = True
                u.fire_lane = True
                u.fire_lane_center = 180
                u.arc_width = 90

    def add_log(self, msg: str):
        self.log.append(msg)
        self.log = self.log[-12:]

    def _base_emit(self, event_type: str, **payload):
        payload["type"] = event_type
        self.events.append(payload)

    def drain_events(self) -> List[dict]:
        out, self.events = (self.events, [])
        return out

    def _base_get_unit(self, uid: Optional[int]) -> Optional[Unit]:
        return next((u for u in self.units if u.uid == uid), None)

    def _base_unit_at(self, x: int, y: int, include_incap=True) -> Optional[Unit]:
        for u in self.units:
            if not u.alive:
                continue
            if not include_incap and (not u.combat_effective):
                continue
            if int(round(u.x)) == x and int(round(u.y)) == y:
                return u
        return None

    def _base_living(self, faction: Optional[str] = None) -> List[Unit]:
        return [
            u
            for u in self.units
            if u.alive and (faction is None or u.faction == faction)
        ]

    @staticmethod
    def in_bounds(x: int, y: int) -> bool:
        return 0 <= x < MAP_W and 0 <= y < MAP_H

    def line_cells(self, a, b) -> List[Coord]:
        x0, y0 = (int(round(a[0])), int(round(a[1])))
        x1, y1 = (int(round(b[0])), int(round(b[1])))
        cells = []
        dx, dy = (abs(x1 - x0), abs(y1 - y0))
        sx, sy = (1 if x0 < x1 else -1, 1 if y0 < y1 else -1)
        err = dx - dy
        while True:
            cells.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        return cells

    def trench_corner_blocked(self, a: Unit, b: Unit) -> bool:
        if dist(a, b) > 5.0:
            return False
        ax, ay = a.tile
        bx, by = b.tile
        if (
            self.grid[ay][ax].terrain != "trench"
            or self.grid[by][bx].terrain != "trench"
        ):
            return False
        aa, ba = (self.grid[ay][ax].axis, self.grid[by][bx].axis)
        return (
            aa is not None
            and ba is not None
            and (aa != ba)
            and (self.time > a.peek_until)
        )

    def visible_to(self, faction: str, target: Unit) -> bool:
        if target.faction == faction:
            return True
        attr = "spotted_player_until" if faction == "player" else "spotted_enemy_until"
        return getattr(target, attr) > self.time

    def effective_cover(self, attacker: Unit, target: Unit) -> float:
        tx, ty = target.tile
        c = self.grid[ty][tx]
        cover = float(TERRAIN[c.terrain]["cover"])
        if c.terrain in ("trench", "firing_step") and c.axis:
            shot = angle_to(target, attacker)
            axis_deg = 0 if c.axis == "H" else 90
            along = min(angle_diff(shot, axis_deg), angle_diff(shot, axis_deg + 180))
            if along < 28:
                cover = 1.0
            else:
                cover = 5.0
        incoming = angle_to(target, attacker)
        flank = angle_diff(target.facing, incoming)
        if flank > 120:
            cover -= 2
        elif flank > 70:
            cover -= 1
        if target.stance == "prone":
            cover += 1.5
        elif target.stance == "crouched":
            cover += 0.7
        cover -= c.cover_wear * 2.2
        return max(0, cover)

    def reaction_delay(self, u: Unit, target: Optional[Unit] = None) -> float:
        base = {
            "Heavy Machine Gun": 0.72,
            "Light Machine Gun": 0.58,
            "Scoped Rifle": 0.62,
            "Marksman Rifle": 0.46,
            "Service Rifle": 0.34,
            "Carbine": 0.3,
            "SMG": 0.24,
            "Automatic Rifle": 0.36,
        }.get(u.weapon_name, 0.36)
        base += u.suppression * 0.012
        base += self.crossfire_pressure(u) * 0.75
        if self.time < u.disoriented_until:
            base += 0.9
        if u.casualty == "wounded":
            base += 0.18 + (1 - u.hp / max(1, u.max_hp)) * 0.35
        if u.prepared > 0.7:
            base *= 0.72
        return clamp(base, 0.16, 2.8)

    def traverse_delay(self, u: Unit, target) -> float:
        turn = angle_diff(u.facing, angle_to(u, target))
        speed = {
            "Heavy Machine Gun": 65,
            "Light Machine Gun": 95,
            "Scoped Rifle": 120,
            "Marksman Rifle": 145,
            "Service Rifle": 170,
            "Carbine": 195,
            "SMG": 230,
            "Automatic Rifle": 150,
        }.get(u.weapon_name, 170)
        if u.deployed and u.weapon_name in ("Heavy Machine Gun", "Light Machine Gun"):
            speed *= 0.72
        speed *= clamp(1 - u.suppression * 0.005, 0.45, 1.0)
        return turn / max(30, speed)

    def degrade_cover(
        self, pos: Tuple[float, float], power: float, weapon_pen: int = 1
    ):
        x, y = (int(round(pos[0])), int(round(pos[1])))
        if not self.in_bounds(x, y):
            return
        c = self.grid[y][x]
        if c.terrain not in (
            "sandbags",
            "woodwall",
            "window",
            "door",
            "trench",
            "firing_step",
            "foxhole",
            "bunker",
            "woods",
        ):
            return
        wear = power / 120.0 * (0.45 + weapon_pen * 0.12)
        c.cover_wear = clamp(c.cover_wear + wear, 0, 1)
        if c.hp is not None and power > 12:
            c.hp -= power * 0.1
            if c.hp <= 0:
                if c.terrain in ("sandbags", "woodwall", "window", "door", "bunker"):
                    c.reset_terrain("rubble")
                elif c.terrain == "woods":
                    c.reset_terrain("open")

    def formation_offsets(self, n: int, formation: str):
        if formation == "line":
            return [(i - (n - 1) / 2, 0) for i in range(n)]
        if formation == "column":
            return [(0, i) for i in range(n)]
        if formation == "wedge":
            out = [(0, 0)]
            for i in range(1, n):
                rank = (i + 1) // 2
                side = -1 if i % 2 else 1
                out.append((side * rank, rank))
            return out
        cols = max(2, int(math.ceil(math.sqrt(n))))
        return [(i % cols - (cols - 1) / 2, i // cols) for i in range(n)]

    def process_command_queue(self, u: Unit):
        if (
            u.order != "idle"
            or u.action_timer > 0
            or u.reload_timer > 0
            or (not u.command_queue)
        ):
            return
        kind, data = u.command_queue.pop(0)
        if kind == "move":
            self.issue_move([u], data, formation="column")
        elif kind == "fire":
            uid, mode = data
            t = self.get_unit(uid)
            if t and t.combat_effective:
                self.issue_fire(u, t, mode)

    def _base_hit_chance(
        self, attacker: Unit, target: Unit, mode: Optional[str] = None, reaction=False
    ) -> float:
        mode = mode or attacker.fire_mode
        w = attacker.weapon
        d = dist(attacker, target)
        if d > w["range"]:
            return 0.0
        clear, smoke, soft_pen, _ = self.line_info(attacker.pos, target.pos)
        if not clear:
            return 0.0
        if soft_pen > w["pen"] + 1:
            return 0.0
        chance = float(w["acc"])
        chance += (
            DIFFICULTY[self.difficulty]["acc"] if attacker.faction == "enemy" else 0
        )
        chance -= max(0, d - 2) * 2.8
        chance -= self.effective_cover(attacker, target) * 9
        chance += STANCE[attacker.stance]["acc"] + STANCE[target.stance]["hit"]
        chance -= attacker.suppression * 0.32
        wound = max(0, 1 - attacker.hp / max(1, attacker.max_hp))
        if attacker.casualty == "wounded":
            chance -= 4 + wound * 12
        if self.time < attacker.disoriented_until:
            chance -= 18
        chance += attacker.prepared * 7
        chance += (attacker.cohesion - 50) * 0.08
        chance += (attacker.morale - 50) * 0.05
        chance -= smoke * 19
        chance -= soft_pen * 7
        if mode == "snap":
            chance -= 16
        elif mode == "aimed":
            chance += 18 + attacker.aim_progress * 10
        elif mode == "rapid":
            chance -= 12
        if attacker.deployed and attacker.role in ("Machine Gunner", "HMG Crew"):
            chance += 8
        if (
            attacker.role == "Sniper"
            and mode == "aimed"
            and (attacker.suppression < 30)
            and (attacker.action_timer <= 0)
            and (smoke < 0.4)
            and (d >= 3)
        ):
            chance = max(chance, 80)
        if reaction:
            chance -= (
                8 + attacker.suppression * 0.06 + self.crossfire_pressure(attacker) * 8
            )
        incoming = angle_to(target, attacker)
        flank = angle_diff(target.facing, incoming)
        if flank > 125:
            chance += 22
        elif flank > 75:
            chance += 11
        tc = self.grid[target.tile[1]][target.tile[0]]
        if tc.terrain in ("trench", "firing_step") and tc.axis:
            shot = angle_to(target, attacker)
            axis_deg = 0 if tc.axis == "H" else 90
            along = min(angle_diff(shot, axis_deg), angle_diff(shot, axis_deg + 180))
            if along < 28:
                chance += 12
        if d <= 2.2:
            if attacker.role == "Assault":
                chance += 18
            if attacker.bayonet and attacker.weapon_name in (
                "Service Rifle",
                "Carbine",
            ):
                chance += 8
            if attacker.weapon_name == "Scoped Rifle":
                chance -= 30
        ah = TERRAIN[self.grid[attacker.tile[1]][attacker.tile[0]].terrain]["height"]
        th = TERRAIN[self.grid[target.tile[1]][target.tile[0]].terrain]["height"]
        chance += (ah - th) * 6.0
        if self.weather == "rain":
            chance -= 3
        elif self.weather == "fog":
            chance -= 7
        return clamp(chance, 2, 96)

    def clear_jam(self, u: Unit):
        if u.jammed and u.action_timer <= 0:
            u.action_timer = 1.8
            u.order = "clear_jam"

    def change_barrel(self, u: Unit):
        if (
            u.role not in ("Machine Gunner", "HMG Crew")
            or u.barrel_spares <= 0
            or u.action_timer > 0
        ):
            return
        u.action_timer = 4.0
        u.order = "barrel"

    def set_overwatch(self, u: Unit, center: float, width=90):
        u.overwatch = True
        u.fire_lane = False
        u.fire_lane_center = center
        u.arc_width = width
        u.arc_range = min(u.weapon["range"], 12)
        u.order = "overwatch"

    def place_satchel(self, u: Unit, pos: Coord):
        if u.satchel <= 0 or dist(u.pos, pos) > 1.5:
            return
        u.satchel -= 1
        u.action_timer = 2.0
        self.explosions.append(
            Explosion(pos[0], pos[1], 3.0, 2.7, 130, 95, "HE", u.faction)
        )

    def bayonet_toggle(self, u: Unit):
        if u.weapon_name not in ("Service Rifle", "Carbine"):
            return
        u.bayonet = not u.bayonet

    def medic_action(self, medic: Unit, target: Unit):
        if (
            medic.role != "Medic"
            or medic.med_supplies <= 0
            or dist(medic, target) > 1.5
        ):
            return
        medic.action_timer = 3.0
        medic.order = "medic"
        medic.target_uid = target.uid

    def drag_toggle(self, u: Unit, target: Unit):
        if dist(u, target) > 1.5:
            return
        if target.casualty != "incapacitated":
            return
        u.carrying_uid = None
        u.dragging_uid = None if u.dragging_uid == target.uid else target.uid

    def carry_toggle(self, u: Unit, target: Unit):
        if dist(u, target) > 1.5:
            return
        if target.casualty != "incapacitated":
            return
        u.dragging_uid = None
        u.carrying_uid = None if u.carrying_uid == target.uid else target.uid
        if u.carrying_uid is not None:
            u.target_uid = None
            u.overwatch = False
            u.fire_lane = False

    def share_ammo(self, u: Unit, target: Unit):
        if dist(u, target) > 1.5 or not u.magazines:
            return
        mag = u.magazines.pop()
        if u.weapon_name == target.weapon_name:
            target.magazines.append(mag)
        else:
            u.magazines.append(mag)
            return
        self.add_log(f"{u.role} shared a magazine with {target.role}.")

    def scan_mines(self, u: Unit):
        if u.role not in ("Engineer", "Recon"):
            return
        ux, uy = u.tile
        radius = 5 if u.role == "Engineer" else 4
        for y in range(max(0, uy - radius), min(MAP_H, uy + radius + 1)):
            for x in range(max(0, ux - radius), min(MAP_W, ux + radius + 1)):
                if self.grid[y][x].mine and math.hypot(x - ux, y - uy) <= radius:
                    if u.faction == "player":
                        self.grid[y][x].mine_seen_player = True
                    else:
                        self.grid[y][x].mine_seen_enemy = True
        u.action_timer = 1.5
        u.signature = max(u.signature, 3)

    def peek(self, u: Unit):
        u.peek_until = self.time + 2.0
        u.action_timer = 0.6
        u.signature = max(u.signature, 4)

    def call_support(self, faction: str, pos: Tuple[float, float], smoke=False):
        key = f"{faction}_{('SMOKE' if smoke else 'HE')}"
        if self.support.get(key, 0) <= 0:
            return
        self.support[key] -= 1
        for i in range(4 if not smoke else 3):
            px = clamp(pos[0] + self.rng.uniform(-2.0, 2.0), 0, MAP_W - 1)
            py = clamp(pos[1] + self.rng.uniform(-2.0, 2.0), 0, MAP_H - 1)
            self.explosions.append(
                Explosion(
                    px,
                    py,
                    3.0 + i * 0.35,
                    3.0,
                    85 if not smoke else 0,
                    80 if not smoke else 0,
                    "SMOKE" if smoke else "HE",
                    faction,
                )
            )

    def update_weather_world(self, dt):
        drift_chance = dt * 0.12
        moves = []
        for y, row in enumerate(self.grid):
            for x, c in enumerate(row):
                if c.smoke > 0:
                    c.smoke = max(
                        0, c.smoke - dt * (0.075 if self.weather == "fog" else 0.11)
                    )
                    if c.smoke > 0.8 and self.rng.random() < drift_chance:
                        nx, ny = (x + self.wind[0], y + self.wind[1])
                        if self.in_bounds(nx, ny):
                            moves.append((nx, ny, c.smoke * 0.1))
                if c.ground_suppression > 0:
                    c.ground_suppression = max(0, c.ground_suppression - dt * 2.1)
                if c.fire > 0:
                    c.fire = max(
                        0, c.fire - dt * (0.42 if self.weather == "rain" else 0.14)
                    )
                    if c.fire > 1 and self.rng.random() < dt * 0.04:
                        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                            if self.in_bounds(nx, ny) and self.grid[ny][nx].terrain in (
                                "woods",
                                "building",
                            ):
                                self.grid[ny][nx].fire = max(
                                    self.grid[ny][nx].fire, 2.0
                                )
                if (
                    self.weather == "rain"
                    and c.terrain == "open"
                    and (self.rng.random() < dt * 0.00035)
                ):
                    c.reset_terrain("mud")
        for x, y, s in moves:
            self.grid[y][x].smoke = max(self.grid[y][x].smoke, s)

    def _base_update_unit(self, u: Unit, dt: float):
        if not u.alive:
            return
        if u.casualty == "incapacitated":
            if u.bleed > 0:
                u.bleed -= dt
                if u.bleed <= 0:
                    u.casualty = "dead"
                    self.blood.append(
                        BloodDecal(
                            u.x,
                            u.y,
                            self.rng.uniform(0.45, 0.75),
                            self.rng.randint(0, 999999),
                            1.0,
                        )
                    )
                    self.emit("death", pos=u.pos, cause="bleedout")
                    self.add_log(f"{u.faction} {u.role} bled out.")
            return
        if not u.combat_effective:
            return
        cell = self.grid[u.tile[1]][u.tile[0]]
        cover = max(0, TERRAIN[cell.terrain]["cover"] - cell.cover_wear * 2.2)
        under_fire = u.under_fire_until > self.time or cell.ground_suppression > 22
        decay = (
            0.75 + cover * 0.16 + u.cohesion / 100 * 0.55
            if under_fire
            else 3.0 + cover * 0.42 + u.cohesion / 100 * 1.45
        )
        u.suppression = max(0, u.suppression - dt * decay)
        u.heat = max(0, u.heat - dt * u.weapon["cool"])
        u.signature = max(0, u.signature - dt * 8)
        u.momentum = max(0, u.momentum - dt * 1.65)
        u.incoming_bearings = [
            (a, t) for a, t in u.incoming_bearings if self.time - t <= 3.2
        ]
        moving = u.order in ("move", "rout") and (u.path or u.waypoints)
        if moving:
            drain = 14 if u.move_mode == "fast" else 5.5
            u.stamina = max(0, u.stamina - dt * drain)
            u.stationary_time = 0
            u.prepared = max(0, u.prepared - dt * 0.9)
        else:
            u.stamina = min(100, u.stamina + dt * (11 if u.stance != "standing" else 8))
            if u.suppression < 35 and cover >= 1:
                u.stationary_time += dt
                u.prepared = clamp(u.stationary_time / 4.0, 0, 1)
            else:
                u.stationary_time = max(0, u.stationary_time - dt)
        if cell.ground_suppression > 18:
            u.suppression = clamp(
                u.suppression + dt * cell.ground_suppression * 0.035, 0, 100
            )
        if (u.morale < 16 or u.suppression >= 98) and u.order not in (
            "rout",
            "surrender",
        ):
            self.handle_break(u)
        if u.order not in ("rout", "surrender") and self.should_auto_reload(u):
            self.start_reload(u)
            return
        if u.action_timer > 0:
            u.action_timer -= dt
            if u.action_timer <= 0:
                self.complete_action(u)
            return
        if u.reload_timer > 0:
            u.reload_timer -= dt
            if u.reload_timer <= 0:
                self.finish_reload(u)
            return
        if u.jammed:
            return
        if self.time < u.command_delay_until:
            return
        if u.order == "fire" and u.fire_mode == "aimed" and (not u.path):
            u.aim_progress = clamp(u.aim_progress + dt * 0.55, 0, 1)
        else:
            u.aim_progress = max(0, u.aim_progress - dt * 0.3)
        if u.order in ("move", "rout"):
            self.update_movement(u, dt)
        elif u.order == "fire":
            target = self.get_unit(u.target_uid)
            if not target or not target.combat_effective:
                u.order = "idle"
                u.target_uid = None
            elif self.time >= u.next_shot:
                self.perform_shot(u, target)
        elif u.order == "suppress":
            if self.time >= u.next_shot:
                self.perform_suppressive_shot(u)
        elif u.order in ("overwatch", "fire_lane", "idle"):
            pass
        self.process_command_queue(u)

    def _base_complete_action(self, u: Unit):
        order = u.order
        if order == "clear_jam":
            u.jammed = False
            u.order = "idle"
        elif order == "barrel":
            u.barrel_spares = max(0, u.barrel_spares - 1)
            u.heat = 5
            u.order = "idle"
        elif order == "deploy":
            u.deployed = True
            u.order = "idle"
        elif order == "pack":
            u.deployed = False
            u.order = "idle"
        elif order == "medic":
            t = self.get_unit(u.target_uid)
            if t and dist(u, t) <= 1.7 and (u.med_supplies > 0):
                u.med_supplies -= 1
                if t.casualty == "incapacitated":
                    t.casualty = "wounded"
                    t.hp = max(22, t.max_hp * 0.24)
                    t.bleed = 0
                    t.morale = max(t.morale, 35)
                    self.add_log(f"Medic stabilized {t.role}.")
                elif t.casualty == "wounded":
                    t.hp = min(t.max_hp * 0.75, t.hp + 30)
                    t.bleed = 0
            u.order = "idle"
        elif order.startswith("eng_"):
            if u.target_pos:
                x, y = (int(u.target_pos[0]), int(u.target_pos[1]))
                c = self.grid[y][x]
                if order == "eng_cut" and c.terrain == "wire":
                    c.reset_terrain("open")
                elif order == "eng_mine":
                    c.mine = False
                    c.mine_seen_player = c.mine_seen_enemy = False
                elif order == "eng_fort":
                    c.reset_terrain("sandbags")
                elif order == "eng_trench":
                    c.reset_terrain("trench", "H")
                elif order == "eng_wire":
                    c.reset_terrain("wire")
            u.order = "idle"

    def on_enter_tile(self, u: Unit, x: int, y: int):
        c = self.grid[y][x]
        if c.mine:
            seen = c.mine_seen_player if u.faction == "player" else c.mine_seen_enemy
            trigger = 0.25 if seen else 0.72
            if self.rng.random() < trigger:
                c.mine = False
                c.mine_seen_player = c.mine_seen_enemy = True
                self.explosions.append(
                    Explosion(x, y, 0.05, 1.7, 90, 80, "HE", u.faction)
                )
        if c.ground_suppression > 20:
            u.suppression = clamp(u.suppression + c.ground_suppression * 0.12, 0, 100)
        if c.terrain in ("trench", "firing_step"):
            enemy_half = (
                u.faction == "player"
                and x > MAP_W * 0.58
                or (u.faction == "enemy" and x < MAP_W * 0.42)
            )
            if enemy_half:
                u.momentum = clamp(u.momentum + 22, 0, 100)
                for e in self.living("enemy" if u.faction == "player" else "player"):
                    if dist(e, u) < 3.2:
                        e.suppression = clamp(e.suppression + 10, 0, 100)
                        e.morale = max(0, e.morale - 6)
        if c.fire > 0:
            self.apply_damage(u, 8, None, "fire")

    def find_nearby_cover(self, u: Unit, radius=4) -> Optional[Coord]:
        ux, uy = u.tile
        best = None
        best_score = -999
        for y in range(max(0, uy - radius), min(MAP_H, uy + radius + 1)):
            for x in range(max(0, ux - radius), min(MAP_W, ux + radius + 1)):
                if not self.passable(x, y, u):
                    continue
                d = math.hypot(x - ux, y - uy)
                c = self.grid[y][x]
                score = (
                    TERRAIN[c.terrain]["cover"] * 2.2
                    - self.tile_threat(u.faction, x, y) * 2.4
                    - d * 0.45
                    - c.ground_suppression * 0.03
                )
                if score > best_score and TERRAIN[c.terrain]["cover"] >= 1:
                    best_score = score
                    best = (x, y)
        return best

    def _base_update_auto_behaviors(self):
        for u in self.living("player"):
            if not u.combat_effective:
                continue
            if (
                u.auto_medic
                and u.role == "Medic"
                and (u.med_supplies > 0)
                and (u.order == "idle")
            ):
                wounded = [
                    a
                    for a in self.living("player")
                    if a.uid != u.uid
                    and a.casualty in ("wounded", "incapacitated")
                    and (dist(a, u) <= 1.5)
                ]
                if wounded:
                    self.medic_action(u, min(wounded, key=lambda a: a.hp))
                    continue
            if (
                u.auto_smoke
                and u.smoke_grenades > 0
                and (u.suppression > 78)
                and (u.order in ("idle", "overwatch", "fire_lane"))
            ):
                if self.grid[u.tile[1]][u.tile[0]].smoke < 1.0:
                    self.throw_grenade(u, u.pos, smoke=True)
                    continue
            if (
                u.auto_cover
                and u.suppression > 84
                and (u.order in ("idle", "overwatch", "fire_lane", "fire"))
            ):
                dest = self.find_nearby_cover(u, 3)
                if dest and dest != u.tile:
                    self.issue_move([u], dest, mode="safe", formation="column")

    def bounding_advance(self, units: List[Unit], dest: Coord):
        us = [u for u in units if u.combat_effective]
        if len(us) < 2:
            self.issue_move(us, dest, mode="safe")
            return
        a = [u.uid for i, u in enumerate(us) if i % 2 == 0]
        b = [u.uid for i, u in enumerate(us) if i % 2 == 1]
        self.bounding_orders.append(BoundingOrder(a, b, dest, 0, 0))
        self.add_log("Bounding overwatch advance started.")

    def update_bounding_orders(self, dt):
        for bo in list(self.bounding_orders):
            bo.timer += dt
            A = [self.get_unit(i) for i in bo.a]
            B = [self.get_unit(i) for i in bo.b]
            A = [u for u in A if u and u.combat_effective]
            B = [u for u in B if u and u.combat_effective]
            if not A and (not B):
                self.bounding_orders.remove(bo)
                continue
            if bo.phase == 0:
                sx = sum((u.x for u in A + B)) / max(1, len(A + B))
                sy = sum((u.y for u in A + B)) / max(1, len(A + B))
                mid = (
                    int(round((sx + bo.dest[0]) / 2)),
                    int(round((sy + bo.dest[1]) / 2)),
                )
                self.issue_move(A, mid, mode="safe", formation="line")
                for u in B:
                    self.set_overwatch(u, angle_to(u, bo.dest), 100)
                bo.phase = 1
                bo.timer = 0
            elif bo.phase == 1 and (
                bo.timer > 5 or all((u.order == "idle" for u in A))
            ):
                self.issue_move(B, bo.dest, mode="safe", formation="line")
                for u in A:
                    self.set_overwatch(u, angle_to(u, bo.dest), 100)
                bo.phase = 2
                bo.timer = 0
            elif bo.phase == 2 and (
                bo.timer > 6 or all((u.order == "idle" for u in B))
            ):
                self.issue_move(A, bo.dest, mode="safe", formation="line")
                bo.phase = 3
                bo.timer = 0
            elif bo.phase == 3 and (
                bo.timer > 6 or all((dist(u.pos, bo.dest) < 3 for u in A + B))
            ):
                for u in A + B:
                    if u.order == "idle":
                        self.set_overwatch(u, angle_to(u, bo.dest), 120)
                self.bounding_orders.remove(bo)

    def _base_update_ai(self, dt):
        delay = DIFFICULTY[self.difficulty]["ai"]
        for u in self.living("enemy"):
            if (
                not u.combat_effective
                or u.order in ("rout", "medic", "deploy", "pack", "barrel", "clear_jam")
                or u.action_timer > 0
            ):
                continue
            if self.time - u.last_ai < delay:
                continue
            u.last_ai = self.time + self.rng.uniform(0, 0.15)
            self.ai_decide(u)

    def _base_toggle_door(self, u: Unit, pos: Coord):
        if dist(u.pos, pos) > 1.6:
            return
        x, y = pos
        c = self.grid[y][x]
        if c.terrain != "door":
            return
        c.door_open = not c.door_open
        u.action_timer = 0.55
        self.add_log(f"{u.role} {('opened' if c.door_open else 'closed')} a door.")

    def coordinated_advance(self, units: List[Unit], dest: Coord):
        """MG/automatic weapons cover while maneuver elements advance."""
        if not units:
            return
        coverers = [
            u
            for u in units
            if u.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman")
            and u.combat_effective
        ]
        movers = [u for u in units if u not in coverers and u.combat_effective]
        for u in coverers:
            if u.role in ("Machine Gunner", "HMG Crew") and (not u.deployed):
                self.toggle_deploy(u)
            u.covering_uid = movers[0].uid if movers else None
            self.suppress_area(u, dest)
        if movers:
            self.issue_move(movers, dest, mode="safe", formation="wedge")
            for m in movers:
                m.momentum = clamp(m.momentum + 10, 0, 100)
        self.add_log("Coordinated covering advance ordered.")

    def cycle_stance(self, u: Unit):
        order = ["standing", "crouched", "prone"]
        u.stance = order[(order.index(u.stance) + 1) % 3]

    def cycle_move_mode(self, u: Unit):
        modes = ["fast", "safe", "manual"]
        u.move_mode = modes[(modes.index(u.move_mode) + 1) % 3]

    def _kz_event_record(self, kind: str, text: str, pos=None):
        if not hasattr(self, "battle_events"):
            self.battle_events = []
        self.battle_events.append(
            {"time": self.time, "kind": kind, "text": text, "pos": pos}
        )
        self.battle_events = self.battle_events[-500:]

    def set_cell(self, x, y, terrain, axis=None):
        self._base_set_cell(x, y, terrain, axis)
        self._terrain_revision = getattr(self, "_terrain_revision", 0) + 1
        if hasattr(self, "_path_cache") and len(self._path_cache) > 256:
            self._path_cache.clear()

    def _kz_generate_map(self):
        for y in range(MAP_H):
            for x in range(MAP_W):
                self.set_cell(x, y, "open")
        road_y = self.rng.randint(7, MAP_H - 8)
        for x in range(MAP_W):
            self.set_cell(x, road_y, "road")
        p = self.primary_line_x
        s = self.secondary_line_x
        for y in range(2, MAP_H - 2):
            xx = p + (1 if y // 6 % 2 else 0)
            self.set_cell(xx, y, "trench", "V")
            if y % 6 == 3:
                self.set_cell(max(1, xx - 1), y, "firing_step", "H")
        for y in range(3, MAP_H - 3):
            if y % 2 == 0 or self.rng.random() < 0.7:
                self.set_cell(s, y, "trench", "V")
        strong_ys = [6, MAP_H // 2, MAP_H - 7]
        for sy in strong_ys:
            for x in range(p, min(MAP_W - 2, s + 1)):
                self.set_cell(x, sy, "trench", "H")
            self.set_cell(p + 2, sy, "bunker")
            self.set_cell(p + 1, sy - 1, "sandbags")
            self.set_cell(p + 1, sy + 1, "sandbags")
            if self.in_bounds(p + 3, sy + 1):
                self.set_cell(p + 3, sy + 1, "dugout")
        cy = MAP_H // 2 + 3
        for x in range(p - 4, s + 1):
            self.set_cell(x, cy, "trench", "H")
        wx = p - 5
        gap_ys = [road_y, 5, MAP_H // 2 + 1, MAP_H - 6]
        for y in range(1, MAP_H - 1):
            if all((abs(y - g) > 1 for g in gap_ys)):
                self.set_cell(wx, y, "wire")
        for _ in range(46):
            x = self.rng.randint(wx - 2, p - 1)
            y = self.rng.randint(2, MAP_H - 3)
            if all((abs(y - g) > 1 for g in gap_ys)) and self.grid[y][x].terrain in (
                "open",
                "mud",
                "road",
            ):
                self.grid[y][x].mine = True
        for lane_y in gap_ys:
            for x in range(7, wx - 1, 3):
                yy = int(clamp(lane_y + self.rng.randint(-2, 2), 1, MAP_H - 2))
                if self.grid[yy][x].terrain == "open":
                    self.set_cell(
                        x, yy, self.rng.choice(["crater", "crater", "foxhole", "mud"])
                    )
                if (
                    self.rng.random() < 0.42
                    and yy + 1 < MAP_H - 1
                    and (self.grid[yy + 1][x].terrain == "open")
                ):
                    self.set_cell(x, yy + 1, "crater")
        for base_y in (4, MAP_H - 5):
            for _ in range(5):
                cx = self.rng.randint(10, wx - 3)
                cy = int(clamp(base_y + self.rng.randint(-3, 3), 2, MAP_H - 3))
                for _ in range(self.rng.randint(7, 13)):
                    x = int(clamp(cx + self.rng.randint(-2, 2), 1, MAP_W - 2))
                    y = int(clamp(cy + self.rng.randint(-2, 2), 1, MAP_H - 2))
                    if self.grid[y][x].terrain == "open":
                        self.set_cell(x, y, self.rng.choice(["woods", "woods", "hill"]))
        bx = self.rng.randint(18, 25)
        by = self.rng.randint(7, MAP_H - 10)
        for x in range(bx, bx + 6):
            for y in (by, by + 5):
                self.set_cell(x, y, "building")
        for y in range(by, by + 6):
            for x in (bx, bx + 5):
                self.set_cell(x, y, "building")
        self.set_cell(bx + 2, by + 5, "door")
        self.set_cell(bx + 1, by, "window")
        self.set_cell(bx + 4, by, "window")
        for _ in range(95):
            x = self.rng.randint(8, wx - 2)
            y = self.rng.randint(2, MAP_H - 3)
            if self.grid[y][x].terrain == "open":
                self.set_cell(
                    x, y, self.rng.choice(["crater", "crater", "mud", "open"])
                )
        for _ in range(18):
            x = self.rng.randint(p - 2, MAP_W - 3)
            y = self.rng.randint(2, MAP_H - 3)
            if self.grid[y][x].terrain == "open":
                self.set_cell(x, y, "wall")
        self.map_features = {
            "road_y": road_y,
            "wire_x": wx,
            "breaches": gap_ys,
            "primary_x": p,
            "secondary_x": s,
        }

    def _kz_add_unit(self, faction, role, x, y):
        u = self._base_add_unit(faction, role, x, y)
        same = [a for a in self.units if a.faction == faction and a.uid != u.uid]
        u.squad_id = len(same) // 4 + 1
        u.wait_until = 0.0
        u.blocked_since = 0.0
        u.mortar_ranging = 0.0
        u.shots_recent = 0
        u.last_shot_time = -99.0
        u.reserve = False
        if hasattr(self, "_uid_index"):
            self._uid_index[u.uid] = u
        if hasattr(self, "_occupancy"):
            self._occupancy[u.tile] = u.uid
        return u

    def _kz_spawn_default_forces(self):
        roles = list(self.player_roster)
        rc = min(self.reserve_count, max(0, len(roles) - 1))
        active = roles[:-rc] if rc else roles
        self.player_reserves = roles[-rc:] if rc else []
        for i, role in enumerate(active):
            x = 3 + i % 4
            y = 4 + i // 4 * 6 + i % 2
            self.add_unit("player", role, x, min(y, MAP_H - 3))
        enemy_pool = [
            "Rifleman",
            "Rifleman",
            "Machine Gunner",
            "Marksman",
            "Assault",
            "Grenadier",
            "Engineer",
            "Medic",
            "Automatic Rifleman",
            "HMG Crew",
            "Sniper",
        ]
        n = DIFFICULTY[self.difficulty]["enemy"]
        spots = []
        for xx in (self.primary_line_x, self.primary_line_x + 1, self.secondary_line_x):
            for y in range(2, MAP_H - 2):
                if self.in_bounds(xx, y) and self.grid[y][xx].terrain in (
                    "trench",
                    "firing_step",
                    "bunker",
                    "sandbags",
                ):
                    spots.append((xx, y))
        self.rng.shuffle(spots)
        for i in range(n):
            role = enemy_pool[i % len(enemy_pool)]
            x, y = spots[i % len(spots)] if spots else (self.primary_line_x, 3 + i)
            if self.unit_at(x, y) is not None:
                y = int(clamp(y + 1, 1, MAP_H - 2))
            u = self.add_unit("enemy", role, x, y)
            if role in ("Machine Gunner", "HMG Crew"):
                u.deployed = True
                u.fire_lane = True
                u.fire_lane_center = 180
                u.arc_width = 85
            u.fallback_point = (self.secondary_line_x, int(clamp(y, 2, MAP_H - 3)))
        self._kz_rebuild_indexes()

    def get_unit(self, uid):
        if uid is None:
            return None
        u = getattr(self, "_uid_index", {}).get(uid)
        if u is None:
            u = next((x for x in self.units if x.uid == uid), None)
            if u is not None:
                self._uid_index[uid] = u
        return u

    def living(self, faction=None):
        if faction is None:
            return [u for u in self.units if u.alive]
        return [
            u
            for u in self.units
            if u.faction == faction and u.alive
        ]

    def unit_at(self, x, y, include_incap=True):
        occ = getattr(self, "_occupancy", None)
        if occ is not None:
            uid = occ.get((x, y))
            if not uid:
                return None
            u = self.get_unit(uid)
            if (
                u
                and u in self.units
                and u.alive
                and (u.tile == (x, y))
                and (include_incap or u.combat_effective)
            ):
                return u
            occ.pop((x, y), None)
            return None
        for u in self.units:
            if not u.alive:
                continue
            if not include_incap and (not u.combat_effective):
                continue
            if u.tile == (x, y):
                return u
        return None

    def _kz_hit_chance(self, attacker, target, mode=None, reaction=False):
        c = self._base_hit_chance(attacker, target, mode=mode, reaction=reaction)
        if (
            attacker.role == "Sniper"
            and attacker.signature < 10
            and (attacker.prepared > 0.65)
            and ((mode or attacker.fire_mode) == "aimed")
        ):
            c = min(96, c + 8)
        return c

    def update_ai(self, dt):
        t0 = time.perf_counter()
        enemies = [u for u in self.living("enemy") if u.combat_effective]
        if not enemies:
            return
        budget = (
            2 if self.difficulty == "Easy" else 3 if self.difficulty == "Hard" else 4
        )
        checked = 0
        done = 0
        delay = DIFFICULTY[self.difficulty]["ai"]
        n = len(enemies)
        while checked < n and done < budget:
            u = enemies[self._ai_cursor % n]
            self._ai_cursor = (self._ai_cursor + 1) % max(1, n)
            checked += 1
            if (
                u.order in ("rout", "medic", "deploy", "pack", "barrel", "clear_jam")
                or u.action_timer > 0
            ):
                continue
            if self.time - u.last_ai < delay:
                continue
            u.last_ai = self.time + self.rng.uniform(0, 0.12)
            self.ai_decide(u)
            done += 1
        self._perf["ai_decisions"] += done
        self._perf["ai_ms"] += (time.perf_counter() - t0) * 1000

    def nearest_open(self, x, y, unit=None, radius=5, prefer=None):
        prefer = prefer or (
            "trench",
            "firing_step",
            "bunker",
            "sandbags",
            "foxhole",
            "dugout",
            "crater",
            "open",
        )
        choices = []
        for rr in range(radius + 1):
            for yy in range(max(1, y - rr), min(MAP_H - 1, y + rr + 1)):
                for xx in range(max(1, x - rr), min(MAP_W - 1, x + rr + 1)):
                    if abs(xx - x) + abs(yy - y) > rr:
                        continue
                    if not self.passable(xx, yy, unit):
                        continue
                    t = self.grid[yy][xx].terrain
                    rank = prefer.index(t) if t in prefer else len(prefer) + 2
                    choices.append((rank, abs(xx - x) + abs(yy - y), xx, yy))
            if choices:
                break
        if not choices:
            return None
        choices.sort()
        return (choices[0][2], choices[0][3])

    def _vs_generate_map(self):
        self._kz_generate_map()
        variants = list(MISSION_VARIANTS)
        self.battle_variant = variants[self.seed % len(variants)]
        p = self.primary_line_x
        s = self.secondary_line_x
        variant = self.battle_variant
        vr = random.Random(self.seed ^ 1511506142)
        if variant == "farmland":
            for _ in range(16):
                y = vr.randint(3, MAP_H - 4)
                x0 = vr.randint(10, max(11, p - 13))
                length = vr.randint(3, 7)
                for x in range(x0, min(p - 6, x0 + length)):
                    if self.grid[y][x].terrain == "open" and vr.random() < 0.72:
                        self.set_cell(x, y, "wall")
        elif variant == "wooded_ridge":
            for base_y in (6, MAP_H - 7):
                for _ in range(55):
                    x = vr.randint(8, max(9, p - 6))
                    y = int(clamp(base_y + vr.randint(-5, 5), 2, MAP_H - 3))
                    if self.grid[y][x].terrain in ("open", "mud", "hill"):
                        self.set_cell(x, y, "woods" if vr.random() < 0.72 else "hill")
        elif variant == "ruined_village":
            for bi in range(3):
                bx = vr.randint(14, max(15, p - 12))
                by = vr.randint(4, MAP_H - 10)
                w = vr.choice((4, 5))
                h = vr.choice((4, 5))
                for x in range(bx, bx + w):
                    for y in (by, by + h):
                        if self.in_bounds(x, y):
                            self.set_cell(
                                x, y, "building" if vr.random() > 0.28 else "rubble"
                            )
                for y in range(by, by + h + 1):
                    for x in (bx, bx + w):
                        if self.in_bounds(x, y):
                            self.set_cell(
                                x, y, "building" if vr.random() > 0.28 else "rubble"
                            )
                if self.in_bounds(bx + w // 2, by + h):
                    self.set_cell(bx + w // 2, by + h, "door")
        else:
            for _ in range(95):
                x = vr.randint(12, min(MAP_W - 2, p + 2))
                y = vr.randint(2, MAP_H - 3)
                if self.grid[y][x].terrain in ("open", "mud") and vr.random() < 0.72:
                    self.set_cell(x, y, "hill")
        command = (MAP_W - 4, MAP_H // 2)
        cx, cy = command
        self.set_cell(cx, cy, "bunker")
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1)):
            if self.in_bounds(cx + dx, cy + dy) and self.grid[cy + dy][
                cx + dx
            ].terrain not in ("trench", "bunker"):
                self.set_cell(cx + dx, cy + dy, "sandbags")
        strong = (min(MAP_W - 3, p + 2), MAP_H // 2)
        self.set_cell(*strong, "bunker")
        self.map_features.update(
            {"variant": variant, "command_post": command, "strongpoint": strong}
        )

    def _vs_add_unit(self, faction, role, x, y):
        u = self._kz_add_unit(faction, role, x, y)
        rr = random.Random(
            self.seed << 9 ^ u.uid * 7919 ^ (1 if faction == "player" else 7)
        )
        if faction == "player":
            letter = chr(64 + max(1, min(5, getattr(u, "squad_id", 1))))
            slot = (u.uid - 1) % 4 + 1
            u.display_name = f"{letter}{slot} {rr.choice(PLAYER_SURNAMES)}"
        else:
            u.display_name = (
                f"{_vs_sector_name(y).title()} {ROLE_CONTACT.get(role, role).title()}"
            )
        u.battle_role = "line"
        u.battle_sector = _vs_sector_name(y)
        u.reserve_active = True
        u.plan_state = "hold"
        u.counterattack_point = None
        u.initial_battle_role = "line"
        return u

    def spawn_default_forces(self):
        self._kz_spawn_default_forces()
        enemies = [u for u in self.units if u.faction == "enemy"]
        p = self.primary_line_x
        s = self.secondary_line_x
        cmd = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
        n = len(enemies)
        reserve_n = max(2, int(round(n * 0.28)))
        command_n = max(1, int(round(n * 0.12)))
        ordered = sorted(enemies, key=lambda u: (u.x, u.uid), reverse=True)
        command_group = ordered[:command_n]
        reserve_group = ordered[command_n : command_n + reserve_n]
        for u in enemies:
            u.battle_sector = _vs_sector_name(u.y)
            u.initial_battle_role = "forward"
            u.battle_role = "forward"
            u.plan_state = "hold"
            u.reserve_active = True
            u.fallback_point = (s, int(clamp(round(u.y), 2, MAP_H - 3)))
        for i, u in enumerate(reserve_group):
            u.initial_battle_role = "reserve"
            u.battle_role = "reserve"
            u.plan_state = "reserve"
            u.reserve_active = False
            target = self.nearest_open(
                s, int(clamp(5 + i * 7 % (MAP_H - 8), 2, MAP_H - 3)), u, 4
            )
            if target:
                u.x, u.y = target
                self._kz_rebuild_indexes()
            u.battle_sector = _vs_sector_name(u.y)
            u.fallback_point = (cmd[0] - 1, int(clamp(round(u.y), 2, MAP_H - 3)))
        for i, u in enumerate(command_group):
            u.initial_battle_role = "command"
            u.battle_role = "command"
            u.plan_state = "command"
            u.reserve_active = True
            target = self.nearest_open(
                cmd[0] - 1, int(clamp(cmd[1] + i - 1, 2, MAP_H - 3)), u, 4
            )
            if target:
                u.x, u.y = target
                self._kz_rebuild_indexes()
            u.battle_sector = _vs_sector_name(u.y)
            u.fallback_point = cmd
        self._kz_rebuild_indexes()

    def _vs_event(self, kind, text, pos=None):
        self._kz_event_record(kind, text, pos)

    def notify(self, text, kind="info", duration=4.0):
        if not hasattr(self, "notifications"):
            self.notifications = []
        self.notifications.append(
            {
                "text": text,
                "kind": kind,
                "until": self.time + duration,
                "born": self.time,
            }
        )
        self.notifications = self.notifications[-8:]

    def launch_counterattack(self):
        if self._counterattack_launched:
            return
        candidates = [
            u
            for u in self.living("enemy")
            if u.combat_effective
            and getattr(u, "initial_battle_role", "") == "reserve"
            and (u.role in ("Assault", "Rifleman", "Grenadier", "Automatic Rifleman"))
        ]
        if not candidates:
            candidates = [
                u
                for u in self.living("enemy")
                if u.combat_effective
                and getattr(u, "initial_battle_role", "") == "reserve"
                and (u.role not in ("Medic", "Mortar Team"))
            ]
        if not candidates:
            return
        self._counterattack_launched = True
        count = (
            1
            if self.difficulty == "Easy"
            else 2
            if self.difficulty == "Hard"
            else min(4, len(candidates))
        )
        point = self.map_features["strongpoint"]
        for u in candidates[:count]:
            u.reserve_active = True
            u.plan_state = "counterattack"
            u.counterattack_point = point
            self.issue_move([u], point, mode="safe", formation="column")
        self.notify("CONTACT — ENEMY COUNTERATTACK", kind="danger", duration=5)
        self._vs_event("counterattack", "Enemy reserve counterattack launched", point)

    def _vs_update_sector_stability(self):
        p = self.primary_line_x
        player_by_sector = {
            sec: [
                u
                for u in self.living("player")
                if u.combat_effective and _vs_sector_name(u.y) == sec and (u.x >= p - 2)
            ]
            for sec in ("NORTH", "CENTRE", "SOUTH")
        }
        for sec in ("NORTH", "CENTRE", "SOUTH"):
            defenders = [
                u
                for u in self.units
                if u.faction == "enemy"
                and getattr(u, "initial_battle_role", "") == "forward"
                and (getattr(u, "battle_sector", "") == sec)
            ]
            alive = [u for u in defenders if u.combat_effective]
            initial = max(1, self.initial_sector_counts.get(sec, len(defenders) or 1))
            loss = 1 - len(alive) / initial
            if alive:
                supp = sum((u.suppression for u in alive)) / len(alive)
                morale = sum((u.morale for u in alive)) / len(alive)
                cross = sum((self.crossfire_pressure(u) for u in alive)) / len(alive)
            else:
                supp = 100
                morale = 0
                cross = 1
            breach = 1 if player_by_sector[sec] else 0
            stability = (
                100
                - loss * 45
                - supp * 0.3
                - (100 - morale) * 0.22
                - cross * 18
                - breach * 24
            )
            stability -= (
                sum((1 for other in self.collapsed_sectors if other != sec)) * 5
            )
            self.sector_stability[sec] = clamp(stability, 0, 100)
            if stability < 27 and sec not in self.collapsed_sectors:
                self.collapsed_sectors.add(sec)
                self.notify(f"ENEMY LINE COLLAPSING — {sec}", kind="good", duration=5)
                self._vs_event(
                    "collapse",
                    f"{sec.title()} defensive sector collapsed",
                    (
                        p,
                        {
                            "NORTH": MAP_H // 6,
                            "CENTRE": MAP_H // 2,
                            "SOUTH": MAP_H * 5 // 6,
                        }[sec],
                    ),
                )
                for u in alive:
                    friend_near = sum(
                        (
                            1
                            for a in self.living("enemy")
                            if a.uid != u.uid
                            and a.combat_effective
                            and (dist(a, u) < 4.5)
                        )
                    )
                    player_near = sum(
                        (
                            1
                            for a in self.living("player")
                            if a.combat_effective and dist(a, u) < 3.5
                        )
                    )
                    if (
                        u.morale < 22
                        and u.suppression > 82
                        and (friend_near <= 1)
                        and player_near
                    ):
                        u.casualty = "surrendered"
                        u.order = "surrender"
                        u.path = []
                        u.waypoints = []
                        self.stats["enemy"]["surrendered"] += 1
                        self._vs_event(
                            "surrender", f"{u.display_name} surrendered", u.pos
                        )
                    else:
                        u.plan_state = "fallback"
                        fp = (
                            self.secondary_line_x,
                            int(clamp(round(u.y), 2, MAP_H - 3)),
                        )
                        u.fallback_point = fp
                        if u.deployed and u.role in ("Machine Gunner", "HMG Crew"):
                            self.toggle_deploy(u)
                        elif self.passable(*fp, u):
                            self.issue_move([u], fp, mode="safe", formation="column")

    def update_battle_stage(self, dt):
        self.combat_intensity = max(0, self.combat_intensity - dt * 1.8)
        if self.objective_index >= 3 or len(self.collapsed_sectors) >= 2:
            stage = "COLLAPSE"
        elif self.objective_index >= 1 or self.assault_orders:
            stage = "ASSAULT"
        elif self.combat_intensity > 5 or any(
            (self.visible_to("player", u) for u in self.living("enemy"))
        ):
            stage = "CONTACT"
        else:
            stage = "APPROACH"
        if stage != self.battle_stage:
            self._last_stage = self.battle_stage
            self.battle_stage = stage
            labels = {
                "CONTACT": "CONTACT — ENEMY ENGAGED",
                "ASSAULT": "ASSAULT PHASE",
                "COLLAPSE": "EXPLOIT — DEFENCE UNRAVELLING",
            }
            if stage in labels:
                self.notify(
                    labels[stage],
                    kind="objective"
                    if stage == "ASSAULT"
                    else "good"
                    if stage == "COLLAPSE"
                    else "danger",
                    duration=4,
                )

    def emit(self, event_type, **payload):
        self._base_emit(event_type, **payload)
        if event_type == "shot":
            self.combat_intensity = min(100, self.combat_intensity + 1.2)
        elif event_type == "explosion":
            self.combat_intensity = min(100, self.combat_intensity + 8)
        elif event_type == "hurt":
            self.combat_intensity = min(100, self.combat_intensity + 2)
        elif event_type == "death":
            self.combat_intensity = min(100, self.combat_intensity + 5)

    def toggle_door(self, u, pos):
        x, y = pos if pos else (-1, -1)
        before = (
            self.grid[y][x].door_open
            if self.in_bounds(x, y) and self.grid[y][x].terrain == "door"
            else None
        )
        self._base_toggle_door(u, pos)
        after = (
            self.grid[y][x].door_open
            if self.in_bounds(x, y) and self.grid[y][x].terrain == "door"
            else None
        )
        if before is not None and before != after:
            self._terrain_state.value += 1

    def _perf_add_unit(self, faction, role, x, y):
        u = self._vs_add_unit(faction, role, x, y)
        u.morale_state = "STEADY"
        u.low_morale_since = None
        u.breaking_since = None
        u.rout_started_at = 0.0
        u.rally_target = None
        u.rallying = False
        u.rally_safe_since = None
        u.hold_position = False
        u.survival_react_at = 0.0
        u.squad_morale = 100.0
        u.rally_shock = 0.0
        u._cleanup_state = None
        return u

    def _perf_cleanup_unit(self, u, reason="combat exit"):
        state = (u.casualty, bool(u.combat_effective))
        if getattr(u, "_cleanup_state", None) == state:
            return
        u._cleanup_state = state
        u.overwatch = False
        u.fire_lane = False
        u.target_uid = None
        u.target_pos = None
        u.reaction_target_uid = None
        u.covering_uid = None
        u.path = []
        u.waypoints = []
        u.command_queue = []
        u.command_delay_until = 0
        u.reaction_ready_at = 0
        u.traverse_ready_at = 0
        if u.dragging_uid is not None:
            u.dragging_uid = None
        if u.carrying_uid is not None:
            u.carrying_uid = None
        for other in self.units:
            if other.uid == u.uid:
                continue
            if other.target_uid == u.uid:
                other.target_uid = None
                if other.order == "fire":
                    other.order = "idle"
            if other.reaction_target_uid == u.uid:
                other.reaction_target_uid = None
            if other.covering_uid == u.uid:
                other.covering_uid = None
            if other.dragging_uid == u.uid:
                other.dragging_uid = None
            if other.carrying_uid == u.uid:
                other.carrying_uid = None
        for bo in list(self.bounding_orders):
            bo.a = [i for i in bo.a if i != u.uid]
            bo.b = [i for i in bo.b if i != u.uid]
            if not bo.a and (not bo.b):
                self.bounding_orders.remove(bo)
        for ao in list(getattr(self, "assault_orders", [])):
            ao.support = [i for i in ao.support if i != u.uid]
            ao.assault = [i for i in ao.assault if i != u.uid]
            if not ao.assault:
                self.assault_orders.remove(ao)
        if (
            hasattr(self, "_occupancy")
            and self._occupancy.get(u.tile) == u.uid
            and (not u.combat_effective)
        ):
            self._occupancy.pop(u.tile, None)

    def _perf_update_unit(self, u, dt):
        before = u.casualty
        was_rout = u.order == "rout"
        self._base_update_unit(u, dt)
        if before != u.casualty and u.casualty in (
            "dead",
            "incapacitated",
            "surrendered",
        ):
            self.cleanup_unit_state(u, u.casualty)
        if not u.combat_effective:
            return
        if was_rout and u.order != "rout":
            u.rallying = True
        if u.order != "rout" and (not getattr(u, "rallying", False)):
            return
        if (
            u.order == "rout"
            and getattr(u, "rally_target", None)
            and (dist(u.pos, u.rally_target) < 1.6)
        ):
            u.path = []
            u.waypoints = []
            u.order = "idle"
            u.rallying = True
        if getattr(u, "rallying", False):
            cell = self.grid[u.tile[1]][u.tile[0]]
            enemy = "enemy" if u.faction == "player" else "player"
            nearest = min(
                (dist(u, e) for e in self.living(enemy) if e.combat_effective),
                default=99,
            )
            safe = (
                u.under_fire_until <= self.time
                and cell.ground_suppression < 18
                and (nearest > 5.5)
            )
            if safe:
                if u.rally_safe_since is None:
                    u.rally_safe_since = self.time
                u.suppression = max(0, u.suppression - dt * 4.5)
                u.morale = clamp(u.morale + dt * 2.7, 0, 100)
                u.cohesion = clamp(u.cohesion + dt * 1.8, 0, 100)
                if (
                    self.time - u.rally_safe_since >= 3.5
                    and u.morale >= 30
                    and (u.suppression < 42)
                    and (u.cohesion >= 40)
                ):
                    u.rallying = False
                    u.rally_safe_since = None
                    u.low_morale_since = None
                    u.breaking_since = None
                    u.morale_state = "SHAKEN"
                    u.order = "idle"
                    self.add_log(f"{getattr(u, 'display_name', u.role)} rallied.")
            else:
                u.rally_safe_since = None

    def update_sector_stability(self):
        p = self.primary_line_x
        player_by_sector = {
            sec: [
                u
                for u in self.living("player")
                if u.combat_effective and _vs_sector_name(u.y) == sec and (u.x >= p - 2)
            ]
            for sec in ("NORTH", "CENTRE", "SOUTH")
        }
        for sec in ("NORTH", "CENTRE", "SOUTH"):
            defenders = [
                u
                for u in self.units
                if u.faction == "enemy"
                and getattr(u, "initial_battle_role", "") == "forward"
                and (getattr(u, "battle_sector", "") == sec)
            ]
            alive = [u for u in defenders if u.combat_effective]
            initial = max(1, self.initial_sector_counts.get(sec, len(defenders) or 1))
            loss = 1 - len(alive) / initial
            if alive:
                supp = sum((u.suppression for u in alive)) / len(alive)
                morale = sum((u.morale for u in alive)) / len(alive)
                cross = sum((self.crossfire_pressure(u) for u in alive)) / len(alive)
            else:
                supp = 100
                morale = 0
                cross = 1
            breach = 1 if player_by_sector[sec] else 0
            stability = (
                100
                - loss * 45
                - supp * 0.3
                - (100 - morale) * 0.22
                - cross * 18
                - breach * 24
                - sum((1 for other in self.collapsed_sectors if other != sec)) * 5
            )
            stability = clamp(stability, 0, 100)
            self.sector_stability[sec] = stability
            if stability < 27 and sec not in self.collapsed_sectors:
                if self._sector_low_since.get(sec) is None:
                    self._sector_low_since[sec] = self.time
                held = self.time - self._sector_low_since[sec]
                if held < 2.5 and stability >= 10:
                    continue
                self.collapsed_sectors.add(sec)
                self._sector_low_since[sec] = None
                self.notify(f"ENEMY LINE COLLAPSING — {sec}", kind="good", duration=5)
                self._vs_event(
                    "collapse",
                    f"{sec.title()} defensive sector collapsed",
                    (
                        p,
                        {
                            "NORTH": MAP_H // 6,
                            "CENTRE": MAP_H // 2,
                            "SOUTH": MAP_H * 5 // 6,
                        }[sec],
                    ),
                )
                for u in alive:
                    low_for = (
                        self.time - u.low_morale_since
                        if u.low_morale_since is not None
                        else 0
                    )
                    friend_near = sum(
                        (
                            1
                            for a in self.living("enemy")
                            if a.uid != u.uid
                            and a.combat_effective
                            and (dist(a, u) < 4.5)
                        )
                    )
                    player_near = sum(
                        (
                            1
                            for a in self.living("player")
                            if a.combat_effective and dist(a, u) < 3.5
                        )
                    )
                    if (
                        u.morale < 18
                        and u.suppression > 88
                        and (friend_near <= 1)
                        and player_near
                        and (low_for >= 5)
                    ):
                        u.casualty = "surrendered"
                        u.order = "surrender"
                        self.cleanup_unit_state(u, "sector surrender")
                        self.stats["enemy"]["surrendered"] += 1
                        self._vs_event(
                            "surrender", f"{u.display_name} surrendered", u.pos
                        )
                    else:
                        u.plan_state = "fallback"
                        u.fallback_point = (
                            self.secondary_line_x,
                            int(clamp(round(u.y), 2, MAP_H - 3)),
                        )
                        if u.deployed and u.role in ("Machine Gunner", "HMG Crew"):
                            self.toggle_deploy(u)
                        else:
                            fp = self.choose_retreat_position(
                                u,
                                extra_rear=u.role in ("Medic", "Mortar Team", "Sniper"),
                            )
                            if self.passable(*fp, u):
                                self.issue_move(
                                    [u], fp, mode="safe", formation="column"
                                )
            elif stability > 34:
                self._sector_low_since[sec] = None

    def _maintenance_add_unit(self, faction, role, x, y):
        squad_id = self.auto_squad_for(faction, role)
        unit = self._perf_add_unit(faction, role, x, y)
        unit.squad_id = squad_id
        if faction == "player" and hasattr(unit, "display_name"):
            surname = unit.display_name.split(" ", 1)[-1]
            slot = sum(
                (
                    other.faction == faction
                    and getattr(other, "squad_id", 0) == squad_id
                    for other in self.units
                )
            )
            unit.display_name = f"{chr(64 + min(26, squad_id))}{slot} {surname}"
        return unit

    def cleanup_unit_state(self, unit, reason="combat exit"):
        unit._cleanup_state = None
        return self._perf_cleanup_unit(unit, reason)

    def _combat2_add_unit(self, faction, role, x, y):
        unit = self._maintenance_add_unit(faction, role, x, y)
        return _combat2_initialize_unit(self, unit)

    def _combat2_hit_chance(self, attacker, target, mode=None, reaction=False):
        chance = self._moving_fire_hit_chance(
            attacker, target, mode=mode, reaction=reaction
        )
        if chance <= 0:
            return chance
        penalty = _combat2_wound_penalties(attacker)["aim"]
        if self.time < getattr(attacker, "combat2_settle_until", 0.0):
            penalty += 12.0
        return clamp(chance - penalty, 2, 96)

    def _combat2_terrain_collision(self, projectile, x, y):
        cell = self.grid[y][x]
        terrain = TERRAIN[cell.terrain]
        cover = float(terrain["cover"])
        resistance = float(terrain["pen"])
        closed_door = cell.terrain == "door" and (not cell.door_open)
        hard = bool(
            terrain["blocks"] or closed_door or cell.terrain in ("wall", "building")
        )
        material = hard or cell.terrain in (
            "woods",
            "sandbags",
            "bunker",
            "woodwall",
            "window",
            "door",
            "dugout",
        )
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
            projectile.penetration = max(
                0.0, projectile.penetration - max(0.65, resistance)
            )
            self.impacts.append(
                Impact(projectile.x, projectile.y, _combat2_impact_kind(cell), 0.16)
            )
            return False
        self.impacts.append(
            Impact(projectile.x, projectile.y, _combat2_impact_kind(cell), 0.22)
        )
        return True

    def _base_combat2_apply_near_miss(self, projectile, unit, distance_to_path):
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
            self.grid[ty][tx].ground_suppression + gain * 0.42, 0, 100
        )

    def complete_action(self, unit):
        medic_target = self.get_unit(unit.target_uid) if unit.order == "medic" else None
        result = self._operation_complete_action(unit)
        if medic_target is not None and medic_target.alive:
            for location in ("head", "torso", "arm", "leg"):
                attr = f"wound_{location}"
                setattr(
                    medic_target, attr, float(getattr(medic_target, attr, 0.0)) * 0.58
                )
            medic_target.wound_treated = True
        return result

    def combat2_local_strength(self, faction, position, radius=5.5):
        return sum(
            (
                1.35 if unit.role in COMBAT2_SUPPORT_ROLES else 1.0
                for unit in self.living(faction)
                if unit.combat_effective and dist(unit.pos, position) <= radius
            )
        )

    def add_unit(self, faction, role, x, y):
        return _polish_initialize_unit(self._combat2_add_unit(faction, role, x, y))

    def smoke_blocks_support(self, thrower, position):
        """Avoid smoke that would blind a friendly support weapon's active lane."""
        px, py = (float(position[0]), float(position[1]))
        for support in self.living(thrower.faction):
            if support.uid == thrower.uid or support.role not in COMBAT2_SUPPORT_ROLES:
                continue
            if support.order not in ("fire", "suppress", "fire_lane", "overwatch"):
                continue
            target = (
                self.get_unit(support.target_uid)
                if support.target_uid is not None
                else None
            )
            aim = (
                target.pos
                if target is not None
                else getattr(support, "target_pos", None)
            )
            if aim is None and support.order in ("fire_lane", "overwatch"):
                radians = math.radians(support.facing)
                aim = (
                    support.x + math.cos(radians) * 11,
                    support.y + math.sin(radians) * 11,
                )
            if aim is None:
                continue
            clearance, along = _combat2_point_segment_distance(
                px, py, support.x, support.y, aim[0], aim[1]
            )
            if 0.1 < along < 0.92 and clearance < 1.7:
                return support
        return None

    def hit_chance(self, attacker, target, mode=None, reaction=False):
        chance = self._combat2_hit_chance(
            attacker, target, mode=mode, reaction=reaction
        )
        if chance <= 0:
            return chance
        distance = dist(attacker, target)
        close_bonus = 8.0 if distance < 3.0 else 3.5 if distance < 5.5 else 0.0
        recoil_penalty = clamp(
            float(getattr(attacker, "polish_recoil", 0.0)), 0.0, 19.0
        )
        return clamp(chance + close_bonus - recoil_penalty, 2, 97)

    def polish_trigger_ready(self, unit, suppressive=False):
        if self.time < getattr(unit, "polish_burst_pause_until", 0.0):
            unit.next_shot = max(unit.next_shot, unit.polish_burst_pause_until)
            return False
        if getattr(unit, "polish_burst_remaining", 0) <= 0:
            profile = combat_polish_weapon_profile(unit)
            low, high = profile["burst"]
            if unit.fire_mode == "aimed":
                high = low = 1
            elif unit.fire_mode == "rapid":
                low, high = (low + 1, high + 2)
            if suppressive and unit.role in (
                "Machine Gunner",
                "HMG Crew",
                "Automatic Rifleman",
            ):
                low, high = (low + 1, high + 2)
            unit.polish_burst_remaining = self.rng.randint(int(low), int(high))
        return True

    def _combat2_apply_near_miss(self, projectile, unit, distance_to_path):
        already_suppressed = unit.uid in projectile.suppressed_uids
        result = self._base_combat2_apply_near_miss(projectile, unit, distance_to_path)
        if already_suppressed:
            return result
        if unit.polish_reaction_stance is None:
            unit.polish_reaction_stance = unit.stance
        severity = clamp(
            (0.92 - distance_to_path) / 0.92 + unit.suppression / 130.0, 0.0, 1.7
        )
        if severity >= 1.05 or unit.suppression >= 78:
            unit.polish_reaction_kind = "PINNED"
            unit.stance = "prone"
            duration = 1.15
            unit.combat2_exposed_until = min(
                unit.combat2_exposed_until, self.time + 0.12
            )
        elif severity >= 0.58:
            unit.polish_reaction_kind = "DUCK"
            if unit.stance == "standing":
                unit.stance = "crouched"
            duration = 0.72
        else:
            unit.polish_reaction_kind = "FLINCH"
            duration = 0.36
        unit.polish_reaction_until = max(
            unit.polish_reaction_until, self.time + duration
        )
        unit.command_delay_until = max(
            unit.command_delay_until, self.time + duration * 0.32
        )
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

    def combat2_terrain_collision(self, projectile, x, y):
        impact_count = len(self.impacts)
        stopped = self._combat2_terrain_collision(projectile, x, y)
        if (
            len(self.impacts) > impact_count
            and self.time - self.polish_last_impact_event_at >= 0.035
        ):
            self.polish_last_impact_event_at = self.time
            self.emit(
                "impact",
                pos=(projectile.x, projectile.y),
                faction=projectile.faction,
                material=self.impacts[-1].kind,
                weapon=projectile.weapon_name,
            )
        return stopped

    def update_defense_attack_orders(self, dt):
        if self.time < self.polish_preparation_until:
            return
        return self._operation_update_defense_attack_orders(dt)

    def update_polish_unit_state(self, unit, dt):
        recovery = 8.5 if unit.order in ("fire", "suppress") else 13.0
        if unit.stance == "prone":
            recovery *= 1.28
        unit.polish_recoil = max(0.0, unit.polish_recoil - recovery * dt)
        self._polish_clear_lane_state(unit)
        if self.time >= unit.polish_reaction_until and unit.polish_reaction_kind:
            if (
                unit.polish_reaction_stance is not None
                and unit.suppression < 38
                and (unit.order != "fire")
            ):
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
