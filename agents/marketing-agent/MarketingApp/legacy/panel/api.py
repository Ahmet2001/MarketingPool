import asyncio
import ast
import inspect
import os
import json
import time
import subprocess
import shutil
import re
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel as PydanticBaseModel
from typing import Optional, Dict, Any, get_args, get_origin
from dotenv import load_dotenv

from MarketingApp.enviroments.automation_runtime import (
    release_automation,
    try_acquire_automation,
)
from MarketingApp.enviroments import heartbeat as heartbeat_runtime
from MarketingApp.llms.runtime_config import (
    get_tool_generator_model_name,
    get_tool_generator_reasoning_effort,
)

app = FastAPI()

_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("PANEL_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global BaseModel instance
_base_model = None
PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
# Absolute path to workspace
FILE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(FILE_DIR)
WORKSPACE_DIR = os.path.join(FILE_DIR, "workspace")
TARGETS_DIR = os.path.join(WORKSPACE_DIR, "targets")
ROLE_FILE = os.path.join(WORKSPACE_DIR, "role.md")
ENV_FILES = {
    ".env": os.path.join(PROJECT_ROOT, ".env"),
    ".env.local": os.path.join(PROJECT_ROOT, ".env.local"),
    ".env.model": os.path.join(PROJECT_ROOT, ".env.model"),
}

# Ensure directories exist
os.makedirs(TARGETS_DIR, exist_ok=True)
for d in ["code", "drafts", "reports", "assets", ".system"]:
    os.makedirs(os.path.join(WORKSPACE_DIR, d), exist_ok=True)


def _resolve_safe_path(base_dir: str, user_path: str) -> str:
    """İstenen yolun hedef dizin altında kaldığını doğrular."""
    if not user_path:
        raise HTTPException(status_code=400, detail="Path boş olamaz")

    base_real = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base_dir, user_path))

    if os.path.commonpath([base_real, candidate]) != base_real:
        raise HTTPException(status_code=400, detail="Path izin verilen dizin dışında")

    return candidate


def _sanitize_filename(name: str) -> str:
    """Upload ve target isimlerinde dizin kaçışını engeller."""
    cleaned = os.path.basename((name or "").strip())
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    return cleaned

class ContentUpdate(PydanticBaseModel):
    content: str

class MemoryWrite(PydanticBaseModel):
    category: str
    key: str
    value: str

class MemoryDelete(PydanticBaseModel):
    category: str
    key: str

class CodeExecute(PydanticBaseModel):
    filename: str
    input_data: Optional[str] = ""

class TargetSource(PydanticBaseModel):
    type: str  # 'url' or 'text'
    name: str
    content: str

class SocialScanRequest(PydanticBaseModel):
    limit: int = 20

class SocialReplyUpdate(PydanticBaseModel):
    text: str

class SocialQueueStatusUpdate(PydanticBaseModel):
    status: str
    note: str = ""

class SocialDraftRequest(PydanticBaseModel):
    tone: Optional[str] = "samimi, kısa ve doğal"


class SocialBrowserLaunchRequest(PydanticBaseModel):
    headless: bool = False
    restart_if_needed: bool = True


class HeartbeatToggleRequest(PydanticBaseModel):
    enabled: bool


class EnvFileUpdate(PydanticBaseModel):
    target: str
    content: str


class AgentStudioAgentPayload(PydanticBaseModel):
    name: str
    enabled: bool = True
    description: str = ""
    model: str = "default"
    tool_mode: str = "custom"
    system_prompt: str = ""
    tools: list[str] = []
    type: str = "config"


class AgentStudioCustomToolPayload(PydanticBaseModel):
    name: str
    description: str = ""
    code: str
    enabled: bool = True
    params_note: str = ""
    env_vars: Dict[str, Any] = {}


class AgentStudioCustomToolTestPayload(PydanticBaseModel):
    arguments: Dict[str, Any] = {}


class AgentStudioCustomToolGeneratePayload(PydanticBaseModel):
    brief: str
    current_name: str = ""
    current_description: str = ""
    current_code: str = ""
    conversation: list[dict[str, str]] = []


class AgentStudioPackPreviewPayload(PydanticBaseModel):
    path: str


class AgentStudioPackInstallPayload(PydanticBaseModel):
    path: str
    overwrite: bool = False

def set_base_model(bm):
    global _base_model
    _base_model = bm


def _resolve_env_target(target: str) -> tuple[str, str]:
    normalized = (target or "").strip()
    if normalized not in ENV_FILES:
        raise HTTPException(status_code=400, detail="Desteklenmeyen env dosyası")
    return normalized, ENV_FILES[normalized]


def _reload_runtime_env_files():
    env_path = ENV_FILES[".env"]
    env_local_path = ENV_FILES[".env.local"]
    env_model_path = ENV_FILES[".env.model"]
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)
    if os.path.exists(env_local_path):
        load_dotenv(dotenv_path=env_local_path, override=True)
    if os.path.exists(env_model_path):
        load_dotenv(dotenv_path=env_model_path, override=True)


def _busy_http_detail(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": "Otomasyon meşgul",
        "busy_owner": snapshot.get("owner") or "",
        "busy_label": snapshot.get("label") or snapshot.get("job_id") or "",
        "busy_started_at": snapshot.get("started_at"),
        "busy_source": snapshot.get("source") or "",
    }


async def _acquire_panel_mutation(label: str, source: str) -> str:
    job_id = f"panel-{source}-{int(time.time() * 1000)}"
    acquired, snapshot = await try_acquire_automation(
        "panel",
        job_id=job_id,
        label=label,
        source=source,
    )
    if not acquired:
        raise HTTPException(status_code=409, detail=_busy_http_detail(snapshot))
    return job_id


def _load_social_workflow():
    try:
        from MarketingApp.araclar.social_browser_workflow import (
            get_browser_status,
            get_x_queue,
            launch_x_browser,
            mark_queue_item,
            scan_x_page,
            send_x_reply,
            update_queue_item,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sosyal workflow yüklenemedi: {e}")

    return {
        "get_browser_status": get_browser_status,
        "get_x_queue": get_x_queue,
        "launch_x_browser": launch_x_browser,
        "mark_queue_item": mark_queue_item,
        "scan_x_page": scan_x_page,
        "send_x_reply": send_x_reply,
        "update_queue_item": update_queue_item,
    }


def _load_agent_studio_helpers():
    try:
        from MarketingApp.llms.agent_studio import (
            AgentStudioError,
            create_builtin_agent_scaffold,
            delete_agent_config,
            install_agent_pack,
            load_agent_studio_catalog,
            load_custom_tool_callable,
            load_custom_tools_config,
            preview_agent_pack,
            upsert_agent_config,
            upsert_custom_tool,
            validate_tool_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Studio yüklenemedi: {e}")

    return {
        "AgentStudioError": AgentStudioError,
        "create_builtin_agent_scaffold": create_builtin_agent_scaffold,
        "delete_agent_config": delete_agent_config,
        "install_agent_pack": install_agent_pack,
        "load_agent_studio_catalog": load_agent_studio_catalog,
        "load_custom_tool_callable": load_custom_tool_callable,
        "load_custom_tools_config": load_custom_tools_config,
        "preview_agent_pack": preview_agent_pack,
        "upsert_agent_config": upsert_agent_config,
        "upsert_custom_tool": upsert_custom_tool,
        "validate_tool_name": validate_tool_name,
    }


def _short_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _build_tool_generator_live_context(helpers: dict[str, Any]) -> str:
    """Build a fresh, compact Agent Studio map for AI custom tool generation."""
    try:
        catalog = helpers["load_agent_studio_catalog"]()
    except Exception as exc:
        return f"Canli Agent Studio katalogu okunamadi: {exc}"

    agents = catalog.get("agents") if isinstance(catalog.get("agents"), list) else []
    tools = catalog.get("tools") if isinstance(catalog.get("tools"), list) else []
    custom_tools = catalog.get("custom_tools") if isinstance(catalog.get("custom_tools"), list) else []
    paths = catalog.get("paths") if isinstance(catalog.get("paths"), dict) else {}
    errors = catalog.get("errors") if isinstance(catalog.get("errors"), list) else []

    category_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for tool in tools:
        category = str(tool.get("category") or "unknown")
        risk = str(tool.get("risk") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    lines = [
        "Bu bolum her AI tool generate isteginde MarketingApp Agent Studio katalogundan canli uretilir; statik dokuman degildir.",
        "Secret degerleri prompt'a alinmaz. API key ve token gibi degerler .env.model icinde tutulur; tool kodu os.getenv ile okur.",
        "",
        "Onemli yollar:",
    ]
    for key in ("agents_config", "custom_tools_config", "agent_packs_config", "custom_tools_dir", "agent_packs_dir", "submodels_dir", "submodels_init", "model_env"):
        value = paths.get(key)
        if value:
            lines.append(f"- {key}: {value}")

    lines.extend(["", "Runtime agent katalogu:"])
    if agents:
        for agent in agents[:40]:
            configured_tools = agent.get("tools") if isinstance(agent.get("tools"), list) else []
            description = _short_text(agent.get("description"), 120)
            lines.append(
                "- "
                f"{agent.get('name')} | type={agent.get('type', 'config')} | enabled={bool(agent.get('enabled', True))} "
                f"| model={agent.get('model', 'default')} | tool_mode={agent.get('tool_mode', 'default')} "
                f"| selected_tools={len(configured_tools)} | desc={description}"
            )
    else:
        lines.append("- Agent yok veya katalog okunamadi.")

    recommended = catalog.get("recommended_memory_tools") or []
    if recommended:
        lines.append("")
        lines.append("Onerilen hafiza tool'lari: " + ", ".join(map(str, recommended)))

    lines.extend(["", "Tool registry ozeti:"])
    if category_counts:
        lines.append(
            "- Kategoriler: "
            + ", ".join(f"{name}={count}" for name, count in sorted(category_counts.items()))
        )
    if risk_counts:
        lines.append(
            "- Risk seviyeleri: "
            + ", ".join(f"{name}={count}" for name, count in sorted(risk_counts.items()))
        )

    active_by_category: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        if not tool.get("active", True):
            continue
        category = str(tool.get("category") or "unknown")
        active_by_category.setdefault(category, []).append(tool)

    for category in sorted(active_by_category):
        examples = []
        for tool in active_by_category[category][:14]:
            signature = _short_text(tool.get("signature"), 80)
            description = _short_text(tool.get("description"), 80)
            source = tool.get("source") or "builtin"
            risk = tool.get("risk") or "unknown"
            examples.append(f"{tool.get('name')}{signature} [{source}/{risk}] {description}".strip())
        if examples:
            lines.append(f"- {category}: " + " | ".join(examples))

    lines.extend(["", "Custom tool katalogu:"])
    if custom_tools:
        for item in custom_tools[:30]:
            env_vars = item.get("env_vars") if isinstance(item.get("env_vars"), list) else []
            env_label = ", ".join(map(str, env_vars)) if env_vars else "-"
            params_note = _short_text(item.get("params_note"), 140)
            description = _short_text(item.get("description"), 140)
            error = _short_text(item.get("error"), 120) if item.get("error") else ""
            suffix = f" | error={error}" if error else ""
            lines.append(
                f"- {item.get('name')} | enabled={bool(item.get('enabled', False))} "
                f"| env_vars={env_label} | params={params_note} | desc={description}{suffix}"
            )
    else:
        lines.append("- Henuz custom tool yok.")

    packs = catalog.get("packs") if isinstance(catalog.get("packs"), list) else []
    lines.extend(["", "Yuklu pack katalogu:"])
    if packs:
        for item in packs[:24]:
            lines.append(
                f"- {item.get('name')} | type={item.get('type', 'agent_bundle')} | version={item.get('version', '0.1.0')} "
                f"| agents={len(item.get('installed_agents') or [])} | tools={len(item.get('installed_tools') or [])}"
            )
    else:
        lines.append("- Henuz yuklu pack yok.")

    if errors:
        lines.extend(["", "Katalog hatalari/uyarilari:"])
        for item in errors[:12]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('scope', 'unknown')}: {_short_text(item.get('message'), 180)}")
            else:
                lines.append(f"- {_short_text(item, 180)}")

    lines.extend(
        [
            "",
            "Custom tool sozlesmesi:",
            "- Tool dosyalari workspace/custom_tools/ altina kaydedilir ve config/custom_tools.yaml ile kataloglanir.",
            "- Her custom tool ayni isimde tek ana Python fonksiyonu export etmeli.",
            "- Fonksiyon parametreleri basit tiplerle yazilmali; panel test_args JSON'unu bu imzaya gore test eder.",
            "- Env gereksinimi varsa env_vars alaninda sadece degisken adlarini dondur; degerleri kullanicidan alip .env.model dosyasina yazacak panel akisi kullanilir.",
        ]
    )
    return "\n".join(lines)[:12000]


def _json_safe_result(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _model_to_dict(model: PydanticBaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Model JSON obje dondurmedi.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Model cevabi JSON obje degil.")
    return parsed


def _strip_code_fence(text: str) -> str:
    code = (text or "").strip()
    if code.startswith("```"):
        code = re.sub(r"^```(?:python|py)?\s*", "", code, flags=re.IGNORECASE)
        code = re.sub(r"\s*```$", "", code)
    return code.strip()


def _first_function_name(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return ""


def _slug_tool_name(text: str, fallback: str = "ai_custom_tool") -> str:
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    normalized = (text or "").translate(tr_map).lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = fallback
    normalized = re.sub(r"_+", "_", normalized)[:48].strip("_") or fallback
    if len(normalized) < 3:
        normalized = fallback
    return normalized


def _normalize_generated_payload(payload: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    data = dict(payload or {})
    code = (
        data.get("code")
        or data.get("python_code")
        or data.get("function_code")
        or data.get("tool_code")
        or ""
    )
    data["code"] = _strip_code_fence(str(code))
    candidate_name = str(data.get("name") or "").strip()
    if not candidate_name:
        candidate_name = _first_function_name(data["code"]) or fallback_name
    data["name"] = candidate_name
    if not data.get("description"):
        data["description"] = "AI tarafindan uretilen custom tool."
    if isinstance(data.get("params_note"), dict):
        data["params_note"] = json.dumps(data["params_note"], ensure_ascii=False)
    return data


def _validate_generated_tool_payload(payload: dict[str, Any], validate_tool_name_func, fallback_name: str = "ai_custom_tool") -> dict[str, Any]:
    payload = _normalize_generated_payload(payload, fallback_name)
    code = str(payload.get("code") or "").strip()
    if not code:
        raise ValueError("AI tool kodu bos geldi.")

    first_func_name = _first_function_name(code)
    raw_name = str(payload.get("name") or "").strip()
    try:
        name = validate_tool_name_func(raw_name)
    except Exception:
        name = validate_tool_name_func(first_func_name or fallback_name)

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"AI tool kodunda syntax hatasi: {exc}") from exc

    function_names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if name not in function_names:
        if len(function_names) == 1:
            name = validate_tool_name_func(function_names[0])
        else:
            raise ValueError(f"AI kodu `{name}` fonksiyonunu tanimlamiyor.")

    return {
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "params_note": str(payload.get("params_note") or "").strip(),
        "test_args": payload.get("test_args") if isinstance(payload.get("test_args"), dict) else {},
        "env_vars": payload.get("env_vars") if isinstance(payload.get("env_vars"), dict) else {},
        "code": code + ("\n" if not code.endswith("\n") else ""),
    }


def _fallback_generated_tool_payload(brief: str, validate_tool_name_func) -> dict[str, Any]:
    name = validate_tool_name_func(_slug_tool_name(brief, "ai_custom_tool"))
    code = (
        f"def {name}(text: str = \"\") -> dict:\n"
        "    \"\"\"AI tool uretimi JSON onarimindan gecemediginde olusan guvenli taslak.\"\"\"\n"
        "    return {\n"
        "        \"status\": \"draft\",\n"
        "        \"message\": \"Bu guvenli iskelet tool'dur; kodu ihtiyaca gore duzenleyip test edin.\",\n"
        f"        \"brief\": {json.dumps(brief[:500], ensure_ascii=False)},\n"
        "        \"input\": text,\n"
        "    }\n"
    )
    return {
        "name": name,
        "description": "AI ciktisi onarilamadigi icin olusturulan guvenli custom tool taslagi.",
        "params_note": "{\"text\": \"ornek metin\"}",
        "test_args": {"text": "ornek metin"},
        "env_vars": {},
        "code": code,
    }


def _annotation_from_string(annotation: str):
    normalized = annotation.strip().lower()
    aliases = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "number": float,
        "bool": bool,
        "boolean": bool,
        "dict": dict,
        "list": list,
    }
    return aliases.get(normalized, annotation)


def _coerce_value_for_annotation(value: Any, annotation: Any) -> Any:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return value
    if isinstance(annotation, str):
        annotation = _annotation_from_string(annotation)

    origin = get_origin(annotation)
    if origin is not None:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if args:
            return _coerce_value_for_annotation(value, args[0])

    if value is None:
        return None
    if annotation is str:
        return str(value)
    if annotation is int and not isinstance(value, bool):
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            return int(value.strip())
    if annotation is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            return float(value.strip().replace(",", "."))
    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "evet", "on"}:
                return True
            if normalized in {"false", "0", "no", "hayir", "hayır", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
    if annotation in {dict, list} and isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, annotation):
            return parsed
    return value


def _coerce_custom_tool_args(func, args: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    coerced = {}
    for name, value in args.items():
        param = sig.parameters.get(name)
        if not param:
            coerced[name] = value
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty and param.default is not inspect.Parameter.empty and param.default is not None:
            annotation = type(param.default)
        try:
            coerced[name] = _coerce_value_for_annotation(value, annotation)
        except Exception:
            coerced[name] = value
    return coerced


def _build_agent_studio_snapshot() -> dict[str, Any]:
    try:
        helpers = _load_agent_studio_helpers()
        return helpers["load_agent_studio_catalog"]()
    except HTTPException as exc:
        return {
            "agents": [],
            "tools": [],
            "custom_tools": [],
            "packs": [],
            "recommended_memory_tools": [],
            "paths": {},
            "errors": [{"scope": "agent_studio", "message": str(exc.detail)}],
        }


def _build_social_snapshot() -> dict[str, Any]:
    try:
        workflow = _load_social_workflow()
        return {
            "browser": workflow["get_browser_status"](),
            "queue": workflow["get_x_queue"](),
        }
    except HTTPException as exc:
        return {
            "browser": {
                "ready": False,
                "title": "",
                "url": "",
                "window_count": 0,
                "error": exc.detail,
            },
            "queue": {
                "platform": "x",
                "updated_at": "",
                "items": [],
            },
        }


def _extract_model_text(result: Any) -> str:
    if isinstance(result, tuple) and len(result) >= 4:
        _audio, transcript, direct_texts, cevap_metinleri = result
        texts = []
        if isinstance(cevap_metinleri, list):
            texts.extend([str(item).strip() for item in cevap_metinleri if str(item).strip()])
        if isinstance(direct_texts, list):
            texts.extend([str(item).strip() for item in direct_texts if str(item).strip()])
        if transcript:
            texts.append(str(transcript).strip())
        if texts:
            return texts[0]
    if isinstance(result, str):
        return result.strip()
    return ""


def _get_heartbeat_config_path() -> str:
    return os.path.join(FILE_DIR, "config", "heartbeat_config.yaml")


def _read_heartbeat_content() -> str:
    config_path = _get_heartbeat_config_path()
    if not os.path.exists(config_path):
        return ""
    with open(config_path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_heartbeat_meta(content: str) -> dict[str, Any]:
    return heartbeat_runtime.summarize_config_content(content)


async def _generate_social_reply(item: dict[str, Any], tone: str) -> str:
    author = item.get("author_name") or item.get("author_handle") or "kullanici"
    comment = (item.get("text") or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Taslak üretmek için yorum metni bulunamadı")

    if _base_model:
        prompt = (
            "Asagidaki sosyal medya yorumuna Turkce bir cevap taslagi yaz. "
            "Cevap en fazla 2 cumle olsun, dogal dursun, karsi tarafin yorumuna direkt baglansin, "
            "fazla kurumsal olmasin, hashtag ve emoji kullanma. "
            f"Istenen ton: {tone or 'samimi, kısa ve doğal'}.\n\n"
            f"Yorum sahibi: {author}\n"
            f"Yorum: {comment}\n\n"
            "Sadece gonderilecek cevap metnini dondur."
        )
        try:
            result = await _base_model.text_query(prompt)
            generated = _extract_model_text(result)
            if generated:
                return generated
        except Exception:
            pass

    if "?" in comment:
        return "Tesekkurler, bunu not aldik. Biraz daha detay paylasirsan net yardimci olabiliriz."
    return "Yorumun icin tesekkurler, bunu gormek guzel. Istersen detayini biraz daha acabiliriz."


@app.get("/panel", include_in_schema=False)
@app.get("/panel/", include_in_schema=False)
async def serve_panel():
    return FileResponse(os.path.join(PANEL_DIR, "index.html"))


@app.get("/panel/{asset_path:path}", include_in_schema=False)
async def serve_panel_assets(asset_path: str):
    safe_asset_path = _resolve_safe_path(PANEL_DIR, asset_path)
    allowed_exts = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico"}
    if os.path.splitext(safe_asset_path)[1].lower() not in allowed_exts:
        raise HTTPException(status_code=404, detail="Panel asset not found")
    if not os.path.exists(safe_asset_path) or os.path.isdir(safe_asset_path):
        raise HTTPException(status_code=404, detail="Panel asset not found")
    return FileResponse(safe_asset_path)

@app.get("/api/system/status")
async def get_status():
    if not _base_model:
        return {"status": "Offline", "uptime": 0}
    return {
        "status": "Online",
        "uptime": int(time.time() - getattr(_base_model, 'start_time', time.time())),
        "model": getattr(_base_model, 'model', 'Unknown')
    }

@app.get("/api/hierarchy")
async def get_hierarchy():
    if not _base_model:
        return {"tools": [], "submodels": []}
    return _base_model.get_hierarchy()


@app.get("/api/panel/bootstrap")
async def get_panel_bootstrap():
    """Panelin ilk açılışında ihtiyaç duyduğu temel verileri tek istekte döner."""
    return {
        "system": await get_status(),
        "hierarchy": await get_hierarchy(),
        "logs": await get_logs(),
        "stats": await get_stats(),
        "pending_actions": await get_pending_actions(),
        "skills": await get_skills_list(),
        "heartbeat": await get_heartbeat_config(),
        "heartbeat_status": await get_heartbeat_status(),
        "heartbeat_jobs": await get_heartbeat_jobs(),
        "social": _build_social_snapshot(),
        "agent_studio": _build_agent_studio_snapshot(),
    }

@app.post("/api/agents/{name}/toggle")
async def toggle_agent(name: str):
    if not _base_model or not hasattr(_base_model, 'active_agents'):
        raise HTTPException(status_code=500, detail="BaseModel not ready")

    try:
        active = _base_model.toggle_agent(name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")

    hierarchy = _base_model.get_hierarchy()
    agent_info = next((agent for agent in hierarchy.get("submodels", []) if agent.get("name") == name), None)
    return {"name": name, "active": active, "agent": agent_info, "hierarchy": hierarchy}

@app.post("/api/tools/{name}/toggle")
async def toggle_tool(name: str):
    if not _base_model or not hasattr(_base_model, 'active_tools'):
        raise HTTPException(status_code=500, detail="BaseModel not ready")

    try:
        if hasattr(_base_model, "toggle_tool"):
            active = _base_model.toggle_tool(name)
        else:
            if name not in _base_model.active_tools:
                raise KeyError(name)
            current = _base_model.active_tools[name]
            _base_model.active_tools[name] = not current
            active = not current
    except KeyError:
        raise HTTPException(status_code=404, detail="Tool not found")

    return {
        "name": name,
        "active": active,
        "hierarchy": _base_model.get_hierarchy() if hasattr(_base_model, "get_hierarchy") else None,
    }


@app.get("/api/agent-studio/catalog")
async def get_agent_studio_catalog():
    payload = _build_agent_studio_snapshot()
    payload["hierarchy"] = _base_model.get_hierarchy() if _base_model else {"tools": [], "submodels": []}
    return payload


@app.post("/api/agent-studio/packs/preview")
async def preview_agent_studio_pack(data: AgentStudioPackPreviewPayload):
    helpers = _load_agent_studio_helpers()
    try:
        preview = helpers["preview_agent_pack"](data.path)
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "preview": preview}


@app.post("/api/agent-studio/packs/install")
async def install_agent_studio_pack(data: AgentStudioPackInstallPayload):
    helpers = _load_agent_studio_helpers()
    try:
        result = helpers["install_agent_pack"](data.path, overwrite=bool(data.overwrite))
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {
        "status": "success",
        "pack": result.get("pack"),
        "catalog": _build_agent_studio_snapshot(),
        "hierarchy": hierarchy,
        "restart_required": _base_model is None,
    }


@app.post("/api/agent-studio/agents")
async def create_agent_studio_agent(data: AgentStudioAgentPayload):
    helpers = _load_agent_studio_helpers()
    try:
        saved = helpers["upsert_agent_config"](_model_to_dict(data), create=True)
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {"status": "success", "agent": saved, "catalog": _build_agent_studio_snapshot(), "hierarchy": hierarchy}


@app.post("/api/agent-studio/builtin-agents")
async def create_agent_studio_builtin_agent(data: AgentStudioAgentPayload):
    helpers = _load_agent_studio_helpers()
    payload = _model_to_dict(data)
    payload["type"] = "builtin"
    try:
        scaffold = helpers["create_builtin_agent_scaffold"](payload)
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {
        "status": "success",
        "agent": scaffold["agent"],
        "path": scaffold["path"],
        "init_path": scaffold["init_path"],
        "catalog": _build_agent_studio_snapshot(),
        "hierarchy": hierarchy,
    }


@app.put("/api/agent-studio/agents/{name}")
async def update_agent_studio_agent(name: str, data: AgentStudioAgentPayload):
    helpers = _load_agent_studio_helpers()
    payload = _model_to_dict(data)
    payload["name"] = name
    try:
        saved = helpers["upsert_agent_config"](payload, create=False)
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {"status": "success", "agent": saved, "catalog": _build_agent_studio_snapshot(), "hierarchy": hierarchy}


@app.delete("/api/agent-studio/agents/{name}")
async def delete_agent_studio_agent(name: str):
    helpers = _load_agent_studio_helpers()
    try:
        deleted = helpers["delete_agent_config"](name)
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {"status": "success", "agent": deleted, "catalog": _build_agent_studio_snapshot(), "hierarchy": hierarchy}


@app.post("/api/agent-studio/custom-tools")
async def save_agent_studio_custom_tool(data: AgentStudioCustomToolPayload):
    helpers = _load_agent_studio_helpers()
    try:
        saved = helpers["upsert_custom_tool"](
            data.name,
            data.description,
            data.code,
            enabled=data.enabled,
            params_note=data.params_note,
            env_vars=data.env_vars,
        )
    except helpers["AgentStudioError"] as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {"status": "success", "custom_tool": saved, "catalog": _build_agent_studio_snapshot(), "hierarchy": hierarchy}


@app.post("/api/agent-studio/custom-tools/generate")
async def generate_agent_studio_custom_tool(data: AgentStudioCustomToolGeneratePayload):
    if not _base_model:
        raise HTTPException(status_code=503, detail="AI tool uretimi icin BaseModel hazir degil")
    brief = (data.brief or "").strip()
    if len(brief) < 8:
        raise HTTPException(status_code=400, detail="Tool brief'i biraz daha acik olmali")

    helpers = _load_agent_studio_helpers()
    live_context = _build_tool_generator_live_context(helpers)
    system_prompt = (
        "Sen MarketingApp Agent Studio icin Python custom tool yazan kidemli bir muhendissin. "
        "Sadece JSON obje dondur. Markdown, aciklama metni veya code fence kullanma.\n\n"
        "Eger tool'u guvenli ve dogru yazmak icin kritik bilgi eksikse tool kodu yazma; soru soran JSON dondur:\n"
        '{ "needs_input": true, "message": "Kisa aciklama", "questions": ["Soru 1", "Soru 2"] }\n\n'
        "Bilgi yeterliyse tool JSON semasi:\n"
        "{\n"
        '  "name": "kucuk_harf_tool_adi",\n'
        '  "description": "Panelde gorunecek kisa aciklama",\n'
        '  "params_note": "{\\"ornek_param\\": \\"ornek\\"}",\n'
        '  "test_args": {"ornek_param": "ornek"},\n'
        '  "env_vars": {"API_KEY_ADI": ""},\n'
        '  "code": "def kucuk_harf_tool_adi(...):\\n    ...\\n"\n'
        "}\n\n"
        "Kurallar:\n"
        "- name regex: ^[a-z][a-z0-9_]{2,63}$\n"
        "- code ayni isimde tek ana fonksiyon export etmeli.\n"
        "- Fonksiyon tipi str veya dict dondurmeli.\n"
        "- Standart kutuphane kullanabilirsin.\n"
        "- API key gerekiyorsa env_vars icinde BUYUK_HARF_KEY_ADI: \"\" ver ve kodda os.getenv(\"BUYUK_HARF_KEY_ADI\") kullan.\n"
        "- Kullanici acikca istemedikce dosya sistemi, subprocess, eval/exec, browser veya ilgisiz gizli env okuma kullanma.\n"
        "- Hata durumlarini try/except ile okunabilir str/dict olarak dondur.\n"
        "- Kod Turkce kullaniciya uygun, sade ve test edilebilir olsun.\n"
        "\nCANLI PROJE KATALOGU:\n"
        f"{live_context}\n"
    )
    user_prompt = (
        f"Kullanici tool istegi:\n{brief}\n\n"
        f"Mevcut tool adi taslagi: {data.current_name or '(bos)'}\n"
        f"Mevcut aciklama taslagi: {data.current_description or '(bos)'}\n"
    )
    if data.conversation:
        history = []
        for item in data.conversation[-8:]:
            role = (item.get("role") or "user").strip()
            content = (item.get("content") or "").strip()
            if content:
                history.append(f"{role}: {content}")
        if history:
            user_prompt += "\nOnceki AI brief konusmasi:\n" + "\n".join(history) + "\n"
    if data.current_code.strip():
        user_prompt += f"\nMevcut kod taslagi:\n{data.current_code[:3000]}\n"

    fallback_name = _slug_tool_name(data.current_name or brief, "ai_custom_tool")
    raw_attempts: list[str] = []
    tool_generator_model = get_tool_generator_model_name()
    tool_generator_reasoning_effort = get_tool_generator_reasoning_effort()
    try:
        create_kwargs = {
            "model": tool_generator_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if tool_generator_reasoning_effort:
            create_kwargs["reasoning_effort"] = tool_generator_reasoning_effort
        completion = await _base_model._client.chat.completions.create(**create_kwargs)
        raw_text = completion.choices[0].message.content or ""
        raw_attempts.append(raw_text)
    except Exception:
        try:
            fallback_kwargs = {
                "model": tool_generator_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            if tool_generator_reasoning_effort:
                fallback_kwargs["reasoning_effort"] = tool_generator_reasoning_effort
            completion = await _base_model._client.chat.completions.create(**fallback_kwargs)
            raw_text = completion.choices[0].message.content or ""
            raw_attempts.append(raw_text)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"AI tool uretimi basarisiz: {exc}")

    validation_error = None
    try:
        parsed_payload = _extract_json_object(raw_text)
        if parsed_payload.get("needs_input"):
            questions = parsed_payload.get("questions") if isinstance(parsed_payload.get("questions"), list) else []
            return {
                "status": "needs_input",
                "message": str(parsed_payload.get("message") or "Tool'u netlestirmek icin birkaç bilgi lazim."),
                "questions": [str(item) for item in questions],
            }
        generated = _validate_generated_tool_payload(
            parsed_payload,
            helpers["validate_tool_name"],
            fallback_name=fallback_name,
        )
    except Exception as exc:
        validation_error = exc
        repair_prompt = (
            "Asagidaki model cevabini gecerli JSON objesine cevir. Sadece JSON dondur. "
            "Kod string'i JSON icinde dogru escape edilmeli. name regex'e uymali ve code ayni isimde fonksiyon tanimlamali.\n\n"
            f"Beklenen fallback name: {fallback_name}\n"
            f"Orijinal brief:\n{brief}\n\n"
            f"Bozuk cevap:\n{raw_text[:7000]}"
        )
        try:
            repair_kwargs = {
                "model": tool_generator_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": repair_prompt},
                ],
                "response_format": {"type": "json_object"},
            }
            if tool_generator_reasoning_effort:
                repair_kwargs["reasoning_effort"] = tool_generator_reasoning_effort
            completion = await _base_model._client.chat.completions.create(**repair_kwargs)
            repaired_text = completion.choices[0].message.content or ""
            raw_attempts.append(repaired_text)
            parsed_repaired = _extract_json_object(repaired_text)
            if parsed_repaired.get("needs_input"):
                questions = parsed_repaired.get("questions") if isinstance(parsed_repaired.get("questions"), list) else []
                return {
                    "status": "needs_input",
                    "message": str(parsed_repaired.get("message") or "Tool'u netlestirmek icin birkaç bilgi lazim."),
                    "questions": [str(item) for item in questions],
                }
            generated = _validate_generated_tool_payload(
                parsed_repaired,
                helpers["validate_tool_name"],
                fallback_name=fallback_name,
            )
        except Exception as repair_exc:
            generated = _fallback_generated_tool_payload(brief, helpers["validate_tool_name"])
            generated["warning"] = (
                "AI ciktisi otomatik dogrulanamadi; guvenli iskelet tool dolduruldu. "
                f"Ilk hata: {validation_error}. Onarim hatasi: {repair_exc}"
            )
            generated["raw_preview"] = (raw_attempts[-1] if raw_attempts else raw_text)[:1200]

    if _base_model and hasattr(_base_model, "log_message"):
        _base_model.log_message("sistem", f"AI custom tool taslagi uretildi: {generated['name']}")

    return {"status": "success", "tool": generated}


@app.post("/api/agent-studio/custom-tools/{name}/test")
async def test_agent_studio_custom_tool(name: str, data: AgentStudioCustomToolTestPayload):
    helpers = _load_agent_studio_helpers()
    config = helpers["load_custom_tools_config"]()
    entry = next((item for item in config.get("custom_tools", []) if item.get("name") == name), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Custom tool bulunamadi")

    func, error = helpers["load_custom_tool_callable"](entry, include_disabled=True)
    if error or not func:
        raise HTTPException(status_code=400, detail=error or "Custom tool yuklenemedi")

    args = data.arguments or {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="arguments dict olmali")
    coerced_args = _coerce_custom_tool_args(func, args)

    try:
        if inspect.iscoroutinefunction(func):
            result = await asyncio.wait_for(func(**coerced_args), timeout=20)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(func, **coerced_args), timeout=20)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Custom tool test zaman asimina ugradi")
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Arguman hatasi: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Custom tool hatasi: {exc}. Kullanilan argumanlar: {coerced_args}")

    return {"status": "success", "name": name, "arguments": coerced_args, "result": _json_safe_result(result)}


@app.post("/api/agent-studio/reload")
async def reload_agent_studio_runtime():
    hierarchy = None
    if _base_model and hasattr(_base_model, "reload_agent_studio"):
        hierarchy = _base_model.reload_agent_studio()
    return {
        "status": "success",
        "hierarchy": hierarchy,
        "catalog": _build_agent_studio_snapshot(),
        "restart_required": _base_model is None,
    }


@app.get("/api/env")
async def get_env_content(target: str = ".env"):
    normalized, path = _resolve_env_target(target)
    content = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    return {
        "target": normalized,
        "path": path,
        "exists": os.path.exists(path),
        "content": content,
        "available_targets": list(ENV_FILES.keys()),
    }


@app.post("/api/env")
async def update_env_content(data: EnvFileUpdate):
    normalized, path = _resolve_env_target(data.target)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data.content)

    _reload_runtime_env_files()

    if _base_model:
        _base_model.log_message("sistem", f"Env dosyasi guncellendi: {normalized}")

    return {
        "status": "success",
        "target": normalized,
        "path": path,
        "message": f"{normalized} kaydedildi.",
    }

# --- SMART MEMORY ---
@app.get("/api/memory/raw")
async def get_memory_raw():
    from MarketingApp.araclar.bellek_araclari import _yukle_bellek
    return _yukle_bellek()

@app.post("/api/memory/raw")
async def set_memory_raw(data: Dict[str, Any]):
    from MarketingApp.araclar.bellek_araclari import _kaydet_bellek
    _kaydet_bellek(data)
    return {"status": "success"}

@app.post("/api/memory/write")
async def write_memory(data: MemoryWrite):
    from MarketingApp.araclar.bellek_araclari import bellek_yaz
    res = bellek_yaz(data.category, data.key, data.value)
    return {"status": "success", "message": res}

@app.post("/api/memory/delete")
async def delete_memory(data: MemoryDelete):
    from MarketingApp.araclar.bellek_araclari import bellek_sil
    res = bellek_sil(data.category, data.key)
    return {"status": "success", "message": res}

@app.get("/api/persona")
async def get_persona():
    if os.path.exists(ROLE_FILE):
        with open(ROLE_FILE, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    return {"content": ""}

@app.post("/api/persona")
async def update_persona(data: ContentUpdate):
    with open(ROLE_FILE, "w", encoding="utf-8") as f:
        f.write(data.content)
    return {"status": "success"}

# --- WORKSPACE & CODE SANDBOX ---

@app.get("/api/workspace/tree")
async def get_workspace_tree():
    def build_tree(path):
        name = os.path.basename(path)
        # Avoid relpath issues on network drives by using string replace
        rel_path = path.replace(WORKSPACE_DIR, "").lstrip(os.sep).lstrip("/")
        item = {"name": name, "path": rel_path if rel_path else "."}
        if os.path.isdir(path):
            item["type"] = "directory"
            item["children"] = [build_tree(os.path.join(path, f)) for f in os.listdir(path)]
        else:
            item["type"] = "file"
            item["size"] = os.path.getsize(path)
        return item
    
    if not os.path.exists(WORKSPACE_DIR): return []
    try:
        nodes = [build_tree(os.path.join(WORKSPACE_DIR, f)) for f in os.listdir(WORKSPACE_DIR)]
        return nodes
    except Exception as e:
        return [{"name": "Error", "type": "file", "path": str(e)}]

@app.get("/api/workspace/read")
async def read_file(path: str):
    full_path = _resolve_safe_path(WORKSPACE_DIR, path)
    if os.path.exists(full_path) and not os.path.isdir(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/workspace/execute")
async def execute_code(data: CodeExecute):
    # Kısıtlı sandbox
    full_path = _resolve_safe_path(WORKSPACE_DIR, data.filename)
    if not os.path.exists(full_path) or not full_path.endswith('.py'):
        raise HTTPException(status_code=400, detail="Sadece .py dosyaları çalıştırılabilir.")
    
    try:
        # Use python from env or direct path if needed
        py_cmd = "python"
        process = subprocess.Popen(
            [py_cmd, full_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.path.dirname(full_path)
        )
        stdout, stderr = process.communicate(input=data.input_data, timeout=30)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode
        }
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode,
            "error": "Kod çalıştırma zaman aşımına uğradı (30s)"
        }
    except Exception as e:
        return {"error": str(e)}

# --- TARGETS ---
@app.post("/api/workspace/targets/upload")
async def upload_target(file: UploadFile = File(...)):
    safe_name = _sanitize_filename(file.filename)
    file_path = _resolve_safe_path(TARGETS_DIR, safe_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "filename": safe_name}

@app.post("/api/workspace/targets/add")
async def add_target_source(data: TargetSource):
    if data.type not in {"url", "text"}:
        raise HTTPException(status_code=400, detail="Target type sadece 'url' veya 'text' olabilir")

    ext = ".url" if data.type == "url" else ".txt"
    base_name = _sanitize_filename(data.name)
    filename = base_name + ext if not base_name.endswith(ext) else base_name
    file_path = _resolve_safe_path(TARGETS_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(data.content)
    return {"status": "success", "filename": filename}

# --- OTHER ---
@app.get("/api/logs")
async def get_logs():
    if not _base_model or not hasattr(_base_model, 'logs'): return []
    return _base_model.logs[-50:]

@app.get("/api/stats")
async def get_stats():
    if not _base_model or not hasattr(_base_model, 'metrics'): return []
    return _base_model.metrics[-20:]

@app.get("/api/actions/pending")
async def get_pending_actions():
    if not _base_model or not hasattr(_base_model, 'pending_actions'): return []
    return [
        {"id": k, "description": v["description"]}
        for k, v in _base_model.pending_actions.items()
        if v["status"] == "pending"
    ]

@app.post("/api/actions/{action_id}/{decision}")
async def decide_action(action_id: str, decision: str):
    if not _base_model or action_id not in _base_model.pending_actions:
        raise HTTPException(status_code=404, detail="Action not found")
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision 'approve' veya 'reject' olmalı")
    _base_model.pending_actions[action_id]["status"] = "approved" if decision == "approve" else "rejected"
    _base_model.pending_actions[action_id]["event"].set()
    return {"status": "success"}

# --- SKILL PLUGIN SİSTEMİ ---

@app.get("/api/skills")
async def get_skills_list():
    """Tüm yüklü skill'leri listeler."""
    from MarketingApp.araclar.skill_loader import list_skills
    return list_skills()

@app.post("/api/skills/{name}/toggle")
async def toggle_skill(name: str):
    """Bir skill'i etkinleştirir veya devre dışı bırakır."""
    from MarketingApp.araclar.skill_loader import get_skills, enable_skill, disable_skill
    skills = get_skills()
    if name not in skills:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' bulunamadı")
    
    if skills[name]["enabled"]:
        disable_skill(name)
        return {"name": name, "enabled": False}
    else:
        success = enable_skill(name)
        return {"name": name, "enabled": success}

@app.post("/api/skills/reload")
async def reload_skills():
    """Tüm skill'leri yeniden yükler (hot-reload)."""
    from MarketingApp.araclar.skill_loader import load_skills
    loaded = load_skills()
    return {"status": "success", "count": len(loaded)}

# --- HEARTBEAT ---

@app.get("/api/heartbeat/config")
async def get_heartbeat_config():
    """Heartbeat yapılandırmasını döner."""
    content = _read_heartbeat_content()
    return {
        "content": content,
        **_parse_heartbeat_meta(content),
    }

@app.post("/api/heartbeat/config")
async def update_heartbeat_config(data: ContentUpdate):
    """Heartbeat yapılandırmasını günceller."""
    try:
        heartbeat_runtime.parse_config_content(data.content)
    except heartbeat_runtime.HeartbeatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    config_path = _get_heartbeat_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(data.content)

    runtime_error = None
    try:
        await heartbeat_runtime.reload_heartbeat_service(reason="api_config_update")
    except RuntimeError as exc:
        runtime_error = str(exc)
    except heartbeat_runtime.HeartbeatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "success",
        "runtime_error": runtime_error,
        **_parse_heartbeat_meta(data.content),
    }


@app.post("/api/heartbeat/toggle")
async def toggle_heartbeat(data: HeartbeatToggleRequest):
    """Heartbeat'i panelden hızlıca açıp kapatır."""
    content = _read_heartbeat_content()
    updated_content = heartbeat_runtime.set_enabled_in_content(content, data.enabled)
    try:
        heartbeat_runtime.parse_config_content(updated_content)
    except heartbeat_runtime.HeartbeatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    config_path = _get_heartbeat_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(updated_content)

    runtime_error = None
    try:
        await heartbeat_runtime.reload_heartbeat_service(reason="api_toggle")
    except RuntimeError as exc:
        runtime_error = str(exc)
    except heartbeat_runtime.HeartbeatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "success",
        "content": updated_content,
        "runtime_error": runtime_error,
        **_parse_heartbeat_meta(updated_content),
    }


@app.get("/api/heartbeat/status")
async def get_heartbeat_status():
    return heartbeat_runtime.get_heartbeat_status_snapshot()


@app.get("/api/heartbeat/jobs")
async def get_heartbeat_jobs():
    return heartbeat_runtime.get_heartbeat_jobs_snapshot()


@app.post("/api/heartbeat/reload")
async def reload_heartbeat():
    try:
        status = await heartbeat_runtime.reload_heartbeat_service(reason="api_reload")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except heartbeat_runtime.HeartbeatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "success",
        "heartbeat_status": status,
        "heartbeat_jobs": heartbeat_runtime.get_heartbeat_jobs_snapshot(),
    }


@app.post("/api/heartbeat/jobs/{job_id}/pause")
async def pause_heartbeat_job_endpoint(job_id: str):
    try:
        job = await heartbeat_runtime.pause_heartbeat_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Heartbeat job bulunamadi")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"status": "success", "job": job}


@app.post("/api/heartbeat/jobs/{job_id}/resume")
async def resume_heartbeat_job_endpoint(job_id: str):
    try:
        job = await heartbeat_runtime.resume_heartbeat_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Heartbeat job bulunamadi")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"status": "success", "job": job}


@app.post("/api/heartbeat/jobs/{job_id}/run")
async def run_heartbeat_job_endpoint(job_id: str):
    try:
        result = await heartbeat_runtime.run_heartbeat_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Heartbeat job bulunamadi")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result

# --- SOCIAL BROWSER WORKFLOW ---

@app.get("/api/social/browser/status")
async def get_social_browser_status():
    workflow = _load_social_workflow()
    return workflow["get_browser_status"]()


@app.post("/api/social/browser/launch")
async def launch_social_browser(data: SocialBrowserLaunchRequest):
    lease_id = await _acquire_panel_mutation("Panel tarayici baslatma", "social_browser_launch")
    workflow = _load_social_workflow()
    try:
        return workflow["launch_x_browser"](
            headless=data.headless,
            restart_if_needed=data.restart_if_needed,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Tarayici baslatilamadi: {e}")
    finally:
        await release_automation("panel", job_id=lease_id)


@app.get("/api/social/x/queue")
async def get_social_x_queue():
    workflow = _load_social_workflow()
    return workflow["get_x_queue"]()


@app.post("/api/social/x/scan")
async def social_scan_x_page(data: SocialScanRequest):
    lease_id = await _acquire_panel_mutation("Panel X tarama", "social_x_scan")
    workflow = _load_social_workflow()
    limit = max(1, min(int(data.limit or 20), 50))
    try:
        return workflow["scan_x_page"](limit=limit)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"X sayfasi taranamadi: {e}")
    finally:
        await release_automation("panel", job_id=lease_id)


@app.post("/api/social/x/queue/{queue_id}/draft")
async def social_generate_x_draft(queue_id: str, data: SocialDraftRequest):
    lease_id = await _acquire_panel_mutation("Panel taslak uretimi", "social_x_draft")
    workflow = _load_social_workflow()
    try:
        queue = workflow["get_x_queue"]()
        item = next((entry for entry in queue.get("items", []) if entry.get("queue_id") == queue_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Queue item bulunamadi")

        draft_text = await _generate_social_reply(item, data.tone or "")
        updated = workflow["update_queue_item"](queue_id, draft_reply=draft_text, status="drafted")
        return {"status": "success", "item": updated, "draft": draft_text}
    finally:
        await release_automation("panel", job_id=lease_id)


@app.post("/api/social/x/queue/{queue_id}/update")
async def social_update_x_draft(queue_id: str, data: SocialReplyUpdate):
    lease_id = await _acquire_panel_mutation("Panel taslak guncelleme", "social_x_update")
    workflow = _load_social_workflow()
    try:
        status = "drafted" if data.text.strip() else "new"
        item = workflow["update_queue_item"](queue_id, draft_reply=data.text, status=status)
        return {"status": "success", "item": item}
    except KeyError:
        raise HTTPException(status_code=404, detail="Queue item bulunamadi")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Taslak guncellenemedi: {e}")
    finally:
        await release_automation("panel", job_id=lease_id)


@app.post("/api/social/x/queue/{queue_id}/status")
async def social_mark_x_queue_item(queue_id: str, data: SocialQueueStatusUpdate):
    lease_id = await _acquire_panel_mutation("Panel queue durum guncelleme", "social_x_status")
    workflow = _load_social_workflow()
    try:
        item = workflow["mark_queue_item"](queue_id, data.status, note=data.note)
        return {"status": "success", "item": item}
    except KeyError:
        raise HTTPException(status_code=404, detail="Queue item bulunamadi")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Queue item guncellenemedi: {e}")
    finally:
        await release_automation("panel", job_id=lease_id)


@app.post("/api/social/x/queue/{queue_id}/send")
async def social_send_x_reply(queue_id: str, data: Optional[SocialReplyUpdate] = None):
    lease_id = await _acquire_panel_mutation("Panel X reply gonderimi", "social_x_send")
    workflow = _load_social_workflow()
    reply_text = data.text if data and data.text is not None else None
    try:
        item = workflow["send_x_reply"](queue_id, message=reply_text)
        return {"status": "success", "item": item}
    except KeyError:
        raise HTTPException(status_code=404, detail="Queue item bulunamadi")
    except Exception as e:
        try:
            workflow["mark_queue_item"](queue_id, "error", note=str(e))
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Reply gonderilemedi: {e}")
    finally:
        await release_automation("panel", job_id=lease_id)
