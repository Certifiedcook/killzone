"""Deterministic multi-battle stress and invariant test for release validation."""

from __future__ import annotations

import argparse
import math
import time

import kill_zone as kz


def assert_invariants(game):
    assert math.isfinite(game.time) and game.time >= 0
    assert len({unit.uid for unit in game.units}) == len(game.units)
    assert len(game.tracers) <= 90
    assert len(game.impacts) <= 140
    assert len(game.blood) <= 180
    assert len(game.dust) <= 90
    assert len(game.notifications) <= 8
    assert len(game._los_cache) <= 701
    assert len(game._line_cache) <= 901
    assert len(game._path_cache) <= 513

    for unit in game.units:
        values = (
            unit.x,
            unit.y,
            unit.hp,
            unit.morale,
            unit.suppression,
            unit.cohesion,
            unit.stamina,
            unit.heat,
        )
        assert all(math.isfinite(value) for value in values), (unit.uid, values)
        assert -0.5 <= unit.x < kz.MAP_W + 0.5
        assert -0.5 <= unit.y < kz.MAP_H + 0.5
        assert 0 <= unit.morale <= 100
        assert 0 <= unit.suppression <= 100
        assert 0 <= unit.cohesion <= 100
        assert 0 <= unit.stamina <= 100
        for x, y in unit.path + unit.waypoints:
            assert game.in_bounds(x, y), (unit.uid, x, y)
        if not unit.combat_effective:
            assert not unit.overwatch and not unit.fire_lane
            assert unit.target_uid is None and unit.reaction_target_uid is None


def run_battle(difficulty, seed, seconds):
    game = kz.RealTimeGame(seed=seed, difficulty=difficulty, reserve_count=3)
    ticks = round(seconds / kz.SIM_DT)
    next_order = 0
    started = time.perf_counter()

    for tick in range(ticks):
        if tick >= next_order and not (game.victory or game.defeat):
            players = [unit for unit in game.living("player") if unit.combat_effective]
            objective = game.current_objective
            if players and objective:
                destination = objective["pos"]
                game.issue_move(players, destination, mode="safe", formation="spread")
                assault_group = players[: min(6, len(players))]
                if len(assault_group) >= 2:
                    game.assault_position(assault_group, destination)
            if game.player_reserves and game.time >= seconds * 0.2:
                game.deploy_player_reserves()
            next_order = tick + round(8 / kz.SIM_DT)

        game.update(kz.SIM_DT)
        if tick % 30 == 0:
            assert_invariants(game)

    assert_invariants(game)
    elapsed = time.perf_counter() - started
    return {
        "difficulty": difficulty,
        "seed": seed,
        "simulated": round(game.time, 1),
        "wall": round(elapsed, 2),
        "player_effective": len([unit for unit in game.living("player") if unit.combat_effective]),
        "enemy_effective": len([unit for unit in game.living("enemy") if unit.combat_effective]),
        "result": "victory" if game.victory else "defeat" if game.defeat else "ongoing",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--seeds", type=int, default=4, help="seeds per difficulty")
    args = parser.parse_args()
    if args.seconds <= 0 or args.seeds <= 0:
        parser.error("--seconds and --seeds must be positive")

    results = []
    for difficulty_index, difficulty in enumerate(kz.DIFFICULTY):
        for offset in range(args.seeds):
            seed = 20_000 + difficulty_index * 1_000 + offset * 137
            result = run_battle(difficulty, seed, args.seconds)
            results.append(result)
            print(
                f"PASS {difficulty:7s} seed={seed} sim={result['simulated']:5.1f}s "
                f"wall={result['wall']:5.2f}s P={result['player_effective']:2d} "
                f"E={result['enemy_effective']:2d} {result['result']}"
            )

    total_wall = sum(result["wall"] for result in results)
    print(f"STRESS PASS: {len(results)} battles, {sum(r['simulated'] for r in results):.1f}s simulated, {total_wall:.2f}s wall time")


if __name__ == "__main__":
    main()
