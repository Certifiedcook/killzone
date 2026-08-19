"""Run the dependency-free historical frontend smoke suite."""

import os
import tempfile
from pathlib import Path

from src.source_loader import game_source, test_source

os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")



def main() -> None:
    root = Path(__file__).resolve().parent
    game = game_source(root)
    test = test_source(root, "legacy_ui_smoke_test.py.gz")
    with tempfile.TemporaryDirectory(prefix="kill_zone_ui_") as temporary:
        temporary_path = Path(temporary)
        (temporary_path / "kill_zone.py").write_text(game, encoding="utf-8")
        test_path = temporary_path / "ui_smoke_test.py"
        namespace = {"__name__": "__main__", "__file__": str(test_path)}
        previous_working_directory = Path.cwd()
        os.chdir(temporary_path)
        try:
            exec(  # noqa: S102 - checked-in test payload, not external input
                compile(test, str(test_path), "exec"),
                namespace,
                namespace,
            )
        finally:
            os.chdir(previous_working_directory)


if __name__ == "__main__":
    main()
