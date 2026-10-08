"""Testler icin izole calisma ortami. Her test modulunun EN ILK import'u olmali.

``MarketingApp.paths`` workspace/config dizinlerini import aninda bir kere hesaplar; bu
yuzden ortam degiskenleri MarketingApp'tan HERHANGI BIR sey import edilmeden once
ayarlanmalidir. Aksi halde testler kullanicinin gercek workspace'ine (ajan/tool
konfigurasyonu, telemetri veritabani) yazardi.

Neden ``tests`` paketi degil de duz modul: venv'deki bir bagimlilik site-packages'a
``tests`` adinda bir paket kuruyor ve ``tests.*`` importlarini golgeliyor. Bu yuzden
``python -m unittest discover -s tests`` kullanilir ve bu dosya ``import _env`` ile alinir.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

if "ETHGENT_TEST_ROOT" not in os.environ:
    _root = Path(tempfile.mkdtemp(prefix="ethgent-tests-"))
    (_root / "config").mkdir()
    (_root / "workspace").mkdir()
    os.environ["ETHGENT_TEST_ROOT"] = str(_root)
    os.environ["ETHGENT_CONFIG_DIR"] = str(_root / "config")
    os.environ["ETHGENT_WORKSPACE_DIR"] = str(_root / "workspace")
    atexit.register(shutil.rmtree, _root, ignore_errors=True)

ROOT = Path(os.environ["ETHGENT_TEST_ROOT"])
CONFIG_DIR = Path(os.environ["ETHGENT_CONFIG_DIR"])
WORKSPACE_DIR = Path(os.environ["ETHGENT_WORKSPACE_DIR"])

_paths = sys.modules.get("MarketingApp.paths")
if _paths is not None and Path(_paths.WORKSPACE_DIR).resolve() != WORKSPACE_DIR.resolve():
    raise RuntimeError(
        "MarketingApp, test ortami ayarlanmadan once import edilmis: testler gercek workspace'e "
        "yazabilirdi. Test modulunde `import _env` satiri diger importlardan once gelmeli."
    )
