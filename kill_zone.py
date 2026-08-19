from pathlib import Path
import gzip

# Exact game source is stored as ordered gzip fragments because the connected
# GitHub transport is much more reliable with small binary blobs.
_root = Path(__file__).resolve().parent
_parts = sorted((_root / "src" / "kill_zone_parts_v4").glob("part_*.pyfrag.gz"))
if not _parts:
    raise RuntimeError("Kill Zone source fragments are missing")
_source = "".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _parts)

# ESC hotfix: Escape may navigate back to the main menu, but Escape on the main
# menu itself is a no-op. Exiting from the menu requires clicking the Quit button.
_old = '            elif e.key==pygame.K_ESCAPE:\n                self.running=False\n'
_new = '            elif e.key==pygame.K_ESCAPE:\n                return  # main-menu Escape is intentionally a no-op; use the Quit button\n'
_source = _source.replace(_old, _new, 1)

exec(compile(_source, str(_root / "kill_zone_monolithic.py"), "exec"), globals(), globals())
