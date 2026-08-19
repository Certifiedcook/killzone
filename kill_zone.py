from pathlib import Path

from src.source_loader import game_source

_root = Path(__file__).resolve().parent
_source = game_source(_root)
exec(compile(_source, str(_root / "kill_zone_monolithic.py"), "exec"), globals(), globals())
