"""Small deterministic simulation benchmark for regression tracking."""

from __future__ import annotations

import argparse
import statistics
import time

import kill_zone as kz


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=900)
    args = parser.parse_args()
    if args.ticks < 60:
        parser.error("--ticks must be at least 60")

    roster = (kz.DEFAULT_PLAYER_ROSTER + ["Rifleman"] * kz.MAX_PLAYER_UNITS)[: kz.MAX_PLAYER_UNITS]
    game = kz.RealTimeGame(seed=31_415, difficulty="Veteran", player_roster=roster)
    game.profile_enabled = True
    players = [unit for unit in game.living("player") if unit.combat_effective]
    game.issue_move(players, (game.primary_line_x - 3, kz.MAP_H // 2), mode="safe", formation="spread")

    samples = []
    for tick in range(args.ticks):
        if tick and tick % 240 == 0:
            destination = (game.primary_line_x - 3, 7 if (tick // 240) % 2 else kz.MAP_H - 7)
            game.issue_move(players, destination, mode="safe", formation="spread")
        started = time.perf_counter()
        game.update(kz.SIM_DT)
        elapsed = (time.perf_counter() - started) * 1_000
        samples.append(
            (
                elapsed,
                game._perf["path_ms"],
                game._perf["paths"],
                game._perf["ai_ms"],
                game._perf["ai_decisions"],
                game.time,
            )
        )

    warm = samples[60:]
    timings = [sample[0] for sample in warm]
    path_timings = [sample[1] for sample in warm]
    worst = max(warm, key=lambda sample: sample[0])
    print(f"BENCHMARK PASS: {len(players)} player units, {args.ticks} fixed ticks")
    print(f"update mean={statistics.fmean(timings):.3f} ms p95={percentile(timings, .95):.3f} ms max={max(timings):.3f} ms")
    print(f"path mean={statistics.fmean(path_timings):.3f} ms p95={percentile(path_timings, .95):.3f} ms")
    print(
        f"worst tick t={worst[5]:.2f}s update={worst[0]:.3f} ms path={worst[1]:.3f} ms/"
        f"{worst[2]} ai={worst[3]:.3f} ms/{worst[4]}"
    )
    print(
        f"last tick sim={game._perf['sim_ms']:.3f} ms path={game._perf['path_ms']:.3f} ms/"
        f"{game._perf['paths']} ai={game._perf['ai_ms']:.3f} ms/{game._perf['ai_decisions']}"
    )


if __name__ == "__main__":
    main()
