"""
Approval Runtime — `araclar/` icindeki duz fonksiyonlarin (worker_video_yayinla
gibi) insan onayi istemesini saglayan surec-genelinde kayit noktasi.

Neden bu modul var: onay isteme mantigi (`BaseModel.request_approval`) bir
sinif metodu, ama `araclar/` icindeki tool'lar duz modul-seviyesi fonksiyonlar
ve hicbir BaseModel referansi tutmuyorlar (`automation_runtime.py`/
`vlm_araclari.get_registered_bot()` ile ayni "surec-seviyesi kayit" deseni).

`BaseModel.__init__` her zaman burada DINAMIK bir kapanis (closure) kayit
eder — `self.request_approval`'i HER cagride yeniden okur, boylece
TerminalManager'in `base_model.request_approval`'i insana-soran bir
versiyonla degistirmesi (bkz. terminal.py) otomatik olarak yansir.

Bassiz (headless) baglamlar (worker.py, ve varsayilan olarak agent_api.py)
kendi HIZLI-REDDET handler'larini kaydeder: onaylayacak insan yoksa
`BaseModel`'in varsayilan 300sn'lik event-wait'ini beklemek yerine aninda ve
acikca reddeder (fail-closed, ama gereksiz beklemeden).
"""

from __future__ import annotations

from typing import Awaitable, Callable

ApprovalHandler = Callable[[str, str], Awaitable[bool]]

_handler: ApprovalHandler | None = None


def register_approval_handler(handler: ApprovalHandler | None) -> None:
    """Surec icin aktif onay isleyicisini kaydeder (son kayit kazanir)."""
    global _handler
    _handler = handler


def get_registered_approval_handler() -> ApprovalHandler | None:
    return _handler


async def request_tool_approval(action_id: str, description: str) -> bool:
    """`araclar/` icindeki bir tool'un onay istemesi icin TEK giris noktasi.

    Kayitli bir handler yoksa (hic kurulum yapilmamis surec) fail-closed
    davranir: onay YOK sayilir, sessizce izin verilmez.
    """
    if _handler is None:
        return False
    return await _handler(action_id, description)


async def reject_all_approvals(action_id: str, description: str) -> bool:
    """Bassiz baglamlar icin varsayilan handler: her istegi aninda reddeder."""
    print(
        f"🚫 [Approval] Reddedildi (bu surecte onaylayacak insan yok): "
        f"{action_id} — {description}"
    )
    return False
