"""Deterministic fingerprints and portable battle-state contracts."""

import unittest
import json
import tempfile
from pathlib import Path
from engine.definitions import SIM_DT
from engine.models import BallisticRound
from engine.revisions import TerrainRevision
from engine.scenarios import Scenario
from engine.state import (
    StateError,
    capture_state,
    encode_value,
    state_fingerprint,
    export_checkpoint,
    save_checkpoint,
)


class StateTest(unittest.TestCase):
    def test_invalid_terrain_revision_is_rejected_at_capture(self):
        for revision in (float("nan"), float("inf"), -1, True, 1.5):
            with (
                self.subTest(revision=revision),
                self.assertRaisesRegex(StateError, "terrain revision"),
            ):
                encode_value(TerrainRevision(revision))

    def test_checkpoint_export_is_complete_versioned_json(self):
        game = Scenario(seed=912).create_game()
        for _ in range(60):
            game.update(SIM_DT)
        game.units[0].wound_torso = 7.0
        checkpoint = export_checkpoint(game)
        self.assertEqual(
            json.loads(json.dumps(checkpoint, allow_nan=False)), checkpoint
        )
        self.assertEqual(checkpoint["format"], "killzone-battle")
        self.assertEqual(checkpoint["schema_version"], 1)
        self.assertEqual(checkpoint["state"], capture_state(game))
        fields = dict(checkpoint["state"]["items"])
        for name in ("_occupancy", "_los_cache", "_path_cache", "rng"):
            self.assertIn(name, fields)
        for name in ("_uid_index", "_ballistic_spatial", "_perf"):
            self.assertNotIn(name, fields)
        self.assertEqual(len(checkpoint["sha256"]), 64)
        game.units[0].wound_torso += 1
        self.assertNotEqual(export_checkpoint(game)["sha256"], checkpoint["sha256"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save" / "battle.json"
            save_checkpoint(game, path)
            self.assertEqual(json.loads(path.read_text()), export_checkpoint(game))

    def test_identical_runs_have_identical_fingerprints(self):
        for mission in ("assault", "defense"):
            with self.subTest(mission=mission):
                first = Scenario(seed=707, mission=mission).create_game()
                second = Scenario(seed=707, mission=mission).create_game()
                for _ in range(120):
                    first.update(SIM_DT)
                    second.update(SIM_DT)
                self.assertEqual(state_fingerprint(first), state_fingerprint(second))

    def test_primary_and_temporal_state_changes_are_detected(self):
        game = Scenario().create_game()
        mutations = (
            lambda: game.rng.random(),
            lambda: game.grid[0][0].reset_terrain("mud"),
            lambda: game.units[0].command_queue.append(("move", (8, 8))),
            lambda: game._los_cache.update({("test",): (game.time, True)}),
            lambda: setattr(game.units[0], "wound_torso", 3.0),
            lambda: game.ballistic_rounds.append(
                BallisticRound(
                    1, 1, "player", "Service Rifle", 3, 4, 10, 0, 20, 30, 1, 5
                )
            ),
        )
        for mutate in mutations:
            before = state_fingerprint(game)
            mutate()
            self.assertNotEqual(state_fingerprint(game), before)

    def test_capture_is_read_only_and_ignores_metrics(self):
        game = Scenario().create_game()
        before = state_fingerprint(game)
        rng = game.rng.getstate()
        game._perf["sim_ms"] = 999
        game.profile_enabled = True
        game._uid_index.clear()
        self.assertEqual(state_fingerprint(game), before)
        self.assertEqual(game.rng.getstate(), rng)
        self.assertEqual(game._uid_index, {})
        self.assertEqual(capture_state(game), capture_state(game))

    def test_unsafe_or_unsupported_values_are_rejected(self):
        recursive = []
        recursive.append(recursive)
        for value in (float("inf"), float("nan"), object(), lambda: None, recursive):
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaises(StateError),
            ):
                encode_value(value)

    def test_sets_are_canonical_but_dictionary_iteration_is_preserved(self):
        self.assertEqual(encode_value({1, 2, 3}), encode_value({3, 2, 1}))
        self.assertNotEqual(
            encode_value({"a": 1, "b": 2}), encode_value({"b": 2, "a": 1})
        )


if __name__ == "__main__":
    unittest.main()
