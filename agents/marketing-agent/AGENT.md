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

`MarketingApp/araclar/worker_yayinlama_araclari.py` adds two tools —
`worker_video_yayinla` and `worker_instagram_carousel_yayinla` — used by the
`sosyal_medya_agent` sub-agent. They validate a request against the schema's
constraints (HTTPS URLs, platform enum, length limits) and insert a row into
`publish_jobs` via the Supabase REST API using `SUPABASE_URL` /
`SUPABASE_SECRET_KEY` — the **same** Supabase project `social-media-worker`
already polls. The worker itself performs the actual publish; this agent
only queues a validated job.

This gives Mimar a capability it never had before: publishing generated
video/carousel content to Instagram, YouTube, and TikTok (previously it
could only reach X/Twitter, and only through a local Selenium browser
session).

**Caller responsibility:** `videoUrl` / `imageUrls` must already be hosted
at an HTTPS URL. This agent does not upload local files anywhere — per the
responsibility map, media storage belongs to the App layer, which does not
exist in this repository yet.

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
`SUPABASE_SECRET_KEY` in `.env` to the same project `social-media-worker`
uses; without them, `worker_video_yayinla` / `worker_instagram_carousel_yayinla`
return a clear configuration error instead of silently failing.

## Embedding

[`MarketingApp/agent_api.py`](./MarketingApp/agent_api.py) exposes a
side-effect-free `MimarAgent` class (no heartbeat/Telegram/Discord
auto-start) for calling this agent programmatically from another
orchestrator, with an injectable workspace/config directory. See its
module docstring for the single-process-per-workspace caveat.
