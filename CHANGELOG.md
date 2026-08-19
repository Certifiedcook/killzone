# Changelog

## Unreleased — release hardening

### Fixed

- Repeated incapacitation after a medic revival now performs combat-exit cleanup every time.
- Cached paths no longer continue through newly occupied tiles or doors closed during the same simulation tick.
- Empty paths caused by temporary blockers are no longer cached indefinitely.
- Defensive line stability colors now match their meaning: healthy is green and collapse is red.
- Invalid programmatic difficulty values now raise a clear `ValueError` listing supported choices.
- The `OVERWATCH` button now waits for a right-clicked facing point instead of deriving its arc from the bottom-bar button position.
- Fullscreen mouse input now uses SDL's window-coordinate extent and is normalized exactly once before every UI or map handler.

### Squads

- Initial forces now auto-allocate assault, fire-support, recon, and support roles into tactically coherent four-person squads.
- Arriving reserves reinforce a matching tactical squad when space is available, with capacity-aware fallbacks for unusual rosters.
- Number keys `1–9` now select Squads A–I during deployment and battle; shifted numbers recall saved control groups.
- Squad tabs, unit cards, and friendly NATO markers now share stable color accents, number badges, and clearer selected-unit feedback.
- Added a full command-bar guide to the main-menu Help page and in-battle `F1` manual.
- Added hover explanations, capability-aware disabled buttons, target-mode reticles, Escape-to-cancel, command confirmations, and double-tap squad focus.
- Added detailed unit-card tooltips, stronger numbered queued-order markers, and wounded/pinned/idle selection shortcuts.
- Added UI scale and larger-text settings with automatic JSON persistence for display, audio, performance, speed, help, and accessibility preferences.
- Added tactical order/contact/casualty/warning/objective sounds on top of the existing distance-aware combat mix.
- Added critical unit-status badges, recent tactical-event pings, and squad-colored off-screen selection arrows.
- Mobile infantry now fires at visible targets while advancing according to fire discipline, with a substantial accuracy penalty; crew-served weapons and pinned troops remain unable to fire on the move.

### Performance

- Replaced the route hot path with a weighted A* implementation using one precomputed occupancy set and direct cached threat-grid reads.
- Discarded stale heap entries and stopped repeatedly calling high-level lookup helpers for every A* edge.
- Spread group-order path calculations to one new route per fixed tick to prevent three expensive searches landing on one frame.
- Reworked spotting to reuse faction lists and prefilter impossible observer/target pairs before LOS evaluation.

### Testing and tooling

- Added 28 focused maintenance regressions.
- Added real headless Pygame menu, battle, zoom, camera, profiler, and display-mode rendering coverage.
- Added configurable deterministic stress testing across all difficulties.
- Added a repeatable 16-unit fixed-step benchmark.
- Added a single-command validation runner and robust Windows launcher/runtime discovery.
- Added a standalone source/release materializer with optional ZIP output.
- Consolidated duplicated source reconstruction into `src/source_loader.py`.
- Added an offline/CI switch for optional presentation-asset downloads.
