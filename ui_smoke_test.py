from pathlib import Path
import gzip
import tempfile
import os

_root=Path(__file__).resolve().parent
_parts=sorted((_root/"src"/"kill_zone_parts_v5").glob("part_*.pyfrag.gz"))
_ext=_root/"src"/"perf_extension_v6.py.gz"
_ui=_root/"src"/"ui_smoke_v6.py.gz"
if not _parts or not _ext.exists() or not _ui.exists():
    raise RuntimeError("Kill Zone v6 UI smoke payload is incomplete")
_base="".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _parts)
_final='\n\nif __name__=="__main__":\n    main()\n'
_game=_base[:-len(_final)]+"\n"+gzip.decompress(_ext.read_bytes()).decode("utf-8")+_final
_test=gzip.decompress(_ui.read_bytes()).decode("utf-8")
with tempfile.TemporaryDirectory(prefix="kill_zone_ui_") as _tmp:
    _tmp=Path(_tmp);(_tmp/"kill_zone.py").write_text(_game,encoding="utf-8")
    _ns={"__name__":"__main__","__file__":str(_tmp/"ui_smoke_test.py")}
    _cwd=os.getcwd();os.chdir(_tmp)
    try:exec(compile(_test,str(_tmp/"ui_smoke_test.py"),"exec"),_ns,_ns)
    finally:os.chdir(_cwd)
