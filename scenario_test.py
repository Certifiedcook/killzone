"""Scenario content must fail clearly before constructing a world."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from engine.content import load_json
from engine.scenarios import Scenario, ScenarioError
from engine.simulation import RealTimeGame


class ScenarioTest(unittest.TestCase):
    def test_invalid_size_limit_never_opens_file(self):
        for limit in (-2, -1, 0, True, 1.5):
            with self.subTest(limit=limit), patch.object(Path, "open") as source:
                with self.assertRaisesRegex(ValueError, "max_bytes"):
                    load_json("unused.json", max_bytes=limit)
                source.assert_not_called()

    def test_strict_json_file_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "content.json"
            for content in (
                '{"seed":NaN}',
                '{"seed":1e999}',
                '{"seed":1,"seed":2}',
                "[" * 2000 + "]" * 2000,
            ):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_json(path)
            path.write_text('"123456789"')
            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_json(path, max_bytes=5)

    def test_round_trip_and_constructor_equivalence(self):
        scenario = Scenario(
            seed=57,
            player_roster=["Rifleman", "Medic"],
            mission="defense",
            weather="rain",
            variant="hill_line",
            reserve_count=2,
        )
        restored = Scenario.from_dict(scenario.to_dict())
        self.assertEqual(restored, scenario)
        first = scenario.create_game()
        second = RealTimeGame(
            seed=57,
            player_roster=["Rifleman", "Medic"],
            reserve_count=2,
            operation_config=scenario.operation_config,
        )
        self.assertEqual(first.rng.getstate(), second.rng.getstate())
        self.assertEqual(first.units, second.units)
        self.assertEqual(first.grid, second.grid)
        self.assertEqual(Scenario.from_game(first), scenario)

    def test_field_errors(self):
        for changes, field in (
            ({"schema_version": True}, "schema_version"),
            ({"schema_version": 99}, "schema_version"),
            ({"seed": False}, "seed"),
            ({"seed": 2.5}, "seed"),
            ({"difficulty": []}, "difficulty"),
            ({"typo": 1}, "typo"),
            ({"reserve_count": -1}, "reserve_count"),
            ({"player_roster": []}, "player_roster"),
            ({"player_roster": ["wizard"]}, "player_roster[0]"),
            ({"operation": {"mission": "typo"}}, "operation.mission"),
            (
                {"operation": {"enemy_strength": float("nan")}},
                "operation.enemy_strength",
            ),
            ({"operation": {"weather": "snow"}}, "operation.weather"),
            ({"operation": {"duration": 4}}, "operation.duration"),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(ScenarioError) as error,
            ):
                Scenario.from_dict(Scenario().to_dict() | changes)
            self.assertEqual(error.exception.field, "scenario." + field)

    def test_roster_is_immutable_and_independent(self):
        roles = ["Medic"]
        scenario = Scenario(player_roster=roles)
        roles.append("Rifleman")
        exported = scenario.to_dict()
        exported["player_roster"].append("Engineer")
        exported["operation"]["weather"] = "rain"
        self.assertEqual(scenario.player_roster, ("Medic",))
        self.assertEqual(scenario.weather, "auto")


if __name__ == "__main__":
    unittest.main()
