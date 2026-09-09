"""Simulation for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from engine.systems.combat import CombatSystem
from engine.systems.lifecycle import LifecycleSystem
from engine.systems.movement import MovementSystem
from engine.systems.operations import OperationsSystem
from engine.systems.tactics import TacticsSystem
from engine.systems.world import WorldSystem


class RealTimeGame(
    CombatSystem,
    LifecycleSystem,
    MovementSystem,
    OperationsSystem,
    TacticsSystem,
    WorldSystem,
):
    """Static composition of the engine systems; methods are never patched at import time."""
