# Kill Zone — Command & Performance Pass

Kill Zone is a top-down realtime infantry tactics prototype built around suppression, prepared defenses, smoke, maneuver, trench fighting, morale, casualty handling, and small-unit command.

This build expands the command layer while deliberately **not** adding new logistics systems yet.

## Display modes

The game now renders to a fixed logical canvas and then presents that frame across the actual display surface. This fixes the old fullscreen behavior where the logical game area could sit in the upper-left with unused black space on the right and bottom.

Available modes:

- **Windowed**
- **Borderless Fullscreen**
- **Exclusive Fullscreen**

**F11** toggles between Windowed and the most recently selected fullscreen mode. Use Settings to switch between Borderless and Exclusive fullscreen.

Mouse coordinates are translated back into logical game coordinates after scaling, so selection boxes, deployment, camera dragging, hover previews, and command clicks remain aligned in fullscreen.

## Performance

- Rendering is uncapped by default.
- Settings can restore a 60/120/240 FPS cap if desired.
- The realtime simulation remains fixed-step and separate from rendering FPS.
- Mass movement uses budgeted pathfinding, indexed occupancy lookup, cached threat information, staggered AI work, capped transient effects, and throttled combat audio.
- **F9** toggles the performance profiler.

## Current command systems

- Persistent Squads A–E
- Control groups
- Pre-battle deployment
- Reserves
- Procedural map seeds
- Camera panning and zoom
- LOS and hit-chance previews
- Directional cover visualization
- Route/exposure previews
- Dedicated Assault orders
- Suppression and bounding overwatch
- Mortar ranging
- Sniper relocation/concealment behavior
- Crew replacement and re-crewing
- After-action statistics and event timeline

## Important controls

- **LMB:** select unit / drag selection box
- **RMB:** contextual move/attack order
- **Shift + RMB:** queue order
- **Middle mouse drag:** move camera
- **Mouse wheel:** zoom
- **Home:** focus selected units
- **Space:** pause/unpause
- **Hold `:** tactical slow motion
- **F2:** Assault order mode
- **F3:** bounding overwatch
- **F4:** cycle formation
- **F7:** cycle fire discipline
- **F8:** cycle target priority
- **F9:** performance profiler
- **F10:** toggle selected-unit autonomy package
- **F11:** Windowed ↔ last selected fullscreen mode
- **F12:** commit reserves
- **Left Alt:** detailed tile/directional cover information
- **Tab:** known-threat overlay
- **Alt + 1..5:** assign selected troops to Squad A–E

## Testing

The current build passes **52/52 headless regression tests** plus the UI smoke harness. The UI harness also exercises Windowed, Borderless Fullscreen, Exclusive Fullscreen, and physical-to-logical mouse-coordinate conversion.

Run:

```bat
py self_test.py
```

For the UI smoke harness:

```bat
py ui_smoke_test.py
```

## Scope

The current priority remains realtime tactical control, AI, performance, map generation, and presentation. Expanded battlefield logistics/ammunition supply systems are intentionally deferred for a later dedicated pass.
