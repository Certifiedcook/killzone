from pathlib import Path
import gzip

_root=Path(__file__).resolve().parent
_parts=sorted((_root/"src"/"kill_zone_parts_v5").glob("part_*.pyfrag.gz"))
_ext=_root/"src"/"perf_extension_v6.py.gz"
if not _parts or not _ext.exists():
    raise RuntimeError("Kill Zone source or performance extension is missing")
_base="".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in _parts)
_final='\n\nif __name__=="__main__":\n    main()\n'
if not _base.endswith(_final):
    raise RuntimeError("Unexpected Kill Zone v5 source layout")
_source=_base[:-len(_final)]+"\n"+gzip.decompress(_ext.read_bytes()).decode("utf-8")+_final
exec(compile(_source,str(_root/"kill_zone_monolithic.py"),"exec"),globals(),globals())
