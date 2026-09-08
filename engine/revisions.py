"""Per-world terrain invalidation, shared only by cells of that world."""

from dataclasses import dataclass


@dataclass(slots=True)
class TerrainRevision:
    value: int = 0
