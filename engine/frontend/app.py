"""Frontend / app for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from engine.frontend.application import ApplicationSystem
from engine.frontend.audio import AudioSystem
from engine.frontend.controls import ControlsSystem
from engine.frontend.rendering import RenderingSystem


class KillZoneApp(ApplicationSystem, AudioSystem, ControlsSystem, RenderingSystem):
    """Static composition of the engine systems; methods are never patched at import time."""
