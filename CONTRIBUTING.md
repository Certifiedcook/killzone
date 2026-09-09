# Contributing to Kill Zone

## Setup and validation

Use Python 3.12 or later:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python validate.py
```

Run `validate.py --stress` before a release or after simulation, AI, pathfinding,
combat, morale, casualty, terrain, or rendering changes. It runs both Assault
and Defense stress matrices. Use `--stress-seconds` and `--stress-seeds` to
configure their size.

Every bug fix should include a regression that fails without the fix. Preserve
deterministic gameplay for a fixed seed and command sequence, and do not add
hidden difficulty accuracy bonuses. Measure optimization claims with matching
benchmark settings and preserve query ordering and simulation outcomes.

## Source and engine contracts

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing module boundaries.
The engine consists of normal Python source; no gzip payload, assembled source
string, or runtime method-patching layer is required.

- Put simulation behavior in `engine/systems/` and data/state in their engine
  modules. Keep Pygame, window creation, and asset work in `engine/frontend/`.
- Import the engine module that owns a name in new code. `kill_zone.py` lazily
  preserves historical names for existing callers; retained private helpers
  are migration details, not a new extension API.
- Compose systems explicitly in `RealTimeGame`. Use normal subclasses, such as
  `NetworkGame`, for different game rules. Avoid patching methods on instances
  or classes during imports.
- Validate network commands before mutating state. Maintain server authority
  and each player's visibility boundary. Socket tests must use loopback;
  routine validation must not contact the configured public service.
- Keep terrain invalidation local to its game. Replacement cells must retain
  the world's revision tracker, and replicated terrain changes must invalidate
  affected caches without invalidating another game.
- Treat `SpatialGrid` as a snapshot: rebuild it after positions change before
  querying the new positions. Preserve stable candidate ordering.
- Keep simulation timesteps separate from render timing. Use `FixedStepClock`
  for bounded desktop catch-up; do not hide dropped time or replay failed steps.

## Validation layers

| Tests | Coverage |
| --- | --- |
| `engine_test.py` | Engine/module boundaries and world isolation |
| `engine_cli_test.py`, `scenario_test.py`, `state_test.py`, `checkpoint_test.py` | Headless tools, strict content, fingerprints and continued save/resume equivalence |
| `clock_test.py`, `spatial_test.py` | Scheduler and spatial-query contracts |
| `performance_test.py`, `benchmark_test.py` | Optimization correctness and benchmark behavior |
| `self_test.py`, `regression_test.py` | Historical model and current maintenance regressions |
| `multiplayer_test.py` | Protocol, authority, malformed input, lifecycle, snapshots, and sockets |
| `presentation_test.py` | Audio/visual behavior and replicated effects |
| `combat2_test.py`, `combat_polish_test.py` | Ballistics, wounds, identity, tactics, and combat feel |
| `ui_smoke_test.py` | Frontend wiring through a Pygame stub |
| `runtime_smoke_test.py` | Real Pygame rendering with SDL dummy drivers |
| `stress_test.py` | Seeded multi-difficulty battle invariants |

`benchmark.py` measures fixed-step and pathfinding latency separately from the
validation suite. Keep its interpreter, mission, seed, and workload consistent
for before/after comparisons.

## Distribution and generated files

`build_release.py` and `build_multiplayer_server.py` package the same engine
modules used during development. Preserve this single source of truth and the
public compatibility names exercised by tests. Validate the relevant bundle
after packaging changes.

Generated files belong under ignored `build/` and `test_output/` directories.
Do not commit release archives, screenshots, optional downloaded assets,
interpreter caches, virtual environments, or one-off work reports. Proposed
features belong in [ROADMAP.md](ROADMAP.md), clearly separated from delivered
behavior.
