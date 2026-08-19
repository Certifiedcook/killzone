from pathlib import Path
import gzip
import tempfile

_root=Path(__file__).resolve().parent
_parts=sorted((_root/"src"/"kill_zone_parts_v5").glob("part_*.pyfrag.gz"))
_ext=_root/"src"/"perf_extension_v6.py.gz"
_tests=_root/"src"/"self_test_v6.py.gz"
if not _parts or not _ext.exists() or not _tests.exists():
    raise RuntimeError("Kill Zone v6 test payload is incomplete")
_base="".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _parts)
_final='\n\nif __name__=="__main__":\n    main()\n'
_game=_base[:-len(_final)]+"\n"+gzip.decompress(_ext.read_bytes()).decode("utf-8")+_final
_test=gzip.decompress(_tests.read_bytes()).decode("utf-8")
with tempfile.TemporaryDirectory(prefix="kill_zone_tests_") as _tmp:
    _tmp=Path(_tmp);(_tmp/"kill_zone.py").write_text(_game,encoding="utf-8")
    _ns={"__name__":"__main__","__file__":str(_tmp/"self_test.py")}
    exec(compile(_test,str(_tmp/"self_test.py"),"exec"),_ns,_ns)
