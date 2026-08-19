from pathlib import Path
import gzip

_root = Path(__file__).resolve().parent
_payload = _root / "src" / "ui_smoke_v4.py.gz"
if not _payload.exists():
    raise RuntimeError("Kill Zone UI smoke test payload is missing")
_source = gzip.decompress(_payload.read_bytes()).decode("utf-8")
exec(compile(_source, str(_root / "ui_smoke_monolithic.py"), "exec"), globals(), globals())
