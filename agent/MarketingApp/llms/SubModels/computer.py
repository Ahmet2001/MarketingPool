"""Agent Studio generated builtin submodel: computer."""

from __future__ import annotations

# Agent Studio generated builtin submodel

from MarketingApp.llms.SubModels.base import register_submodel
from MarketingApp.llms.SubModels.generic_config_agent import (
    GenericConfigAgent,
    build_generic_config_system_prompt,
)


DEFAULT_SYSTEM_PROMPT = 'Sen Agent Studio ile uretilmis dosya tabanli bir builtin alt ajansin. Sana baglanan araclari kullanarak gorevi denetlenebilir sekilde tamamla.'


class ComputerSubModel(GenericConfigAgent):
    """Bilgisyarla ilgili bi iş yapılması gerektiinde"""

    def __init__(self):
        super().__init__(
            {
                "name": 'computer',
                "type": "builtin",
                "enabled": True,
                "description": 'Bilgisyarla ilgili bi iş yapılması gerektiinde',
                "model": 'default',
                "tool_mode": "custom",
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "tools": [],
            },
            tools=[],
        )

    def _build_system_prompt(self) -> str:
        prompt = DEFAULT_SYSTEM_PROMPT
        try:
            from MarketingApp.llms.agent_studio import load_agents_config

            for agent in load_agents_config().get("agents", []):
                if agent.get("name") == self.name:
                    prompt = (agent.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
                    break
        except Exception:
            pass
        return build_generic_config_system_prompt(prompt)


register_submodel(ComputerSubModel())
