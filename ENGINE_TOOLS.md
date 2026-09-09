# Engine tools

All tools run on Python 3.12 or later. Headless tools require only the standard
library and never connect to the multiplayer server or download assets.

```console
python -m engine play
python -S -m engine simulate --seed 42 --mission defense --ticks 900 --output build/run.json
python -S -m engine scenario --seed 42 --mission defense --output build/scenario.json
python -S -m engine simulate --scenario build/scenario.json --ticks 900
```

Explicit `--seed`, `--difficulty`, and `--mission` arguments override imported
scenario values. `scenario --input FILE` validates and prints normalized settings;
add `--output FILE` to export them. Errors identify the invalid field. Duplicate
JSON keys, non-finite numbers, excessive nesting and oversized files are rejected.
Scenario files describe initial settings, not the current battle state.

```python
from engine.scenarios import Scenario
from engine.state import state_fingerprint, save_checkpoint

scenario = Scenario(seed=42, mission="defense", player_roster=("Rifleman", "Medic"))
game = scenario.create_game()
print(state_fingerprint(game))
save_checkpoint(game, "build/battle.json")
```

Fingerprints include ordered dictionaries, RNG state, dynamic model fields, pending
actions, projectiles and temporal tactical memoization. They ignore wall-clock
metrics and rebuildable unit/spatial indexes. Querying a fingerprint never changes
the world. Timed LOS, threat and path caches are retained because their expiration
and stored tactical information can affect future decisions. Occupancy is retained
because an incapacitated unit may have deliberately released its occupied tile.

Checkpoint export produces versioned, non-executable JSON with a SHA-256 integrity
digest, simulation source signature, runtime version and scenario metadata. Only
explicit engine model types are encoded. Network sessions and unknown custom
objects are rejected. The digest detects accidental damage; it is not an
authentication mechanism. Restoration is the next tracked update and is not yet
available in this checkpoint.
