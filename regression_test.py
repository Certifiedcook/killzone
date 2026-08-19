"""Focused regressions for maintenance fixes that are kept as plain source."""

from __future__ import annotations

import math

import kill_zone as kz


def fresh(seed=1001):
    game = kz.RealTimeGame(seed=seed, difficulty="Hard")
    game.units = []
    game.next_uid = 1
    game.explosions = []
    game.tracers = []
    game.check_end = lambda: None
    for y in range(kz.MAP_H):
        for x in range(kz.MAP_W):
            game.set_cell(x, y, "open")
            cell = game.grid[y][x]
            cell.mine = False
            cell.smoke = 0
            cell.fire = 0
            cell.ground_suppression = 0
    return game


def step(game, seconds):
    for _ in range(round(seconds / kz.SIM_DT)):
        game.update(kz.SIM_DT)


def test_repeated_combat_exit_is_fully_cleaned():
    game = fresh()
    casualty = game.add_unit("player", "Rifleman", 3, 3)
    observer = game.add_unit("enemy", "Rifleman", 7, 3)

    casualty.casualty = "incapacitated"
    casualty.hp = 0
    game.cleanup_unit_state(casualty, "first incapacitation")

    casualty.casualty = "wounded"
    casualty.hp = 30
    game.set_overwatch(casualty, 0, 90)
    casualty.target_uid = observer.uid
    casualty.reaction_target_uid = observer.uid
    observer.target_uid = casualty.uid
    observer.order = "fire"

    casualty.casualty = "incapacitated"
    casualty.hp = 0
    game.cleanup_unit_state(casualty, "second incapacitation")

    assert not casualty.overwatch
    assert casualty.target_uid is None
    assert casualty.reaction_target_uid is None
    assert observer.target_uid is None and observer.order == "idle"


def test_cached_path_revalidates_dynamic_occupancy():
    game = fresh(1002)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    destination = (7, 2)
    original = game.find_path(mover, destination, "fast")
    assert (3, 2) in original

    game.add_unit("player", "Rifleman", 3, 2)
    alternate = game.find_path(mover, destination, "fast")
    assert alternate and (3, 2) not in alternate
    assert all(game.passable(x, y, mover) for x, y in alternate)


def test_cached_path_revalidates_closed_door_immediately():
    game = fresh(1003)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    game.set_cell(3, 2, "door")
    game.toggle_door(mover, (3, 2))
    through_open_door = game.find_path(mover, (7, 2), "fast")
    assert (3, 2) in through_open_door

    game.toggle_door(mover, (3, 2))
    around_closed_door = game.find_path(mover, (7, 2), "fast")
    assert around_closed_door and (3, 2) not in around_closed_door


def test_weighted_safe_path_still_avoids_known_threat():
    game = fresh(1004)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    threat = [[0.0 for _ in range(kz.MAP_W)] for _ in range(kz.MAP_H)]
    for x in range(3, 7):
        threat[2][x] = 8.0

    def fixed_threat(faction, x, y):
        game._threat_grids[faction] = threat
        game._threat_cache_time = game.time
        return threat[y][x]

    game.tile_threat = fixed_threat
    fast = game.find_path(mover, (7, 2), "fast")
    safe = game.find_path(mover, (7, 2), "safe")
    assert all(y == 2 for _, y in fast)
    assert any(y != 2 for _, y in safe)
    assert sum(threat[y][x] for x, y in safe) < sum(threat[y][x] for x, y in fast)


def test_sector_stability_colors_match_meaning():
    assert kz.sector_stability_color(100) == "good"
    assert kz.sector_stability_color(50) == "contact"
    assert kz.sector_stability_color(10) == "danger"


def test_invalid_difficulty_has_a_clear_error():
    try:
        kz.RealTimeGame(seed=1005, difficulty="Impossible")
    except ValueError as exc:
        assert "Easy" in str(exc) and "Hard" in str(exc) and "Veteran" in str(exc)
    else:
        raise AssertionError("invalid difficulty was accepted")


def test_player_reserves_deploy_only_once():
    game = kz.RealTimeGame(
        seed=1006,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Engineer"],
        reserve_count=2,
    )
    before = len(game.units)
    first = game.deploy_player_reserves()
    after_first = len(game.units)
    second = game.deploy_player_reserves()
    assert len(first) == 2 and after_first == before + 2
    assert second == [] and len(game.units) == after_first
    assert game.stats["player"]["reserves"] == 2


def test_multiseed_simulation_invariants():
    for difficulty, seed in zip(kz.DIFFICULTY, (1011, 1012, 1013), strict=True):
        game = kz.RealTimeGame(seed=seed, difficulty=difficulty, reserve_count=2)
        players = [unit for unit in game.living("player") if unit.combat_effective]
        game.issue_move(players, (game.primary_line_x - 2, kz.MAP_H // 2), mode="safe")
        step(game, 12)
        assert math.isfinite(game.time)
        assert len({unit.uid for unit in game.units}) == len(game.units)
        for unit in game.units:
            assert all(math.isfinite(value) for value in (unit.x, unit.y, unit.hp, unit.morale, unit.suppression, unit.cohesion))
            assert 0 <= unit.x < kz.MAP_W and 0 <= unit.y < kz.MAP_H
            assert 0 <= unit.morale <= 100 and 0 <= unit.suppression <= 100
            if not unit.combat_effective:
                assert not unit.overwatch and not unit.fire_lane
                assert unit.target_uid is None and unit.reaction_target_uid is None


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
    print(f"ALL {len(TESTS)} MAINTENANCE REGRESSIONS PASSED")
