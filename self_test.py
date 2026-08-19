from pathlib import Path
import gzip

_root = Path(__file__).resolve().parent
_parts = sorted((_root / "src" / "test_parts_v4").glob("part_*.gzpart"))
if not _parts:
    raise RuntimeError("Kill Zone test fragments are missing")
_source = gzip.decompress(b"".join(p.read_bytes() for p in _parts)).decode("utf-8")
exec(compile(_source, str(_root / "self_test_monolithic.py"), "exec"), globals(), globals())
