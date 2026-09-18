"""Runs one policy-approved action through the platform's official-API toolbox.

The toolbox modules (`toolboxes/<platform>/api/toolbox.py`) read their platform
credentials from this process's environment. That is the point of this worker:
the agent never holds them. Callers hand this module an `ActionSpec` that has
already passed `Policy.validate`; on top of that the executor refuses to run a
function that is not the manifest's named, read-shaped one.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
from pathlib import Path
from typing import Any

from .policy import READ_FUNCTION, ActionSpec

DEFAULT_MAX_RESULT_BYTES = 200_000
# Environment variables whose VALUES must never appear in a result written to the queue.
_SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|REFRESH|BEARER)", re.IGNORECASE)
# Raw duplicates of data the toolbox already extracted, dropped first when shrinking.
_REDUNDANT_KEYS = ("response", "raw_text")
_LIST_KEYS = ("items", "comment_items", "post_items", "rows", "data", "media", "results")


class ExecutionError(RuntimeError):
    """The toolbox could not be located or does not match its manifest."""


def _secret_values() -> list[str]:
    return sorted(
        {value for name, value in os.environ.items() if _SECRET_NAME.search(name) and len(value) >= 8},
        key=len,
        reverse=True,
    )


def _redact(payload: Any) -> Any:
    secrets = _secret_values()
    if not secrets:
        return payload
    text = json.dumps(payload, ensure_ascii=False, default=str)
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
        # the same value can appear JSON-escaped inside a string
        text = text.replace(json.dumps(secret)[1:-1], "[redacted]")
    return json.loads(text)


def _size(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _shrink(data: Any, max_bytes: int) -> tuple[Any, bool]:
    """Fits `data` under `max_bytes`: drops raw duplicate keys, then halves the
    longest lists until it fits. Returns (data, truncated)."""
    if _size(data) <= max_bytes:
        return data, False
    if not isinstance(data, dict):
        return {"note": "result exceeded the size limit and was dropped"}, True
    data = dict(data)
    truncated = False
    if any(key in data for key in _REDUNDANT_KEYS) and any(key in data for key in _LIST_KEYS):
        for key in _REDUNDANT_KEYS:
            data.pop(key, None)
        truncated = True
    while _size(data) > max_bytes:
        candidates = [(k, v) for k, v in data.items() if isinstance(v, list) and len(v) > 1]
        if not candidates:
            return {"note": "result exceeded the size limit and was dropped"}, True
        key, value = max(candidates, key=lambda kv: _size(kv[1]))
        data[key] = value[: max(1, len(value) // 2)]
        truncated = True
    return data, truncated


class ToolboxExecutor:
    def __init__(self, toolboxes_dir: str | Path, *, max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES):
        self._root = Path(toolboxes_dir)
        self._max_result_bytes = max_result_bytes
        self._modules: dict[str, Any] = {}

    def _module(self, platform: str):
        if platform not in self._modules:
            path = self._root / platform / "api" / "toolbox.py"
            if not path.is_file():
                raise ExecutionError(f"toolbox for '{platform}' not found at {path}")
            spec = importlib.util.spec_from_file_location(f"platform_toolbox_{platform}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._modules[platform] = module
        return self._modules[platform]

    def _resolve(self, spec: ActionSpec, params: dict[str, Any]):
        if not READ_FUNCTION.match(spec.function):
            raise ExecutionError(f"refusing to run non-read function '{spec.function}'")
        module = self._module(spec.platform)
        function = getattr(module, spec.function, None)
        if not callable(function) or getattr(function, "__module__", None) != module.__name__:
            raise ExecutionError(f"{spec.platform} toolbox has no function '{spec.function}' (manifest out of date?)")
        accepted = set(inspect.signature(function).parameters)
        missing = sorted(set(params) - accepted)
        if missing:
            raise ExecutionError(f"manifest params {missing} are not parameters of {spec.function} (manifest out of date?)")
        return function

    def run(self, spec: ActionSpec, params: dict[str, Any]) -> dict[str, Any]:
        """Returns {ok, platform, action, data, truncated, error?}; never raises for
        anything a platform or the toolbox can do wrong -- that is a `failed` job,
        not a crashed worker."""
        base = {"platform": spec.platform, "action": spec.action_id, "truncated": False}
        try:
            function = self._resolve(spec, params)
        except ExecutionError as exc:
            return {**base, "ok": False, "data": None, "error": str(exc)}

        try:
            raw = function(**params)
        except ValueError as exc:
            return {**base, "ok": False, "data": None, "error": _redact(f"invalid parameters: {exc}")}
        except Exception as exc:  # noqa: BLE001 - toolbox/network errors become a failed job
            return {**base, "ok": False, "data": None, "error": _redact(f"{type(exc).__name__}: {exc}")}

        data = _redact(raw)
        ok = bool(data.get("ok", True)) if isinstance(data, dict) else True
        error = None
        if isinstance(data, dict) and not ok:
            error = str(data.get("error") or data.get("api_error") or "platform request failed")
        data, truncated = _shrink(data, self._max_result_bytes)
        result = {**base, "ok": ok, "data": data, "truncated": truncated}
        if error:
            result["error"] = error[:1000]
        return result
