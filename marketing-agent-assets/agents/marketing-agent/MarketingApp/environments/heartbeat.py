"""
Heartbeat scheduler service.

APScheduler tabanli zamanlayici, YAML config'ten gorevleri yukler
ve terminal tarafina runtime durumunu sunar.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .automation_runtime import (
    get_automation_snapshot,
    release_automation,
    try_acquire_automation,
)

try:
    import yaml
    _YAML_IMPORT_ERROR = None
except ImportError as yaml_import_error:
    yaml = None
    _YAML_IMPORT_ERROR = yaml_import_error

try:
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _SCHEDULER_IMPORT_ERROR = None
except Exception as scheduler_import_error:
    SQLAlchemyJobStore = None
    AsyncIOScheduler = None
    CronTrigger = None
    _SCHEDULER_IMPORT_ERROR = scheduler_import_error

try:
    from openai import RateLimitError
except Exception:
    RateLimitError = None


from MarketingApp.paths import config_path, workspace_path

_CONFIG_PATH = config_path("heartbeat_config.yaml")
_RUNTIME_DIR = workspace_path("runtime")
_JOBSTORE_PATH = os.path.join(_RUNTIME_DIR, "apscheduler_jobs.sqlite")
_RUNTIME_DB_PATH = os.path.join(_RUNTIME_DIR, "scheduler_runtime.sqlite")
_TIMEZONE = ZoneInfo("Europe/Istanbul")
_WATCH_INTERVAL_SECONDS = 2.0
_MAX_RETRY_ATTEMPTS = 3
_RETRY_DELAYS_SECONDS = (2, 6, 14)
_DEFAULT_CONFIG = {"enabled": False, "interval_minutes": 30, "tasks": []}
_PROGRESS_DEDUPE_SECONDS = 1.2
_TRIVIAL_PROGRESS_TOOLS = {
    "workspace_oku",
    "workspace_sonunu_oku",
    "workspace_yaz",
    "workspace_ekle",
    "workspace_listele",
    "rol_oku",
    "rol_guncelle",
    "metinle_cevapla",
    "ekrana_yazdir",
}
_PROGRESS_EVENT_RE = re.compile(
    r"^\[\+[0-9.]+s\]\s+(?P<emoji>\S+)\s+(?P<name>[A-Za-z0-9_]+)\s+"
    r"(?P<verb>calistiriliyor|bitti)(?:\.{3})?(?:\s+\((?P<duration>[^)]+)\))?"
)

_heartbeat_service: "HeartbeatService | None" = None


class HeartbeatConfigError(ValueError):
    """Config dogrulama hatasi."""


@dataclass(slots=True)
class HeartbeatTask:
    task_id: str
    name: str
    cron: str
    gorev: str
    enabled: bool
    source_index: int


def _now() -> datetime:
    return datetime.now(_TIMEZONE)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TIMEZONE)
    return dt.isoformat()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return cleaned


def _ensure_runtime_dirs() -> None:
    os.makedirs(_RUNTIME_DIR, exist_ok=True)


def _resolve_telegram_target(telegram_bot=None, chat_id: int | None = None):
    """Varsa heartbeat ciktisi icin Telegram bot/chat hedefini cozer."""
    resolved_bot = telegram_bot
    resolved_chat_id = chat_id

    if resolved_chat_id is None:
        env_chat_id = os.getenv("HEARTBEAT_CHAT_ID") or os.getenv("DEFAULT_CHAT_ID")
        if env_chat_id:
            try:
                resolved_chat_id = int(env_chat_id)
            except ValueError:
                resolved_chat_id = None

    if resolved_bot is None or resolved_chat_id is None:
        try:
            from MarketingApp.araclar.vlm_araclari import get_registered_bot

            registered_bot, registered_chat_id = get_registered_bot()
            if resolved_bot is None:
                resolved_bot = registered_bot
            if resolved_chat_id is None:
                resolved_chat_id = registered_chat_id
        except Exception:
            pass

    return resolved_bot, resolved_chat_id


def get_config_path() -> str:
    return _CONFIG_PATH


def read_config_content() -> str:
    if not os.path.exists(_CONFIG_PATH):
        return ""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _derive_task_name(gorev: str, cron: str, index: int) -> str:
    for line in gorev.splitlines():
        cleaned = " ".join(line.strip().split())
        if cleaned:
            return cleaned[:72]
    return f"Gorev {index + 1} ({cron})"


def _validate_task_id(task_id: str) -> str:
    cleaned = (task_id or "").strip()
    if not cleaned:
        raise HeartbeatConfigError("Task id bos olamaz.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cleaned):
        raise HeartbeatConfigError(
            f"Gecersiz task id '{cleaned}'. Sadece harf, rakam, '_' ve '-' kullanin."
        )
    return cleaned


def _validate_cron(cron: str) -> None:
    value = (cron or "").strip()
    if value == "startup":
        return
    if re.fullmatch(r"\*/\d+", value):
        interval = int(value[2:])
        if interval < 1:
            raise HeartbeatConfigError(f"Cron araligi gecersiz: {value}")
        return
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise HeartbeatConfigError(f"Saat bazli cron gecersiz: {value}")
        return
    raise HeartbeatConfigError(
        f"Desteklenmeyen cron formati '{value}'. 'startup', '*/N' veya 'HH:MM' kullanin."
    )


def parse_config_content(content: str) -> dict[str, Any]:
    if yaml is None:
        raise HeartbeatConfigError(f"PyYAML yuklu degil: {_YAML_IMPORT_ERROR}")

    raw = (content or "").strip()
    if not raw:
        return dict(_DEFAULT_CONFIG)

    try:
        parsed = yaml.safe_load(raw) or {}
    except Exception as exc:
        raise HeartbeatConfigError(f"YAML parse hatasi: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HeartbeatConfigError("Heartbeat config koku key/value yapisinda olmali.")

    interval_raw = parsed.get("interval_minutes", 30)
    try:
        interval_minutes = max(1, int(interval_raw or 30))
    except Exception as exc:
        raise HeartbeatConfigError(
            f"interval_minutes sayi olmali, gelen deger: {interval_raw}"
        ) from exc

    tasks_raw = parsed.get("tasks", []) or []
    if not isinstance(tasks_raw, list):
        raise HeartbeatConfigError("'tasks' alani liste olmali.")

    seen_ids: set[str] = set()
    tasks: list[HeartbeatTask] = []

    for index, task_raw in enumerate(tasks_raw):
        if not isinstance(task_raw, dict):
            raise HeartbeatConfigError(f"tasks[{index}] nesne olmali.")

        cron = str(task_raw.get("cron", "") or "").strip()
        gorev = str(task_raw.get("gorev", "") or "").strip()
        if not cron:
            raise HeartbeatConfigError(f"tasks[{index}].cron bos olamaz.")
        if not gorev:
            raise HeartbeatConfigError(f"tasks[{index}].gorev bos olamaz.")

        _validate_cron(cron)

        raw_id = str(task_raw.get("id", "") or "").strip()
        if raw_id:
            task_id = _validate_task_id(raw_id)
        else:
            seed = task_raw.get("name") or cron or f"job-{index + 1}"
            task_id = _validate_task_id(
                f"task_{index + 1:02d}_{_slugify(str(seed))[:24] or 'job'}"
            )

        if task_id in seen_ids:
            raise HeartbeatConfigError(f"Tekrarlanan task id bulundu: {task_id}")
        seen_ids.add(task_id)

        name = str(task_raw.get("name", "") or "").strip() or _derive_task_name(gorev, cron, index)
        enabled = bool(task_raw.get("enabled", True))
        tasks.append(
            HeartbeatTask(
                task_id=task_id,
                name=name[:96],
                cron=cron,
                gorev=gorev,
                enabled=enabled,
                source_index=index,
            )
        )

    return {
        "enabled": bool(parsed.get("enabled", False)),
        "interval_minutes": interval_minutes,
        "tasks": tasks,
    }


def summarize_config_content(content: str) -> dict[str, Any]:
    meta = {
        "enabled": False,
        "interval_minutes": 30,
        "legacy_interval_minutes": 30,
        "task_count": 0,
        "valid": False,
        "validation_error": "",
    }

    try:
        parsed = parse_config_content(content)
    except HeartbeatConfigError as exc:
        meta["validation_error"] = str(exc)
        return meta

    meta.update(
        {
            "enabled": bool(parsed.get("enabled", False)),
            "interval_minutes": int(parsed.get("interval_minutes", 30) or 30),
            "legacy_interval_minutes": int(parsed.get("interval_minutes", 30) or 30),
            "task_count": len(parsed.get("tasks", []) or []),
            "valid": True,
            "validation_error": "",
        }
    )
    return meta


def set_enabled_in_content(content: str, enabled: bool) -> str:
    enabled_line = f"enabled: {'true' if enabled else 'false'}"
    if re.search(r"(?m)^\s*enabled\s*:\s*(true|false)\s*$", content or ""):
        return re.sub(
            r"(?m)^\s*enabled\s*:\s*(true|false)\s*$",
            enabled_line,
            content,
            count=1,
        )
    return f"{enabled_line}\n\n{(content or '').lstrip()}" if (content or "").strip() else f"{enabled_line}\n"


def write_config_content(content: str) -> dict[str, Any]:
    """Config metnini once dogrular, sonra atomik olarak diske yazar."""
    summary = summarize_config_content(content)
    if not summary["valid"]:
        raise HeartbeatConfigError(summary["validation_error"] or "Config gecersiz.")

    directory = os.path.dirname(_CONFIG_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = f"{_CONFIG_PATH}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, _CONFIG_PATH)
    return summary


def _locate_tasks_block(content: str) -> tuple[list[str], int, int, str]:
    """'tasks:' listesinin satir sinirlarini ve list item girintisini bulur.

    Config YAML anchor/alias (`&post_gorevi` / `*post_gorevi`) ve yorum iceriyor;
    safe_load + safe_dump ile round-trip bunlari yok edecegi icin gorev ekleme ve
    cikarma islemleri metin seviyesinde yapilir.
    """
    lines = (content or "").splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"tasks\s*:\s*", line)), None)
    if start is None:
        raise HeartbeatConfigError("Config icinde 'tasks:' anahtari bulunamadi.")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line[0].isspace():
            end = index
            break

    indent = "  "
    for index in range(start + 1, end):
        match = re.match(r"^(\s*)-\s", lines[index])
        if match:
            indent = match.group(1)
            break
    return lines, start, end, indent


def _task_item_ranges(lines: list[str], start: int, end: int, indent: str) -> list[tuple[int, int]]:
    starts = [i for i in range(start + 1, end) if re.match(rf"^{re.escape(indent)}-\s", lines[i])]
    return [(item, starts[pos + 1] if pos + 1 < len(starts) else end) for pos, item in enumerate(starts)]


def add_task_to_content(
    content: str,
    *,
    gorev: str,
    cron: str,
    task_id: str = "",
    name: str = "",
    enabled: bool = True,
) -> tuple[str, str]:
    """tasks listesine yeni bir gorev blogu ekler; (yeni_icerik, task_id) dondurur."""
    gorev_text = (gorev or "").strip()
    if not gorev_text:
        raise HeartbeatConfigError("Gorev metni bos olamaz.")
    cron_value = (cron or "").strip()
    _validate_cron(cron_value)

    existing = {task.task_id for task in parse_config_content(content)["tasks"]}
    if task_id:
        task_id = _validate_task_id(task_id)
        if task_id in existing:
            raise HeartbeatConfigError(f"'{task_id}' zaten kayitli.")
    else:
        seed = _slugify(name or cron_value or "job")[:24] or "job"
        counter = len(existing) + 1
        task_id = f"task_{counter:02d}_{seed}"
        while task_id in existing:
            counter += 1
            task_id = f"task_{counter:02d}_{seed}"
        task_id = _validate_task_id(task_id)

    lines, start, end, indent = _locate_tasks_block(content)
    child = indent + "  "
    block = [f"{indent}- id: {task_id}"]
    if (name or "").strip():
        block.append(f"{child}name: {json.dumps(name.strip(), ensure_ascii=False)}")
    block.append(f"{child}cron: {json.dumps(cron_value, ensure_ascii=False)}")
    if not enabled:
        block.append(f"{child}enabled: false")
    block.append(f"{child}gorev: >")
    block.extend(f"{child}  {line.strip()}" for line in gorev_text.splitlines() if line.strip())

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1

    updated = "\n".join(lines[:insert_at] + [""] + block + lines[insert_at:]).rstrip() + "\n"
    parse_config_content(updated)
    return updated, task_id


def remove_task_from_content(content: str, task_id: str) -> str:
    """tasks listesinden verilen id'ye sahip gorev blogunu siler."""
    normalized = _validate_task_id(task_id)
    if not any(task.task_id == normalized for task in parse_config_content(content)["tasks"]):
        raise HeartbeatConfigError(f"Task bulunamadi: {normalized}")

    lines, start, end, indent = _locate_tasks_block(content)
    target: tuple[int, int] | None = None
    for item_start, item_end in _task_item_ranges(lines, start, end, indent):
        chunk = "\n".join(lines[item_start:item_end])
        match = re.search(r"(?m)^\s*(?:-\s+)?id\s*:\s*(.+?)\s*$", chunk)
        if match and match.group(1).strip().strip("\"'") == normalized:
            target = (item_start, item_end)
            break

    if target is None:
        raise HeartbeatConfigError(
            f"'{normalized}' config metninde acik bir 'id:' satiriyla tanimlanmamis; elle silmen gerekiyor."
        )

    item_start, item_end = target
    updated = "\n".join(lines[:item_start] + lines[item_end:]).rstrip() + "\n"
    parse_config_content(updated)
    return updated


def load_config() -> dict[str, Any]:
    if yaml is None:
        print(f"⚠️ [Heartbeat] PyYAML yuklu degil, heartbeat devre disi: {_YAML_IMPORT_ERROR}")
        return dict(_DEFAULT_CONFIG)

    try:
        return parse_config_content(read_config_content())
    except HeartbeatConfigError as exc:
        print(f"⚠️ [Heartbeat] Config gecersiz, varsayilan kullaniliyor: {exc}")
        return dict(_DEFAULT_CONFIG)


def _build_trigger(cron: str):
    if cron == "startup":
        return None
    if cron.startswith("*/"):
        minutes = int(cron[2:])
        return CronTrigger(minute=f"*/{minutes}", second=0, timezone=_TIMEZONE)
    hour, minute = cron.split(":")
    return CronTrigger(hour=int(hour), minute=int(minute), second=0, timezone=_TIMEZONE)


def _is_retryable_model_error(exc: Exception) -> bool:
    if RateLimitError is not None and isinstance(exc, RateLimitError):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code in {429, 503}:
        return True

    lowered = str(exc).lower()
    retry_markers = (
        "503",
        "429",
        "high demand",
        "status': 'unavailable'",
        "temporarily unavailable",
        "rate limit",
        "quota",
    )
    return any(marker in lowered for marker in retry_markers)


def get_heartbeat_service() -> "HeartbeatService | None":
    return _heartbeat_service


def get_heartbeat_status_snapshot() -> dict[str, Any]:
    service = get_heartbeat_service()
    if service is None:
        dependency_error = None
        if yaml is None:
            dependency_error = f"PyYAML eksik: {_YAML_IMPORT_ERROR}"
        elif AsyncIOScheduler is None:
            dependency_error = f"APScheduler eksik: {_SCHEDULER_IMPORT_ERROR}"
        return {
            "ready": False,
            "enabled": False,
            "running": False,
            "paused": True,
            "active_job_id": None,
            "active_job_name": "",
            "job_count": 0,
            "scheduled_job_count": 0,
            "last_reload_at": None,
            "config_valid": summarize_config_content(read_config_content()).get("valid", False),
            "config_error": summarize_config_content(read_config_content()).get("validation_error", ""),
            "jobstore_path": _JOBSTORE_PATH,
            "runtime_db_path": _RUNTIME_DB_PATH,
            "legacy_interval_minutes": summarize_config_content(read_config_content()).get("interval_minutes", 30),
            "dependency_error": dependency_error or "",
        }
    return service.get_status()


def get_heartbeat_jobs_snapshot() -> list[dict[str, Any]]:
    service = get_heartbeat_service()
    if service is None:
        return []
    return service.list_jobs()


async def reload_heartbeat_service(reason: str = "api_reload") -> dict[str, Any]:
    service = get_heartbeat_service()
    if service is None:
        raise RuntimeError("Heartbeat servisi henuz hazir degil.")
    await service.reload_from_disk(reason=reason)
    return service.get_status()


async def pause_heartbeat_job(job_id: str) -> dict[str, Any]:
    service = get_heartbeat_service()
    if service is None:
        raise RuntimeError("Heartbeat servisi henuz hazir degil.")
    return await service.pause_job(job_id)


async def resume_heartbeat_job(job_id: str) -> dict[str, Any]:
    service = get_heartbeat_service()
    if service is None:
        raise RuntimeError("Heartbeat servisi henuz hazir degil.")
    return await service.resume_job(job_id)


async def run_heartbeat_job(job_id: str) -> dict[str, Any]:
    service = get_heartbeat_service()
    if service is None:
        raise RuntimeError("Heartbeat servisi henuz hazir degil.")
    return await service.run_job_now(job_id)


async def _execute_heartbeat_task(
    base_model,
    gorev: str,
    telegram_bot=None,
    chat_id: int | None = None,
    notify_telegram: bool = True,
    progress_handler=None,
) -> dict[str, Any]:
    print(f"💓 [Heartbeat] Gorev calistiriliyor: {gorev[:60]}...")
    telegram_bot, chat_id = _resolve_telegram_target(telegram_bot, chat_id)

    collected_texts: list[str] = []

    async def on_text(metin: str):
        text = str(metin or "").strip()
        if not text:
            return
        if progress_handler:
            handled = await progress_handler(text)
            if handled:
                return
        collected_texts.append(text)

    async def on_cevap(cevap: str):
        text = str(cevap or "").strip()
        if not text:
            return
        collected_texts.append(text)

    _audio, transcript, direct_texts, cevap_metinleri = await base_model.text_query(
        user_text=f"[HEARTBEAT OTOMATIK GOREV] {gorev}",
        on_direct_text=on_text,
        on_cevap_metni=on_cevap,
    )

    all_output: list[str] = []
    if cevap_metinleri:
        all_output.extend(cevap_metinleri)
    if direct_texts:
        all_output.extend(direct_texts)
    if transcript and not all_output:
        all_output.append(transcript)
    for text in collected_texts:
        if text not in all_output:
            all_output.append(text)

    if notify_telegram and telegram_bot and chat_id and all_output:
        for text in all_output:
            parts = [text[i : i + 4000] for i in range(0, len(text), 4000)]
            for part in parts:
                try:
                    await telegram_bot.send_message(
                        chat_id=chat_id,
                        text=f"💓 *Heartbeat*\n\n{part}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    await telegram_bot.send_message(
                        chat_id=chat_id,
                        text=f"💓 Heartbeat\n\n{part}",
                    )

    print("✅ [Heartbeat] Gorev tamamlandi.")
    return {
        "outputs": all_output,
        "transcript": transcript,
        "direct_texts": direct_texts or [],
        "cevap_metinleri": cevap_metinleri or [],
    }


class HeartbeatService:
    def __init__(self, base_model, telegram_bot=None, chat_id: int | None = None):
        self.base_model = base_model
        self.telegram_bot = telegram_bot
        self.chat_id = chat_id
        self.scheduler = None
        self.stop_event = asyncio.Event()
        self.config_lock = asyncio.Lock()
        self.run_lock = asyncio.Lock()
        self.admission_lock = asyncio.Lock()
        self.ready = False
        self.enabled = False
        self.applied_config: dict[str, Any] = dict(_DEFAULT_CONFIG)
        self.task_map: dict[str, HeartbeatTask] = {}
        self.current_job_id: str | None = None
        self.current_job_started_at: str | None = None
        self.last_reload_at: str | None = None
        self.config_error = ""
        self.last_config_mtime: float | None = None
        self.watch_interval = _WATCH_INTERVAL_SECONDS
        self._progress_last_sent: dict[str, float] = {}

    def _connect_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(_RUNTIME_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _format_busy_error(self, snapshot: dict[str, Any]) -> str:
        owner = snapshot.get("owner") or "bilinmeyen"
        label = snapshot.get("label") or snapshot.get("job_id") or "aktif gorev"
        started_at = snapshot.get("started_at") or ""
        suffix = f" (baslangic: {started_at})" if started_at else ""
        return f"Otomasyon meşgul: {owner} -> {label}{suffix}"

    def _normalize_progress_message(self, raw_text: str) -> tuple[str, str] | None:
        text = str(raw_text or "").strip()
        if not text or text.startswith("[SISTEM_MESAJI_GIZLI]"):
            return None

        match = _PROGRESS_EVENT_RE.match(text)
        if not match:
            return None

        tool_name = match.group("name")
        if tool_name in _TRIVIAL_PROGRESS_TOOLS:
            return None

        emoji = match.group("emoji")
        verb = match.group("verb")
        duration = (match.group("duration") or "").strip()
        is_submodel = emoji == "🤖"
        noun = "Alt ajan" if is_submodel else "Arac"

        if verb == "calistiriliyor":
            message = f"⏳ {noun} basladi: `{tool_name}`"
            signature = f"start:{tool_name}"
        else:
            duration_suffix = f" ({duration})" if duration else ""
            message = f"✅ {noun} bitti: `{tool_name}`{duration_suffix}"
            signature = f"finish:{tool_name}:{duration or 'na'}"

        return message, signature

    async def _send_progress_message(
        self,
        message: str,
        *,
        signature: str | None = None,
        force: bool = False,
    ) -> bool:
        if not message:
            return False

        telegram_bot, chat_id = _resolve_telegram_target(self.telegram_bot, self.chat_id)
        if not telegram_bot or not chat_id:
            return False

        dedupe_key = signature or message
        now_monotonic = time.monotonic()
        if not force:
            last_sent = self._progress_last_sent.get(dedupe_key)
            if last_sent is not None and (now_monotonic - last_sent) < _PROGRESS_DEDUPE_SECONDS:
                return False

        self._progress_last_sent[dedupe_key] = now_monotonic
        rendered = f"💓 Heartbeat\n\n{message}"
        try:
            await telegram_bot.send_message(
                chat_id=chat_id,
                text=rendered,
                parse_mode="Markdown",
            )
        except Exception:
            await telegram_bot.send_message(chat_id=chat_id, text=rendered.replace("`", ""))
        return True

    async def _handle_progress_text(self, raw_text: str) -> bool:
        normalized = self._normalize_progress_message(raw_text)
        if not normalized:
            return False
        message, signature = normalized
        await self._send_progress_message(message, signature=signature)
        return True

    def _init_runtime_db(self) -> None:
        _ensure_runtime_dirs()
        with self._connect_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runtime (
                    job_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    cron TEXT NOT NULL,
                    task_enabled INTEGER NOT NULL DEFAULT 1,
                    paused INTEGER NOT NULL DEFAULT 0,
                    running INTEGER NOT NULL DEFAULT 0,
                    last_run_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    last_duration_ms INTEGER,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT,
                    source_index INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute("UPDATE job_runtime SET running = 0")
            conn.commit()

    def _read_runtime_rows(self) -> dict[str, sqlite3.Row]:
        with self._connect_db() as conn:
            rows = conn.execute("SELECT * FROM job_runtime").fetchall()
        return {row["job_id"]: row for row in rows}

    def _sync_runtime_rows(self, tasks: list[HeartbeatTask]) -> None:
        desired_ids = {task.task_id for task in tasks}
        now_iso = _iso(_now())

        with self._connect_db() as conn:
            for task in tasks:
                conn.execute(
                    """
                    INSERT INTO job_runtime (
                        job_id, name, cron, task_enabled, paused, running,
                        last_run_at, last_status, last_error, last_duration_ms,
                        run_count, updated_at, source_index
                    ) VALUES (?, ?, ?, ?, 0, 0, NULL, NULL, NULL, NULL, 0, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        name = excluded.name,
                        cron = excluded.cron,
                        task_enabled = excluded.task_enabled,
                        source_index = excluded.source_index,
                        updated_at = excluded.updated_at
                    """,
                    (
                        task.task_id,
                        task.name,
                        task.cron,
                        1 if task.enabled else 0,
                        now_iso,
                        task.source_index,
                    ),
                )

            if desired_ids:
                placeholders = ",".join("?" for _ in desired_ids)
                conn.execute(
                    f"DELETE FROM job_runtime WHERE job_id NOT IN ({placeholders})",
                    tuple(desired_ids),
                )
            else:
                conn.execute("DELETE FROM job_runtime")

            conn.commit()

    def _set_job_paused(self, job_id: str, paused: bool) -> None:
        with self._connect_db() as conn:
            conn.execute(
                """
                UPDATE job_runtime
                SET paused = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (1 if paused else 0, _iso(_now()), job_id),
            )
            conn.commit()

    def _set_job_running(self, job_id: str, running: bool, status: str | None = None) -> None:
        with self._connect_db() as conn:
            conn.execute(
                """
                UPDATE job_runtime
                SET running = ?, last_status = COALESCE(?, last_status),
                    last_error = CASE WHEN ? THEN NULL ELSE last_error END,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    1 if running else 0,
                    status,
                    1 if running else 0,
                    _iso(_now()),
                    job_id,
                ),
            )
            conn.commit()

    def _record_job_result(
        self,
        job_id: str,
        *,
        status: str,
        error: str = "",
        duration_ms: int | None = None,
    ) -> None:
        with self._connect_db() as conn:
            conn.execute(
                """
                UPDATE job_runtime
                SET running = 0,
                    last_run_at = ?,
                    last_status = ?,
                    last_error = ?,
                    last_duration_ms = ?,
                    run_count = run_count + 1,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    _iso(_now()),
                    status,
                    error or None,
                    duration_ms,
                    _iso(_now()),
                    job_id,
                ),
            )
            conn.commit()

    def _is_job_paused(self, job_id: str) -> bool:
        row = self._read_runtime_rows().get(job_id)
        return bool(row["paused"]) if row else False

    def _get_scheduler_job(self, job_id: str):
        if not self.scheduler:
            return None
        try:
            return self.scheduler.get_job(job_id)
        except Exception:
            return None

    def _update_last_mtime(self) -> None:
        try:
            self.last_config_mtime = os.path.getmtime(_CONFIG_PATH)
        except OSError:
            self.last_config_mtime = None

    async def start(self) -> None:
        if yaml is None:
            self.config_error = f"PyYAML yuklu degil: {_YAML_IMPORT_ERROR}"
            print(f"⚠️ [Heartbeat] {self.config_error}")
            return

        if AsyncIOScheduler is None:
            self.config_error = f"APScheduler yuklu degil: {_SCHEDULER_IMPORT_ERROR}"
            print(f"⚠️ [Heartbeat] {self.config_error}")
            return

        _ensure_runtime_dirs()
        self._init_runtime_db()

        self.scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(url=f"sqlite:///{_JOBSTORE_PATH}")
            },
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
            timezone=_TIMEZONE,
        )
        self.scheduler.start(paused=True)
        self._update_last_mtime()

        try:
            await self.reload_from_disk(reason="startup")
        except HeartbeatConfigError as exc:
            self.config_error = str(exc)
            print(f"⚠️ [Heartbeat] Ilk config uygulanamadi: {exc}")

        self.ready = True
        print(
            "💓 [Heartbeat] Scheduler hazir"
            f" — {len(self.applied_config.get('tasks', []))} gorev, enabled={self.enabled}"
        )

    async def shutdown(self) -> None:
        self.stop_event.set()
        if self.scheduler:
            jobstores = list(getattr(self.scheduler, "_jobstores", {}).values())
            self.scheduler.shutdown(wait=False)
            for jobstore in jobstores:
                engine = getattr(jobstore, "engine", None)
                if engine is not None:
                    engine.dispose()

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.watch_interval)
            except asyncio.TimeoutError:
                await self._reload_if_file_changed()

    async def _reload_if_file_changed(self) -> None:
        try:
            current_mtime = os.path.getmtime(_CONFIG_PATH)
        except OSError:
            current_mtime = None

        if current_mtime == self.last_config_mtime:
            return

        self.last_config_mtime = current_mtime
        try:
            await self.reload_from_disk(reason="file_watch")
            print("💓 [Heartbeat] Config dosya degisikligi algilandi, scheduler yenilendi.")
        except HeartbeatConfigError as exc:
            self.config_error = str(exc)
            print(f"⚠️ [Heartbeat] Dosya degisikligi gecersiz config urettigi icin uygulanmadi: {exc}")

    async def reload_from_disk(self, reason: str = "reload") -> dict[str, Any]:
        content = read_config_content()
        self._update_last_mtime()
        parsed = parse_config_content(content)
        await self._apply_config(parsed, reason=reason)
        return self.get_status()

    async def _apply_config(self, parsed: dict[str, Any], reason: str) -> None:
        async with self.config_lock:
            if not self.scheduler:
                return

            previous_enabled = self.enabled
            tasks: list[HeartbeatTask] = list(parsed.get("tasks", []) or [])
            self.task_map = {task.task_id: task for task in tasks}
            self.applied_config = parsed
            self._sync_runtime_rows(tasks)

            self.scheduler.pause()

            desired_scheduled_ids = {
                task.task_id
                for task in tasks
                if task.enabled and task.cron != "startup"
            }
            runtime_rows = self._read_runtime_rows()

            for job in self.scheduler.get_jobs():
                if job.id not in desired_scheduled_ids:
                    self.scheduler.remove_job(job.id)

            for task in tasks:
                if task.cron == "startup" or not task.enabled:
                    if self._get_scheduler_job(task.task_id):
                        self.scheduler.remove_job(task.task_id)
                    continue

                existing_job = self._get_scheduler_job(task.task_id)
                runtime_row = runtime_rows.get(task.task_id)
                paused = bool(runtime_row["paused"]) if runtime_row else False
                add_job_kwargs = {
                    "trigger": _build_trigger(task.cron),
                    "args": [task.task_id],
                    "id": task.task_id,
                    "name": task.name,
                    "replace_existing": True,
                }
                next_run_time = getattr(existing_job, "next_run_time", None)
                if next_run_time is not None:
                    add_job_kwargs["next_run_time"] = next_run_time

                self.scheduler.add_job(
                    _scheduled_job_entry,
                    **add_job_kwargs,
                )
                if paused:
                    self.scheduler.pause_job(task.task_id)

            self.enabled = bool(parsed.get("enabled", False))
            self.last_reload_at = _iso(_now())
            self.config_error = ""

            if self.enabled and (reason == "startup" or not previous_enabled):
                startup_tasks = [
                    task
                    for task in tasks
                    if task.enabled and task.cron == "startup" and not self._is_job_paused(task.task_id)
                ]
                if startup_tasks:
                    for task in startup_tasks:
                        await self._run_job(task.task_id, trigger_reason="startup", notify_telegram=True)

            if self.enabled:
                self.scheduler.resume()

    async def pause_job(self, job_id: str) -> dict[str, Any]:
        task = self.task_map.get(job_id)
        if task is None:
            raise KeyError(job_id)

        self._set_job_paused(job_id, True)
        scheduler_job = self._get_scheduler_job(job_id)
        if scheduler_job:
            self.scheduler.pause_job(job_id)
        return self._job_snapshot(task)

    async def resume_job(self, job_id: str) -> dict[str, Any]:
        task = self.task_map.get(job_id)
        if task is None:
            raise KeyError(job_id)

        self._set_job_paused(job_id, False)
        scheduler_job = self._get_scheduler_job(job_id)
        if scheduler_job and task.enabled and self.enabled:
            self.scheduler.resume_job(job_id)
        return self._job_snapshot(task)

    async def run_job_now(self, job_id: str) -> dict[str, Any]:
        task = self.task_map.get(job_id)
        if task is None:
            raise KeyError(job_id)

        async with self.admission_lock:
            if self.run_lock.locked():
                raise RuntimeError(
                    f"Baska bir heartbeat gorevi calisiyor: {self.current_job_id or 'bilinmeyen'}"
                )
            automation_snapshot = get_automation_snapshot()
            if automation_snapshot.get("busy") and automation_snapshot.get("owner") != "heartbeat":
                raise RuntimeError(self._format_busy_error(automation_snapshot))
            await self.run_lock.acquire()
            asyncio.create_task(
                self._run_job(
                    job_id,
                    trigger_reason="manual",
                    notify_telegram=True,
                    reserved_lock=True,
                )
            )

        await asyncio.sleep(0)
        return {
            "status": "accepted",
            "job": self._job_snapshot(task),
            "active_job_id": self.current_job_id or job_id,
        }

    async def _run_job(
        self,
        job_id: str,
        *,
        trigger_reason: str,
        notify_telegram: bool,
        reserved_lock: bool = False,
    ) -> dict[str, Any]:
        task = self.task_map.get(job_id)
        if task is None:
            if reserved_lock and self.run_lock.locked():
                self.run_lock.release()
            raise KeyError(job_id)

        if not reserved_lock:
            async with self.admission_lock:
                if self.run_lock.locked():
                    self._record_job_result(
                        job_id,
                        status="skipped",
                        error=f"Baska job calisiyor: {self.current_job_id or 'bilinmeyen'}",
                    )
                    return {"status": "skipped", "job_id": job_id}
                await self.run_lock.acquire()

        acquired_automation = False
        start_monotonic = time.monotonic()

        try:
            acquired_automation, automation_snapshot = await try_acquire_automation(
                "heartbeat",
                job_id=job_id,
                label=task.name,
                source="heartbeat",
            )
            if not acquired_automation:
                busy_error = self._format_busy_error(automation_snapshot)
                self._record_job_result(job_id, status="skipped", error=busy_error)
                return {"status": "skipped", "job_id": job_id, "error": busy_error}

            self._progress_last_sent = {}
            self.current_job_id = job_id
            self.current_job_started_at = _iso(_now())
            self._set_job_running(job_id, True, status="running")
            await self._send_progress_message(
                f"▶️ Job basladi: *{task.name}* (`{task.task_id}`)",
                signature=f"job_start:{job_id}",
                force=True,
            )

            result = await self._execute_with_retry(
                task,
                trigger_reason=trigger_reason,
                notify_telegram=notify_telegram,
            )
            duration_ms = int((time.monotonic() - start_monotonic) * 1000)
            self._record_job_result(job_id, status="success", duration_ms=duration_ms)
            await self._send_progress_message(
                f"✅ Job bitti: *{task.name}* ({duration_ms} ms)",
                signature=f"job_success:{job_id}:{duration_ms}",
                force=True,
            )
            return {"status": "success", "job_id": job_id, "result": result}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_monotonic) * 1000)
            self._record_job_result(job_id, status="error", error=str(exc), duration_ms=duration_ms)
            await self._send_progress_message(
                f"❌ Job hata verdi: *{task.name}*\n`{str(exc)[:800]}`",
                signature=f"job_error:{job_id}:{str(exc)}",
                force=True,
            )
            print(f"❌ [Heartbeat] Job '{job_id}' hatasi: {exc}")
            return {"status": "error", "job_id": job_id, "error": str(exc)}
        finally:
            self.current_job_id = None
            self.current_job_started_at = None
            if acquired_automation:
                await release_automation("heartbeat", job_id=job_id)
            if self.run_lock.locked():
                self.run_lock.release()

    async def _execute_with_retry(
        self,
        task: HeartbeatTask,
        *,
        trigger_reason: str,
        notify_telegram: bool,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                print(
                    f"💓 [Heartbeat] Tetiklendi: {task.task_id} "
                    f"(cron={task.cron}, reason={trigger_reason}, attempt={attempt})"
                )
                return await _execute_heartbeat_task(
                    self.base_model,
                    task.gorev,
                    telegram_bot=self.telegram_bot,
                    chat_id=self.chat_id,
                    notify_telegram=notify_telegram,
                    progress_handler=self._handle_progress_text,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_RETRY_ATTEMPTS or not _is_retryable_model_error(exc):
                    raise

                delay = _RETRY_DELAYS_SECONDS[min(attempt - 1, len(_RETRY_DELAYS_SECONDS) - 1)]
                print(
                    f"⚠️ [Heartbeat] Gecici model hatasi ({exc}), "
                    f"{delay}sn sonra yeniden denenecek."
                )
                await self._send_progress_message(
                    f"⚠️ Gecici hata: `{task.task_id}` {delay} sn sonra yeniden denenecek.",
                    signature=f"retry:{task.task_id}:{attempt}",
                    force=True,
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Heartbeat gorevi calistirilamadi.")

    def get_status(self) -> dict[str, Any]:
        scheduler_running = bool(self.scheduler and self.scheduler.running)
        scheduled_job_count = len(
            [
                task
                for task in self.applied_config.get("tasks", [])
                if task.enabled and task.cron != "startup"
            ]
        )
        return {
            "ready": self.ready,
            "enabled": self.enabled,
            "running": bool(self.current_job_id),
            "paused": not self.enabled,
            "active_job_id": self.current_job_id,
            "active_job_name": self.task_map.get(self.current_job_id).name if self.current_job_id in self.task_map else "",
            "active_job_started_at": self.current_job_started_at,
            "job_count": len(self.applied_config.get("tasks", [])),
            "scheduled_job_count": scheduled_job_count,
            "last_reload_at": self.last_reload_at,
            "config_valid": not bool(self.config_error),
            "config_error": self.config_error,
            "jobstore_path": _JOBSTORE_PATH,
            "runtime_db_path": _RUNTIME_DB_PATH,
            "legacy_interval_minutes": int(self.applied_config.get("interval_minutes", 30) or 30),
            "scheduler_running": scheduler_running,
        }

    def _job_snapshot(self, task: HeartbeatTask) -> dict[str, Any]:
        runtime_rows = self._read_runtime_rows()
        row = runtime_rows.get(task.task_id)
        scheduler_job = self._get_scheduler_job(task.task_id)

        paused = bool(row["paused"]) if row else False
        running = bool(row["running"]) if row else False
        last_status = row["last_status"] if row else None
        if not task.enabled:
            last_status = "disabled"
        elif running:
            last_status = "running"
        elif paused:
            last_status = "paused"
        elif not last_status:
            last_status = "idle"

        return {
            "job_id": task.task_id,
            "name": task.name,
            "enabled": task.enabled,
            "cron": task.cron,
            "next_run_at": _iso(getattr(scheduler_job, "next_run_time", None)),
            "paused": paused,
            "running": running,
            "last_run_at": row["last_run_at"] if row else None,
            "last_status": last_status,
            "last_error": row["last_error"] if row else None,
            "last_duration_ms": row["last_duration_ms"] if row else None,
            "run_count": row["run_count"] if row else 0,
            "source_index": task.source_index,
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        tasks = sorted(
            self.applied_config.get("tasks", []),
            key=lambda item: item.source_index,
        )
        return [self._job_snapshot(task) for task in tasks]


async def _scheduled_job_entry(job_id: str):
    service = get_heartbeat_service()
    if service is None:
        print(f"⚠️ [Heartbeat] Scheduler entry icin servis bulunamadi: {job_id}")
        return
    await service._run_job(job_id, trigger_reason="schedule", notify_telegram=True)


async def heartbeat_loop(base_model, telegram_bot=None, chat_id: int | None = None):
    """
    APScheduler tabanli heartbeat servisini baslatir ve config degisikliklerini izler.
    """
    global _heartbeat_service

    service = HeartbeatService(base_model, telegram_bot=telegram_bot, chat_id=chat_id)
    _heartbeat_service = service

    try:
        await service.start()
        await service.run()
    finally:
        await service.shutdown()
        if _heartbeat_service is service:
            _heartbeat_service = None


async def test_tick():
    """Config'i dogrular ve normalize edilmis task ozetini gosterir."""
    content = read_config_content()
    meta = summarize_config_content(content)

    print(f"🧪 [Heartbeat Test] Config yolu: {_CONFIG_PATH}")
    print(f"   Gecerli mi: {'evet' if meta['valid'] else 'hayir'}")
    if not meta["valid"]:
        print(f"   Hata: {meta['validation_error']}")
        return

    parsed = parse_config_content(content)
    tasks = parsed.get("tasks", [])
    print(f"   Enabled: {parsed.get('enabled')}")
    print(f"   Legacy interval_minutes: {parsed.get('interval_minutes')}")
    print(f"   Gorev sayisi: {len(tasks)}")
    for task in tasks:
        print(
            f"     - id={task.task_id} cron={task.cron} enabled={task.enabled} "
            f"name={task.name[:48]}"
        )


if __name__ == "__main__":
    import sys

    if "--test-tick" in sys.argv:
        asyncio.run(test_tick())
    else:
        print("Kullanim: python -m MarketingApp.environments.heartbeat --test-tick")
