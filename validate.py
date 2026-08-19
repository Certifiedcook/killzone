"""Run Kill Zone's complete local validation suite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def run(name, *arguments):
    command = [sys.executable, str(ROOT / name), *arguments]
    print(f"\n==> {name}", flush=True)
    environment = os.environ | {
        "KILLZONE_DISABLE_ASSET_DOWNLOADS": "1",
        "PYGAME_HIDE_SUPPORT_PROMPT": "1",
    }
    subprocess.run(command, cwd=ROOT, check=True, env=environment)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stress", action="store_true", help="include deterministic multi-battle stress testing")
    parser.add_argument("--stress-seconds", type=float, default=60)
    parser.add_argument("--stress-seeds", type=int, default=4)
    args = parser.parse_args()

    run("self_test.py")
    run("regression_test.py")
    run("ui_smoke_test.py")
    try:
        __import__("pygame")
    except ImportError:
        print("\nSKIP runtime_smoke_test.py (install requirements.txt to enable real Pygame validation)")
    else:
        run("runtime_smoke_test.py")
    if args.stress:
        run("stress_test.py", "--seconds", str(args.stress_seconds), "--seeds", str(args.stress_seeds))
    print("\nALL REQUESTED VALIDATION PASSED")


if __name__ == "__main__":
    main()
