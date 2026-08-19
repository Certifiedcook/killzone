from pathlib import Path
import gzip

# Exact game source is stored as ordered gzip fragments because the connected
# GitHub transport is much more reliable with small binary blobs.
_root = Path(__file__).resolve().parent
_parts = sorted((_root / "src" / "kill_zone_parts_v4").glob("part_*.pyfrag.gz"))
if not _parts:
    raise RuntimeError("Kill Zone source fragments are missing")
_source = "".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _parts)
exec(compile(_source, str(_root / "kill_zone_monolithic.py"), "exec"), globals(), globals())
