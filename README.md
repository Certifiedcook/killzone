# Kill Zone — Realtime Tactical Infantry Prototype

**Kill Zone** is a top-down realtime infantry tactics game built around suppression, positioning, trench fighting, fog of war, weapon handling, casualty management and coordinated movement.

The game is a systems-heavy prototype rather than a finished release. The current goal is to make the infantry combat and controls good before adding campaign or mod systems.

## Run on Windows

Double-click:

```text
launch_kill_zone.bat
```

The launcher installs the pinned Pygame dependency if needed and then starts the game.

Manual launch:

```bat
py -m pip install -r requirements.txt
py kill_zone.py
```

The first launch also starts a background download for the optional CC0 combat-audio and blood-sprite pack. If the download is unavailable, the game still runs: combat remains functional and blood falls back to procedural decals. See `ASSET_SOURCES.md` for the source/licence register.

## Main menu

- **Continue** — return to the current battle.
- **Play** — open skirmish setup and generate a new procedural battlefield.
- **Settings** — default simulation speed, combat audio and help-overlay settings.
- **Quit** — exit.
- **Esc in battle** — pause and return to the main menu.

## Core realtime controls

### Selection and movement

- **Left click:** select a friendly unit.
- **Drag left mouse:** box-select.
- **Shift + left click:** add/remove from selection.
- **Right click ground:** move selected units using the active formation.
- **Shift + right click:** queue a movement waypoint/order.
- **Ctrl + 1..9:** assign selected units to a control group.
- **1..9:** recall a control group.
- **F4:** cycle formation: Wedge / Line / Column / Spread.
- **X:** cycle route policy: Fast / Safe / Manual.
- **Backspace:** cancel current orders.

### Time control

- **Space:** pause/unpause.
- **Hold ` (backquote):** tactical slow motion at 0.25x while issuing orders.
- **-:** 0.5x simulation speed.
- **=:** 1x simulation speed.
- **]:** 2x simulation speed.

### Fire and tactical orders

- **Right click visible enemy:** fire with the selected unit's current fire mode.
- **Shift + right click enemy:** queue that attack after existing orders.
- **A:** aimed fire.
- **F:** snap fire.
- **W:** rapid fire.
- **Q:** area suppression mode.
- **O:** directional Overwatch toward mouse position.
- **I:** MG/HMG fire lane toward mouse position.
- **C:** coordinated covering advance.
- **F3:** bounding-overwatch advance mode.
- **F7:** cycle fire discipline: Hold / Return Fire / Fire at Will / High-Confidence Only.
- **F8:** cycle target priority: Nearest / Exposed / Specialist / Suppressed.
- **Tab:** known-threat / movement-exposure overlay.

### Weapon handling

- **R:** tactical reload; retains the partial magazine.
- **Shift + R:** emergency reload; faster but discards the partial magazine.
- **J:** clear jam.
- **D:** deploy/pack MG, HMG or mortar.
- **B:** MG/HMG barrel change.
- **F9:** transfer a compatible magazine to an adjacent friendly.
- Sustained automatic fire produces heat; overheated weapons stop until cooled or serviced.

### Stance and close combat

- **Z:** cycle Standing / Crouched / Prone.
- **V:** fix/remove bayonet.
- **P:** peek from cover.
- A bayonet-equipped soldier right-clicking an adjacent enemy in a connected trench can perform a trench assault.

### Grenades and support

- **G:** hand grenade.
- **Shift + C:** increase grenade cooking time.
- **S:** smoke grenade.
- **L:** rifle grenade.
- **K:** satchel charge.
- **M:** on-map mortar HE.
- **N:** on-map mortar smoke.
- **H:** off-map HE support.
- **Y:** off-map smoke support.

### Medics and casualties

- Units can be **healthy, wounded, incapacitated, killed or surrendered**.
- Incapacitated soldiers bleed out unless treated.
- **Right click wounded/incapacitated ally with Medic:** stabilize/treat.
- **Right click incapacitated ally with another soldier:** drag.
- **Alt + right click incapacitated ally:** carry. Carrying prevents firing.
- Persistent blood decals mark substantial wounds and fatalities.

### Engineers

- **E on wire:** cut wire.
- **E on known mine:** clear mine.
- **E on suitable terrain:** build sandbags.
- **Shift + E:** deliberate mine scan.
- **T:** dig trench.
- **4:** place wire.
- **U:** Bangalore/demolition breach on adjacent wire.

## Context command bar

The bottom command bar exposes common actions without requiring keyboard memorisation:

`SUPPRESS | OVERWATCH | GRENADE | SMOKE | RELOAD | STANCE | FORMATION | DISCIPLINE | PRIORITY | BOUND`

The keyboard shortcuts remain available for faster control.

## The ten control/tactics upgrades

The current build includes the ten systems selected for the realtime control pass:

1. **Tactical slow motion** while holding backquote.
2. **Control groups and formation movement.**
3. **Context-sensitive bottom command bar.**
4. **Fire discipline and target-priority policies.**
5. **Queued movement and attack orders.**
6. **Bounding-overwatch advance.**
7. **Known-threat and route-exposure visualisation.** Hidden enemies are not leaked by the overlay.
8. **Visible tracer travel and near-miss suppression along the bullet path.**
9. **Richer trench geometry:** traverses, firing steps, dugouts and interrupted sight lines.
10. **Symmetric fog-of-war intelligence:** enemy AI uses sightings and last-known contacts rather than tracking hidden player positions.

## Military-map unit presentation

On-map units use a deliberately restrained **APP-6 / MIL-STD-2525-inspired tactical-map presentation**:

- friendly land units use a blue/cyan rectangular frame;
- hostile units use a red diamond frame;
- infantry uses the familiar crossed-diagonal infantry base;
- game-specific class abbreviations such as `MG`, `MED`, `SN` and `DMR` are displayed separately as role metadata.

The class abbreviations are **not claimed to be official APP-6 entity symbols**. This avoids inventing fake NATO symbology for game-specific roles while retaining the recognisable affiliation language.

## Combat audio and blood effects

The presentation layer can use online-sourced CC0 assets for:

- 5.56 rifle / automatic-rifle fire;
- 7.62 rifle / sniper / HMG fire;
- SMG fire;
- explosion variants;
- hurt/grunt variants;
- death/pain vocalisation;
- blood decal sprite.

Gunfire, explosions, hurt sounds and death sounds are triggered from simulation events rather than being tied to animation frames. Audio has no gameplay effect and there is no sound-detection mechanic.

If an asset is absent, the game continues without it. Blood has a procedural fallback.

## Major combat systems

- Realtime simultaneous simulation at a fixed 30 Hz model step.
- Directional facing, flank/rear bonuses and enfilade.
- Directional trenches, Overwatch and MG fire lanes.
- Fog of war, recon, signatures and last-known contacts.
- Suppression, morale, cohesion, routing and surrender.
- Standing/crouched/prone stances.
- Riflemen, MGs, snipers, medics, engineers, recon, grenadiers, assault infantry, automatic riflemen, marksmen, HMG crews and mortar teams.
- Magazine-state ammunition, tactical/emergency reloads and ammo sharing.
- MG heat, jams, barrel changes and assistant-gunner degradation.
- Smoke density/drift, weather, fire and persistent battlefield damage.
- Mines, wire, sandbags, foxholes, bunkers, buildings, doors, windows and destructible cover.
- Elevation, reverse slopes and penetration through light structures.
- Grenades, rifle grenades, satchels, mortars and delayed support fire.
- Medics, bleeding, dragging and carrying casualties.
- Safe/fast/manual routing and coordinated covering advances.

## Testing

The headless model test suite does not require Pygame:

```bat
py self_test.py
```

The current suite covers the original realtime combat systems plus formations, queued commands, fire discipline, bounding overwatch, symmetric fog-of-war contact memory, combat events/blood decals, richer trench generation and the media manifest.

## Project scope

For now the project intentionally does **not** prioritise campaign progression, modding, expanded mission types or RPG-style squad progression. The next useful work is playtesting, tuning, UI refinement and improving the realtime tactical AI rather than adding another large content layer.
