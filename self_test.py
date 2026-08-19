"""Run the compact historical deterministic model suite."""

import tempfile
from pathlib import Path

from src.source_loader import game_source, test_source


def main() -> None:
    root = Path(__file__).resolve().parent
    game = game_source(root)
    test = test_source(root, "legacy_self_test.py.gz")
    with tempfile.TemporaryDirectory(prefix="kill_zone_tests_") as temporary:
        temporary_path = Path(temporary)
        (temporary_path / "kill_zone.py").write_text(game, encoding="utf-8")
        test_path = temporary_path / "self_test.py"
        namespace = {"__name__": "__main__", "__file__": str(test_path)}
        exec(  # noqa: S102 - checked-in test payload, not external input
            compile(test, str(test_path), "exec"),
            namespace,
            namespace,
        )


if __name__ == "__main__":
    main()
