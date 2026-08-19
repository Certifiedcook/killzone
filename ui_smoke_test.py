from pathlib import Path
import tempfile
import os

from src.source_loader import game_source, test_source

os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

_root=Path(__file__).resolve().parent
_game = game_source(_root)
_test = test_source(_root, "ui_smoke_v6.py.gz")
with tempfile.TemporaryDirectory(prefix="kill_zone_ui_") as _tmp:
    _tmp=Path(_tmp);(_tmp/"kill_zone.py").write_text(_game,encoding="utf-8")
    _ns={"__name__":"__main__","__file__":str(_tmp/"ui_smoke_test.py")}
    _cwd=os.getcwd();os.chdir(_tmp)
    try:exec(compile(_test,str(_tmp/"ui_smoke_test.py"),"exec"),_ns,_ns)
    finally:os.chdir(_cwd)
