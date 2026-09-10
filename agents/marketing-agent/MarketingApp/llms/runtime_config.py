"""
Runtime model/provider ayarlari.

Bu dosya patched kopyada OpenAI-compatible LLM saglayicilari arasinda
yerel varsayilanlar saglar. Gizli anahtarlar kaynak koda gomulmez;
ortam degiskenlerinden okunur.
"""

from __future__ import annotations

import os


_DEFAULT_PROVIDER = "gemini"
_DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEFAULT_MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"
_DEFAULT_BASE_MODEL = "gemini-3.1-flash-lite-preview"
_DEFAULT_SUBMODEL_MODEL = "gemini-3.1-flash-lite-preview"
_DEFAULT_BROWSER_MODEL = "gemini-3.1-flash-lite-preview"
_DEFAULT_TOOL_GENERATOR_MODEL = "gemini-3.1-flash-lite-preview"
_DEFAULT_BASE_REASONING_EFFORT = "low"
_DEFAULT_SUBMODEL_REASONING_EFFORT = "low"
_DEFAULT_BROWSER_REASONING_EFFORT = "low"
_DEFAULT_TOOL_GENERATOR_REASONING_EFFORT = "low"


def model_supports_reasoning_effort(model_name: str | None) -> bool:
    normalized = (model_name or "").strip().lower()
    if not normalized:
        return True
    if normalized.startswith("gemma-"):
        return False
    return True


def get_model_provider() -> str:
    explicit_provider = os.getenv("MODEL_PROVIDER") or os.getenv("LLM_PROVIDER")
    if explicit_provider:
        return explicit_provider.strip().lower()

    configured_model = (
        os.getenv("BASE_MODEL_NAME")
        or os.getenv("BROWSER_AGENT_MODEL")
        or _DEFAULT_BASE_MODEL
    ).lower()

    if configured_model.startswith("gemini-"):
        return "gemini"
    if configured_model.startswith("kimi-") or "moonshot" in configured_model:
        return "moonshot"
    return _DEFAULT_PROVIDER


def get_provider_display_name() -> str:
    provider = get_model_provider()
    if provider == "gemini":
        return "Gemini"
    if provider == "moonshot":
        return "Moonshot/Kimi"
    return provider.upper()


def get_model_api_key() -> str:
    provider = get_model_provider()
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY") or ""
    return os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY") or ""


def get_model_api_keys() -> list[str]:
    provider = get_model_provider()
    raw_keys: list[str] = []
    if provider == "gemini":
        raw_keys = [
            os.getenv("GEMINI_API_KEY") or "",
            os.getenv("GEMINI_API_KEY_SECONDARY") or "",
            os.getenv("GEMINI_API_KEY_FALLBACK") or "",
        ]
    else:
        raw_keys = [
            os.getenv("MOONSHOT_API_KEY") or "",
            os.getenv("KIMI_API_KEY") or "",
        ]

    unique_keys: list[str] = []
    for key in raw_keys:
        cleaned = key.strip()
        if cleaned and cleaned not in unique_keys:
            unique_keys.append(cleaned)
    return unique_keys


def get_openai_compat_base_url() -> str:
    custom_base_url = os.getenv("OPENAI_COMPAT_BASE_URL")
    if custom_base_url:
        return custom_base_url

    provider = get_model_provider()
    if provider == "gemini":
        return os.getenv("GEMINI_OPENAI_BASE_URL") or _DEFAULT_GEMINI_BASE_URL
    return os.getenv("MOONSHOT_BASE_URL") or _DEFAULT_MOONSHOT_BASE_URL


def get_moonshot_base_url() -> str:
    """Geriye donuk uyumluluk icin korunan isim."""
    return get_openai_compat_base_url()


def get_base_model_name() -> str:
    return os.getenv("BASE_MODEL_NAME") or _DEFAULT_BASE_MODEL


def get_browser_model_name() -> str:
    return os.getenv("BROWSER_AGENT_MODEL") or _DEFAULT_BROWSER_MODEL


def get_submodel_model_name() -> str:
    return os.getenv("SUBMODEL_MODEL_NAME") or _DEFAULT_SUBMODEL_MODEL or get_base_model_name()


def get_tool_generator_model_name() -> str:
    return os.getenv("TOOL_GENERATOR_MODEL") or _DEFAULT_TOOL_GENERATOR_MODEL


def get_base_reasoning_effort() -> str | None:
    if not model_supports_reasoning_effort(get_base_model_name()):
        return None
    explicit_value = os.getenv("BASE_REASONING_EFFORT")
    if explicit_value:
        return explicit_value
    if get_model_provider() == "gemini":
        return _DEFAULT_BASE_REASONING_EFFORT
    return None


def get_submodel_reasoning_effort() -> str | None:
    if not model_supports_reasoning_effort(get_submodel_model_name()):
        return None
    explicit_value = os.getenv("SUBMODEL_REASONING_EFFORT")
    if explicit_value:
        return explicit_value
    if get_model_provider() == "gemini":
        return _DEFAULT_SUBMODEL_REASONING_EFFORT
    return get_base_reasoning_effort()


def get_browser_reasoning_effort() -> str | None:
    if not model_supports_reasoning_effort(get_browser_model_name()):
        return None
    explicit_value = os.getenv("BROWSER_REASONING_EFFORT")
    if explicit_value:
        return explicit_value
    if get_model_provider() == "gemini":
        return _DEFAULT_BROWSER_REASONING_EFFORT
    return None


def get_tool_generator_reasoning_effort() -> str | None:
    if not model_supports_reasoning_effort(get_tool_generator_model_name()):
        return None
    explicit_value = os.getenv("TOOL_GENERATOR_REASONING_EFFORT")
    if explicit_value:
        return explicit_value
    if get_tool_generator_model_name().lower().startswith("gemini-"):
        return _DEFAULT_TOOL_GENERATOR_REASONING_EFFORT
    return None
