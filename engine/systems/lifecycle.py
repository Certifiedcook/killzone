"""Systems / lifecycle for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.rules import _combat2_initialize_unit
from engine.rules import _polish_initialize_unit
from engine.rules import sanitize_operation_config
from engine.definitions import DEFENSE_ATTACK_SECTORS
from engine.definitions import DIFFICULTY
from engine.definitions import MAP_H
from engine.definitions import MAP_W
from engine.definitions import MISSION_VARIANTS
from typing import List
from typing import Optional
import time
import math


class LifecycleSystem:
    def _base_update(self, dt: float):
        if self.paused or self.victory or self.defeat:
            return
        self.time += dt
        self._world_timer -= dt
        self._spot_timer -= dt
        self._cohesion_timer -= dt
        if self._world_timer <= 0:
            self.update_weather_world(0.2)
            self._world_timer = 0.2
        if self._spot_timer <= 0:
            self.update_spotting()
            self._spot_timer = 0.16
        for u in list(self.units):
            self.update_unit(u, dt)
        self.update_reaction_fire()
        self.update_auto_behaviors()
        self.update_autofire()
        self.update_bounding_orders(dt)
        self.update_explosions(dt)
        if self._cohesion_timer <= 0:
            self.update_cohesion_and_morale(0.33)
            self._cohesion_timer = 0.33
        self.update_ai(dt)
        self.check_end()
        for t in list(self.tracers):
            t.life -= dt
            if t.life <= 0:
                self.tracers.remove(t)
        for i in list(self.impacts):
            i.life -= dt
            if i.life <= 0:
                self.impacts.remove(i)
        for b in self.blood:
            b.fresh = max(0, b.fresh - dt * 0.09)

    def _kz_rt_init(
        self,
        seed: Optional[int] = None,
        difficulty: str = "Hard",
        player_roster: Optional[List[str]] = None,
        reserve_count: int = 0,
    ):
        self.reserve_count = max(0, int(reserve_count))
        self._uid_index = {}
        self._occupancy = {}
        self._living_cache = {"player": [], "enemy": []}
        self._threat_grids = {}
        self._threat_cache_time = -999.0
        self._path_budget = 3
        self._path_cache = {}
        self._terrain_revision = 0
        self._ai_cursor = 0
        self._perf = {
            "sim_ms": 0.0,
            "path_ms": 0.0,
            "ai_ms": 0.0,
            "paths": 0,
            "ai_decisions": 0,
        }
        self.battle_events = []
        self.assault_orders = []
        self.dust = []
        self.stats = {
            f: {
                "shots": 0,
                "hits": 0,
                "kills": 0,
                "grenades": 0,
                "smoke": 0,
                "casualties": 0,
                "surrendered": 0,
                "reserves": 0,
            }
            for f in ("player", "enemy")
        }
        self.player_reserves = []
        self.primary_line_x = MAP_W - 13
        self.secondary_line_x = MAP_W - 6
        self.deployment_zone_x = 10
        self._mortar_solutions = {}
        self._base_init(seed=seed, difficulty=difficulty, player_roster=player_roster)
        self._kz_rebuild_indexes()
        self.enemy_estimate = (
            max(1, DIFFICULTY[self.difficulty]["enemy"] - 2),
            DIFFICULTY[self.difficulty]["enemy"] + 2,
        )

    def _kz_update(self, dt):
        if self.paused or self.victory or self.defeat:
            return
        t0 = time.perf_counter()
        self._path_budget = 3
        self._perf["path_ms"] = 0.0
        self._perf["paths"] = 0
        self._perf["ai_ms"] = 0.0
        self._perf["ai_decisions"] = 0
        self._kz_rebuild_indexes()
        self._base_update(dt)
        self.update_assault_orders(dt)
        for puff in list(self.dust):
            puff.life -= dt
            if puff.life <= 0:
                self.dust.remove(puff)
        self._kz_rebuild_indexes()
        self._perf["sim_ms"] = (time.perf_counter() - t0) * 1000

    def _vs_rt_init(self, *args, **kwargs):
        self._kz_rt_init(*args, **kwargs)
        self.notifications = []
        self._contact_last_report = {}
        self._mission_timer = 0.0
        self._stability_timer = 0.0
        self._counterattack_launched = False
        self._reserves_activated = False
        self._mission_complete_recorded = False
        self.combat_intensity = 0.0
        self.battle_stage = "APPROACH"
        self._last_stage = "APPROACH"
        self.initial_enemy_total = max(
            1, len([u for u in self.units if u.faction == "enemy"])
        )
        self.initial_role_counts = {
            r: max(
                1,
                len(
                    [
                        u
                        for u in self.units
                        if u.faction == "enemy"
                        and getattr(u, "initial_battle_role", "") == r
                    ]
                ),
            )
            for r in ("forward", "reserve", "command")
        }
        self.initial_sector_counts = {
            sec: max(
                1,
                len(
                    [
                        u
                        for u in self.units
                        if u.faction == "enemy"
                        and getattr(u, "battle_sector", "") == sec
                        and (getattr(u, "initial_battle_role", "") == "forward")
                    ]
                ),
            )
            for sec in ("NORTH", "CENTRE", "SOUTH")
        }
        self.sector_stability = {sec: 100.0 for sec in ("NORTH", "CENTRE", "SOUTH")}
        self.collapsed_sectors = set()
        p = self.primary_line_x
        s = self.secondary_line_x
        strong = self.map_features["strongpoint"]
        cmd = self.map_features["command_post"]
        self.objectives = [
            {
                "title": "BREAK THE FORWARD LINE",
                "desc": "Get a fighting element through Line 1 and force the defenders off the parapet.",
                "pos": (p, MAP_H // 2),
                "progress": 0.0,
                "state": "active",
            },
            {
                "title": "SECURE THE STRONGPOINT",
                "desc": "Clear and occupy the central bunker controlling the communication trenches.",
                "pos": strong,
                "progress": 0.0,
                "state": "locked",
            },
            {
                "title": "BREAK THE RESERVE LINE",
                "desc": "Push through Line 2 before the reserve can stabilise the defence.",
                "pos": (s, MAP_H // 2),
                "progress": 0.0,
                "state": "locked",
            },
            {
                "title": "CAPTURE THE COMMAND POST",
                "desc": "Seize the rear command bunker or collapse the remaining defensive force.",
                "pos": cmd,
                "progress": 0.0,
                "state": "locked",
            },
        ]
        self.objective_index = 0
        self.mission_title = (
            f"ASSAULT — {MISSION_VARIANTS[self.battle_variant]['name']}"
        )
        self.mission_brief = MISSION_VARIANTS[self.battle_variant]["brief"]
        self.notify(
            "MISSION — Break the defensive line", kind="objective", duration=5.0
        )
        self._vs_event("mission", self.mission_title, (p, MAP_H // 2))

    def _vs_update2(self, dt):
        self._kz_update(dt)
        if not self.paused and (not (self.victory or self.defeat)):
            self.update_mission_state(dt)

    def _perf_rt_init(self, *args, **kwargs):
        self._los_cache = {}
        self._line_cache = {}
        self._last_visual_terrain_rev = -1
        self.profile_enabled = False
        self._intensity_timer = 0.0
        self._sector_low_since = {s: None for s in ("NORTH", "CENTRE", "SOUTH")}
        self._vs_rt_init(*args, **kwargs)
        self._perf.update(
            {
                "los_ms": 0.0,
                "los_calls": 0,
                "los_hits": 0,
                "line_calls": 0,
                "line_hits": 0,
            }
        )
        self._last_visual_terrain_rev = self.terrain_revision

    def _perf_mission_update(self, dt):
        self._mission_timer += dt
        self._stability_timer += dt
        self._intensity_timer += dt
        if self._intensity_timer >= 0.25:
            self.update_battle_stage(self._intensity_timer)
            self._intensity_timer = 0
        else:
            self.combat_intensity = max(0, self.combat_intensity - dt * 1.8)
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

    def _perf_update3(self, dt):
        prof = getattr(self, "profile_enabled", False)
        if prof:
            for k in ("los_ms", "los_calls", "los_hits", "line_calls", "line_hits"):
                self._perf[k] = 0 if k != "los_ms" else 0.0
        if self._last_visual_terrain_rev != self.terrain_revision:
            self._last_visual_terrain_rev = self.terrain_revision
            self._terrain_revision += 1
            self._path_cache.clear()
            self._los_cache.clear()
            self._line_cache.clear()
        t0 = time.perf_counter()
        self._vs_update2(dt)
        self._perf["sim_ms"] = (time.perf_counter() - t0) * 1000

    def _maintenance_init(
        self,
        seed: Optional[int] = None,
        difficulty: str = "Hard",
        player_roster: Optional[List[str]] = None,
        reserve_count: int = 0,
    ):
        if difficulty not in DIFFICULTY:
            choices = ", ".join(DIFFICULTY)
            raise ValueError(
                f"Unknown difficulty {difficulty!r}; choose one of: {choices}"
            )
        self._perf_rt_init(
            seed=seed,
            difficulty=difficulty,
            player_roster=player_roster,
            reserve_count=reserve_count,
        )
        self._maintenance_visual_revision = self.terrain_revision

    def _maintenance_update(self, dt):
        self._maintenance_paths_started = 0
        return self._perf_update3(dt)

    def _operation_init(
        self,
        seed: Optional[int] = None,
        difficulty: str = "Hard",
        player_roster: Optional[List[str]] = None,
        reserve_count: int = 0,
        operation_config=None,
    ):
        config = sanitize_operation_config(operation_config)
        self.operation_config = config
        self.mission_type = config["mission"]
        self.operation_variant = config["variant"]
        self.operation_weather = config["weather"]
        self.operation_enemy_strength = config["enemy_strength"]
        self.defense_time_limit = float(config["defense_duration"])
        self.deployment_zone_side = "west"
        self.squad_doctrine = {}
        self._engineer_builder_timer = 0.0
        self._last_engineer_builder_update = 0.0
        self.construction_reservations = {}
        self._defense_attack_order_timer = 0.0
        self._defense_next_plan_time = 0.0
        self.defense_attack_plan = {}
        self.defense_sector_pressure = {
            sector: 0.0 for sector in DEFENSE_ATTACK_SECTORS
        }
        self.defense_main_effort = "CENTRE"
        self.defense_plan_revision = 0
        self._maintenance_init(
            seed=seed,
            difficulty=difficulty,
            player_roster=player_roster,
            reserve_count=reserve_count,
        )
        if self.operation_weather != "auto":
            self.weather = self.operation_weather
            for index in range(len(self.log) - 1, -1, -1):
                if self.log[index].startswith("Realtime battle started."):
                    self.log[index] = (
                        f"Realtime battle started. Seed {self.seed}. Weather: {self.weather}."
                    )
                    break
        self._operation_scale_enemy_force()
        if self.mission_type == "defense":
            self._operation_configure_defense()
        self._operation_refresh_force_counts()
        for unit in self.units:
            squad = max(1, int(getattr(unit, "squad_id", 1)))
            key = (unit.faction, squad)
            if unit.faction == "enemy":
                role = getattr(unit, "initial_battle_role", "")
                default = (
                    "aggressive"
                    if role.startswith("wave")
                    else "cautious"
                    if role in ("command", "reserve")
                    else "balanced"
                )
            else:
                default = "balanced"
            self.squad_doctrine.setdefault(key, default)

    def _operation_update(self, dt):
        self._maintenance_update(dt)
        if self.paused or self.victory or self.defeat:
            return
        self.update_engineer_assignments()
        self.update_emplacements()
        self.update_enemy_builders()
        self.update_defense_attack_orders(dt)

    def _network_game_update(self, dt):
        if getattr(self, "network_replica", False):
            return
        return self._operation_update(dt)

    def _combat2_init(self, *args, **kwargs):
        self._operation_init(*args, **kwargs)
        self.ballistic_rounds = []
        self.next_ballistic_round_id = 1
        self.combat2_tactical_plans = {}
        self.combat2_next_plan_at = 0.0
        self.combat2_last_projectile_count = 0
        for unit in self.units:
            _combat2_initialize_unit(self, unit)

    def _combat2_update(self, dt):
        if getattr(self, "network_replica", False):
            return self._network_game_update(dt)
        active = not self.paused and (not (self.victory or self.defeat))
        if active:
            self.plan_combat2_squads()
        result = self._network_game_update(dt)
        if active:
            self.update_ballistic_rounds(dt)
        return result

    def __init__(self, *args, **kwargs):
        self._combat2_init(*args, **kwargs)
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

    def update(self, dt):
        """Advance one simulation step in an explicit, deterministic phase order.

        The desktop clock and dedicated server own scheduling. Presentation
        consumes events after this method; it never changes the tick order.
        """
        if not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        if (
            dt == 0
            or self.paused
            or self.victory
            or self.defeat
            or getattr(self, "network_replica", False)
        ):
            return
        started = time.perf_counter()
        self.plan_combat2_squads()
        self._maintenance_paths_started = 0
        self._path_budget = 3
        for name in (
            "paths",
            "ai_decisions",
            "los_calls",
            "los_hits",
            "line_calls",
            "line_hits",
        ):
            self._perf[name] = 0
        for name in ("path_ms", "ai_ms", "los_ms"):
            self._perf[name] = 0.0
        if self._last_visual_terrain_rev != self.terrain_revision:
            self._last_visual_terrain_rev = self.terrain_revision
            self._terrain_revision += 1
            self._path_cache.clear()
            self._los_cache.clear()
            self._line_cache.clear()
        self._kz_rebuild_indexes()
        self._base_update(dt)
        self.update_assault_orders(dt)
        for puff in self.dust:
            puff.life -= dt
        self.dust[:] = [puff for puff in self.dust if puff.life > 0]
        self._kz_rebuild_indexes()
        if not (self.victory or self.defeat):
            self.update_mission_state(dt)
        if not (self.victory or self.defeat):
            self.update_engineer_assignments()
            self.update_emplacements()
            self.update_enemy_builders()
            self.update_defense_attack_orders(dt)
        self.update_ballistic_rounds(dt)
        for unit in self.units:
            if unit.alive:
                self.update_polish_unit_state(unit, dt)
        self.update_polish_engagement_state(dt)
        self._perf["sim_ms"] = (time.perf_counter() - started) * 1000
