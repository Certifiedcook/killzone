"""Shared, deterministic helpers for generated distribution directories."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def recreate_generated_directory(output: Path, marker_name: str, marker_text: str) -> None:
    """Recreate *output* only when it is empty or carries our exact marker."""
    if output.exists() and any(output.iterdir()):
        marker = output / marker_name
        if not marker.is_file():
            raise RuntimeError(f"Refusing to replace unmarked non-empty directory: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / marker_name).write_text(marker_text, encoding="utf-8")


def write_zip(source: Path, destination: Path, *, include_root: bool) -> None:
    """Write a stable ZIP while excluding interpreter cache files."""
    archive_root = source.parent if include_root else source
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            archive.write(path, path.relative_to(archive_root))
