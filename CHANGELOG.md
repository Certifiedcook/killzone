# Changelog

## Unreleased — release hardening

### Fixed

- Repeated incapacitation after a medic revival now performs combat-exit cleanup every time.
- Cached paths no longer continue through newly occupied tiles or doors closed during the same simulation tick.
- Empty paths caused by temporary blockers are no longer cached indefinitely.
- Defensive line stability colors now match their meaning: healthy is green and collapse is red.
- Invalid programmatic difficulty values now raise a clear `ValueError` listing supported choices.

### Performance

- Replaced the route hot path with a weighted A* implementation using one precomputed occupancy set and direct cached threat-grid reads.
- Discarded stale heap entries and stopped repeatedly calling high-level lookup helpers for every A* edge.
- Spread group-order path calculations to one new route per fixed tick to prevent three expensive searches landing on one frame.
- Reworked spotting to reuse faction lists and prefilter impossible observer/target pairs before LOS evaluation.

### Testing and tooling

- Added 8 focused maintenance regressions.
- Added real headless Pygame menu, battle, zoom, camera, profiler, and display-mode rendering coverage.
- Added configurable deterministic stress testing across all difficulties.
- Added a repeatable 16-unit fixed-step benchmark.
- Added a single-command validation runner and robust Windows launcher/runtime discovery.
- Added a standalone source/release materializer with optional ZIP output.
- Consolidated duplicated source reconstruction into `src/source_loader.py`.
- Added an offline/CI switch for optional presentation-asset downloads.
