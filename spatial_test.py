"""Dependency-free grid checks against deterministic brute-force queries."""

import math
import random
from types import SimpleNamespace

from engine.spatial import SpatialGrid


def point(x, y):
    return SimpleNamespace(x=x, y=y)


def same_objects(actual, expected):
    assert len(actual) == len(expected)
    assert all(a is b for a, b in zip(actual, expected))


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid input was accepted")


def test_seeded_queries_match_brute_force():
    rng = random.Random(2137)
    points = [point(rng.uniform(-90, 90), rng.uniform(-90, 90)) for _ in range(500)]
    for size in (0.25, 1, 4, 19.5):
        grid = SpatialGrid(size)
        grid.rebuild(points)
        for _ in range(100):
            x, y, radius = (
                rng.uniform(-100, 100),
                rng.uniform(-100, 100),
                rng.uniform(0, 40),
            )
            same_objects(
                grid.query_radius(x, y, radius),
                [p for p in points if math.hypot(p.x - x, p.y - y) <= radius],
            )
            width, height = rng.uniform(0, 40), rng.uniform(0, 40)
            same_objects(
                grid.query_aabb(x, y, x + width, y + height),
                [p for p in points if x <= p.x <= x + width and y <= p.y <= y + height],
            )


def test_inclusive_boundaries_negative_cells_and_order():
    points = [
        point(4, 0),
        point(-4, 0),
        point(0, 4),
        point(0, -4),
        point(0, 0),
        point(-0.001, -0.001),
        point(4.001, 0),
        point(4, 4),
    ]
    grid = SpatialGrid(4)
    grid.rebuild(points)
    same_objects(grid.query_radius(0, 0, 4), points[:6])
    same_objects(grid.query_aabb(-4, -4, 4, 4), points[:6] + points[7:])
    same_objects(grid.query_aabb(-0.001, -0.001, -0.001, -0.001), [points[5]])
    same_objects(grid.query_radius(0, 0, 0), [points[4]])
    # Populate enough distant cells to exercise the small-cell enumeration path.
    grid.rebuild(points + [point(i * 40, 400) for i in range(30)])
    same_objects(grid.query_radius(0, 0, 4), points[:6])


def test_rebuild_snapshot_duplicates_and_atomic_failure():
    a, b = point(0, 0), point(10, 10)
    grid = SpatialGrid()
    assert len(grid) == 0 and grid.query_radius(0, 0, 100) == []
    grid.rebuild(iter([b, a, a]))
    a.x = a.y = 20
    same_objects(grid.query_radius(0, 0, 0), [a, a])
    same_objects(grid.query_aabb(-100, -100, 100, 100), [b, a, a])
    rejects(lambda: grid.rebuild([a, point(float("nan"), 0)]))
    same_objects(grid.query_radius(0, 0, 0), [a, a])
    grid.rebuild([a, b])
    assert len(grid) == 2 and grid.query_radius(0, 0, 0) == []
    same_objects(grid.query_radius(20, 20, 0), [a])
    grid.rebuild([])
    assert len(grid) == 0 and grid.query_aabb(-100, -100, 100, 100) == []


def test_invalid_queries_and_cell_sizes():
    for size in (0, -1, float("nan"), float("inf"), -float("inf"), None):
        rejects(lambda: SpatialGrid(size))
    grid = SpatialGrid()
    for bad in (float("nan"), float("inf"), -float("inf"), None):
        for index in range(3):
            args = [0, 0, 1]
            args[index] = bad
            rejects(lambda: grid.query_radius(*args))
        for index in range(4):
            args = [0, 0, 1, 1]
            args[index] = bad
            rejects(lambda: grid.query_aabb(*args))
    rejects(lambda: grid.query_radius(0, 0, -1))
    rejects(lambda: grid.query_aabb(1, 0, 0, 1))
    rejects(lambda: grid.query_aabb(0, 1, 1, 0))


def test_extreme_finite_sparse_queries_do_not_enumerate_empty_space():
    points = [point(0, 0), point(1e308, 0), point(-1e308, 0)]
    grid = SpatialGrid(1e-308)
    grid.rebuild(points)
    same_objects(grid.query_aabb(-1e308, -1e308, 1e308, 1e308), points)
    same_objects(grid.query_radius(1e308, 0, 1e308), points[:2])
    same_objects(grid.query_radius(-1e308, 0, 0), [points[2]])


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
    print(f"ALL {len(TESTS)} SPATIAL REGRESSIONS PASSED")
