"""Generic config-backed SubModel used by Agent Studio."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from .base import SubModel, SubModelRateLimitError
from MarketingApp.llms.runtime_config import (
    get_base_model_name,
    get_browser_model_name,
    get_model_api_key,
    get_model_api_keys,
    get_openai_compat_base_url,
    get_provider_display_name,
    get_submodel_model_name,
    get_submodel_reasoning_effort,
)


GENERIC_CONFIG_DEFAULT_PROMPT = (
    "Sen Agent Studio ile olusturulmus ozel bir alt ajansin. "
    "Sadece sana baglanan araclari kullan, gorevi kisa ve net tamamla."
)

GENERIC_CONFIG_WORK_RULES = (
    "CALISMA KURALLARI:\n"
    "1. Sadece tool listende bulunan araclari kullan.\n"
    "2. Workspace veya sosyal medya baglami gerekiyorsa once mevcut hafiza/context araclarini kullan.\n"
    "3. Final cevabini Turkce, kisa ve denetlenebilir sekilde ver.\n"
)


def build_generic_config_system_prompt(system_prompt: str | None = None) -> str:
    prompt = (system_prompt or "").strip() or GENERIC_CONFIG_DEFAULT_PROMPT
    return f"{prompt}\n\n{GENERIC_CONFIG_WORK_RULES}"


class GenericConfigAgent(SubModel):
    """A SubModel assembled from agents.yaml prompt, model and selected tools."""

    def __init__(self, config: dict[str, Any], tools: list):
        self.config = dict(config)
        self.provider_name = get_provider_display_name()
        self.reasoning_effort = get_submodel_reasoning_effort()
        api_keys = get_model_api_keys()
        api_key = api_keys[0] if api_keys else get_model_api_key()
        model_id = self._resolve_model_id(self.config.get("model"))
        description = self.config.get("description") or "Config tabanli ozel alt ajan."
        super(GenericConfigAgent, self).__init__(
            name=self.config["name"],
            description=description,
            model_id=model_id,
            api_key=api_key,
            tools=tools,
        )
        self._configure_openai_client(get_openai_compat_base_url(), api_keys)

    def _resolve_model_id(self, configured: str | None) -> str:
        model = (configured or "default").strip()
        if model in {"", "default"}:
            return get_submodel_model_name()
        if model == "base_default":
            return get_base_model_name()
        if model == "browser_default":
            return get_browser_model_name()
        return model

    def _strip_thought_blocks(self, text: str) -> str:
        return re.sub(r"<thought>.*?</thought>", "", text or "", flags=re.DOTALL | re.IGNORECASE).strip()

    def _extract_message_text(self, message) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return self._strip_thought_blocks(content)
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                else:
                    maybe_text = getattr(item, "text", None)
                    if maybe_text:
                        texts.append(maybe_text)
            return self._strip_thought_blocks("\n".join(part.strip() for part in texts if part and part.strip()))
        return ""

    def _assistant_message_payload(self, message) -> dict:
        payload = {
            "role": "assistant",
            "content": self._extract_message_text(message),
        }
        tool_calls = []
        for call in getattr(message, "tool_calls", []) or []:
            if isinstance(call, dict):
                call_payload = dict(call)
            elif hasattr(call, "to_dict"):
                call_payload = call.to_dict()
            else:
                call_payload = {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments or "{}",
                    },
                }
            function_payload = call_payload.get("function") or {}
            function_payload["name"] = function_payload.get("name") or call.function.name
            function_payload["arguments"] = function_payload.get("arguments") or call.function.arguments or "{}"
            call_payload["function"] = function_payload
            call_payload["id"] = call_payload.get("id") or call.id
            call_payload["type"] = call_payload.get("type") or "function"
            tool_calls.append(call_payload)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    def _parse_tool_args(self, raw_args) -> dict:
        if isinstance(raw_args, dict):
            return raw_args
        if not raw_args:
            return {}
        try:
            return json.loads(raw_args)
        except Exception:
            return {}

    def _build_system_prompt(self) -> str:
        return build_generic_config_system_prompt(self.config.get("system_prompt"))

    async def run(self, gorev: str) -> str:
        print(f"\n[{self.name}] Config agent gorevi baslatiliyor: {gorev[:120]}...")
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": gorev},
        ]
        final_response = "Tamamlandi"

        try:
            for _ in range(12):
                create_kwargs = {
                    "model": self.model_id,
                    "messages": messages,
                    "tools": self._build_tool_schemas(),
                    "tool_choice": "auto",
                }
                if self.reasoning_effort:
                    create_kwargs["reasoning_effort"] = self.reasoning_effort

                completion = await self._create_chat_completion_with_failover(create_kwargs)
                message = completion.choices[0].message
                current_text = self._extract_message_text(message)
                tool_calls = getattr(message, "tool_calls", None) or []

                if tool_calls:
                    messages.append(self._assistant_message_payload(message))
                    if current_text:
                        final_response = current_text
                    for call in tool_calls:
                        args = self._parse_tool_args(call.function.arguments)
                        result = await self._execute_tool(call.function.name, args)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": call.function.name,
                                "content": json.dumps({"result": str(result)[:6000]}, ensure_ascii=False),
                            }
                        )
                    continue

                if current_text:
                    final_response = current_text
                break
        except Exception as exc:
            err = str(exc)
            if "429" in err or "quota" in err.lower() or "limit" in err.lower():
                raise SubModelRateLimitError(self.name, self.tools)
            return f"{self.name} hatasi: {exc}"

        return final_response
