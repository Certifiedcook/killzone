"""Restored worlds must reproduce uninterrupted combat and reject bad content."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from engine.checkpoints import load_checkpoint, restore_checkpoint
from engine.definitions import SIM_DT
from engine.models import BallisticRound, Explosion
from engine.scenarios import Scenario
from engine.state import (
    StateError,
    canonical_json,
    export_checkpoint,
    encode_value,
    save_checkpoint,
    state_fingerprint,
)


def resign(payload):
    unsigned = {key: value for key, value in payload.items() if key != "sha256"}
    payload["sha256"] = hashlib.sha256(canonical_json(unsigned).encode()).hexdigest()
    return payload


def fields_of(encoded):
    return dict(encoded["items"])


class CheckpointTest(unittest.TestCase):
    def test_malformed_tactical_records_fail(self):
        original = export_checkpoint(Scenario().create_game())
        records = (
            ("_threat_grids", {"enemy": [[0.0]]}),
            ("_line_cache", {(0, 0, 2, 2, 0, 0): (True, 0, 0)}),
            (
                "_los_cache",
                {(1, 2, (0, 0), (0, 1), "standing", "standing", 0, 0): "true"},
            ),
            ("_path_cache", {((0, 0), (0, 1), "safe", "player", 0): [(0, 1)]}),
            (
                "intel",
                {"player": {1: {"pos": (0, 0), "role": "Rifleman"}}, "enemy": {}},
            ),
            ("objectives", []),
        )
        for name, value in records:
            payload = copy.deepcopy(original)
            next(pair for pair in payload["state"]["items"] if pair[0] == name)[1] = (
                encode_value(value)
            )
            with self.subTest(field=name), self.assertRaises(StateError):
                restore_checkpoint(resign(payload))

    def test_unknown_runtime_attributes_fail_before_overwriting_save(self):
        game = Scenario().create_game()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            path.write_text("prior save")
            game.units[0].polish_recoul = 1.0
            with self.assertRaisesRegex(StateError, "unregistered model"):
                save_checkpoint(game, path)
            self.assertEqual(path.read_text(), "prior save")
            del game.units[0].polish_recoul
            game.updtae = True
            with self.assertRaisesRegex(StateError, "unregistered game"):
                save_checkpoint(game, path)
            self.assertEqual(path.read_text(), "prior save")

    def test_resumed_combat_matches_uninterrupted_both_missions(self):
        for mission in ("assault", "defense"):
            with self.subTest(mission=mission):
                game = Scenario(
                    seed=31415, mission=mission, difficulty="Veteran"
                ).create_game()
                game.issue_move(
                    game.living("player"),
                    (game.primary_line_x - 3, 18),
                    mode="safe",
                    formation="spread",
                )
                for _ in range(120):
                    game.update(SIM_DT)
                game.rng.gauss(0, 1)
                game.units[0].wound_torso = 1.0
                game.units[0].command_queue.append(("move", (7, 7)))
                game.explosions.append(Explosion(20, 18, 0.25, 2, 20, 30))
                game.ballistic_rounds.append(
                    BallisticRound(
                        game.next_ballistic_round_id,
                        game.units[0].uid,
                        "player",
                        "Service Rifle",
                        6,
                        18,
                        80,
                        0,
                        30,
                        25,
                        1,
                        10,
                    )
                )
                game.next_ballistic_round_id += 1
                restored = restore_checkpoint(
                    json.loads(json.dumps(export_checkpoint(game)))
                )
                self.assertEqual(state_fingerprint(restored), state_fingerprint(game))
                self.assertTrue(
                    all(
                        cell._revision_state is restored._terrain_state
                        for row in restored.grid
                        for cell in row
                    )
                )
                self.assertIs(
                    restored.get_unit(restored.units[0].uid), restored.units[0]
                )
                game.set_cell(15, 18, "door")
                restored.set_cell(15, 18, "door")
                for tick in range(300):
                    game.update(SIM_DT)
                    restored.update(SIM_DT)
                    if tick % 60 == 0:
                        self.assertEqual(
                            state_fingerprint(restored),
                            state_fingerprint(game),
                            f"diverged at {tick}",
                        )
                self.assertEqual(state_fingerprint(restored), state_fingerprint(game))

    def test_released_casualty_occupancy_is_preserved(self):
        game = Scenario().create_game()
        unit = game.units[0]
        game._kz_rebuild_indexes()
        unit.casualty = "incapacitated"
        game.cleanup_unit_state(unit)
        self.assertIsNone(game.unit_at(*unit.tile))
        restored = restore_checkpoint(export_checkpoint(game))
        self.assertIsNone(restored.unit_at(*unit.tile))
        self.assertEqual(restored._occupancy, game._occupancy)
        self.assertEqual(state_fingerprint(restored), state_fingerprint(game))

    def test_file_round_trip_and_world_independence(self):
        game = Scenario().create_game()
        game.paused = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            save_checkpoint(game, path)
            restored = load_checkpoint(path)
        self.assertEqual(state_fingerprint(restored), state_fingerprint(game))
        restored.units[0].hp -= 1
        revision = game.terrain_revision
        restored.set_cell(0, 0, "mud")
        self.assertEqual(game.terrain_revision, revision)
        self.assertNotEqual(restored.units[0].hp, game.units[0].hp)

    def test_version_runtime_signature_and_corruption_fail(self):
        original = export_checkpoint(Scenario().create_game())
        for key, value in (
            ("schema_version", True),
            ("schema_version", 2),
            ("python_runtime", ["cpython", 0, 0]),
            ("engine_signature", "unknown"),
            ("sha256", "bad"),
        ):
            with self.subTest(key=key), self.assertRaises(StateError):
                restore_checkpoint(original | {key: value})

    def test_unknown_tags_attributes_shapes_and_ids_fail_even_with_valid_hash(self):
        original = export_checkpoint(Scenario().create_game())
        for defect in (
            "root_method",
            "unit_method",
            "unknown_type",
            "duplicate_id",
            "bad_grid",
            "duplicate_key",
            "unhashable_key",
            "bad_rng",
            "bad_coordinate",
            "huge_coordinate",
            "fractional_index",
            "dynamic_field_type",
            "bad_notifications",
            "bad_operation_keys",
            "bad_wind",
        ):
            payload = copy.deepcopy(original)
            root = fields_of(payload["state"])
            unit = root["units"][0]["fields"]
            if defect == "root_method":
                payload["state"]["items"].append(["update", 1])
            elif defect == "unit_method":
                unit["items"].append(["__class__", "builtins.object"])
            elif defect == "unknown_type":
                root["units"][0]["$type"] = "os.system"
            elif defect == "duplicate_id":
                second_uid = fields_of(root["units"][1]["fields"])["uid"]
                next(pair for pair in unit["items"] if pair[0] == "uid")[1] = second_uid
            elif defect == "bad_grid":
                root["grid"].pop()
            elif defect == "duplicate_key":
                payload["state"]["items"].append(["time", 0])
            elif defect == "unhashable_key":
                payload["state"]["items"].append([[], 0])
            elif defect == "bad_rng":
                root["rng"]["state"]["items"][1]["items"][-1] = 999
            elif defect == "bad_coordinate":
                next(pair for pair in unit["items"] if pair[0] == "x")[1] = -9
            elif defect == "huge_coordinate":
                next(pair for pair in unit["items"] if pair[0] == "x")[1] = 10**400
            elif defect == "fractional_index":
                next(
                    pair
                    for pair in payload["state"]["items"]
                    if pair[0] == "objective_index"
                )[1] = 0.5
            elif defect == "dynamic_field_type":
                next(pair for pair in unit["items"] if pair[0] == "polish_recoil")[
                    1
                ] = {"$type": "dict", "items": []}
            elif defect == "bad_notifications":
                next(
                    pair
                    for pair in payload["state"]["items"]
                    if pair[0] == "notifications"
                )[1] = [0]
            elif defect == "bad_operation_keys":
                root["operation_config"]["items"].append([42, 1])
            elif defect == "bad_wind":
                root["wind"]["items"].pop()
            with self.subTest(defect=defect), self.assertRaises(StateError):
                restore_checkpoint(resign(payload))


if __name__ == "__main__":
    unittest.main()
