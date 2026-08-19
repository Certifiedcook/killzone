# Changelog

## Unreleased — Operations & Engineering

### Operations

- Added Defensive Battle mode with east-side deployment, three timed assault waves, sequential hold objectives, sector stability, a contested command post, and dedicated victory/defeat rules.
- Defensive attackers now use distributed open assault waypoints and a stalled-order watchdog instead of repeatedly targeting an occupied objective tile.
- Defensive attackers now form role-aware assault groups, assess recently observed resistance, concentrate breachers on the weak sector, retain fixing elements, stage fire support behind the advance, and re-plan as battlefield intelligence changes.
- Added Advanced Operations setup for mission type, deterministic battlefield selection, forced/automatic weather, 80/100/125% enemy force strength, and 3/5/7-minute defense duration.
- Added defense-specific briefing, deployment instructions, objective language, countdown/wave/command-post HUD, and after-action event recording.

### Squad doctrine

- Added Cautious, Balanced, and Aggressive squad doctrines, cycled with `Shift+D` or by right-clicking a squad tab.
- Doctrine now affects default movement pace, automatic smoke/cover reactions, and whether advancing troops attempt moving fire.
- Added persistent doctrine feedback beside the engineer controls and in the field manual.

### Engineering

- Engineers on both factions can now construct sandbags, wire, trenches, MG turrets, field guns, and artillery batteries from a visual `Shift+B` construction palette.
- Player construction now uses an RTS workflow: choose a project, click a reachable site, and the nearest available engineer automatically moves adjacent to the blueprint before building.
- All six construction choices now have visual palette previews; completed MG nests, field guns, and artillery batteries use distinct code-drawn weapon silhouettes instead of the default infantry marker.
- Static weapons are destructible combat units with independent direct/indirect fire behavior and no squad-capacity cost.
- Enemy engineers use the same construction pipeline with AI build choices, build time, cooldowns, and a temporary emplacement cap.
- Construction currently has no supply cost by design; supplies and logistics are deferred to the next balance update.

### Testing

- Added regressions for deterministic operation options, defense deployment/waves, doctrine policy, and construction for both factions.
- Expanded the focused maintenance/expansion regression suite from 28 to 37 tests, including tactical defense planning, distinct emplacement visuals, advancing attackers, and remote engineer construction.

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
# Multiplayer alpha

- Added a two-player public server browser, create/join lobby, Blue/Red slots, ready flow, match result handling, and a configurable server address defaulting to `88.99.98.156:25503`.
- Added an authoritative dedicated Python server with room isolation, command ownership/rate validation, 10 Hz perspective-filtered snapshots, fog-of-war contacts, disconnect forfeits, and headless Pygame simulation.
- Network-enabled movement, direct fire, grenades, smoke, suppression, overwatch, reloading, stance, deployment, fire modes, weapon servicing, mortar fire, assault/bounding/fallback movement, engineer construction, doctrine, discipline, target priority, autonomy, and hold orders.
- Added symmetric PvP force generation, Red-side client normalization, framed JSON transport, a background desktop networking thread, and an upload-ready server bundle builder.
- Added protocol, authority, perspective, real two-client socket, and multiplayer render smoke coverage.
