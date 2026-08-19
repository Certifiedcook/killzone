# Kill Zone overnight hardening report

Date: 2026-08-19
Branch: `codex/overnight-polish`

## Outcome

The pass focused on correctness, frame pacing, deterministic validation, packaging, and maintainability rather than expanding content scope. It fixed three user-visible/state defects, replaced two simulation hot paths, added a layered release-validation stack, and produced a reproducible standalone build process.

## Defects found and fixed

### Repeated casualty cleanup

Combat-exit cleanup used a casualty-state sentinel to avoid duplicate work. The sentinel was not reset after a medic revived a soldier, so a second incapacitation in the same state could skip cleanup and leave Overwatch, fire-lane, target, reaction, path, assault, bounding, drag, or carry references behind.

Cleanup is now safely idempotent and executes for every separate exit. A focused regression covers incapacitation, revival, re-entry into combat state, and a second incapacitation, including another unit targeting the casualty.

### Cached routes through changed state

The path cache did not include dynamic occupancy. A route calculated before a friendly unit occupied its next tile could be returned unchanged after the traffic-jam logic requested a repath. Cached empty routes could also outlive a temporary blocker, and a door changed within the current tick could leave a stale route until the next update.

Routes now validate occupancy and terrain immediately, failures caused by transient blockades are not cached, and visual-terrain changes invalidate routing before the next fixed update. Regressions cover a new occupant and an immediately closed door.

### Inverted line-stability colors

The sidebar mapped stability above 65% to danger and stability below 30% to good. The mapping is now healthy/green, threatened/amber, and collapse/red. The real Pygame smoke screenshot verifies the corrected 100% green rows.

## Performance work

The original safe-route A* repeatedly called high-level threat and occupancy helpers at every edge, processed stale heap entries, and allowed three new group routes to land on one fixed tick. Full spotting also rebuilt faction lists for every target and sent obviously out-of-range pairs through LOS checks.

The replacement path uses:

- one precomputed combat-effective occupancy set per route;
- direct reads from the cached faction threat grid;
- stale-heap rejection and a closed set;
- a real-time weighted heuristic;
- exact terrain-revision cache keys and dynamic cache validation;
- one new group route per fixed tick, giving a 16-unit order roughly half-second worst-case scheduling latency without stacking three searches on one frame.

Spotting now builds faction lists once and performs a conservative distance prefilter before LOS while preserving contact intelligence and mine detection.

### Repeatable 16-unit benchmark

Command:

```text
python benchmark.py --ticks 900
```

| Measurement | Audit baseline | Final |
|---|---:|---:|
| Fixed update mean | 31.429 ms | 10.420 ms |
| Fixed update p95 | 142.154 ms | 31.934 ms |
| Worst observed update | 487.216 ms | 102.523 ms |
| Path work mean | 23.741 ms | 1.992 ms |
| Path work p95 | 132.269 ms | 13.358 ms |

The final stress matrix completed 720 simulated battle-seconds in 55.41 wall-seconds. The pre-optimization matrix took 126.17 wall-seconds for 710.7 simulated seconds on the same host and scenario structure.

## Validation completed

- 71/71 historical deterministic model tests passed.
- 8/8 focused maintenance regressions passed.
- Dependency-free Pygame-stub UI smoke test passed.
- Real Pygame SDL-dummy smoke test passed across menu/setup/settings/help, briefing/deployment/game, all zoom levels, camera extremes, threat/profiler overlays, display modes, and screenshot output.
- 12/12 deterministic stress battles passed: four seeds each on Easy, Hard, and Veteran, totaling 720 simulated seconds.
- Static compilation and Ruff fatal/bug checks passed for every reviewable Python file.
- The standalone release was generated twice to prove reproducible replacement, contained no bytecode/cache files, and passed its full quick validation from inside the materialized package.

## Repository and release improvements

- Consolidated three duplicated compressed-source assembly paths into `src/source_loader.py`.
- Kept current fixes in the reviewable `src/maintenance_extension.py` rather than creating another opaque binary payload.
- Added `validate.py` / `validate.bat`, `regression_test.py`, `runtime_smoke_test.py`, `stress_test.py`, and `benchmark.py`.
- Added `build_release.py`, including ownership-marker protection before replacing generated directories and cache-free ZIP output.
- Updated Windows launch/test scripts to prefer `.venv` and fall back cleanly between `py` and `python`.
- Added `KILLZONE_DISABLE_ASSET_DOWNLOADS` for offline and CI validation.
- Added current README instructions, changelog, and contributor guidance.

## Remaining priorities

1. Replace the historical compressed/monkey-patch architecture with conventional modules in a dedicated refactor. The shared loader and plain maintenance layer make that safer, but doing it alongside gameplay fixes would create an unnecessarily risky diff.
2. Perform a human balance/playability session through complete victories and defeats. Automated stress deliberately proves stability and invariants, not whether every seed is fun or fairly tuned.
3. Profile real GPU rendering, audio mixing, and fullscreen behavior on the target player machine. SDL-dummy validation proves call-path correctness but cannot measure drivers or presentation latency.
4. Decide whether optional CC0 audio/FX should be bundled for a fully offline release instead of downloaded on first launch.
5. Consider a signed installer or packaged executable once gameplay scope and asset distribution are settled.
