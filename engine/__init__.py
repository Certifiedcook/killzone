"""Kill Zone's headless simulation and reusable scheduling/query primitives."""
from engine.clock import FixedStepClock
from engine.spatial import SpatialGrid

__all__ = ["RealTimeGame", "FixedStepClock", "SpatialGrid"]


def __getattr__(name):
    if name == "RealTimeGame":
        from engine.simulation import RealTimeGame
        return RealTimeGame
    raise AttributeError(name)
