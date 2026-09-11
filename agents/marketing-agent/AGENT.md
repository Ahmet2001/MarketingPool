# Marketing Agent (Mimar)

An OpenAI-compatible, tool-calling orchestrator (`BaseModel`) that delegates
content-creation, research, and social-operations work to specialized
sub-agents. This is the `agents/marketing-agent` referenced in the repo
root's [`future_work.md`](../../future_work.md) roadmap (Phase 2).

## Where this sits in the App ⇄ Worker ⇄ Agent split

```text
App ⇄ Social-media worker environment ⇄ Marketing agent (this)
```

Per `future_work.md`'s responsibility map, this agent owns **content
strategy, content creation, repurposing, and publish recommendations** — not
credentials, not direct platform automation policy, not source-of-truth
storage.

## What actually works today (honest scope)

The `future_work.md` "Planned worker environment interface"
(`collect_assets`, `collect_platform_data`, `prepare_media`,
`request_video_generation`, `execute_publish`) is **not implemented
upstream yet** — it's a roadmap, not a live HTTP surface. This agent does
not pretend otherwise. The one integration point that genuinely exists
today is [`social-media-worker`](../../social-media-worker)'s `publish_jobs`
Supabase queue, which accepts exactly two schema-valid actions:
`video.publish` and `instagram.carousel`
(see [`schemas/publish_request.schema.json`](../../schemas/publish_request.schema.json)).

`MarketingApp/araclar/worker_yayinlama_araclari.py` adds three tools used by
the `sosyal_medya_agent` sub-agent:

- `worker_video_yayinla` / `worker_instagram_carousel_yayinla` validate a
  request against the schema's constraints (HTTPS URLs, platform enum,
  length limits), **require approval** (see below) and insert a row into
  `publish_jobs` via the Supabase REST API. The worker itself performs the
  actual publish; this agent only queues a validated, approved job.
- `worker_yayin_durumu_sorgula(job_id)` reads that row back — `status`,
  `results`, `error`, matching
  [`schemas/publish_result.schema.json`](../../schemas/publish_result.schema.json).
  **This is not optional to skip:** queuing a job successfully only means
  the row was inserted, not that anything was published. The agent's system
  prompt tells it to check this before logging a publish as successful —
  without it, the only signal Mimar ever had was its own "✅ queued" message,
  which said nothing about what `social-media-worker` actually did with it.

All three talk to the **same** Supabase project `social-media-worker` already
polls, authenticated via `SUPABASE_AGENT_KEY` (preferred, scoped) or
`SUPABASE_SECRET_KEY` (fallback, full service-role) — see "Supabase
anahtarını daraltma" below.

This gives Mimar a capability it never had before: publishing generated
video/carousel content to Instagram, YouTube, and TikTok (previously it
could only reach X/Twitter, and only through a local Selenium browser
session).

**Caller responsibility:** `videoUrl` / `imageUrls` must already be hosted
at an HTTPS URL. This agent does not upload local files anywhere — per the
responsibility map, media storage belongs to the App layer, which does not
exist in this repository yet.

### Approval gate

`future_work.md`'s "Present external-write actions for approval when
required" rule now has a real gate, not just documentation: before either
publish tool inserts a job, it calls
[`environments/approval_runtime.request_tool_approval`](./MarketingApp/environments/approval_runtime.py).
That module is a process-wide registry (same pattern as
`automation_runtime.py`/`vlm_araclari.get_registered_bot()`) that any plain
`araclar/` function can reach into without holding a `BaseModel` reference:

- **Terminal** (`main.py`): `BaseModel` always registers a handler that
  defers to `self.request_approval`, which `TerminalManager` overrides with
  an interactive `y/n` prompt — unchanged behavior, a human approves.
- **Headless** (`MimarAgent`, and therefore `worker.py` and any other
  embedder that doesn't pass its own `approval_handler`): registers
  `reject_all_approvals` by default — every gated action is refused
  immediately and logged, because there is no one to ask. This is
  deliberately fail-closed rather than silently approving or hanging on
  `BaseModel`'s 300-second default wait for an event nothing will ever set.
  Pass `MimarAgent(approval_handler=...)` to plug in a real approval flow
  (e.g. a callback into a dashboard) once one exists.

Net effect: today, a risky publish requested through `worker.py` (queue or
MCP) is **always rejected** — there is no approver wired up for headless
contexts yet. Run it through the terminal (a human present) if you need a
publish to actually go through. That's an intentional, honest limitation,
not a bug — building a real headless-approval channel is future work.

### Idempotency

`worker_video_yayinla`/`worker_instagram_carousel_yayinla` (and
`agent_job_queue.insert_agent_job`) derive a deterministic `idempotency_key`
from the request payload before inserting. A second call with the exact
same content — a network retry, an LLM re-attempting a tool call it thinks
failed — hits the unique index added in
[`../../social-media-worker/migrations/002_publish_jobs_idempotency_key.sql`](../../social-media-worker/migrations/002_publish_jobs_idempotency_key.sql)
(and this repo's own
[`migrations/002_agent_jobs_idempotency_key.sql`](./migrations/002_agent_jobs_idempotency_key.sql))
and returns the **existing** job's status instead of creating a duplicate.
Trade-off, stated plainly: two genuinely-intentional identical publishes
(same URL, same caption, same platforms) will also dedupe. Given how
specific a publish payload is, that's judged unlikely enough to accept for
now — vary the caption slightly if you really mean to re-publish the exact
same thing.

### Supabase anahtarını daraltma

Today both `worker_yayinlama_araclari.py` and `worker.py`'s `agent_jobs`
client fall back to `SUPABASE_SECRET_KEY` — the service-role key, which
bypasses RLS and can read/write **every** table in the project, not just
`publish_jobs`/`agent_jobs`. That's a wider grant than the responsibility
map intends ("Marketing agent... does not own: direct secret access"), and
it exists purely because provisioning a narrower one requires access to the
actual Supabase project (which this repo doesn't have).

Both new migrations ship a commented-out, ready-to-run role + RLS policy
(`marketing_agent_writer`: insert+select on `publish_jobs`,
insert+select+update on `agent_jobs`, nothing else). To actually adopt it:

1. Uncomment and run the `create role` / `grant` / `create policy`
   statements in `migrations/002_*_idempotency_key.sql` (both repos).
2. In the Supabase dashboard, generate a new API key mapped to
   `marketing_agent_writer` (Project Settings → API Keys).
3. Put that key in `SUPABASE_AGENT_KEY` in `.env` — both
   `worker_yayinlama_araclari.py` and `agent_job_queue.py` already prefer it
   over `SUPABASE_SECRET_KEY` and log a one-time warning whenever they fall
   back to the broad key.

Until that's done, nothing changes — the agent keeps working exactly as it
does today, just with more access than it strictly needs.

## Asset collection (new)

The `future_work.md` "Planned worker environment interface" item #1
(`collect_assets`) now has a first concrete implementation on the agent
side: a new `asset_collector_agent` sub-agent with three tools
(`app_baglanti_durumu`, `app_asset_listele`, `app_asset_detay`, in
[`MarketingApp/araclar/app_asset_araclari.py`](./MarketingApp/araclar/app_asset_araclari.py))
that read approved media assets — matching
[`schemas/asset.schema.json`](../../schemas/asset.schema.json) — from the
App over plain HTTP (`GET {APP_INTERNAL_URL}/api/assets` and
`GET {APP_INTERNAL_URL}/api/assets/{id}`, bearer-token auth).

**Honest scope:** the App does not expose this endpoint yet (same "roadmap,
not a live HTTP surface" caveat as the worker section above). Until
`APP_INTERNAL_URL` is set, every call returns a clear configuration error
instead of silently failing or fabricating data. Once the App implements
the two-endpoint contract described in `app_asset_araclari.py`'s module
docstring, setting `APP_INTERNAL_URL` (and `APP_INTERNAL_TOKEN` if the App
requires it) is enough to make it work — no code changes needed.

These tools are read-only by design: no credentials, upload, or approval-state
mutation ever happens through them, per the responsibility map's "does not
own: direct secret access" rule for this agent. A successful listing is also
cached to `workspace/assets/app_asset_catalog.json` so `content_creator_agent`
and `sosyal_medya_agent` can reference the same asset URLs without re-querying
the App.

## Running the agent as a worker (new)

Besides the interactive terminal (`main.py`), this agent can now run
unattended as a worker: `python -m MarketingApp.worker` (or `./worker.sh`)
starts one process with **two** entry points sharing a single `MimarAgent`
instance, serialized through the existing `AutomationCoordinator` so they
never touch `BaseModel`/the browser session concurrently:

1. **Queue poller** — polls the new `agent_jobs` Supabase table (schema in
   [`migrations/001_agent_jobs.sql`](./migrations/001_agent_jobs.sql), same
   Supabase project as `publish_jobs`) for `status='queued'` rows, claims one
   at a time (`claim_next_agent_job()`, same skip-locked pattern as
   `social-media-worker`'s `claim_publish_job()`), runs
   `payload.task`/`payload.context` through `MimarAgent.run()`, and writes
   `results`/`error`/`status` back. Anything — the App, a cron job, a human
   via `psql`/Studio — queues work just by inserting a row; nothing needs to
   import Python to use it.
2. **MCP server** (Streamable HTTP, `POST /mcp`) — same protocol and
   bearer-token pattern as [`mcp_worker`](../../mcp_worker): any MCP client
   can call `run_marketing_task(task, context)` on demand. Because a task can
   run long (`browser_agent`'s tool calls have no timeout), it blocks up to
   `AGENT_WORKER_WAIT_MS` and then returns `{status:"running", jobId}` instead
   of hanging, mirroring `mcp_worker`'s `generate_lesson_video` /
   `check_lesson_status` pattern — poll with `check_marketing_task(job_id)`.
   Without `AGENT_WORKER_MCP_TOKEN` set, the server answers every request
   with 500 rather than running open (same rule as `mcp_worker/server.js`).

Both entry points write to the same `agent_jobs` table when Supabase is
configured, so it doubles as an audit trail regardless of which one handled
a given task; the MCP path still works standalone (no Supabase) if you only
want on-demand calls.

**Known limitation:** the two entry points coordinate with each other only
*inside this one process*. Running `worker.py` and `main.py` against the
same `workspace_dir` at the same time is unsupported — that's the same
single-process/single-workspace constraint [`agent_api.py`](./MarketingApp/agent_api.py)
already documents for `MimarAgent`, just restated here because `worker.py`
is a second thing that constructs one. Pick one per workspace.

## What deliberately stays out of the worker

Everything the worker has no contract for — liking, following, commenting,
posting text tweets, scanning notifications, reading feeds — keeps running
exactly as it did in the standalone Mimar project: through the `browser_*`
Selenium tools in `sosyal_medya_agent`, marked `supervised_local_only` in
spirit (an interactive, signed-in browser session, not something a
background worker replica should run). Moving these into the worker would
require the worker to gain real per-platform write actions beyond
`video.publish`/`instagram.carousel`, which is future work, not something
this change invents.

## Running it standalone

This agent is a full, independently runnable copy of the upstream
[BrowserAgent](https://github.com/Ahmet2001/BrowserAgent) project (as of the
commit it was copied at). See its own [README](./README.md) for setup,
configuration, and terminal usage — nothing about running it changed by
being placed here.

To also use the worker-publish tools, set `SUPABASE_URL` and
`SUPABASE_AGENT_KEY` (preferred) or `SUPABASE_SECRET_KEY` in `.env` to the
same project `social-media-worker` uses; without them,
`worker_video_yayinla` / `worker_instagram_carousel_yayinla` /
`worker_yayin_durumu_sorgula` return a clear configuration error instead of
silently failing. Remember the two tools that write also require approval
(see "Approval gate" above) — from the terminal that's an interactive
prompt; from `worker.py` it's an automatic rejection until a headless
approval flow is wired up.

## Embedding

[`MarketingApp/agent_api.py`](./MarketingApp/agent_api.py) exposes a
side-effect-free `MimarAgent` class (no heartbeat/Telegram/Discord
auto-start) for calling this agent programmatically from another
orchestrator, with an injectable workspace/config directory. See its
module docstring for the single-process-per-workspace caveat. It also
accepts an `approval_handler` — see "Approval gate" above — defaulting to
an immediate rejection, since a headless embedder has no one to ask.
