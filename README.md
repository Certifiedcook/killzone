# Kill Zone

Kill Zone is a top-down realtime infantry tactics prototype built around suppression, prepared defenses, smoke, maneuver, trench fighting, morale, casualty handling, and small-unit command.

## Current release hardening

The current branch concentrates on correctness, frame pacing, maintainability, and release validation:

- repeated casualty/revival cycles now clean every stale combat reference;
- cached routes are revalidated when terrain or unit occupancy changes;
- safe-route A* reads cached threat/occupancy data directly, skips stale heap work, and spreads group searches across fixed ticks;
- spotting reuses faction lists and rejects out-of-range pairs before LOS work;
- healthy line-stability values are green, threatened values amber, and collapsed values red;
- optional asset downloads can be disabled with `KILLZONE_DISABLE_ASSET_DOWNLOADS=1` for offline and CI runs;
- historical compressed payloads now share one source loader, while current maintenance code remains reviewable plain Python;
- focused regressions, real headless Pygame rendering, deterministic multi-battle stress tests, a benchmark, and a release builder are included.

The 900-tick Veteran benchmark with a 16-unit player force measured a **10.4 ms mean** and **31.9 ms p95** fixed update on this host. Path work measured **2.0 ms mean** and **13.4 ms p95**. Actual results depend on CPU, battle state, and map seed.

## Quick start

On Windows, double-click:

```text
launch_kill_zone.bat
```

The launcher prefers a local `.venv`, falls back to `py` or `python`, and installs the pinned Pygame dependency when needed.

Manual launch:

```bat
python -m pip install -r requirements.txt
python kill_zone.py
```

## Validation and packaging

Run the complete quick suite:

```bat
validate.bat
```

Include the multi-seed stress matrix:

```bat
validate.bat --stress
```

Run the repeatable simulation benchmark or build a standalone single-file release:

```bat
python benchmark.py
python build_release.py --zip
```

The validation stack contains 71 historical model tests, 8 focused maintenance regressions, a dependency-free UI smoke test, and a real Pygame runtime/render smoke test. `stress_test.py` adds configurable Easy/Hard/Veteran battle matrices with numerical, bounds, cache, transient-effect, and stale-state invariants.

## Source layout

`src/source_loader.py` reconstructs the historical compressed source and appends `src/maintenance_extension.py` before the entry point. The three runtime/test loaders use that single assembly path. `build_release.py` materializes a normal standalone `kill_zone.py` for distribution.

## Previous stability and performance pass

This build hardens the vertical slice rather than expanding its content scope. It targets the mid-30 FPS regression, stale combat-state graphics, and troops routing too quickly. The graphics remain deliberately simple and there are **no graphics-quality presets**; performance is improved by eliminating redundant work instead.

## What changed in this pass

### Performance and diagnostics

- Static battlefield terrain is rendered once to a cached world surface and reused until terrain actually changes.
- Rendering strictly culls off-camera units, corpses, blood, projectiles, explosions and tactical arcs.
- Dynamic smoke/fire/ground-suppression tiles are collected at a throttled rate instead of scanning and redrawing every terrain detail every frame.
- Repeated UI text and dust-puff surfaces are cached.
- LOS and line-of-fire results use short-lived caches keyed to movement/time/terrain state.
- Battle-intensity presentation logic runs at 4 Hz instead of being recomputed every rendered frame.
- Existing pathfinding budgets, threat-grid caches, indexed occupancy and staggered AI remain intact.
- F9 now exposes a more useful profiler: frame, map/static/dynamic, units/effects, UI, simulation, AI, pathfinding and LOS timing plus active effect counts.

### Combat-state cleanup

- A centralized combat-exit cleanup removes Overwatch, fire lanes, reaction targets, queued paths, assault/bounding assignments and drag/carry references when a soldier dies, becomes incapacitated or surrenders.
- This fixes the ghost **Overwatch lines remaining after their owner dies** and prevents the same stale-reference class of bug elsewhere.
- Non-combat-effective selected units are automatically removed from selection.

### Morale, cohesion and retreat behavior

- Morale now has hysteresis: **Steady → Shaken → Pinned → Breaking → Routing/Rallying** rather than instantly crossing a flee threshold.
- Suppression by itself primarily pins troops; healthy soldiers no longer immediately run because one suppression value spikes.
- Severe morale/cohesion failure must persist for several seconds before routing.
- Casualty shock is partly temporary and decays as a unit recovers.
- Squad morale influences individual breaking delay, so one shaken soldier does not automatically collapse a healthy fireteam.
- Routed troops pick protected rearward positions, can rally out of contact, and return to player/AI control once sufficiently recovered.
- AI specialists preserve themselves more sensibly during a genuine collapse: crew-served weapons pack up and medics/mortars/snipers seek deeper cover.
- Sector collapse and local surrender also require sustained instability rather than a brief half-second dip.

### New control tools

- **HOLD**: selected troops resist voluntary withdrawal longer. They can still be pinned and can still collapse under catastrophic conditions.
- **FALLBACK**: click the command, then right-click a map position to designate where the selected troops should retreat/rally if they break.
- The selected-unit sidebar now shows morale state, major morale-pressure/support factors, time under break pressure, and the assigned fallback/HOLD state.

## Validation

- **71/71 model regression tests pass.**
- **UI smoke test passes**, including terrain-cache reuse and HOLD/FALLBACK frontend wiring.
- 40-second Easy/Hard/Veteran stress battles completed without numerical-state failures or stale Overwatch/fire-lane state on combat-exited units.
- The current 16-unit benchmark and its latency distribution are documented at the top of this file; the renderer and simulation both remain instrumented through F9.


## Vertical-slice battle systems

- Four staged assault objectives: break the forward line, secure the central strongpoint, break the reserve line, and capture the rear command post.
- Enemy force-level plans with forward sectors, a genuine held reserve, fallback positions, counterattack triggers, and a rear command group.
- Sector stability and defensive collapse driven by casualties, morale, suppression, crossfire, and actual breaches.
- Local surrender for isolated, badly pinned defenders.
- Battle pacing states: Approach, Contact, Assault, and Collapse.
- Contact reports and aged last-known-contact uncertainty without exposing live hidden positions.
- Assault-plan visualization separating support/suppression and maneuver elements.
- Deterministic unit identity labels for player soldiers without XP, loot, or RPG progression.
- Expanded shot-chance breakdown explaining cover, range, stance, suppression, smoke, preparation, flank/enfilade, weather, and fire mode.
- Four procedural battlefield variants: open farmland, wooded ridge, ruined village, and ridgeline.
- Stronger static terrain detailing for trenches, craters, woods, buildings, and sandbags.
- Distance-aware combat audio, procedural bullet-snap/impact/thump layers, and restrained distant battlefield ambience.
- Expanded after-action report with objective completion, force statistics, and a key-event timeline.

The existing optimization architecture is retained: pathfinding/AI work remains budgeted across simulation ticks, threat and occupancy lookups are cached, transient effects are capped, and render FPS remains uncapped by default. Logistics expansion is still intentionally deferred.


This build expands the command layer while deliberately **not** adding new logistics systems yet.

## Run

Windows:

```text
launch_kill_zone.bat
```

Manual:

```bat
py -m pip install -r requirements.txt
py kill_zone.py
```

Historical model tests only:

```bat
py self_test.py
```

The historical model suite contains **71 tests**. Use `validate.bat` for the complete current validation stack.

## Major changes in this pass

### Performance

- Rendering FPS is **uncapped by default**. The fixed-step simulation remains 30 Hz.
- Settings can restore a 60/120/240 FPS cap if desired.
- Threat routing uses cached faction threat grids rather than recalculating every enemy for every A* node.
- Unit lookup and occupancy are indexed.
- Mass pathfinding is budgeted across simulation ticks instead of all selected units calculating A* in one frame.
- AI decisions are similarly budgeted/staggered.
- Tracers, impacts, dust effects, and simultaneous audio playback are capped/throttled.
- The simulation prevents a runaway catch-up spiral if the machine temporarily falls behind.
- **F9** toggles an on-screen performance profiler with simulation/path/AI timing.

### Larger battlefield and camera

- Battlefield increased to **56×36 tiles**.
- Fixed camera viewport keeps the UI readable.
- Arrow keys or screen-edge scrolling pan the camera.
- Hold middle mouse and drag to pan.
- Mouse wheel zooms.
- **Home** focuses the camera on the current selection.
- Display modes: **Windowed**, **Borderless Fullscreen**, and **Exclusive Fullscreen**.
- **F11** toggles between Windowed and the most recently selected fullscreen mode.

### Squads and selection

- Friendly and hostile troops are organized into persistent four-man fireteams/squads.
- Initial forces and arriving reserves automatically group assault, fire-support, recon, and support roles into tactically coherent squads; unusual rosters use capacity-aware fallbacks.
- Click `SQUAD A`, `SQUAD B`, etc. to select a squad.
- **1..9** quickly selects Squad A–I during deployment or battle.
- **Alt+1..5** reassigns the current selection to Squad A–E.
- **Ctrl+1..9** saves control groups and **Shift+1..9** recalls them.
- Squad tabs, unit cards, and friendly map markers now share stable color accents and numbered hotkey badges; tabs also identify each squad's dominant tactical role.
- The main-menu Help page and in-battle **F1** guide explain every command-bar button, targeted versus instant commands, and changing setting labels.
- Hover command buttons for concise instructions; unavailable actions are dimmed with a reason, active target modes show a map reticle, and **Escape** cancels a pending mode before opening the menu.
- Press a squad number twice quickly to select and center its troops. Use **Shift+W**, **Shift+P**, and **Shift+I** to select all wounded, pinned/breaking, or idle troops.
- Hover unit cards for full health, loaded/reserve ammunition, suppression, morale, and condition details.
- Planned movement and queued move/fire orders use stronger colored paths and numbered destination markers.
- Settings now include 90/100/110% UI scale and a larger-text toggle, and automatically persist display, audio, performance, speed, help, and accessibility preferences.
- A bottom unit-card strip gives health/suppression status and direct selection for up to 16 deployed troops.
- Visible drag-box selection remains supported with the camera and zoom system.

### Pre-battle deployment and reserves

- Skirmish setup now accepts an optional numeric **map seed**.
- Enemy strength is shown as an **estimate**, not an exact force count.
- A configurable number of your chosen troops can be held as reserves.
- `DEPLOY FORCE` opens a deployment phase before combat.
- Select units/squads and right-click inside the western deployment zone to position them.
- Enter or Space begins the battle.
- **F12** commits held reserves from the western edge during combat.

### Tactical previews

- Hover a visible enemy with a selected soldier to see:
  - line of fire;
  - hit chance;
  - range;
  - target cover;
  - smoke and penetration effects;
  - target suppression state.
- Hover ground with a selected soldier to preview the chosen route, approximate ETA, and threat along each route segment.
- Hold **Left Alt** over a tile for detailed terrain intelligence and directional cover edges:
  - green = strong protection;
  - yellow = partial protection;
  - red = exposed direction.
- Ground under sustained fire receives a visible suppression tint.
- Unit suppression is displayed as a progressively stronger halo.

### Dedicated Assault order

Press **F2** or click `ASSAULT`, then right-click the objective.

The selected group is divided into a support element and assault element. Supporting automatic/precision weapons establish suppressive fire, available assault troops can deploy smoke, and the assault element advances when sufficient suppression or preparation time has developed. Supporting fire continues while the assault closes.

The player can still override every individual soldier at any point.

### AI coordination

- AI automatic weapons preferentially establish support-by-fire.
- Rifle/assault elements can maneuver while squad support is firing.
- AI flank decisions consider known threat rather than blindly taking the shortest route.
- Defenders can fall back toward generated secondary defensive positions.
- Snipers relocate after repeated firing rather than remaining permanently in one nest.
- Veteran AI makes more aggressive use of coordinated maneuver and smoke.
- Difficulty now changes **force size, decision cadence, and tactical coordination** rather than receiving hidden weapon-accuracy bonuses.

### Formation and traffic behavior

- Existing line, column, wedge, and spread formations remain.
- Large groups automatically compress toward column when their route crosses trenches, doors, bridges, or similar narrow movement corridors.
- Friendly movement has local waiting/repath behavior to reduce trench traffic jams and units stacking on the same point.

### Snipers and mortars

Snipers gain additional concealment and first-shot effectiveness when settled, prepared, and low-signature. Firing raises their signature; AI snipers will relocate after repeated shots.

Mortars now have:

- a 5-tile minimum range;
- a 19-tile effective maximum range;
- ranging dispersion;
- improving follow-up solutions;
- improved accuracy when Recon/Marksman observers can see near the target;
- HE and smoke ammunition as before.

### Crew-served weapons

Machine-gun/HMG crews can lose an assistant gunner from casualties. Adjacent friendly infantry can replace the assistant. An incapacitated HMG crew can also be re-crewed by an adjacent infantryman through the normal contextual friendly interaction.

### Battlefield effects and destruction

- HE explosions create capped dust-puff effects and local screen shake when near the camera.
- Woods, walls, buildings, sandbags, and firing positions can continue degrading or collapsing under heavy fire/explosives.
- Blood, craters, rubble, fire, smoke, cover wear, and suppression persist as battlefield state.

### Map generation

Procedural maps now deliberately construct a tactical problem rather than distributing terrain as noise:

- primary defensive line;
- secondary fallback line;
- communication trenches;
- strongpoints and bunkers;
- wire belt and mine patches;
- deliberate breaches;
- cratered assault lanes;
- wooded flank routes;
- central ruins/compound;
- firing steps and dugouts.

### Battle record / after-action

The simulation records significant battle events such as casualties, explosions, mortar ranging, reserve commitment, surrender, and assaults.

At victory/defeat the after-action overlay shows:

- remaining troops;
- casualties;
- shots/hits;
- accuracy;
- kills;
- grenades/smoke used;
- reserve commitment;
- recent battle timeline;
- duration and map seed.

### Pause planning

Space still pauses the simulation, but movement and queued orders can be issued while paused. Selected-unit planned paths and queued movement markers are drawn on the battlefield so the plan is readable before resuming.

## Important controls

- **LMB:** select / drag selection box
- **Shift+LMB:** additive selection
- **RMB:** movement, target attack, or active contextual command
- **Shift+RMB:** queue order
- **Space:** pause and plan
- **F2:** Assault order
- **F3:** bounding overwatch
- **F4:** formation
- **F7:** fire discipline
- **F8:** target priority
- **F9:** performance profiler
- **F10:** selected-unit autonomy
- **F11:** toggle Windowed ↔ last selected fullscreen mode
- **F12:** commit reserves
- **Left Alt:** directional tile/cover intelligence
- **Tab:** threat overlay
- **Alt+1..5:** assign Squad A–E
- **Ctrl+1..9:** assign control group
- **Shift+1..9:** recall control group
- **1..9:** select Squad A–I; double-tap to focus
- **Shift+W:** select all wounded troops
- **Shift+P:** select all pinned/breaking troops
- **Shift+I:** select all idle troops
- **Arrow keys / screen edge:** pan camera
- **MMB drag:** pan camera
- **Mouse wheel:** zoom
- **Home:** focus current selection
- **` (backquote):** tactical slow motion

The in-game Field Manual contains the rest of the weapon, engineer, casualty, stance, support-fire, and specialist controls.

## Scope intentionally deferred

No new logistics layer was added in this pass. Existing magazine/ammunition mechanics remain, but ammo bearers, supply crates, dropped-equipment economy, expanded resupply chains, and similar systems are being held for a later dedicated logistics pass.
