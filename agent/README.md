# Ethgent

**AI-powered social media management, content creation, and browser automation orchestrator.**

Ethgent is a standalone, operable product, not a framework you assemble — clone it, run `./run.sh`, and you have a working orchestrator LLM (`BaseModel`) that delegates to specialized sub-agents (social media, content creation, browser automation, research), a terminal to manage it, and its own logs/run-history/cost tracking out of the box. Agents and tools live in YAML and can be created, edited, and shared from that terminal without touching code. (It can also be embedded as a library in another Python process when that's genuinely what you need — see [below](#using-ethgent-as-an-embedded-agent) — but that's the exception, not how Ethgent is meant to be used day to day.)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> In this repository the agent lives next to [`marketing-agent-assets`](../marketing-agent-assets/README.md),
> where it is the [`future_work.md`](../marketing-agent-assets/future_work.md) "marketing agent" wired to
> [`social-media-worker`](../marketing-agent-assets/social-media-worker)'s publish queue. See
> [`AGENT.md`](./AGENT.md) for what that integration actually covers today, and the
> [top-level README](../README.md) for how to run it with Docker.
> Everything below describes running this project on its own, which is unchanged.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Terminal Commands](#terminal-commands)
- [Operations: logs, run history, usage](#operations-logs-run-history-usage)
- [Telegram and Discord](#telegram-and-discord)
- [Using Ethgent as an Embedded Agent](#using-ethgent-as-an-embedded-agent)
- [Running as a Worker](#running-as-a-worker)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Asset Collector Agent** — lists and fetches App-approved media assets (video/image/audio/document, schema-validated) over HTTP for the other agents to reuse (see [`AGENT.md`](./AGENT.md)).
- **Content Creator Agent** — text, image, and video content generation (HTML/CSS → PNG posts, stock footage → MP4 reels, website-to-post extraction).
- **Social Media Agent** — X (Twitter), Instagram, and YouTube automation: posting, replies, likes, follows, notification scanning, market snapshots. Can also queue Instagram/YouTube/TikTok video and carousel publishes onto `social-media-worker`'s job queue (see [`AGENT.md`](./AGENT.md)).
- **Browser Agent** — Selenium-based navigation, DOM reading, and form interaction.
- **Research Agent** — multi-query web research and report synthesis (Gemini Live API).
- **System Agent** — file/workspace management and system status monitoring.
- **VLM Agent** — screen capture, mouse/keyboard control with self-verifying vision loop.
- **Agent Studio** — add, enable/disable, and reconfigure agents and tools through YAML config, no code changes required.
- **Agent Packs** — plug-and-play bundles of agents, tools, and prompts.
- **Heartbeat Scheduler** — cron/interval-based background jobs (APScheduler), managed from the terminal.
- **Interactive terminal control interface** — create, edit, copy, test and delete agents and tools, schedule heartbeat jobs, package and share a setup, review logs, approve risky actions, all from one CLI session and without a restart.
- **Operations store** — persistent logs, per-run history (what each scheduled job did, how long it took, what it cost) and LLM token usage, queryable from the terminal.
- **Remote management with access control** — the same management commands over Telegram/Discord for allow-listed admins only, with remote code upload deliberately blocked.

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
- **`telemetry`** (`MarketingApp/telemetry.py`) is the operations store: a `run` is opened per unit of work (a chat turn, a heartbeat job) and carried in a `ContextVar`, so every log line and LLM call made inside it is attached to it automatically.
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
| `TELEGRAM_ALLOWED_USER_IDS` / `DISCORD_ALLOWED_USER_IDS` | Who may chat with the bot (see [Telegram and Discord](#telegram-and-discord)) |
| `TELEGRAM_ADMIN_IDS` / `DISCORD_ADMIN_IDS` | Who may run management commands remotely |
| `ETHGENT_TELEMETRY_RETENTION_DAYS` | How long logs/runs/usage are kept (default `30`, `0` = forever) |

All API keys and tokens live only in the gitignored `.env*` files (`.env`, `.env.local`, `.env.model`, `.env.secrets`) — never commit real credentials.

## Terminal Commands

Once running, type a message to chat with Ethgent, or use a command. `/help` prints everything below.

| Command | Description |
|---|---|
| `/status` | Model, provider, uptime, channels, config errors, store health and today's token usage |
| `/agents`, `/agent list` | List agents |
| `/agent <name> on\|off\|toggle` | Enable/disable an agent |
| `/agent show <name>` | Type, model, tool list, prompt and any config errors for one agent |
| `/agent create <name> [flags]` | Create an agent (`--model`, `--tools`, `--tool-group`, `--tool-category`, `--prompt`, `--desc`, `--dry-run`) |
| `/agent edit <name> [flags]` | Change one (`--add-tools`, `--remove-tools`, `--remove-tool-group`, `--enable`/`--disable`, …) |
| `/agent copy <from> <to>` | Clone an agent with its resolved tool list |
| `/agent test <name> "task"` | Run a single agent directly and record it as a run |
| `/agent delete <name> [--yes]` | Delete a config agent |
| `/agent pack list\|preview\|install\|export` | Manage agent packs, see [Sharing a setup](#sharing-a-setup) |
| `/tools [query] [--group G] [--category C] [--risk high]` | List and filter tools; `--list-groups` shows the groups, categories and risk split |
| `/tool <name> on\|off\|toggle` | Enable/disable a tool |
| `/tool create\|edit\|show\|delete\|list` | Manage custom tools, see [Custom tools](#custom-tools) |
| `/heartbeat` | Scheduler and job status |
| `/heartbeat add --cron X --gorev "..."` | Add a scheduled task (`startup`, `*/N` or `HH:MM`) |
| `/heartbeat remove <id>`, `show <id>`, `on`, `off` | Remove/inspect a task, enable/disable the scheduler |
| `/heartbeat run\|pause\|resume <id>`, `reload` | Control jobs, reload the config |
| `/heartbeat log [id] [n]` | Past runs of a job: when, how long, what it produced |
| `/logs [n] [--since 24h] [--type T] [--grep text] [--run id]` | Persistent logs (`--memory` = this process only) |
| `/runs [n] [--source S] [--status S] [--since 24h]` | Run history across the terminal, heartbeat, Telegram and Discord |
| `/run <id>` | One run in detail: duration, error, token breakdown by agent/model, its log lines |
| `/usage [--since 24h] [--by agent\|model\|source\|day\|run]` | LLM token usage, plus a cost estimate if `config/pricing.yaml` exists |
| `/errors [text]` | Config problems that were previously collected but never shown |
| `/reload` | Reload agent/custom tool config |
| `/provider` | Show the active provider/model and which agents have a literal (non-default) model pinned in `agents.yaml` |
| `/provider set <name> [--base-model M] [--submodel-model M] [--browser-model M] [--base-url URL] [--api-key K] [--reset-pins] [--dry-run]` | Switch provider/model, writing to `.env.model`; `--reset-pins` un-pins agents back to the `default` sentinel so they follow the new provider |
| `/memory [category] [key]`, `/memory search <text>`, `/memory delete <category> <key> --yes` | Inspect, search and remove entries from the agent's long-term memory (`bellek_yaz`/`bellek_oku`) without going through chat |
| `/history`, `/clear`, `/exit` | Chat history / shut down |

Destructive commands ask for confirmation unless you pass `--yes`. `--dry-run` on `agent create/edit` and `heartbeat add` previews the result without saving.

**Switching providers:** each agent's `model:` field in `agents.yaml` is normally the sentinel `default` (or `browser_default`), which is re-resolved from `SUBMODEL_MODEL_NAME`/`BROWSER_AGENT_MODEL` on every boot. If an agent has ever been given an explicit `--model` (via `/agent create`/`edit`/`copy`), that literal name is pinned and does **not** follow a later `/provider set` — use `--reset-pins` to un-pin it. Also note that model *name* changes take effect immediately via `/reload`, but a provider swap (`--base-url`/`--api-key`) only fully applies after restarting the app, since the underlying HTTP clients are built once at boot.

### Custom tools

```
/tool create fiyat_getir --file ~/fiyat_getir.py --desc "Returns a price"
/tool create --file ~/kripto.py --all            # every public function in the file becomes a tool
/tool create --file ~/kripto.py --names a,b      # only these, sharing one copy of the file
/tool create x --code "def x(): return 1" --desc "inline"
```

The code is compiled, checked for a function named after the tool, and actually imported before it is accepted, so a broken tool is rejected at write time. The file is **copied** into `workspace/custom_tools/`; re-run `/tool edit <name> --file …` to pick up later changes. `--env NAME=value` writes to the gitignored `.env.model`; a bare `--env NAME` only records the requirement.

### Sharing a setup

```
/agent pack export my_pack --agents my_agent --out ~/my_pack   # or --all
/agent pack install ~/my_pack
/agent pack install github:user/repo[@branch][#sub/dir]   # shallow-clones the repo, shows the preview, asks before installing
```

`export` writes `plugin.yaml`, `agents/`, `prompts/`, `tools/`, a README and an `env.example` that contains variable **names only** — never values. Builtin tools cannot be packaged (they already exist in every install). Builtin agents *can* be packaged: one you scaffolded yourself (`/agent create --builtin`) travels with its own `submodels/<name>.py` source and installs even where it doesn't exist yet; one of the six agents the app ships with (`sosyal_medya_agent`, `content_creator_agent`, …) travels as config only — model/tools/prompt — since the target install already has its code.

## Operations: logs, run history, usage

Everything is stored in `workspace/runtime/telemetry.sqlite` (gitignored) and kept for `ETHGENT_TELEMETRY_RETENTION_DAYS` days.

- **Logs** survive restarts (`/logs`).
- **Runs** record every chat turn and heartbeat job — including skipped ones and retry attempts — with status, duration, error and a summary of the output (`/runs`, `/run`, `/heartbeat log`). The heartbeat's own `job_runtime` table only keeps the *last* run per job; this keeps them all.
- **Usage** records the tokens of every LLM call, attributed to the run, agent, model and channel it happened in (`/usage`).

Cost is estimated only for models you price in `config/pricing.yaml` (USD per 1M tokens); Ethgent ships no prices because they change and model names are install-specific:

```yaml
models:
  gemini-2.5-flash: {input: 0.30, output: 2.50}
```

Known limits: the Gemini Live agents (`arastirma_agent`, `sistem_agent`, `vlm_agent`) produce one **approximate** usage row per session, because the SDK does not document whether Live `usage_metadata` is cumulative; providers that return no usage data are counted as calls with unknown tokens.

## Telegram and Discord

The bots can now run the management commands above, but **who may talk to them is configured by you**:

| Variable | Meaning |
|---|---|
| `<CHANNEL>_ALLOWED_USER_IDS` | Who may chat. **If unset, chat is open to everyone** (the old behaviour) and startup prints a warning. |
| `<CHANNEL>_ADMIN_IDS` | Who may run management commands. If unset they are **disabled**. |

Send `/id` (Telegram) or `!id` (Discord) to the bot to learn your numeric ID. Unauthorised users get no reply; each attempt is written to the log (`/logs --type remote`).

Management commands are `/agent`, `/tool`, `/heartbeat`, `/usage`, … on Telegram and `!agent`, `!tool`, … on Discord. Even for an admin, remote sessions cannot run `/tool create|edit|delete` or `/tool show --code` (tool code runs on the server), `/agent pack …` (filesystem paths) or `/agent create --builtin`, and `agent delete` / `heartbeat remove` require `--yes`.

## Using Ethgent as an Embedded Agent

**This is an advanced, secondary integration path.** Ethgent's primary form is the standalone terminal app described above; nothing here changes that. `MarketingApp/agent_api.py` exists only for the narrow case where another Python orchestrator (e.g. an asset-generation pipeline) needs to call Ethgent's `BaseModel` in-process instead of running it as a separate app — no logs/run-history/telemetry UI, no bots, no terminal, just a single `run()` call:

```python
from MarketingApp.agent_api import EthgentAgent

agent = EthgentAgent(workspace_dir="/path/to/pool/brandX/workspace")
result = await agent.run("Draft a post about today's topic for X")
print(result.text)
```

`EthgentAgent` never starts the heartbeat/Telegram/Discord background tasks. Workspace and config directories can be redirected per instance via `workspace_dir`/`config_dir` (see the module docstring for the single-process-per-workspace caveat).

## Running as a Worker

```bash
./worker.sh
# or, with the venv already active:
python -m MarketingApp.worker
```

`python -m MarketingApp.worker` runs Ethgent unattended, with two entry points sharing one `EthgentAgent` instance:

- A **queue poller** that claims `status='queued'` rows from an `agent_jobs` Supabase table (schema: [`migrations/001_agent_jobs.sql`](./migrations/001_agent_jobs.sql)) and runs each one through `EthgentAgent.run()`.
- An **MCP server** (Streamable HTTP, `POST /mcp`, bearer-token auth) exposing `run_marketing_task(task, context)` / `check_marketing_task(job_id)` for on-demand calls from any MCP client.

See [`AGENT.md`](./AGENT.md#running-the-agent-as-a-worker-new) for the full picture, including the single-process-per-workspace limitation this shares with `EthgentAgent`.

## Project Structure

```
MarketingApp/
├── agent_api.py         # Embeddable agent wrapper (EthgentAgent)
├── worker.py              # Unattended entry point: agent_jobs queue poller + MCP server
├── paths.py              # Central, overridable workspace/config path resolution
├── main.py               # Entry point (python -m MarketingApp.main)
├── telemetry.py           # Persistent logs, run history and token usage
├── araclar/               # Tools: browser, search, memory, content creation, workspace, skills
├── config/                # agents.yaml, custom_tools.yaml, agent_packs.yaml, heartbeat_config.yaml
├── environments/          # terminal.py, heartbeat.py, telegram.py, discord_bot.py, automation_runtime.py,
│                          # access.py (bot allowlists), remote_commands.py (terminal commands over chat),
│                          # agent_job_queue.py, agent_mcp_server.py
├── llms/                  # BaseModel orchestrator, Agent Studio, SubModels/
├── legacy/panel/          # Archived FastAPI web panel (superseded by the terminal interface)
└── workspace/              # Runtime data: memory, drafts, assets, custom tools, agent packs

migrations/                 # agent_jobs table + claim_next_agent_job() (worker.py's queue)
tests/                       # unittest suite (isolated temp workspace)
```

## Requirements

- Python 3.11+
- Chrome browser (for X/social automation)
- An active X (Twitter) session in a Chrome profile, for social features

## Testing

```bash
python -m unittest discover -s tests
```

The suite runs against a temporary workspace and config directory (`tests/_env.py`), so it never touches your real agents, tools or telemetry. Use `discover -s tests` rather than `tests.<module>`: a dependency installs a top-level `tests` package that shadows it.

## Contributing

Issues and pull requests are welcome. Please keep changes scoped and include a short description of what changed and why.

## License

MIT © 2026 Ahmet Rıfat Öztürk — see [LICENSE](LICENSE).
