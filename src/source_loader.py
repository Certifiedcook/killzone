"""Reconstruct the runnable Kill Zone sources from the checked-in payloads.

The historical game and test payloads are compressed to keep the repository
compact.  New maintenance code stays as normal, reviewable Python and is
appended before the application entry point.
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
    parts = sorted((root / "src" / "kill_zone_parts_v5").glob("part_*.pyfrag.gz"))
    if not parts:
        raise RuntimeError("Kill Zone source fragments are missing")

    base = "".join(_read_gzip(part) for part in parts)
    if not base.endswith(ENTRY_POINT):
        raise RuntimeError("Unexpected Kill Zone v5 source layout")

    extensions = [
        _read_gzip(root / "src" / "perf_extension_v6.py.gz"),
        (root / "src" / "maintenance_extension.py").read_text(encoding="utf-8"),
    ]
    return base[: -len(ENTRY_POINT)] + "\n" + "\n".join(extensions) + ENTRY_POINT


def test_source(root: Path, name: str) -> str:
    """Return a decompressed historical test payload by filename."""
    return _read_gzip(root / "src" / name)
