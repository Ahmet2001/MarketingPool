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

## Things the agent needed to work here (found by running it)

- `config/agents.yaml` pins the sub-agents to `gemma-4-26b-a4b-it`, which DeepSeek rejects. The agent image rewrites that to `default` (= `SUBMODEL_MODEL_NAME`) at build time; the source file is untouched.
- The agent checks a platform-data request against `toolboxes/*/manifest.yaml` before queueing it. The compose file mounts that folder read-only at `/toolboxes` and sets `TOOLBOXES_DIR`.

Checked end to end: a task given to the agent as an `agent_jobs` row made it call `platform_data_agent`, which queued a correct `platform_data_jobs` row (`youtube.videos`); `platform-data-worker` ran it and failed with `Set YOUTUBE_API_KEY...`; the agent read that and reported it. Not checked: the same with a real `YOUTUBE_API_KEY` (put it in `env/platform-data-worker.env`).

## Known quirk

When the queue is empty, `claim_*` returns a row whose fields are all `null` instead of `null`. The Python workers handle that; `social-media-worker/adapters/supabase.js` treats it as a job and logs `invalid input syntax for type uuid: "null"` on every poll. The fix there is one line: return `data && data.id ? data : null`.
