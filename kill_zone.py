from pathlib import Path

# The GitHub connector used for this project only supports UTF-8 text writes and
# cannot stream the 116 KB source file in one local-file upload. The authoritative
# source is therefore stored in ordered, readable fragments. They are concatenated
# byte-for-byte here and executed as one module.
_root = Path(__file__).resolve().parent
_parts = sorted((_root / "src" / "kill_zone_parts").glob("part_*.pyfrag"))
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_root / "kill_zone_monolithic.py"), "exec"), globals(), globals())
