"""`platform_data_jobs` over Supabase's REST API (see migrations/001_platform_data_jobs.sql).

Python counterpart of social-media-worker/adapters/supabase.js: claim one queued
job atomically, then finish or fail it. Uses the service key because this is the
worker's own infrastructure; the agent side uses a narrower one.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

_TIMEOUT_SECONDS = 20


class QueueError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupabaseQueue:
    def __init__(self, url: str | None = None, key: str | None = None, session: Any = requests):
        self._url = (url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self._key = (key or os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self._http = session
        if not self._url or not self._key:
            raise QueueError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set for platform_data_worker")

    def _headers(self, **extra: str) -> dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            **extra,
        }

    def _request(self, method: str, path: str, **kwargs: Any):
        try:
            response = self._http.request(method, f"{self._url}/rest/v1/{path}", timeout=_TIMEOUT_SECONDS, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise QueueError(f"{method} {path} failed: {exc}") from exc

    def claim_next(self) -> dict[str, Any] | None:
        response = self._request("POST", "rpc/claim_platform_data_job", headers=self._headers(), json={})
        data = response.json()
        return data if isinstance(data, dict) and data.get("id") else None

    def _patch(self, job_id: str, patch: dict[str, Any]) -> None:
        self._request("PATCH", "platform_data_jobs", headers=self._headers(), params={"id": f"eq.{job_id}"}, json=patch)

    def finish(self, job_id: str, results: dict[str, Any]) -> None:
        now = _now().isoformat()
        self._patch(job_id, {"status": "done", "results": results, "error": None, "completed_at": now, "updated_at": now})

    def fail(self, job_id: str, error: str, results: dict[str, Any] | None = None) -> None:
        now = _now().isoformat()
        self._patch(job_id, {
            "status": "failed", "results": results or {}, "error": str(error)[:2000],
            "completed_at": now, "updated_at": now,
        })

    def count_recent(self, platform: str, action: str, *, hours: float = 1.0) -> int:
        """Jobs for (platform, action) that ran (or are running) in the last `hours`."""
        since = (_now() - timedelta(hours=hours)).isoformat()
        response = self._request(
            "GET", "platform_data_jobs",
            headers=self._headers(Prefer="count=exact", Range="0-0"),
            params={
                "select": "id",
                "payload->>platform": f"eq.{platform}",
                "payload->>action": f"eq.{action}",
                "status": "in.(processing,done)",
                "created_at": f"gte.{since}",
            },
        )
        # Content-Range looks like "0-0/42" or "*/0"
        total = (response.headers.get("Content-Range") or "").rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else 0
