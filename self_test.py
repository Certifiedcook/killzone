from pathlib import Path
import gzip
import tempfile

_root = Path(__file__).resolve().parent
_test_parts = sorted((_root / "src" / "test_parts_v4").glob("part_*.gzpart"))
_game_parts = sorted((_root / "src" / "kill_zone_parts_v4").glob("part_*.pyfrag.gz"))
if not _test_parts or not _game_parts:
    raise RuntimeError("Kill Zone test or game source fragments are missing")
_test_source = gzip.decompress(b"".join(p.read_bytes() for p in _test_parts)).decode("utf-8")
_game_source = "".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _game_parts)
with tempfile.TemporaryDirectory(prefix="kill_zone_tests_") as _tmp:
    _tmp = Path(_tmp)
    (_tmp / "kill_zone.py").write_text(_game_source, encoding="utf-8")
    _ns = {"__name__": "__main__", "__file__": str(_tmp / "self_test.py")}
    exec(compile(_test_source, str(_tmp / "self_test.py"), "exec"), _ns, _ns)
