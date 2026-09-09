# Engine architecture

Kill Zone has a game-specific Python engine with a separate Pygame frontend.
Its source is ordinary importable modules. The compressed historical payloads,
source concatenation, and `exec`-based runtime loader are gone. Release builders
copy these modules unchanged rather than generating another implementation.

## Boundaries

| Module | Responsibility |
| --- | --- |
| `engine.simulation` | `RealTimeGame`, statically composed from the six system classes |
| `engine.systems` | World, movement, combat, tactics, operations, and lifecycle behavior |
| `engine.models` | Mutable game state, including units, cells, and effects |
| `engine.definitions` / `engine.rules` | Game data tables and shared rule functions |
| `engine.clock` | `FixedStepClock`, independent of gameplay and rendering |
| `engine.spatial` | `SpatialGrid`, deterministic snapshot-based point queries |
| `engine.revisions` | Terrain revision state owned by one world |
| `engine.scenarios` / `engine.content` | Strict versioned scenario settings and bounded JSON content loading |
| `engine.state` | Canonical battle fingerprints and versioned checkpoint export |
| `engine.cli` | Headless simulation reports and scenario import/export |
| `engine.networking` | `NetworkGame`, authoritative commands, snapshots, and PvP rules |
| `engine.frontend` | Desktop lifecycle, input, rendering, audio, and Pygame backend |
| `src.multiplayer_net` / `multiplayer_server.app` | Framed transport and dedicated-server orchestration |
| `engine.compat` / `kill_zone.py` | Lazy resolution of historical entry-point names |

Systems use ordinary methods with explicit composition in `RealTimeGame`.
Function-local imports are used where needed to avoid dependency cycles;
importing the simulation does not initialize or require the Pygame frontend.

```python
from engine.definitions import SIM_DT
from engine.simulation import RealTimeGame

game = RealTimeGame(seed=42, difficulty="Hard")
for _ in range(30):
    game.update(SIM_DT)
```

Import `engine.frontend.app.KillZoneApp` for the desktop application. Existing
`import kill_zone as kz` callers retain their public names through lazy
compatibility lookup. New engine code should import its actual dependencies.

## Time, spatial queries, and cache ownership

The desktop owns a `FixedStepClock` that calls the simulation with fixed steps.
Catch-up is bounded, fractional time is retained, and dropped simulation time
is exposed. Speed changes scale newly elapsed time. A failed callback is not
replayed automatically. The dedicated server currently maintains its own
fixed-tick loop.

`SpatialGrid` reduces ballistic collision candidates before the existing exact
intersection checks. Rebuild captures positions and preserves input ordering;
queries do not silently follow later object movement. Radius and box queries
include their boundaries. Large sparse queries avoid enumerating unbounded
empty grid regions.

Terrain revisions belong to each game through its revision tracker. Cells
retain that tracker, and terrain/door mutations invalidate the affected
world's cached terrain, visibility, and path work. Snapshot application compares
final terrain against the prior state, so an unchanged snapshot does not
invalidate caches merely because dynamic cells were restored and reapplied.
Running another game must not invalidate this world's caches.

## Multiplayer rules

`NetworkGame` explicitly subclasses `RealTimeGame`. It uses symmetric forces
and an elimination objective, disables campaign AI and campaign mission
progression, and retains the shared combat systems. It does not replace
methods on individual game instances.

The server owns simulation state. Commands are checked for ownership and valid
field types, ranges, modes, and coordinates before mutation. Snapshots and
effects are filtered for each player's perspective. Shared framed JSON decoding
rejects malformed and non-finite values.

Writes have deadlines, a broken peer cannot suppress the opponent's result,
and disconnect cleanup releases sockets and empty rooms. The simulation still
awaits snapshot sends, so a slow peer can delay its room until the send timeout.
Independent bounded writer queues, interpolation, delta snapshots, and reconnect
are proposed work, not current capabilities.

## Scope and remaining structure

This is a foundation for this tactics game, not a general-purpose ECS or editor.
Some private compatibility methods remain while behavior is moved into clearer
system APIs. Several frontend, shared-rules, and definition modules are still
large. Static composition makes ownership reviewable, but does not by itself
make every system independently replaceable.

A fixed seed supports repeatable simulation under matching code, settings, and
commands. Versioned checkpoint export and canonical state fingerprints are available;
checkpoint restoration and replay are tracked next. See [ENGINE_TOOLS.md](ENGINE_TOOLS.md),
[ROADMAP.md](ROADMAP.md) for prioritized extensions and
[CONTRIBUTING.md](CONTRIBUTING.md) for validation contracts.
