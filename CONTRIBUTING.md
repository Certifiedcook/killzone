# Contributing to Kill Zone

## Development setup

Create a virtual environment, install the pinned dependency, and run validation:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python validate.py
```

Use `validate.py --stress` before a release or after simulation, AI, pathfinding, morale, casualty, terrain, or rendering changes.

## Source model

The historical game is stored in compressed fragments under `src/kill_zone_parts_v5`, followed by the historical performance extension. `src/source_loader.py` assembles those payloads and then appends `src/maintenance_extension.py`.

Keep new fixes in normal reviewable Python. If a future refactor replaces the historical payloads with a conventional package, preserve the public names used by the tests and keep `build_release.py` producing the standalone distribution.

## Validation layers

- `self_test.py`: 71 historical deterministic model regressions.
- `regression_test.py`: focused current maintenance regressions.
- `ui_smoke_test.py`: dependency-free frontend wiring through a Pygame stub.
- `runtime_smoke_test.py`: real Pygame rendering with SDL dummy drivers.
- `stress_test.py`: configurable multi-difficulty, multi-seed battle invariants.
- `benchmark.py`: repeatable fixed-step and pathfinding latency distribution.

Every bug fix should include a regression that fails without the fix. Keep gameplay physics deterministic for a fixed seed, and do not introduce hidden difficulty accuracy bonuses.
