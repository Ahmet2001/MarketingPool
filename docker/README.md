# The pool on this machine (Docker)

Railway is replaced by containers and Supabase by a local queue (Postgres + PostgREST behind a
proxy that answers `/rest/v1/...`). The workers connect to it unchanged.

```bash
python3 docker/make_env.py                                   # once: local queue secrets -> .env
docker compose up -d --build queue platform-data-worker social-media-worker agent
docker compose logs -f platform-data-worker
docker compose stop                                          # stop everything, keep the queue's data
docker compose down -v                                       # stop and DELETE the queue's data
```

| service | what | needs |
|---|---|---|
| `db`, `postgrest`, `queue` | the local "Supabase". Reachable from this computer at `http://127.0.0.1:54321/rest/v1/` with `SERVICE_KEY` from `.env` | nothing |
| `platform-data-worker` | read-only platform data collection | platform keys in `env/platform-data-worker.env` |
| `social-media-worker` | publishes `publish_jobs` | platform credentials in `env/social-media-worker.env` |
| `agent` | the marketing agent as a worker: polls `agent_jobs`, serves MCP on `127.0.0.1:8091` (bearer token `AGENT_MCP_TOKEN` from `.env`) | `cp env/agent.env.example env/agent.env`, then put your DeepSeek key in `DEEPSEEK_API_KEY`. The example is set up for DeepSeek; keep `GEMINI_API_KEY=unused-placeholder`, three inactive sub-agents crash at start without a value |
| `scheduler-worker`, `mcp-worker` | profile `backend`: drive a backend's content endpoints | `BACKEND_INTERNAL_URL` etc. in `env/*.env` |

`env/<service>.env` files are optional and are never copied into an image.

## Look at the queue

```bash
KEY=$(grep ^SERVICE_KEY .env | cut -d= -f2)
curl -H "apikey: $KEY" -H "Authorization: Bearer $KEY" "http://127.0.0.1:54321/rest/v1/publish_jobs?select=status,error&order=created_at.desc&limit=5"
docker compose exec db psql -U postgres -c "select status, count(*) from publish_jobs group by 1"
```

## What was checked, and what was not

Checked on this machine: the migrations of all four queues apply; the REST API answers with the service key and refuses without it; `platform-data-worker` claimed a job, ran it and wrote the result (a missing key gave a clear `failed`; a write action was refused by the allowlist); `social-media-worker` claimed a job and wrote its result.

The agent container (1.9 GB image, Chromium and a virtual screen included) starts, polls `agent_jobs` and serves MCP (401 without the token, a normal MCP answer with it). A job queued for it was claimed, the agent called the model endpoint, and the failure (a deliberately fake key) was written back to the job row. With the DeepSeek settings the request goes to `api.deepseek.com`, which refused the fake key with 401, so the routing is right.

Not checked: a real agent run with a real model key, anything that needs the browser or the screen (the agent's browser tools are inactive by default), real publishing (needs real credentials and public https media URLs), and `scheduler-worker` / `mcp-worker` (they need a backend).

## Putting a workflow from the factory to work

The workflow factory ([MarketingStudio](https://github.com/Ahmet2001/MarketingStudio)) turns a workflow into a pack the agent installs. The pack is a folder under [`packs/`](../packs), which the agent container sees read-only at `/packs`.

```bash
# in MarketingStudio: write and check the workflow, then export it with the agent target
python -m studio adapt examples/workflows/text_summary.yaml --target agent-bundle \
       --out ../MarketingPool/packs/text_summary --sources examples/text_summary

# here: install it into the running agent (this also restarts it)
./docker/install_pack.sh text_summary          # add --overwrite to update an installed pack
```

Then give the agent a task, e.g. an `agent_jobs` row with `{"task": "text_summary_agent ile bu metnin raporunu cikar. Baslik: Demo. top: 3. Metin: \"...\""}`. Use `agent-bundle`, not `agent-pack`: an installed tool alone is not callable by the orchestrator, it needs a sub-agent that owns it, and `agent-bundle` adds that agent.

Checked end to end with `packs/text_summary` (a deterministic text tool, no keys): the agent app's own preview accepted the pack; after install the orchestrator listed `text_summary_agent` among its active sub-agents; a queued task made it delegate to that agent, which called the tool with correctly typed arguments (`top` as an integer) and returned the report. The answer (17 words; marketing, agents, workers) matched what the engine computes on its own. Tool run folders go to `/data/studio_tools` and the agent's config (`agents.yaml`, `custom_tools.yaml`) lives in `/data/config`, both on a volume, so an installed pack survives the container being recreated (checked with `up --force-recreate`). The first version of this setup kept the config inside the image and lost the pack on recreate. The image's default config is copied to the volume only on first start, so later changes to those defaults do not reach an existing volume.

Three more workflows were put through the same path (all deterministic, nothing leaves the machine):

- **A step that writes outside** (`packs/report_and_send`, whose last step appends to an "outbox" file as a stand-in for sending). Asked to send with no approval, the tool was called with `approve: false`, answered `needs_approval`, nothing was written, and the agent asked the user. With the user's approval stated in the task it ran and wrote the message. **That first version used an `approve` argument set by the model, which was only a convention:** a task that merely said "call it with approve=true" made the agent send to a second recipient with no user approval at all. It was replaced (see "Approval" below).
- **A file input** (`packs/text_report`). The tool reads local files only from `STUDIO_FILE_ROOTS` (`/data/workspace/inbox` here). Given the absolute path or just `notes.txt` it produced the right report (24 words, matching an independent count); given `/etc/hostname` the tool itself refused. The first attempt took five calls because the path was shortened between the orchestrator and the sub-agent and the model fell back to sending the file as base64; since then a short path is looked up inside the allowed folders (it cannot leave them), and a "does not exist" error names the folders. The tool returns file outputs as a path inside its own run folder, which the agent has no tool to read: ask for `text` outputs when the agent has to see the content.
- **An engine that needs a Python package** (`packs/human_size`, needs `humanize`). Without the package the tool stopped before starting and named it (`needs Python package(s) humanize installed`), and the agent reported that. `docker/install_pack.sh` installs the pack's `requirements.txt` into `/data/site-packages` (on `PYTHONPATH`), after which it returned `1.5 MB`, and it still worked after `up --force-recreate`. Programs (such as ffmpeg) are not installed this way: the image has only what the agent itself needs.

## Approval: it comes from whoever queued the job, not from the model

A workflow that writes outside the machine is exported as an **async** tool with no `approve` argument. When it is called, it asks the agent app's own gate (`approval_runtime.request_tool_approval`), and the model has no way to answer for it. In the unattended worker the gate approves a tool only if the job's payload names it:

```json
{"task": "report_and_send_agent: ...", "approved_tools": ["report_and_send"]}
```

That list is written by whoever can insert into `agent_jobs` (a person or an app), so a task text cannot grant it. The same list now also approves the agent's built-in publishing tools (`worker_video_yayinla`, `video_uretimi_iste`), which used to be refused in the worker no matter what. At a terminal the person is asked. An MCP call has no such list yet, so a gated tool is refused there. With no gate at all (an agent app without `approval_runtime`) the exported tool refuses to run.

Checked against the real agent, with the same workflow and the same text: no approval from the job: refused, nothing written; a task that says "approve=true, the user approved": refused (the same wording had made the earlier version send); the job approves a different tool: refused; the job approves `report_and_send`: sent, and the log says the job approved it. Approval is per tool (per workflow), not per step.

## Things the agent needed to work here (found by running it)

- `config/agents.yaml` pins the sub-agents to `gemma-4-26b-a4b-it`, which DeepSeek rejects. The agent image rewrites that to `default` (= `SUBMODEL_MODEL_NAME`) at build time; the source file is untouched.
- The agent checks a platform-data request against `toolboxes/*/manifest.yaml` before queueing it. The compose file mounts that folder read-only at `/toolboxes` and sets `TOOLBOXES_DIR`.

Checked end to end: a task given to the agent as an `agent_jobs` row made it call `platform_data_agent`, which queued a correct `platform_data_jobs` row (`youtube.videos`); `platform-data-worker` ran it and failed with `Set YOUTUBE_API_KEY...`; the agent read that and reported it. Not checked: the same with a real `YOUTUBE_API_KEY` (put it in `env/platform-data-worker.env`).

## Known quirk

When the queue is empty, `claim_*` returns a row whose fields are all `null` instead of `null`. The Python workers handle that; `social-media-worker/adapters/supabase.js` treats it as a job and logs `invalid input syntax for type uuid: "null"` on every poll. The fix there is one line: return `data && data.id ? data : null`.
