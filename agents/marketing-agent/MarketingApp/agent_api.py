"""Mimar'i disaridan (baska bir orkestratorden) bir agent olarak kullanmak
icin ince, yan-etkisiz programatik API.

`python -m MarketingApp.main` (terminal.py) bu projeyi TEK BASINA CALISAN bir
uygulama olarak ayaga kaldirir: heartbeat/telegram/discord'u otomatik baslatir
ve bir input() dongusu bekler. Bu modul onun tam tersini yapar: hicbir arka
plan gorevi baslatmaz, hicbir input beklemez -- sadece BaseModel'i kurup
`run()` cagrisina hazir bir nesne dondurur. Baska bir sistemin (ornegin bir
"marketing asset pool" orkestratorunun) bu projeyi bir agent bacagi olarak
cagirmasi icin dusunulmustur.

Kullanim:

    from MarketingApp.agent_api import MimarAgent

    agent = MimarAgent(
        workspace_dir="/path/to/pool/brandX/workspace",
        config_dir="/path/to/pool/brandX/config",  # opsiyonel, verilmezse repo varsayilani
    )
    result = await agent.run("X hesabinda gundem hakkinda bir post tasla")
    print(result.text)

ONEMLI -- workspace_dir / config_dir enjeksiyonu hakkinda:
Workspace ve config yollari (`MarketingApp.paths`) modul ilk import
edildiginde BIR KERE hesaplanir ve tum araclar (browser cookie/profile
dizinleri, hafiza dosyalari, agent config'i, heartbeat config'i, ...) o
degeri kullanir. Bu yuzden:
  - Bu process'te `MarketingApp` altindan HERHANGI BIR seyi import etmeden
    once `MimarAgent(...)` cagrilmalidir (constructor bunu kendisi kontrol
    eder ve gec kalinirsa acik bir hata firlatir).
  - Ayni process icinde FARKLI workspace_dir/config_dir degerleriyle birden
    fazla `MimarAgent` calistirmak desteklenmez -- bu proje su an tek
    workspace/tek process modeliyle calisir. Coklu pool/coklu marka
    senaryosunda cagiran taraf her workspace icin ayri bir process
    (ör. ayri bir subprocess/worker) baslatmalidir.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any


class AgentConfigurationError(RuntimeError):
    """workspace_dir/config_dir, MarketingApp zaten import edildikten sonra
    degistirilmeye calisildiginda firlatilir."""


@dataclass
class AgentResult:
    """`MimarAgent.run()` cagrisinin yapilandirilmis sonucu."""

    text: str
    """Modelin nihai (kullaniciya gosterilecek) yaniti."""

    direct_texts: list[str] = field(default_factory=list)
    """Araç turlari arasinda modelin ürettigi ara/dogrudan metinler (varsa)."""

    step_texts: list[str] = field(default_factory=list)
    """Sohbet dongusundeki her turun cevap metni gecmisi."""

    raw: tuple = ()
    """BaseModel.text_query'nin ham donus degeri (bytes, text, direct_texts, step_texts)."""


def _apply_path_override(env_var: str, value: str | None) -> None:
    if value is None:
        return
    if "MarketingApp.paths" in sys.modules:
        from MarketingApp import paths as _paths

        current = str(_paths.WORKSPACE_DIR if env_var == "MIMAR_WORKSPACE_DIR" else _paths.CONFIG_DIR)
        if os.path.abspath(current) != os.path.abspath(value):
            raise AgentConfigurationError(
                f"{env_var} artik degistirilemez: MarketingApp bu process icinde zaten "
                f"'{current}' degeriyle import edilmis. Farkli bir workspace/config icin "
                "yeni bir process baslatin (ayni process'te birden fazla MimarAgent "
                "farkli dizinlerle desteklenmez)."
            )
        return
    os.environ[env_var] = value


class MimarAgent:
    """Mimar'in BaseModel orkestratorunu yan-etkisiz, programatik olarak sarmalar.

    Terminal/heartbeat/telegram gibi hicbir arka plan gorevi baslatmaz;
    sadece `run()` ile tek seferlik/ardisik gorev cagirmaya yarar.
    """

    def __init__(
        self,
        *,
        workspace_dir: str | None = None,
        config_dir: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        _apply_path_override("MIMAR_WORKSPACE_DIR", workspace_dir)
        _apply_path_override("MIMAR_CONFIG_DIR", config_dir)

        # BaseModel (ve onun uzerinden tum araclar/SubModel'lar) burada, path
        # override'lari uygulandiktan SONRA import edilir.
        from MarketingApp.llms import BaseModel as _BaseModel
        from MarketingApp.paths import CONFIG_DIR, WORKSPACE_DIR

        self.workspace_dir = str(WORKSPACE_DIR)
        self.config_dir = str(CONFIG_DIR)
        self._base_model = _BaseModel(api_key=api_key, model=model)

    async def run(self, task: str, *, context: str = "") -> AgentResult:
        """Bir gorevi calistirir ve yapilandirilmis sonucu dondurur.

        Args:
            task: Dogal dilde gorev/istek metni.
            context: Modelin gorev oncesi gorecegi ek baglam (opsiyonel).
        """
        raw = await self._base_model.text_query(task, context=context)
        _, text, direct_texts, step_texts = raw
        return AgentResult(
            text=text,
            direct_texts=list(direct_texts or []),
            step_texts=list(step_texts or []),
            raw=raw,
        )

    def get_capabilities(self) -> dict[str, Any]:
        """Aktif/pasif alt-ajanlari ve tool'lari disari acan kucuk bir 'yetenek' ozeti.

        Ust orkestratorun bu agent'i cagirmadan once ne yapabildigini
        kesfedebilmesi icin dusunulmustur.
        """
        return self._base_model.get_hierarchy()
