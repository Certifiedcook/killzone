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
from engine.checkpoints import load_checkpoint

scenario = Scenario(seed=42, mission="defense", player_roster=("Rifleman", "Medic"))
game = scenario.create_game()
print(state_fingerprint(game))
save_checkpoint(game, "build/battle.json")
restored = load_checkpoint("build/battle.json")
assert state_fingerprint(restored) == state_fingerprint(game)
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
authentication mechanism. Restoration validates the format, signature, runtime,
model types, registered attributes, collections, coordinates and IDs before
creating a new world. Invalid content never replaces an existing game. Python's
implementation and major/minor version must match the saved battle. Saves from
different simulation source are rejected explicitly; migrations are not inferred.

Register new serialized game and Unit fields in `engine/state_fields.py` and add
their value validation when extending the engine. Unknown attributes are rejected
at export, so a typo cannot create a checkpoint that silently loses state.
