"""Executable contracts for the engine command-line interface."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from engine.cli import simulate

ROOT = Path(__file__).resolve().parent


class EngineCLITest(unittest.TestCase):
    def test_scenario_export_import_and_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scenario.json"
            export = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "engine",
                    "scenario",
                    "--mission",
                    "defense",
                    "--seed",
                    "77",
                    "--output",
                    str(path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=15,
            )
            self.assertEqual(json.loads(export.stdout), json.loads(path.read_text()))
            run = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "engine",
                    "simulate",
                    "--scenario",
                    str(path),
                    "--ticks",
                    "30",
                    "--seed",
                    "78",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=15,
            )
            report = json.loads(run.stdout)
            self.assertEqual(report["mission"], "defense")
            self.assertEqual(report["seed"], 78)
            path.write_text('{"schema_version": 1, "seed": 2, "seed": 3}')
            failed = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "engine",
                    "simulate",
                    "--scenario",
                    str(path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("duplicate JSON field", failed.stderr)

    def test_headless_command_works_without_site_packages(self):
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-m",
                "engine",
                "simulate",
                "--ticks",
                "60",
                "--seed",
                "2026",
                "--mission",
                "defense",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["mission"], "defense")
        self.assertEqual(report["seed"], 2026)
        self.assertEqual(report["ticks_completed"], 60)
        self.assertAlmostEqual(report["simulated_seconds"], 2.0)

    def test_json_file_matches_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reports" / "run.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "engine",
                    "simulate",
                    "--ticks",
                    "1",
                    "--output",
                    str(path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=15,
            )
            self.assertEqual(
                json.loads(result.stdout), json.loads(path.read_text(encoding="utf-8"))
            )

    def test_seeded_results_match(self):
        first, second = simulate(ticks=90, seed=116), simulate(ticks=90, seed=116)
        for key in ("wall_seconds", "mean_update_ms"):
            first.pop(key)
            second.pop(key)
        self.assertEqual(first, second)

    def test_invalid_cli_inputs_fail(self):
        for option, value in (
            ("--ticks", "0"),
            ("--ticks", "-1"),
            ("--ticks", "abc"),
            ("--mission", "typo"),
        ):
            result = subprocess.run(
                [sys.executable, "-m", "engine", "simulate", option, value],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("error:", result.stderr)


if __name__ == "__main__":
    unittest.main()
