"""Reconstruct the runnable Kill Zone sources from the checked-in payloads.

Each historical game or test payload is one deterministic gzip archive.
Current feature code stays as normal, reviewable Python and is appended before
the application entry point.
"""

from __future__ import annotations

import gzip
from pathlib import Path

ENTRY_POINT = '\n\nif __name__=="__main__":\n    main()\n'


def _read_gzip(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"Required Kill Zone payload is missing: {path}")
    try:
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Invalid Kill Zone payload: {path}") from exc


def game_source(root: Path) -> str:
    """Return the complete runnable game source for *root*."""
    base = _read_gzip(root / "src" / "legacy_game.py.gz")
    if not base.endswith(ENTRY_POINT):
        raise RuntimeError("Unexpected legacy Kill Zone source layout")

    extensions = [
        _read_gzip(root / "src" / "legacy_performance.py.gz"),
        (root / "src" / "maintenance_extension.py").read_text(encoding="utf-8"),
        (root / "src" / "multiplayer_extension.py").read_text(encoding="utf-8"),
        (root / "src" / "presentation_extension.py").read_text(encoding="utf-8"),
        (root / "src" / "combat2_extension.py").read_text(encoding="utf-8"),
        (root / "src" / "combat_polish_extension.py").read_text(encoding="utf-8"),
    ]
    return base[: -len(ENTRY_POINT)] + "\n" + "\n".join(extensions) + ENTRY_POINT


def test_source(root: Path, name: str) -> str:
    """Return a decompressed historical test payload by filename."""
    return _read_gzip(root / "src" / name)
