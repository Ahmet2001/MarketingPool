# Mimar

**AI-powered social media management, content creation, and browser automation orchestrator.**

Mimar is a Python agent platform built around a single orchestrator LLM (`BaseModel`) that delegates work to specialized sub-agents — social media, content creation, browser automation, research — each with its own tool set. It's controlled through an interactive terminal, and can also be embedded as a component ("agent leg") inside a larger system.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> This copy lives at `agents/marketing-agent` inside
> [`marketing-agent-assets`](../../README.md), where it's the
> [`future_work.md`](../../future_work.md) "marketing agent" wired to
> [`social-media-worker`](../../social-media-worker)'s publish queue. See
> [`AGENT.md`](./AGENT.md) for what that integration actually covers today.
> Everything below describes running this project on its own — that part is
> unchanged.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Terminal Commands](#terminal-commands)
- [Using Mimar as an Embedded Agent](#using-mimar-as-an-embedded-agent)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Content Creator Agent** — text, image, and video content generation (HTML/CSS → PNG posts, stock footage → MP4 reels, website-to-post extraction).
- **Social Media Agent** — X (Twitter), Instagram, and YouTube automation: posting, replies, likes, follows, notification scanning, market snapshots. Can also queue Instagram/YouTube/TikTok video and carousel publishes onto `social-media-worker`'s job queue (see [`AGENT.md`](./AGENT.md)).
- **Browser Agent** — Selenium-based navigation, DOM reading, and form interaction.
- **Research Agent** — multi-query web research and report synthesis (Gemini Live API).
- **System Agent** — file/workspace management and system status monitoring.
- **VLM Agent** — screen capture, mouse/keyboard control with self-verifying vision loop.
- **Agent Studio** — add, enable/disable, and reconfigure agents and tools through YAML config, no code changes required.
- **Agent Packs** — plug-and-play bundles of agents, tools, and prompts.
- **Heartbeat Scheduler** — cron/interval-based background jobs (APScheduler), managed from the terminal.
- **Interactive terminal control interface** — inspect and toggle agents/tools, run heartbeat jobs, review logs, approve risky actions, all from one CLI session.

## Architecture

```
main.py
 ├─ background tasks: heartbeat_loop, telegram bot (optional), discord bot (optional)
 └─ TerminalManager (foreground)
       └─ AutomationCoordinator (mutex: only one caller touches BaseModel/browser at a time)
             └─ BaseModel.text_query()
                   └─ tool-calling loop (≤12 turns, repeat-call guard)
                         ├─ base tools (memory, workspace, search, …)
                         └─ SubModel agents (each runs its own inner LLM + tool loop)
```

- **`BaseModel`** (`MarketingApp/llms/BaseModel.py`) is the orchestrator: an OpenAI-compatible chat-completions loop that calls tools and sub-agents until it has a final answer.
- **`SubModel`** agents (`MarketingApp/llms/SubModels/`) are self-contained mini-agents, each with their own model and tool subset, exposed to `BaseModel` as a single callable tool.
- **`AutomationCoordinator`** (`MarketingApp/environments/automation_runtime.py`) is a lock ensuring the terminal, heartbeat, and Telegram/Discord triggers never touch the shared browser session concurrently.
- **`Agent Studio`** (`MarketingApp/llms/agent_studio.py`) reads `config/agents.yaml`, `config/custom_tools.yaml`, and `config/agent_packs.yaml` to assemble the runtime — agents and tools can be added, toggled, or reconfigured without touching code.

## Quick Start

```bash
cd agents/marketing-agent   # inside a marketing-agent-assets checkout
chmod +x run.sh
./run.sh
```

(Standalone: `git clone https://github.com/Ahmet2001/BrowserAgent.git && cd BrowserAgent && ./run.sh` — this directory is a copy of that project.)

`run.sh`:
1. Creates a `.venv` if one doesn't exist.
2. Installs/updates packages from `requirements.txt`.
3. Launches the interactive terminal via `python -m MarketingApp.main`.

For PNG/video rendering, also install the Playwright browser once:

```bash
source .venv/bin/activate
playwright install chromium
```

## Configuration

Copy `.env.example` to `.env` and fill in your keys. Settings are loaded in this order (later files override earlier ones): `.env` → `.env.local` → `.env.model` → `.env.secrets`.

| File | Purpose |
|---|---|
| `.env` | Base model/provider settings, Telegram token |
| `.env.local` *(optional)* | Local overrides, kept out of version control |
| `.env.model` *(optional)* | Model-specific overrides |
| `.env.secrets` *(optional)* | Additional API keys (Pexels, etc.) |

Key variables:

| Variable | Description |
|---|---|
| `MODEL_PROVIDER` | `gemini` or an OpenAI-compatible provider |
| `OPENAI_COMPAT_BASE_URL` | Base URL for the OpenAI-compatible endpoint |
| `BASE_MODEL_NAME` / `SUBMODEL_MODEL_NAME` / `BROWSER_AGENT_MODEL` | Model IDs per role |
| `GEMINI_API_KEY` / `GEMINI_API_KEY_SECONDARY` | Gemini API keys (with failover) |
| `TELEGRAM_TOKEN` / `DISCORD_TOKEN` | Optional chat platform integrations |
| `PEXELS_API_KEY` | Stock photo/video search for the Content Creator agent |

All API keys and tokens live only in the gitignored `.env*` files — never commit real credentials.

## Terminal Commands

Once running, type a message to chat with Mimar, or use a command:

| Command | Description |
|---|---|
| `/help`, `/?` | Show the command list |
| `/status` | Show model, provider, uptime, and channel status |
| `/agents` | List all registered agents |
| `/agent <name> on\|off\|toggle` | Enable/disable an agent |
| `/tools [query]` | List or filter tools |
| `/tool <name> on\|off\|toggle` | Enable/disable a tool |
| `/logs [count]` | Show recent logs (default 15) |
| `/heartbeat` | Show scheduler and job status |
| `/heartbeat run\|pause\|resume <id>` | Control a scheduled job |
| `/heartbeat reload` | Reload the heartbeat config from disk |
| `/reload` | Reload agent/custom tool config |
| `/history` | Show terminal chat history |
| `/clear` | Clear terminal chat history |
| `/exit` | Shut down safely |

## Using Mimar as an Embedded Agent

`MarketingApp/agent_api.py` exposes a thin, side-effect-free API for calling Mimar from another orchestrator (e.g. an asset-generation pipeline) instead of running it as a standalone terminal app:

```python
from MarketingApp.agent_api import MimarAgent

agent = MimarAgent(workspace_dir="/path/to/pool/brandX/workspace")
result = await agent.run("Draft a post about today's topic for X")
print(result.text)
```

`MimarAgent` never starts the heartbeat/Telegram/Discord background tasks. Workspace and config directories can be redirected per instance via `workspace_dir`/`config_dir` (see the module docstring for the single-process-per-workspace caveat).

## Project Structure

```
MarketingApp/
├── agent_api.py         # Embeddable agent wrapper (MimarAgent)
├── paths.py              # Central, overridable workspace/config path resolution
├── main.py               # Entry point (python -m MarketingApp.main)
├── araclar/               # Tools: browser, search, memory, content creation, workspace, skills
├── config/                # agents.yaml, custom_tools.yaml, agent_packs.yaml, heartbeat_config.yaml
├── environments/          # terminal.py, heartbeat.py, telegram.py, discord_bot.py, automation_runtime.py
├── llms/                  # BaseModel orchestrator, Agent Studio, SubModels/
├── legacy/panel/          # Archived FastAPI web panel (superseded by the terminal interface)
└── workspace/              # Runtime data: memory, drafts, assets, custom tools, agent packs
```

## Requirements

- Python 3.11+
- Chrome browser (for X/social automation)
- An active X (Twitter) session in a Chrome profile, for social features

## Contributing

Issues and pull requests are welcome. Please keep changes scoped and include a short description of what changed and why.

## License

MIT © 2026 Ahmet Rıfat Öztürk — see [LICENSE](LICENSE).
