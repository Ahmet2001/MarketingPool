"""Merkezi yol cozumleme.

Workspace ve config dizinlerini tum projede TEK bir yerden hesaplar, boylece
disaridan (ornegin MarketingApp.agent_api.MimarAgent uzerinden) farkli bir
workspace/config dizinine yonlendirmek mumkun olur.

Oncelik sirasi:
1. MIMAR_WORKSPACE_DIR / MIMAR_CONFIG_DIR / MIMAR_APP_DIR ortam degiskenleri
2. Bu paketin (MarketingApp/) icindeki varsayilan workspace/ ve config/ klasorleri

ONEMLI: Bu degerler modul ilk import edildiginde bir kere hesaplanir. Farkli
bir workspace/config kullanmak isteyen bir cagiran, MarketingApp altindan
HERHANGI BIR seyi import etmeden once ilgili ortam degiskenini ayarlamalidir.
`MimarAgent` bunu constructor'inda otomatik yapar; dogrudan bu paketi
kullanan kod icin de ayni kural gecerlidir.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_APP_DIR = Path(__file__).resolve().parent

APP_DIR: Path = Path(os.environ.get("MIMAR_APP_DIR") or _DEFAULT_APP_DIR).resolve()
WORKSPACE_DIR: Path = Path(os.environ.get("MIMAR_WORKSPACE_DIR") or (APP_DIR / "workspace")).resolve()
CONFIG_DIR: Path = Path(os.environ.get("MIMAR_CONFIG_DIR") or (APP_DIR / "config")).resolve()


def workspace_path(*parts: str) -> str:
    """WORKSPACE_DIR altindaki bir alt yolu str olarak dondurur."""
    return str(WORKSPACE_DIR.joinpath(*parts))


def config_path(*parts: str) -> str:
    """CONFIG_DIR altindaki bir alt yolu str olarak dondurur."""
    return str(CONFIG_DIR.joinpath(*parts))
