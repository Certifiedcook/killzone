"""Development entry point for the assembled Kill Zone runtime."""

from pathlib import Path

from src.source_loader import game_source

ROOT = Path(__file__).resolve().parent
SOURCE = game_source(ROOT)
exec(  # noqa: S102 - checked-in runtime payload, not external input
    compile(SOURCE, str(ROOT / "kill_zone_runtime.py"), "exec"),
    globals(),
    globals(),
)
