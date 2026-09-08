"""Regressions for benchmark sampling, terminal battles, and JSON output."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_minimum_tick_run_keeps_measurements(self):
        # Previously --ticks 60 passed validation, then max([]) crashed.
        result = benchmark.run_benchmark(ticks=60)
        self.assertEqual(result["executed_ticks"], 60)
        self.assertGreater(result["measured_ticks"], 0)
        self.assertEqual(result["warmup_ticks"] + result["measured_ticks"], 60)
        self.assertGreater(result["update"]["mean_ms"], 0)

    def test_invalid_warmup_fails_before_creating_game(self):
        with patch.object(benchmark.kz, "RealTimeGame") as create:
            for warmup in (-1, 60, 90):
                with self.subTest(warmup=warmup), self.assertRaises(ValueError):
                    benchmark.run_benchmark(ticks=60, warmup=warmup)
            create.assert_not_called()

    def test_sampling_excludes_warmup_and_terminal_noops(self):
        class FakeGame:
            def __init__(self):
                self.victory = self.defeat = False
                self.time = 0.0
                self.primary_line_x = 30
                self.tick = 0
                self._perf = {}

            def living(self, faction):
                return [SimpleNamespace(combat_effective=True)]

            def issue_move(self, *args, **kwargs):
                pass

            def update(self, dt):
                self.tick += 1
                self.time += dt
                self.victory = self.tick == 4
                self._perf = {
                    "path_ms": self.tick,
                    "paths": 1,
                    "ai_ms": 0,
                    "ai_decisions": 0,
                }

        game = FakeGame()
        # Two intentionally slow warmup updates, then 1 and 3 ms measured.
        clock = [0, 1, 2, 3, 4, 4.001, 5, 5.003]
        with (
            patch.object(benchmark.kz, "RealTimeGame", return_value=game) as create,
            patch.object(benchmark.time, "perf_counter", side_effect=clock),
        ):
            result = benchmark.run_benchmark(ticks=60, warmup=2, seed=912)
        self.assertEqual(create.call_args.kwargs["seed"], 912)
        self.assertEqual(result["executed_ticks"], 4)
        self.assertEqual(result["measured_ticks"], 2)
        self.assertEqual(result["battle_result"], "victory")
        self.assertAlmostEqual(result["update"]["mean_ms"], 2)
        self.assertAlmostEqual(result["update"]["max_ms"], 3)
        self.assertEqual(result["path"]["mean_ms"], 3.5)

    def test_json_stdout_is_parseable_without_status_text(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = benchmark.main(
                ["--ticks", "60", "--warmup", "0", "--seed", "7", "--json"]
            )
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertEqual(result["seed"], 7)
        self.assertEqual(result["measured_ticks"], 60)

    def test_json_file_matches_returned_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                result = benchmark.main(["--ticks", "60", "--json", str(path)])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
