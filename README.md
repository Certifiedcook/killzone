# Kill Zone

Kill Zone is a top-down real-time infantry tactics game about suppression,
cover, maneuver, morale, casualties, engineering, and small-unit command.
It includes single-player Assault and Defense operations and two-player PvP.
Python runs the simulation; Pygame provides the desktop interface.

The game now uses an ordinary Python engine package. Simulation, networking,
and frontend code have separate modules, and development and release builds
use the same source files. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
boundaries and remaining limitations, and [ROADMAP.md](ROADMAP.md) for proposed
additions. [ENGINE_TOOLS.md](ENGINE_TOOLS.md) covers headless simulation, validated
scenario import/export, state fingerprints and checkpoint export.

## Play

On Windows, double-click `launch_kill_zone.bat`. For a manual setup, use Python
3.12 or later:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python kill_zone.py
```

The launcher prefers `.venv`, falls back to `py` or `python`, and installs the
pinned Pygame dependency when needed. Optional media is unnecessary for offline
play; sources and licensing are listed in [ASSET_SOURCES.md](ASSET_SOURCES.md).

## Current gameplay

- Physical small-arms rounds, penetration, destructible cover, friendly fire,
  and suppression along near-miss trajectories.
- Localized wounds, bleeding, medics, stamina, weapon preparation, recoil,
  bursts, and reactions to incoming fire.
- Assault objectives, defensive lines, reserves, morale collapse, and timed
  Defense waves with support, maneuver, assault, and sustainment roles.
- Squad doctrines, formations, fire discipline, engineer construction,
  emplacements, mortars, and artillery.
- Seeded soldier identities, procedural audio and weather effects, tactical
  cues, camera controls, and persistent presentation settings.

PvP uses an authoritative dedicated server with command ownership, input
validation, fog of war, symmetric forces, password-protected rooms, readiness,
and match results. It remains a friends-only alpha: TCP is unencrypted, and
accounts, matchmaking, reconnect/resume, and chat are not implemented. The
configured browser default is `88.99.98.156:25503`; the address is editable.

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
| `F11` | Toggle the selected fullscreen mode |
| `F12` | Commit held reserves |
| `Home` | Focus the current selection |
| Arrow keys / edge scroll / middle drag | Pan the camera |
| Mouse wheel | Zoom |
| `Escape` | Cancel target mode, then open the pause menu |

The Help page and `F1` manual cover the remaining commands and targeting modes.

## Validation

```bat
.venv\Scripts\python validate.py
.venv\Scripts\python validate.py --stress
```

`validate.bat` accepts the same options. The suite covers engine isolation,
fixed-step scheduling, spatial queries, performance behavior, benchmark
correctness, historical simulation regressions, current gameplay, multiplayer
sockets, presentation, and frontend wiring. Real Pygame rendering runs when
Pygame is installed. `--stress` adds both Assault and Defense battles across
multiple seeds and difficulties.

Run the fixed-step and pathfinding benchmark separately:

```bat
.venv\Scripts\python benchmark.py
```

Use the same interpreter, arguments, seeds, and mission when comparing results.
See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks.

## Packaging and dedicated server

```bat
.venv\Scripts\python build_release.py --zip
.venv\Scripts\python build_multiplayer_server.py --zip
```

Both builders copy the tested engine modules; they do not assemble a second
runtime. Generated directories and archives belong under ignored `build/`.
Builders refuse to replace a non-empty directory without their generated
marker. Desktop bundles contain Python source and still require the Python
runtime and listed dependencies.

For a hosted server, extract the contents of `dedicated_server.zip` into
`/home/container`, with `app.py` at `/home/container/app.py`. Use Python 3.12+,
install `requirements.txt`, and assign TCP port `25503`. See the generated
`SERVER_SETUP.txt` for launch details.

## Source layout

| Path | Purpose |
| --- | --- |
| `kill_zone.py` | Desktop entry point and lazy compatibility facade |
| `engine/simulation.py` | Headless `RealTimeGame` with static system composition |
| `engine/systems/` | Combat, lifecycle, movement, operations, tactics, and world systems |
| `engine/models.py`, `engine/definitions.py`, `engine/rules.py` | State, data tables, and shared rules |
| `engine/clock.py`, `engine/spatial.py` | Fixed-step scheduling and spatial queries |
| `engine/revisions.py` | Per-world terrain revision state |
| `engine/networking.py` | `NetworkGame`, commands, snapshots, and PvP rules |
| `engine/frontend/` | Pygame application, controls, rendering, audio, and support |
| `src/multiplayer_net.py` | Framed JSON transport and background desktop client |
| `multiplayer_server/` | Authoritative service process |
| `src/release_tools.py` | Shared packaging helpers |
| `*_test.py`, `validate.py`, `benchmark.py` | Validation and measurement |

The compressed runtime payloads and source-assembly loader have been removed.
Edit engine modules directly. Historical changes remain in
[CHANGELOG.md](CHANGELOG.md).
