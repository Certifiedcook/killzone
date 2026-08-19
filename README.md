# Kill Zone

Kill Zone is a top-down real-time infantry tactics game about suppression,
cover, maneuver, morale, casualty handling, field engineering, and small-unit
command. It runs on Python and Pygame and includes single-player Assault and
Defense operations plus friends-only two-player PvP.

## Current systems

### Combat 2.0

- Small-arms rounds physically cross the map and can hit terrain, intended
  targets, or friendly and unintended soldiers.
- Near misses suppress units along the round's actual trajectory.
- Walls, buildings, timber, windows, woods, bunkers, doors, and sandbags use
  material resistance, penetration loss, and persistent damage.
- Head, torso, arm, and leg wounds affect disorientation, bleeding, accuracy,
  reload speed, stamina, and mobility. Medics reduce localized trauma.
- Movement and firing increase exposure; reacquisition and post-movement
  settling affect weapon response.
- Weapons fire in role-specific bursts with recoil recovery and close-range
  lethality; soldiers flinch, duck, or go prone under near misses.
- Deliberate fire checks friendly firing lanes before shooting, while physical
  rounds can still cause accidental friendly fire after they are airborne.
- Every mobile soldier receives a deterministic full name and callsign from a
  1,600-combination identity pool.

### Operations and AI

- Assault battles use four staged objectives, prepared defensive lines,
  reserves, local collapse, surrender, and a rear command post.
- Defense battles reverse deployment and ask the player to hold three timed
  waves while protecting the command post.
- Enemy attack plans separate support-by-fire, maneuver, assault, breach, and
  sustainment elements. Defensive plans use covered lanes, screens,
  repositioning, reserves, and favorable counterattacks.
- AI target, movement, deployment, smoke, and squad-plan commitments resist
  order thrashing; formations reserve distinct arrival positions.
- Squad doctrines—Cautious, Balanced, and Aggressive—change movement and
  autonomy policy.
- Engineers can build sandbags, wire, trenches, MG emplacements, field guns,
  and artillery through an RTS-style blueprint workflow.

### Presentation and multiplayer

- Procedural weapon reports, distant tails, explosions, ambience, weather,
  terrain detail, tracers, impacts, unit-state accents, and tactical cues are
  generated locally. Optional documented audio samples are used when present.
- Incoming/outgoing fire, material impacts, near-miss cracks, protective
  reactions, order delays, and blocked friendly lanes receive distinct cues.
- Camera focus eases to the selected squad; camera shake and edge scrolling
  have separate persistent settings.
- Multiplayer uses an authoritative dedicated server: simulation, fog of war,
  combat, construction, and command ownership are validated server-side.
- The public browser defaults to `88.99.98.156:25503` and supports room
  creation, Blue/Red slots, ready state, symmetric forces, and match results.
- PvP is a friends-only alpha: TCP transport is unencrypted and there are no
  accounts, reconnects, matchmaking, chat, or anti-abuse systems yet.

## Quick start

On Windows, double-click `launch_kill_zone.bat`.

Manual launch:

```bat
python -m pip install -r requirements.txt
python kill_zone.py
```

The launcher prefers `.venv`, falls back to `py` or `python`, and installs the
pinned Pygame dependency if necessary.

## Important controls

| Input | Action |
| --- | --- |
| Left click / drag | Select units |
| Right click | Issue the active contextual order |
| `1`–`9` | Select Squads A–I; tap twice to focus |
| `Ctrl+1`–`9` / `Shift+1`–`9` | Save / recall control groups |
| `Alt+1`–`5` | Reassign selection to Squad A–E |
| `Shift+B` | Open engineer construction |
| `Shift+D` | Cycle squad doctrine |
| `F1` | Open the in-battle field manual |
| `F2` | Begin a coordinated assault order |
| `F9` | Toggle the performance profiler |
| `F11` | Toggle the most recently selected fullscreen mode |
| `F12` | Commit held reserves |
| `Home` | Focus the current selection |
| Arrow keys / edge scroll / middle drag | Pan the camera |
| Mouse wheel | Zoom |
| `Escape` | Cancel target mode, then open the pause menu |

The main-menu Help page and in-battle `F1` manual document every command-bar
button, fire mode, autonomy setting, and targeting workflow.

## Validation

Run the complete suite:

```bat
validate.bat
```

Include deterministic multi-seed stress battles:

```bat
validate.bat --stress
```

The suite contains:

- 71 historical deterministic simulation tests;
- 37 current maintenance and operations regressions;
- real two-client authoritative multiplayer integration;
- presentation/audio, Combat 2.0, and Combat Feel 2.1 tests;
- dependency-free UI smoke coverage;
- real headless Pygame rendering;
- configurable Assault/Defense stress matrices.

Run the repeatable fixed-tick benchmark separately:

```bat
python benchmark.py
```

## Packaging

Build the standalone game directory and ZIP:

```bat
python build_release.py --zip
```

Build the upload-ready dedicated-server directory and ZIP:

```bat
python build_multiplayer_server.py --zip
```

Generated output belongs under the ignored `build/` directory. The builders
refuse to replace non-empty directories unless their generated marker is
present.

For the hosted server, extract the contents of `dedicated_server.zip` directly
into `/home/container` so `app.py` is `/home/container/app.py`. Use Python
3.12+, set the requirements file to `requirements.txt`, and assign TCP port
`25503`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `kill_zone.py` | Thin development entry point |
| `src/legacy_game.py.gz` | Compact historical runtime baseline |
| `src/legacy_performance.py.gz` | Historical performance layer |
| `src/maintenance_extension.py` | Current controls, operations, engineering, AI, and fixes |
| `src/multiplayer_extension.py` | Authoritative PvP state and desktop multiplayer UI |
| `src/presentation_extension.py` | Audio and visual presentation layer |
| `src/combat2_extension.py` | Projectiles, wounds, identities, and squad tactics |
| `src/combat_polish_extension.py` | Weapon rhythm, lane safety, reactions, AI commitment, and camera/audio polish |
| `src/source_loader.py` | Single runtime/test assembly path |
| `src/release_tools.py` | Shared safe release-directory and ZIP helpers |
| `multiplayer_server/` | Dedicated-server process and requirements |
| `*_test.py` | Focused, smoke, integration, and historical test launchers |
| `build_release.py` | Standalone desktop distribution builder |
| `build_multiplayer_server.py` | Dedicated-server bundle builder |

The compressed legacy baseline remains stable. New work should stay in normal,
reviewable Python, preserve the public names used by tests, and pass
`validate.py --stress` after simulation, AI, pathfinding, combat, terrain, or
rendering changes. See `CONTRIBUTING.md` for the development contract and
`CHANGELOG.md` for historical details.

## Optional assets

Kill Zone remains playable offline without downloaded media. Optional CC0
audio and visual assets, their sources, and licensing notes are documented in
`ASSET_SOURCES.md`. Runtime downloads live under ignored `assets/audio/` and
`assets/fx/` directories.
