"""Command-line entry points for reproducible headless engine runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from engine.definitions import DIFFICULTY, OPERATION_MISSIONS, SIM_DT
from engine.scenarios import Scenario
from engine.content import load_json, write_json


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def simulate(
    *, ticks=900, seed=42, difficulty="Hard", mission="assault", scenario=None
):
    """Run a seeded operation without graphics, networking, or asset downloads."""
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
        raise ValueError("ticks must be a positive integer")
    if mission not in OPERATION_MISSIONS:
        raise ValueError(f"unknown mission {mission!r}")
    game = (
        scenario or Scenario(seed=seed, difficulty=difficulty, mission=mission)
    ).create_game()
    started = time.perf_counter()
    completed = 0
    for _ in range(ticks):
        if game.victory or game.defeat:
            break
        game.update(SIM_DT)
        completed += 1
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "seed": game.seed,
        "difficulty": game.difficulty,
        "mission": game.mission_type,
        "ticks_requested": ticks,
        "ticks_completed": completed,
        "step_seconds": SIM_DT,
        "simulated_seconds": game.time,
        "wall_seconds": elapsed,
        "mean_update_ms": elapsed * 1000 / completed if completed else 0.0,
        "result": "victory" if game.victory else "defeat" if game.defeat else "ongoing",
        "forces": {
            faction: {
                "living": len(game.living(faction)),
                "effective": sum(
                    unit.combat_effective for unit in game.living(faction)
                ),
                "hp": sum(unit.hp for unit in game.living(faction)),
            }
            for faction in ("player", "enemy")
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m engine",
        description="Kill Zone desktop and headless engine tools",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("play", help="launch the desktop game")
    run = commands.add_parser("simulate", help="run a seeded operation without Pygame")
    run.add_argument("--ticks", type=positive_int, default=900)
    run.add_argument("--seed", type=int)
    run.add_argument("--difficulty", choices=tuple(DIFFICULTY))
    run.add_argument("--mission", choices=OPERATION_MISSIONS)
    run.add_argument(
        "--scenario", type=Path, help="load a validated scenario JSON file"
    )
    run.add_argument(
        "--output", type=Path, help="also save the JSON summary to this file"
    )
    scenario = commands.add_parser(
        "scenario", help="validate or export initial scenario settings"
    )
    scenario.add_argument(
        "--input", type=Path, help="scenario to validate; defaults to built-in settings"
    )
    scenario.add_argument("--output", type=Path, help="write the normalized scenario")
    scenario.add_argument("--seed", type=int)
    scenario.add_argument("--difficulty", choices=tuple(DIFFICULTY))
    scenario.add_argument("--mission", choices=OPERATION_MISSIONS)
    return parser


def _scenario_from_args(args):
    source = getattr(args, "scenario", None) or getattr(args, "input", None)
    payload = (
        Scenario.from_dict(load_json(source)).to_dict()
        if source
        else Scenario().to_dict()
    )
    for name in ("seed", "difficulty"):
        if getattr(args, name) is not None:
            payload[name] = getattr(args, name)
    if args.mission is not None:
        payload["operation"]["mission"] = args.mission
    return Scenario.from_dict(payload)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "play"):
        from engine.frontend.support import main as play

        play()
        return 0
    try:
        scenario = _scenario_from_args(args)
        report = (
            scenario.to_dict()
            if args.command == "scenario"
            else simulate(ticks=args.ticks, scenario=scenario)
        )
        payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            write_json(args.output, report)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(payload, end="")
    return 0
