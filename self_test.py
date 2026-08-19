from pathlib import Path
import tempfile

from src.source_loader import game_source, test_source

_root=Path(__file__).resolve().parent
_game = game_source(_root)
_test = test_source(_root, "self_test_v6.py.gz")
with tempfile.TemporaryDirectory(prefix="kill_zone_tests_") as _tmp:
    _tmp=Path(_tmp);(_tmp/"kill_zone.py").write_text(_game,encoding="utf-8")
    _ns={"__name__":"__main__","__file__":str(_tmp/"self_test.py")}
    exec(compile(_test,str(_tmp/"self_test.py"),"exec"),_ns,_ns)
