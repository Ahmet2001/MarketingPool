"""Manifest-approved action policy.

`toolboxes/<platform>/manifest.yaml` carries a `data_collection.actions`
allowlist. This module loads it and is the ONE place that decides whether a
request from the agent may run:

  * the platform must be one of the known platforms and have that section,
  * the action must be listed (unlisted actions -- including every write
    action the toolbox has -- simply do not exist as far as callers can tell),
  * `params` may only contain declared names, each checked against its declared
    type / enum / pattern / length / range,
  * declared `require_one_of` groups must be satisfied.

The agent runs the same kind of pre-check to fail fast, but nothing here trusts
it: the worker re-validates every job at execution time (future_work.md,
"The worker validates action schemas and platform constraints again").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLATFORMS = ("youtube", "instagram", "tiktok", "x", "reddit")
PARAM_TYPES = ("string", "integer", "boolean")
# Only read-shaped toolbox functions may ever be named in a manifest.
READ_FUNCTION = re.compile(r"^(get|search|list)_[a-z0-9_]+$")
ACTION_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class PolicyError(ValueError):
    """The request is not allowed, or the manifest itself is malformed."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    required: bool = False
    max_length: int | None = None
    pattern: re.Pattern | None = None
    enum: tuple = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class ActionSpec:
    platform: str
    action_id: str
    function: str
    description: str
    params: dict[str, ParamSpec] = field(default_factory=dict)
    require_one_of: tuple[str, ...] = ()
    personal_data: bool = False
    rate_limit_per_hour: int | None = None


def _build_param(platform: str, action_id: str, name: str, raw: Any) -> ParamSpec:
    where = f"{platform}.{action_id}.{name}"
    if not isinstance(raw, dict) or raw.get("type") not in PARAM_TYPES:
        raise PolicyError(f"{where}: type must be one of {', '.join(PARAM_TYPES)}")
    unknown = set(raw) - {"type", "required", "max_length", "pattern", "enum", "minimum", "maximum"}
    if unknown:
        raise PolicyError(f"{where}: unknown spec key(s) {sorted(unknown)}")
    try:
        pattern = re.compile(raw["pattern"]) if raw.get("pattern") else None
    except re.error as exc:
        raise PolicyError(f"{where}: bad pattern ({exc})") from exc
    return ParamSpec(
        name=name,
        type=raw["type"],
        required=bool(raw.get("required", False)),
        max_length=raw.get("max_length"),
        pattern=pattern,
        enum=tuple(raw.get("enum") or ()),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
    )


def _build_action(platform: str, action_id: str, raw: Any) -> ActionSpec:
    where = f"{platform}.{action_id}"
    if not ACTION_ID.match(action_id):
        raise PolicyError(f"{where}: invalid action id")
    if not isinstance(raw, dict):
        raise PolicyError(f"{where}: must be a mapping")
    function = str(raw.get("function") or "")
    if not READ_FUNCTION.match(function):
        raise PolicyError(f"{where}: function '{function}' is not a get_/search_/list_ function")
    raw_params = raw.get("params") or {}
    if not isinstance(raw_params, dict):
        raise PolicyError(f"{where}: params must be a mapping")
    params = {name: _build_param(platform, action_id, name, spec) for name, spec in raw_params.items()}
    one_of = tuple(raw.get("require_one_of") or ())
    for name in one_of:
        if name not in params:
            raise PolicyError(f"{where}: require_one_of names undeclared param '{name}'")
    limit = raw.get("rate_limit_per_hour")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise PolicyError(f"{where}: rate_limit_per_hour must be a positive integer")
    return ActionSpec(
        platform=platform,
        action_id=action_id,
        function=function,
        description=str(raw.get("description") or ""),
        params=params,
        require_one_of=one_of,
        personal_data=bool(raw.get("personal_data", False)),
        rate_limit_per_hour=limit,
    )


def _present(value: Any) -> bool:
    return value not in (None, "", False)


class Policy:
    def __init__(self, actions: dict[tuple[str, str], ActionSpec]):
        self._actions = actions

    def actions(self, platform: str | None = None) -> list[ActionSpec]:
        return [spec for (plat, _), spec in sorted(self._actions.items()) if platform in (None, plat)]

    def get(self, platform: str, action: str) -> ActionSpec:
        spec = self._actions.get((str(platform), str(action)))
        if spec is None:
            raise PolicyError(f"'{platform}.{action}' is not a manifest-approved data collection action")
        return spec

    def validate(self, platform: str, action: str, params: Any) -> tuple[ActionSpec, dict[str, Any]]:
        """Returns the spec and the normalized params, or raises PolicyError."""
        spec = self.get(platform, action)
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise PolicyError("params must be an object")

        unknown = sorted(set(params) - set(spec.params))
        if unknown:
            allowed = ", ".join(sorted(spec.params)) or "(none)"
            raise PolicyError(f"unknown param(s) {unknown} for {platform}.{action}; allowed: {allowed}")

        clean: dict[str, Any] = {}
        for name, param in spec.params.items():
            if name not in params or params[name] in (None, ""):
                if param.required:
                    raise PolicyError(f"param '{name}' is required for {platform}.{action}")
                continue
            clean[name] = self._coerce(name, param, params[name])

        if spec.require_one_of and not any(_present(clean.get(name)) for name in spec.require_one_of):
            raise PolicyError(f"{platform}.{action} needs at least one of: {', '.join(spec.require_one_of)}")
        return spec, clean

    @staticmethod
    def _coerce(name: str, param: ParamSpec, value: Any) -> Any:
        if param.type == "string":
            if not isinstance(value, str):
                raise PolicyError(f"param '{name}' must be a string")
            value = value.strip()
            if param.max_length is not None and len(value) > param.max_length:
                raise PolicyError(f"param '{name}' must be at most {param.max_length} characters")
            if param.enum and value not in param.enum:
                raise PolicyError(f"param '{name}' must be one of {', '.join(param.enum)}")
            if param.pattern is not None and not param.pattern.fullmatch(value):
                raise PolicyError(f"param '{name}' has an invalid format")
            return value

        if param.type == "integer":
            if isinstance(value, bool):
                raise PolicyError(f"param '{name}' must be an integer")
            if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
                value = int(value.strip())
            if not isinstance(value, int):
                raise PolicyError(f"param '{name}' must be an integer")
            if param.minimum is not None and value < param.minimum:
                raise PolicyError(f"param '{name}' must be >= {param.minimum}")
            if param.maximum is not None and value > param.maximum:
                raise PolicyError(f"param '{name}' must be <= {param.maximum}")
            return value

        # boolean
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise PolicyError(f"param '{name}' must be a boolean")


def load_policy(toolboxes_dir: str | Path) -> Policy:
    """Reads every `<toolboxes_dir>/<platform>/manifest.yaml` that has a
    `data_collection` section. A malformed section is a hard error (a policy that
    silently loads half a manifest is worse than none)."""
    root = Path(toolboxes_dir)
    actions: dict[tuple[str, str], ActionSpec] = {}
    for platform in PLATFORMS:
        manifest_path = root / platform / "manifest.yaml"
        if not manifest_path.is_file():
            continue
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        section = manifest.get("data_collection")
        if not section:
            continue
        raw_actions = (section or {}).get("actions") or {}
        if not isinstance(raw_actions, dict):
            raise PolicyError(f"{platform}: data_collection.actions must be a mapping")
        for action_id, raw in raw_actions.items():
            actions[(platform, str(action_id))] = _build_action(platform, str(action_id), raw)
    return Policy(actions)
