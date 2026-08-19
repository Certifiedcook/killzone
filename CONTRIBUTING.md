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

The historical game and its performance layer are stored as the deterministic
`src/legacy_game.py.gz` and `src/legacy_performance.py.gz` payloads.
`src/source_loader.py` appends the current reviewable maintenance, multiplayer,
presentation, and Combat 2.0 extensions in that order.

Keep new fixes in normal reviewable Python. If a future refactor replaces the historical payloads with a conventional package, preserve the public names used by the tests and keep `build_release.py` producing the standalone distribution.

## Validation layers

- `self_test.py`: 71 historical deterministic model regressions.
- `regression_test.py`: focused current maintenance regressions.
- `multiplayer_test.py`: protocol, authority, fog-of-war, and real socket coverage.
- `presentation_test.py`: deterministic audio/visual and replicated-effect coverage.
- `combat2_test.py`: projectiles, wounds, identities, squad tactics, and network state.
- `ui_smoke_test.py`: dependency-free frontend wiring through a Pygame stub.
- `runtime_smoke_test.py`: real Pygame rendering with SDL dummy drivers.
- `stress_test.py`: configurable multi-difficulty, multi-seed battle invariants.
- `benchmark.py`: repeatable fixed-step and pathfinding latency distribution.

Generated files belong under ignored `build/` and `test_output/` directories.
Do not commit release archives, screenshots, downloaded optional assets,
interpreter caches, virtual environments, or one-off work reports.

Every bug fix should include a regression that fails without the fix. Keep gameplay physics deterministic for a fixed seed, and do not introduce hidden difficulty accuracy bonuses.
