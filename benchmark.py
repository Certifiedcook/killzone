"""Deterministic simulation benchmark with machine-readable regression results."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one sample")
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def _distribution(values):
    return {
        "mean_ms": statistics.fmean(values),
        "p95_ms": percentile(values, 0.95),
        "max_ms": max(values),
    }


def run_benchmark(ticks=900, warmup=None, seed=31_415):
    """Measure active fixed steps, excluding setup and the warmup period."""
    if ticks < 60:
        raise ValueError("--ticks must be at least 60")
    if warmup is None:
        warmup = min(60, ticks // 10)
    if not 0 <= warmup < ticks:
        raise ValueError("--warmup must be nonnegative and less than --ticks")

    roster = (kz.DEFAULT_PLAYER_ROSTER + ["Rifleman"] * kz.MAX_PLAYER_UNITS)[
        : kz.MAX_PLAYER_UNITS
    ]
    game = kz.RealTimeGame(seed=seed, difficulty="Veteran", player_roster=roster)
    game.profile_enabled = True
    players = [unit for unit in game.living("player") if unit.combat_effective]
    game.issue_move(
        players,
        (game.primary_line_x - 3, kz.MAP_H // 2),
        mode="safe",
        formation="spread",
    )

    samples = []
    for tick in range(ticks):
        # Ended battles do no simulation work; including them understates cost.
        if game.victory or game.defeat:
            break
        if tick and tick % 240 == 0:
            players = [unit for unit in game.living("player") if unit.combat_effective]
            destination = (
                game.primary_line_x - 3,
                7 if (tick // 240) % 2 else kz.MAP_H - 7,
            )
            game.issue_move(players, destination, mode="safe", formation="spread")
        started = time.perf_counter()
        game.update(kz.SIM_DT)
        elapsed = (time.perf_counter() - started) * 1_000
        samples.append(
            {
                "update_ms": elapsed,
                "path_ms": game._perf["path_ms"],
                "paths": game._perf["paths"],
                "ai_ms": game._perf["ai_ms"],
                "ai_decisions": game._perf["ai_decisions"],
                "simulation_seconds": game.time,
            }
        )

    measured = samples[warmup:]
    if not measured:
        raise ValueError(
            "battle ended during warmup; choose a shorter --warmup or another --seed"
        )
    return {
        "schema_version": 1,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "seed": seed,
        "difficulty": "Veteran",
        "player_units": len(roster),
        "requested_ticks": ticks,
        "executed_ticks": len(samples),
        "warmup_ticks": warmup,
        "measured_ticks": len(measured),
        "step_seconds": kz.SIM_DT,
        "simulation_seconds": game.time,
        "battle_result": "victory"
        if game.victory
        else "defeat"
        if game.defeat
        else "ongoing",
        "update": _distribution([sample["update_ms"] for sample in measured]),
        "path": _distribution([sample["path_ms"] for sample in measured]),
        "ai": _distribution([sample["ai_ms"] for sample in measured]),
        "worst_tick": max(measured, key=lambda sample: sample["update_ms"]),
        "last_tick": samples[-1],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=900)
    parser.add_argument(
        "--warmup", type=int, help="steps to discard (default: min(60, ticks // 10))"
    )
    parser.add_argument("--seed", type=int, default=31_415)
    parser.add_argument(
        "--json",
        nargs="?",
        const="-",
        metavar="PATH",
        help="write JSON to PATH, or stdout if omitted",
    )
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(ticks=args.ticks, warmup=args.warmup, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json is not None:
        serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.json == "-":
            print(serialized, end="")
            return result
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, encoding="utf-8")

    print(
        f"BENCHMARK PASS: {result['player_units']} player units, {result['executed_ticks']} fixed ticks, "
        f"{result['measured_ticks']} measured (seed {result['seed']})"
    )
    for name in ("update", "path", "ai"):
        values = result[name]
        print(
            f"{name} mean={values['mean_ms']:.3f} ms p95={values['p95_ms']:.3f} ms max={values['max_ms']:.3f} ms"
        )
    worst = result["worst_tick"]
    print(
        f"worst tick t={worst['simulation_seconds']:.2f}s update={worst['update_ms']:.3f} ms "
        f"path={worst['path_ms']:.3f} ms/{worst['paths']} ai={worst['ai_ms']:.3f} ms/{worst['ai_decisions']}"
    )
    if result["executed_ticks"] < result["requested_ticks"]:
        print(
            f"Stopped at battle {result['battle_result']}; terminal no-op ticks excluded."
        )
    if args.json is not None:
        print(f"JSON results: {args.json}")
    return result


if __name__ == "__main__":
    main()
