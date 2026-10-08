"""
Ortak otomasyon koordinasyonu.

Heartbeat, Telegram ve terminalin ayni BaseModel / browser oturumunu
eszamanli kullanmasini engelleyen hafif runtime kilidi.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo


_TIMEZONE = ZoneInfo("Europe/Istanbul")


def _now_iso() -> str:
    return datetime.now(_TIMEZONE).isoformat(timespec="seconds")


class AutomationCoordinator:
    def __init__(self):
        self._guard = asyncio.Lock()
        self._state = {
            "busy": False,
            "owner": "",
            "job_id": "",
            "label": "",
            "started_at": None,
            "source": "",
        }

    def snapshot(self) -> dict:
        return dict(self._state)

    async def try_acquire(
        self,
        owner: str,
        *,
        job_id: str = "",
        label: str = "",
        source: str = "",
    ) -> tuple[bool, dict]:
        async with self._guard:
            if self._state["busy"]:
                return False, dict(self._state)

            self._state = {
                "busy": True,
                "owner": (owner or "").strip(),
                "job_id": (job_id or "").strip(),
                "label": (label or "").strip(),
                "started_at": _now_iso(),
                "source": (source or "").strip(),
            }
            return True, dict(self._state)

    async def release(self, owner: str, *, job_id: str = "") -> bool:
        async with self._guard:
            if not self._state["busy"]:
                return False
            if owner and self._state["owner"] != owner:
                return False
            if job_id and self._state["job_id"] and self._state["job_id"] != job_id:
                return False

            self._state = {
                "busy": False,
                "owner": "",
                "job_id": "",
                "label": "",
                "started_at": None,
                "source": "",
            }
            return True

    async def reset(self) -> None:
        async with self._guard:
            self._state = {
                "busy": False,
                "owner": "",
                "job_id": "",
                "label": "",
                "started_at": None,
                "source": "",
            }


_automation_coordinator = AutomationCoordinator()


def get_automation_snapshot() -> dict:
    return _automation_coordinator.snapshot()


async def try_acquire_automation(
    owner: str,
    *,
    job_id: str = "",
    label: str = "",
    source: str = "",
) -> tuple[bool, dict]:
    return await _automation_coordinator.try_acquire(
        owner,
        job_id=job_id,
        label=label,
        source=source,
    )


async def release_automation(owner: str, *, job_id: str = "") -> bool:
    return await _automation_coordinator.release(owner, job_id=job_id)


async def reset_automation_runtime() -> None:
    await _automation_coordinator.reset()
