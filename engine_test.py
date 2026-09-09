"""Integration contracts for the headless engine and migrated systems."""

from __future__ import annotations

import ast
import math
from pathlib import Path
import subprocess
import sys

from engine import FixedStepClock, RealTimeGame
from combat_polish_test import fresh, round_toward

ROOT = Path(__file__).resolve().parent


def test_simulation_import_and_execution_need_no_frontend():
    code = """
import sys
from engine import RealTimeGame, FixedStepClock, SpatialGrid
game = RealTimeGame(seed=123)
for _ in range(60):
    game.update(1 / 30)
assert 'pygame' not in sys.modules
assert not any(name.startswith('engine.frontend') for name in sys.modules)
assert game.time > 1.9
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_runtime_is_normal_source_without_assembly_or_patching():
    for path in (ROOT / "engine").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("exec", "eval", "compile"), path
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assert not (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in ("RealTimeGame", "KillZoneApp", "Cell")
                    ), path


def test_worlds_do_not_invalidate_each_others_caches():
    first, second = fresh(1001), fresh(1001)
    first_revision = first.terrain_revision
    first._path_cache["sentinel"] = [1]
    second.grid[4][4].reset_terrain("wall")
    assert first.terrain_revision == first_revision
    assert second.terrain_revision > first_revision
    assert first._path_cache["sentinel"] == [1]
    first.grid[3][3].reset_terrain("door")
    unit = first.add_unit("player", "Engineer", 2, 3)
    before = first.terrain_revision
    other_before = second.terrain_revision
    first.toggle_door(unit, (3, 3))
    assert first.terrain_revision == before + 1
    assert second.terrain_revision == other_before


def test_fixed_steps_are_deterministic_across_render_rates():
    def simulate(frame_dt, frames):
        game = RealTimeGame(seed=2201)
        clock = FixedStepClock()
        for _ in range(frames):
            clock.advance(frame_dt, game.update)
        return game

    slow = simulate(1 / 30, 120)
    fast = simulate(1 / 144, 576)
    assert slow.time == fast.time
    assert slow.rng.getstate() == fast.rng.getstate()
    assert [vars(unit) for unit in slow.units] == [vars(unit) for unit in fast.units]


def test_inactive_worlds_and_zero_steps_do_not_mutate():
    for attribute in ("paused", "victory", "defeat", "network_replica"):
        game = RealTimeGame(seed=1003)
        setattr(game, attribute, True)
        game.units[0].polish_recoil = 10
        before = [dict(vars(unit)) for unit in game.units]
        rng = game.rng.getstate()
        game.update(1 / 30)
        assert game.time == 0
        assert game.rng.getstate() == rng
        assert [vars(unit) for unit in game.units] == before
    game = RealTimeGame(seed=1003)
    state = game.rng.getstate()
    game.update(0)
    assert game.time == 0 and game.rng.getstate() == state


def test_invalid_steps_are_rejected_before_mutation():
    game = RealTimeGame(seed=1004)
    for dt in (-0.01, math.inf, -math.inf, math.nan, None, "0.1"):
        try:
            game.update(dt)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid step {dt!r}")
        assert game.time == 0


def test_ballistic_spatial_queries_match_exhaustive_collision_scan():
    class ExhaustiveScan:
        def rebuild(self, units):
            self.units = list(units)

        def query_aabb(self, *bounds):
            return self.units

    for seed in (1401, 1402, 1403):
        indexed, exhaustive = fresh(seed), fresh(seed)
        exhaustive._ballistic_spatial = ExhaustiveScan()
        for game in (indexed, exhaustive):
            shooter = game.add_unit("player", "Machine Gunner", 2, 10)
            targets = [
                game.add_unit("enemy", "Rifleman", 5 + i % 8, 6 + i // 8 * 2)
                for i in range(32)
            ]
            game.add_unit("player", "Rifleman", 4, 10)
            for index, target in enumerate(targets):
                round_toward(game, shooter, target, y_offset=(index % 3 - 1) * 0.52)
        for _ in range(12):
            indexed.update_ballistic_rounds(1 / 30)
            exhaustive.update_ballistic_rounds(1 / 30)
            assert [vars(unit) for unit in indexed.units] == [
                vars(unit) for unit in exhaustive.units
            ]
            assert indexed.events == exhaustive.events
            assert indexed.rng.getstate() == exhaustive.rng.getstate()


if __name__ == "__main__":
    tests = [
        value for name, value in sorted(globals().items()) if name.startswith("test_")
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"ALL {len(tests)} ENGINE TESTS PASSED")
