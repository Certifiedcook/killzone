"""Deterministic point queries over an explicit snapshot of moving objects."""

from math import floor, hypot, isfinite


def _finite(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class SpatialGrid:
    """Uniform grid returning original objects in their rebuild insertion order.

    Objects must expose finite x/y coordinates. Queries include their boundaries
    and use coordinates captured by rebuild(), including after an object moves.
    Duplicate input objects remain duplicate results. A failed rebuild leaves
    the previous snapshot intact.
    """

    def __init__(self, cell_size=4.0):
        self._cell_size = _finite(cell_size, "cell_size")
        if self._cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self._entries = []
        self._cells = {}

    @property
    def cell_size(self):
        return self._cell_size

    def __len__(self):
        return len(self._entries)

    def _cell(self, coordinate):
        scaled = coordinate / self._cell_size
        if isfinite(scaled):
            return floor(scaled)
        # Finite coordinates and very small cells can overflow float division.
        numerator, denominator = coordinate.as_integer_ratio()
        size_numerator, size_denominator = self._cell_size.as_integer_ratio()
        return (numerator * size_denominator) // (denominator * size_numerator)

    def rebuild(self, items):
        entries, cells = [], {}
        for index, item in enumerate(items):
            x, y = _finite(item.x, "item.x"), _finite(item.y, "item.y")
            entry = (index, item, x, y)
            entries.append(entry)
            cells.setdefault((self._cell(x), self._cell(y)), []).append(entry)
        self._entries, self._cells = entries, cells

    def _candidates(self, min_x, min_y, max_x, max_y):
        if not self._entries:
            return []
        if not all(isfinite(v) for v in (min_x, min_y, max_x, max_y)):
            # Radius bounds can overflow even though the query itself is finite.
            return self._entries
        left, bottom = self._cell(min_x), self._cell(min_y)
        right, top = self._cell(max_x), self._cell(max_y)
        candidates = []
        if (right - left + 1) * (top - bottom + 1) <= len(self._cells):
            for cy in range(bottom, top + 1):
                for cx in range(left, right + 1):
                    candidates.extend(self._cells.get((cx, cy), ()))
        else:
            # A large sparse query must not enumerate billions of empty cells.
            for (cx, cy), entries in self._cells.items():
                if left <= cx <= right and bottom <= cy <= top:
                    candidates.extend(entries)
        candidates.sort(key=lambda entry: entry[0])
        return candidates

    def query_aabb(self, min_x, min_y, max_x, max_y):
        min_x, min_y = _finite(min_x, "min_x"), _finite(min_y, "min_y")
        max_x, max_y = _finite(max_x, "max_x"), _finite(max_y, "max_y")
        if min_x > max_x or min_y > max_y:
            raise ValueError("minimum bounds must not exceed maximum bounds")
        return [
            item
            for _, item, x, y in self._candidates(min_x, min_y, max_x, max_y)
            if min_x <= x <= max_x and min_y <= y <= max_y
        ]

    def query_radius(self, x, y, radius):
        x, y, radius = _finite(x, "x"), _finite(y, "y"), _finite(radius, "radius")
        if radius < 0:
            raise ValueError("radius must be nonnegative")
        return [
            item
            for _, item, px, py in self._candidates(
                x - radius, y - radius, x + radius, y + radius
            )
            if hypot(px - x, py - y) <= radius
        ]
