"""Ortak test yardimcilari: sahte BaseModel, terminal sarmalayici, durum sifirlama."""

import _env  # noqa: F401  (her seyden once)

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from _env import CONFIG_DIR, REPO, ROOT, WORKSPACE_DIR

_CONFIG_FILES = ("agents.yaml", "custom_tools.yaml", "agent_packs.yaml", "heartbeat_config.yaml")


def reset_state() -> None:
    """Config'i repo varsayilanlarina, custom tool/pack dizinlerini bos haline dondurur."""
    for name in _CONFIG_FILES:
        source = REPO / "MarketingApp" / "config" / name
        target = CONFIG_DIR / name
        if source.exists():
            shutil.copy(source, target)
        else:
            target.unlink(missing_ok=True)
    (CONFIG_DIR / "pricing.yaml").unlink(missing_ok=True)

    for sub in ("custom_tools", "agent_packs", "exports"):
        shutil.rmtree(WORKSPACE_DIR / sub, ignore_errors=True)
    tools_dir = WORKSPACE_DIR / "custom_tools"
    tools_dir.mkdir(parents=True)
    for source in (REPO / "MarketingApp" / "workspace" / "custom_tools").glob("*.py"):
        shutil.copy(source, tools_dir / source.name)


@contextmanager
def fresh_telemetry(directory: Path | None = None):
    """Telemetri deposunu bos, gecici bir veritabanina yonlendirir ve modul durumunu sifirlar."""
    from MarketingApp import telemetry

    owned = None
    if directory is None:
        owned = tempfile.TemporaryDirectory(dir=ROOT)
        directory = Path(owned.name)
    saved = (telemetry.DB_PATH, telemetry._initialized_path, telemetry._last_error, telemetry._last_prune_monotonic)
    telemetry.close()
    telemetry.DB_PATH = str(directory / "telemetry.sqlite")
    telemetry._initialized_path = None
    telemetry._last_error = None
    telemetry._last_prune_monotonic = None
    try:
        yield telemetry
    finally:
        telemetry.close()
        telemetry.DB_PATH, telemetry._initialized_path, telemetry._last_error, telemetry._last_prune_monotonic = saved
        if owned:
            owned.cleanup()


def patch_model_env():
    """agent_studio.MODEL_ENV_PATH kod-goreceli (repo koku); testte gercek .env.model'e yazilmasin."""
    from MarketingApp.llms import agent_studio

    directory = tempfile.TemporaryDirectory(dir=ROOT)
    patcher = mock.patch.object(agent_studio, "MODEL_ENV_PATH", Path(directory.name) / ".env.model")
    patcher.start()

    def stop():
        patcher.stop()
        directory.cleanup()

    return stop


class FakeBase:
    """TerminalManager'in ihtiyac duydugu BaseModel yuzeyi."""

    model = "test-model"
    provider_name = "test"
    start_time = 0.0

    def __init__(self):
        self.logs = []
        self.active_agents = {}
        self.active_tools = {}
        self.agent_studio_errors = []
        self._submodel_func_map = {}

    def get_hierarchy(self):
        from MarketingApp.llms.agent_studio import build_tool_registry

        tools = [
            {"name": tool["name"], "desc": tool["description"], "active": True}
            for tool in build_tool_registry()["tools"]
        ]
        return {"submodels": [], "tools": tools}

    def reload_agent_studio(self):
        return self.get_hierarchy()

    def set_agent_active(self, name, active):
        self.active_agents[name] = active
        return active

    def set_tool_active(self, name, active):
        self.active_tools[name] = active
        return active

    def log_message(self, type_, message):
        self.logs.append({"time": "00:00:00", "type": type_, "message": message})

    def default_system_instruction(self):
        return "FAKE VARSAYILAN ORKESTRATOR PROMPTU"


class Term:
    """TerminalManager'i sarar; her komutun ciktisini dondurur."""

    def __init__(self, base=None, answers=()):
        from MarketingApp.environments.terminal import TerminalManager

        self.base = base or FakeBase()
        self.out: list[str] = []
        self._answers = list(answers)
        self.manager = TerminalManager(
            self.base,
            input_func=lambda _prompt: self._answers.pop(0) if self._answers else "",
            output_func=self.out.append,
            history_file=str(ROOT / "terminal_history_test.json"),
        )

    async def run(self, line: str) -> str:
        mark = len(self.out)
        await self.manager.handle_line(line)
        return "\n".join(self.out[mark:])
