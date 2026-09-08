"""Correctness regressions for simulation hot paths and visibility caches."""

from __future__ import annotations

import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

from engine.definitions import MAP_H, MAP_W
from engine.rules import angle_to, dist
from engine.simulation import RealTimeGame
from engine.systems.tactics import TacticsSystem


def clear_battle():
    game = RealTimeGame(seed=1001, difficulty="Hard")
    game.units = []
    game.next_uid = 1
    for y in range(MAP_H):
        for x in range(MAP_W):
            game.set_cell(x, y, "open")
            game.grid[y][x].smoke = 0
    observer = game.add_unit("player", "Rifleman", 3, 3)
    target = game.add_unit("enemy", "Rifleman", 5, 3)
    return game, observer, target


class VisibilityCacheTests(unittest.TestCase):
    def test_cached_visible_target_becomes_dead_or_surrendered(self):
        for casualty in ("dead", "surrendered"):
            with self.subTest(casualty=casualty):
                game, observer, target = clear_battle()
                self.assertTrue(game.can_see(observer, target))
                target.casualty = casualty
                self.assertFalse(game.can_see(observer, target))

    def test_cached_observer_loses_combat_effectiveness(self):
        game, observer, target = clear_battle()
        self.assertTrue(game.can_see(observer, target))
        observer.casualty = "incapacitated"
        self.assertFalse(game.can_see(observer, target))
        observer.casualty = "healthy"
        self.assertTrue(game.can_see(observer, target))
        observer.hp = 0
        self.assertFalse(game.can_see(observer, target))

    def test_door_changes_invalidate_los_and_line_without_advancing_time(self):
        game, observer, target = clear_battle()
        game.set_cell(4, 3, "door")
        for opened in (False, True, False):
            with self.subTest(opened=opened):
                self.assertEqual(game.grid[3][4].door_open, opened)
                self.assertEqual(game.can_see(observer, target), opened)
                self.assertEqual(game.line_info(observer.pos, target.pos)[0], opened)
                game.toggle_door(observer, (4, 3))
        self.assertEqual(game.time, 0)


class GeometryTests(unittest.TestCase):
    def test_geometry_reads_dynamic_position_once_per_operand(self):
        class Position:
            def __init__(self, pos):
                self.value = pos
                self.reads = 0

            @property
            def pos(self):
                self.reads += 1
                return self.value

        for operation, expected in (
            (dist, 5),
            (angle_to, math.degrees(math.atan2(4, 3))),
        ):
            with self.subTest(operation=operation.__name__):
                a, b = Position((0, 0)), Position((3, 4))
                self.assertAlmostEqual(operation(a, b), expected)
                self.assertEqual((a.reads, b.reads), (1, 1))
                self.assertAlmostEqual(operation((0, 0), (3, 4)), expected)


class AutomaticTargetTests(unittest.TestCase):
    def test_range_rejection_skips_los_and_boundary_remains_inclusive(self):
        shooter = SimpleNamespace(
            pos=(0, 0), faction="player", target_priority="nearest", weapon={"range": 5}
        )
        far = SimpleNamespace(pos=(6, 0), combat_effective=True)
        boundary = SimpleNamespace(pos=(3, 4), combat_effective=True)
        queried = []

        def can_see(observer, target):
            queried.append(target)
            return True

        game = SimpleNamespace(
            living=lambda faction: [far, boundary],
            visible_to=lambda faction, unit: True,
            can_see=can_see,
        )
        self.assertIs(TacticsSystem.choose_auto_target(game, shooter), boundary)
        self.assertEqual(queried, [boundary])

    def test_target_priority_and_ties_match_previous_selection(self):
        shooter = SimpleNamespace(pos=(0, 0), faction="player", weapon={"range": 10})
        # Equal-distance candidates deliberately retain roster order.
        enemies = [
            SimpleNamespace(
                pos=(3, 4),
                combat_effective=True,
                role="Rifleman",
                suppression=10,
                cover=2,
            ),
            SimpleNamespace(
                pos=(-3, 4),
                combat_effective=True,
                role="Rifleman",
                suppression=10,
                cover=2,
            ),
            SimpleNamespace(
                pos=(6, 0), combat_effective=True, role="Medic", suppression=40, cover=1
            ),
        ]
        game = SimpleNamespace(
            living=lambda faction: enemies,
            visible_to=lambda faction, unit: True,
            can_see=lambda observer, target: True,
            effective_cover=lambda observer, target: target.cover,
        )
        for priority, expected in (
            ("nearest", enemies[0]),
            ("exposed", enemies[2]),
            ("suppressed", enemies[2]),
            ("threat", enemies[2]),
        ):
            with self.subTest(priority=priority):
                shooter.target_priority = priority
                self.assertIs(TacticsSystem.choose_auto_target(game, shooter), expected)


if __name__ == "__main__":
    unittest.main()
