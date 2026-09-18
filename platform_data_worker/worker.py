"""platform_data_worker: the environment side of `collect_platform_data`.

Claims jobs from `platform_data_jobs`, checks each against the manifest
allowlist (policy.py), runs the approved read-only toolbox action with THIS
process's platform credentials (executor.py), and writes a normalized result
back. The agent only ever inserts a request and reads the answer.

    python -m platform_data_worker.worker            # from the repo root
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .executor import DEFAULT_MAX_RESULT_BYTES, ToolboxExecutor
from .jobstore import QueueError, SupabaseQueue
from .policy import Policy, PolicyError, load_policy


def log(message: str) -> None:
    print(f"[platform-data-worker] {message}", flush=True)


def process_job(job: dict[str, Any], policy: Policy, executor: ToolboxExecutor, store: Any) -> str:
    """Handles one claimed job. Returns 'done' or 'failed'."""
    job_id = str(job["id"])
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    platform = str(payload.get("platform") or "")
    action = str(payload.get("action") or "")

    def refuse(reason: str) -> str:
        log(f"job {job_id} refused: {reason}")
        store.fail(job_id, reason, {"ok": False, "platform": platform, "action": action, "error": reason})
        return "failed"

    unexpected = sorted(set(payload) - {"platform", "action", "params", "credentialRef"})
    if unexpected:
        return refuse(f"unexpected field(s) in payload: {unexpected}")
    if payload.get("credentialRef"):
        # The toolboxes read one set of credentials from the environment. Silently
        # answering with the default account's data for a request that named a
        # different account would be worse than refusing.
        return refuse("credentialRef is not supported by this worker yet (single credential set)")

    try:
        spec, params = policy.validate(platform, action, payload.get("params"))
    except PolicyError as exc:
        return refuse(str(exc))

    if spec.rate_limit_per_hour:
        used = store.count_recent(platform, action)  # includes this job (it is `processing`)
        if used > spec.rate_limit_per_hour:
            return refuse(f"rate limit: {platform}.{action} allows {spec.rate_limit_per_hour} per hour")

    result = executor.run(spec, params)
    if result.get("ok"):
        store.finish(job_id, result)
        log(f"job {job_id} done: {platform}.{action}" + (" (truncated)" if result.get("truncated") else ""))
        return "done"
    store.fail(job_id, result.get("error") or "platform request failed", result)
    log(f"job {job_id} failed: {platform}.{action}: {result.get('error')}")
    return "failed"


def run_once(policy: Policy, executor: ToolboxExecutor, store: Any) -> bool:
    """Claims and processes one job. Returns False when the queue was empty."""
    job = store.claim_next()
    if not job:
        return False
    try:
        process_job(job, policy, executor, store)
    except Exception as exc:  # noqa: BLE001 - never leave a claimed job stuck in 'processing'
        log(f"job {job['id']} crashed: {type(exc).__name__}: {exc}")
        store.fail(str(job["id"]), f"worker error: {type(exc).__name__}")
    return True


def default_toolboxes_dir() -> Path:
    return Path(os.getenv("TOOLBOXES_DIR") or Path(__file__).resolve().parent.parent / "toolboxes")


def main() -> None:
    try:  # optional convenience: read platform_data_worker/.env when python-dotenv is installed
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    policy = load_policy(default_toolboxes_dir())
    executor = ToolboxExecutor(
        default_toolboxes_dir(),
        max_result_bytes=int(os.getenv("PLATFORM_DATA_MAX_RESULT_BYTES") or DEFAULT_MAX_RESULT_BYTES),
    )
    store = SupabaseQueue()
    poll_seconds = max(1.0, int(os.getenv("PLATFORM_DATA_POLL_MS") or 5000) / 1000)
    log(f"started: {len(policy.actions())} approved actions, polling every {poll_seconds:g}s")
    while True:
        try:
            while run_once(policy, executor, store):
                pass
        except QueueError as exc:
            log(f"queue error: {exc}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
