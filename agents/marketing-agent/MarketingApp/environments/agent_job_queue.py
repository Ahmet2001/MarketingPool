"""
Agent Job Queue — `agent_jobs` Supabase tablosuna karsi ince bir REST istemcisi.

`MarketingApp/worker.py`'nin iki girdi noktasi da (queue-poller ve MCP
on-demand) bu tabloyu kullanir; `social-media-worker/adapters/supabase.js` +
`services/jobQueue.js`'in Python karsiligidir, ayni Supabase projesi ve ayni
SUPABASE_URL/SUPABASE_SECRET_KEY degiskenleri uzerinden calisir (bkz.
`MarketingApp/araclar/worker_yayinlama_araclari.py`).

Tasarim gerekcesi: bu modul SADECE queue-poller'i besler ve MCP tool'unun
audit-trail insert'ini yapar; asil is (`MimarAgent.run`) burada degil
`MarketingApp/worker.py`'de calisir.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

_TIMEOUT_SECONDS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentJobQueueError(RuntimeError):
    """Supabase istegi basarisiz oldugunda veya yapilandirma eksikse firlatilir."""


def is_configured() -> bool:
    return bool((os.getenv("SUPABASE_URL") or "").strip()) and bool(
        (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    )


def _config() -> tuple[str, str]:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise AgentJobQueueError(
            "SUPABASE_URL / SUPABASE_SECRET_KEY tanimli degil; agent_jobs kuyrugu kullanilamaz."
        )
    return url, key


def _headers(key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def claim_next_agent_job() -> dict[str, Any] | None:
    """`claim_next_agent_job()` RPC'sini cagirir; is yoksa None dondurur."""
    base_url, key = _config()
    try:
        response = requests.post(
            f"{base_url}/rest/v1/rpc/claim_next_agent_job",
            headers=_headers(key),
            json={},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AgentJobQueueError(f"claim_next_agent_job basarisiz: {exc}") from exc

    data = response.json()
    if not data or not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def insert_agent_job(payload: dict[str, Any], *, owner_ref: str = "", status: str = "queued") -> dict[str, Any]:
    """Yeni bir agent_jobs satiri ekler; eklenen satiri dondurur.

    status='processing' MCP on-demand cagrilarinin kendi isini hemen kendisi
    calistirip audit-trail birakmasi icindir (claim RPC'sini atlamak gerekir,
    cunku is zaten bu process tarafindan sahipli).
    """
    base_url, key = _config()
    body: dict[str, Any] = {"payload": payload, "status": status}
    if owner_ref:
        body["owner_ref"] = owner_ref
    if status == "processing":
        body["attempts"] = 1

    try:
        response = requests.post(
            f"{base_url}/rest/v1/agent_jobs",
            headers=_headers(key, prefer="return=representation"),
            json=body,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AgentJobQueueError(f"agent_jobs kaydi eklenemedi: {exc}") from exc

    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise AgentJobQueueError("agent_jobs insert bos yanit dondurdu.")
    return rows[0]


def _update_job(job_id: str, patch: dict[str, Any]) -> None:
    base_url, key = _config()
    try:
        response = requests.patch(
            f"{base_url}/rest/v1/agent_jobs",
            headers=_headers(key),
            params={"id": f"eq.{job_id}"},
            json=patch,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AgentJobQueueError(f"agent_jobs guncellenemedi ({job_id}): {exc}") from exc


def finish_agent_job(job_id: str, results: dict[str, Any]) -> None:
    now = _now_iso()
    _update_job(
        job_id,
        {
            "status": "done",
            "results": results,
            "error": None,
            "completed_at": now,
            "updated_at": now,
        },
    )


def requeue_agent_job(job_id: str) -> None:
    """Bir isi 'queued' durumuna geri dondurur (basarisiz sayilmadan tekrar denensin diye).

    Ornegin: worker.py bu process icinde otomasyon mesgulken claim edilmis bir
    isi birkac kez denedikten sonra hala mesgulse, isi 'failed' olarak
    isaretlemek yerine burayi cagirip sonraki poll'e (ya da baska bir
    replica'ya) birakir.
    """
    _update_job(
        job_id,
        {
            "status": "queued",
            "started_at": None,
            "error": None,
            "updated_at": _now_iso(),
        },
    )


def fail_agent_job(job_id: str, error: str, results: dict[str, Any] | None = None) -> None:
    now = _now_iso()
    _update_job(
        job_id,
        {
            "status": "failed",
            "results": results or {},
            "error": str(error)[:2000],
            "completed_at": now,
            "updated_at": now,
        },
    )
