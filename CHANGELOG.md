# Changelog

## Unreleased — Combat Feel 2.1

### Firefights

- Added weapon-specific burst lengths, recovery pauses, recoil buildup/decay, and modest close-range lethality so rifles, automatic weapons, support guns, and precision weapons no longer share a metronomic firing rhythm.
- Deliberate direct and suppressive fire now checks the intended lane for friendlies. Enemy troops seek another safe visible target or offset a suppression lane; already-airborne rounds retain physical friendly-fire risk.
- Near misses now make soldiers face the threat, flinch, duck, or go prone according to danger and suppression. Localized hits expose a clear wounded reaction.
- Added material-specific impact events, near-miss cracks, restrained automatic-fire mix ducking, and player/hostile tracer accents.

### Tactics, movement, and feedback

- Added target, plan, movement, and crew-weapon deployment commitments to stop AI order thrashing while preserving emergency reactions to suppression, morale, ammunition, and jams.
- Enemy specialists withdraw into cover when badly wounded or completely depleted; smoke is refused when it would blind an active friendly support lane.
- Squad plans use stable lateral lanes, formation moves reserve distinct arrival cells, stalled routes surface a reason and force enemy re-planning, and arrivals settle facing the intended threat.
- Added a short preparation beat, sustained contact/engagement presentation states, order-state tooltips, lane-risk markers, reaction indicators, and a restrained delay before the after-action panel.
- Squad focus now eases the camera instead of snapping. Camera shake and edge scrolling are independently configurable and persist with existing settings.

### Testing

- Added deterministic coverage for firing-lane refusal and AI retargeting, weapon bursts, danger reactions, support-lane smoke safety, formation arrival slots, AI preparation/commitment, new audio layers, and multiplayer state replication.

## Unreleased — repository cleanup

- Removed the unreferenced original and v4 game fragments, superseded v4/v5 test payloads, a stale one-off overnight report, and a redundant validation launcher.
- Consolidated the active historical game into one deterministic legacy archive instead of ten versioned fragments.
- Renamed the active historical performance and test payloads around their purpose rather than an obsolete version number.
- Centralized release-directory safety and ZIP creation shared by the game and dedicated-server builders.
- Expanded ignore rules for common tool caches, coverage output, and logs, and documented the authoritative source/test layout.

## Unreleased — Combat 2.0

### Ballistics and wounds

- Replaced instant small-arms damage with persistent ballistic rounds that travel over simulation ticks, collide with soldiers and terrain, can cause friendly fire, and emit readable short tracer segments.
- Near-miss suppression now follows each round's physical trajectory instead of applying only around the selected target.
- Added material interception, cover damage, and penetration energy loss for hard and soft battlefield structures.
- Added localized head, torso, arm, and leg wounds with disorientation, bleeding, accuracy, reload, stamina, and mobility consequences. Medic treatment now reduces localized trauma.
- Added reacquisition and post-movement weapon-settling time while preserving deliberate moving fire at its existing accuracy cost.

### Tactics and identity

- Added a squad-level enemy planner with support-by-fire, maneuver, assault, sustainment, defensive screen, covered-lane, reserve, reposition, and favorable-counterattack states.
- Preserved the operation planner's terrain-aware staged assault routes, then hands contact fights to the new suppression-and-maneuver logic.
- Added deterministic full names and callsigns from a 1,600-combination identity pool, with compact squad-slot labels and multiplayer replication.
- Unit tooltips now expose full identity, localized trauma, and observed AI tactical assignment/phase; wounded units receive an additional battlefield status corner.

### Testing

- Added deterministic tests for delayed projectile resolution, direct wounds, trajectory suppression, friendly fire, hard-cover interception, wound penalties, 1,000 unique generated names, offensive/defensive squad jobs, and multiplayer state round trips.
- Extended stress invariants to cover projectile counts and all localized wound values.

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
# Audio and visual overhaul

- Added distinct layered procedural reports for rifles, heavy weapons, SMGs, artillery, and explosions with stereo positioning, distance tails, debris, rumble, ambience ducking, and optional recorded-sample foreground layers.
- Added weather-, stage-, intensity-, fire-, and suppression-responsive ambience without using audio to reveal hidden contacts.
- Added deterministic cached terrain micro-detail, animated rain/fog, fire embers, muzzle flashes, explosion blooms, shock rings, enhanced tracers/impacts, selection brackets, squad pips, stance marks, suppression accents, and map/menu atmosphere.
- Replicated transient combat effects and audio events in authoritative multiplayer snapshots.
- Added deterministic audio mix, weather, terrain, network-effect, dependency-free UI, and real Pygame render coverage.
