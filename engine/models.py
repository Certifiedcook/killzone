"""Models for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from engine.revisions import TerrainRevision
from engine.definitions import Coord
from engine.definitions import TERRAIN
from engine.definitions import WEAPONS
from typing import List
from typing import Optional
from typing import Tuple


@dataclass
class Cell:
    terrain: str = "open"
    axis: Optional[str] = None
    hp: Optional[float] = None
    smoke: float = 0.0
    fire: float = 0.0
    mine: bool = False
    mine_seen_player: bool = False
    mine_seen_enemy: bool = False
    fort_progress: float = 0.0
    door_open: bool = False
    cover_wear: float = 0.0
    ground_suppression: float = 0.0
    _revision_state: Optional[TerrainRevision] = field(
        default=None, repr=False, compare=False
    )

    def _base_reset_terrain(self, terrain: str, axis: Optional[str] = None):
        self.terrain = terrain
        self.axis = axis
        hp = TERRAIN[terrain]["hp"]
        self.hp = float(hp) if hp is not None else None
        self.cover_wear = 0.0

    def reset_terrain(self, terrain, axis=None):
        before = (self.terrain, self.axis, self.door_open)
        self._base_reset_terrain(terrain, axis)
        if (
            before != (self.terrain, self.axis, self.door_open)
            and self._revision_state is not None
        ):
            self._revision_state.value += 1


@dataclass
class Explosion:
    x: float
    y: float
    timer: float
    radius: float
    damage: float
    suppression: float
    kind: str = "HE"
    faction: str = "neutral"


@dataclass
class Tracer:
    a: Tuple[float, float]
    b: Tuple[float, float]
    life: float = 0.2
    total: float = 0.2


@dataclass
class Impact:
    x: float
    y: float
    kind: str = "dirt"
    life: float = 0.22


@dataclass
class BloodDecal:
    x: float
    y: float
    size: float
    seed: int
    fresh: float = 1.0


@dataclass
class BoundingOrder:
    a: List[int]
    b: List[int]
    dest: Coord
    phase: int = 0
    timer: float = 0.0


@dataclass
class Unit:
    uid: int
    faction: str
    role: str
    x: float
    y: float
    hp: float
    max_hp: float
    morale: float = 100.0
    suppression: float = 0.0
    cohesion: float = 100.0
    stance: str = "standing"
    facing: float = 0.0
    casualty: str = "healthy"
    bleed: float = 0.0
    weapon_name: str = "Service Rifle"
    ammo: int = 0
    magazines: List[int] = field(default_factory=list)
    grenades: int = 0
    smoke_grenades: int = 0
    rifle_grenades: int = 0
    satchel: int = 0
    med_supplies: int = 0
    tools: int = 0
    mortar_shells: int = 0
    crew: int = 1
    assistant_alive: bool = False
    barrel_spares: int = 1
    heat: float = 0.0
    jammed: bool = False
    deployed: bool = False
    bayonet: bool = False
    aim_progress: float = 0.0
    order: str = "idle"
    fire_mode: str = "normal"
    target_uid: Optional[int] = None
    target_pos: Optional[Tuple[float, float]] = None
    path: List[Coord] = field(default_factory=list)
    waypoints: List[Coord] = field(default_factory=list)
    move_mode: str = "safe"
    action_timer: float = 0.0
    reload_timer: float = 0.0
    next_shot: float = 0.0
    signature: float = 0.0
    overwatch: bool = False
    arc_width: float = 90.0
    arc_range: float = 10.0
    fire_lane: bool = False
    fire_lane_center: float = 0.0
    dragging_uid: Optional[int] = None
    carrying_uid: Optional[int] = None
    reload_emergency: bool = False
    covering_uid: Optional[int] = None
    route_preview: List[Coord] = field(default_factory=list)
    selected: bool = False
    last_ai: float = 0.0
    spotted_player_until: float = 0.0
    spotted_enemy_until: float = 0.0
    peek_until: float = 0.0
    rally_shock: float = 0.0
    momentum: float = 0.0
    fire_discipline: str = "free"
    target_priority: str = "specialist"
    command_queue: List[Tuple[str, object]] = field(default_factory=list)
    under_fire_until: float = 0.0
    last_attacker_uid: Optional[int] = None
    stamina: float = 100.0
    disoriented_until: float = 0.0
    traverse_ready_at: float = 0.0
    reaction_ready_at: float = 0.0
    reaction_target_uid: Optional[int] = None
    command_delay_until: float = 0.0
    stationary_time: float = 0.0
    prepared: float = 0.0
    incoming_bearings: List[Tuple[float, float]] = field(default_factory=list)
    auto_reload: bool = True
    auto_cover: bool = True
    auto_smoke: bool = True
    auto_medic: bool = True
    fallback_point: Optional[Coord] = None

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def tile(self) -> Coord:
        return (int(round(self.x)), int(round(self.y)))

    @property
    def weapon(self) -> dict:
        return WEAPONS[self.weapon_name]

    @property
    def alive(self) -> bool:
        return self.casualty not in ("dead", "surrendered")

    @property
    def combat_effective(self) -> bool:
        return self.casualty in ("healthy", "wounded") and self.hp > 0


@dataclass
class AssaultOrder:
    support: List[int]
    assault: List[int]
    dest: Coord
    target_uid: Optional[int] = None
    phase: int = 0
    timer: float = 0.0


@dataclass
class DustPuff:
    x: float
    y: float
    size: float
    life: float
    total: float


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
