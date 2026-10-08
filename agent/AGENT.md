# Marketing Agent (Mimar)

An OpenAI-compatible, tool-calling orchestrator (`BaseModel`) that delegates
content-creation, research, and social-operations work to specialized
sub-agents. This is the `agents/marketing-agent` referenced in the repo
root's [`future_work.md`](../marketing-agent-assets/future_work.md) roadmap (Phase 2).

## Where this sits in the App ⇄ Worker ⇄ Agent split

```text
App ⇄ Social-media worker environment ⇄ Marketing agent (this)
```

Per `future_work.md`'s responsibility map, this agent owns **content
strategy, content creation, repurposing, and publish recommendations** — not
credentials, not direct platform automation policy, not source-of-truth
storage.

## What actually works today (honest scope)

The `future_work.md` "Planned worker environment interface" now has a
concrete agent-side implementation for all five items — but "implemented on
the agent side" and "there's a live App to talk to" are different claims,
and this repo is honest about which is which:

| Capability | Agent side | Needs from the App / a worker |
| --- | --- | --- |
| `collect_assets` | `asset_collector_agent`: `app_asset_listele`/`app_asset_detay` | An [asset-pool](../marketing-agent-assets/asset-pool)-shaped `GET /api/assets` — build your own or use the kit |
| `prepare_media` | `asset_collector_agent`: `medya_dogrula`/`medya_hazirla` | Optional `POST {id}/prepare`; without it, the listed asset is validated as-is |
| `request_video_generation` | `asset_collector_agent`: `video_uretimi_iste`/`video_uretimi_durumu` | Optional `POST /api/video-requests`; without it, the tool returns a clear "not implemented" error |
| `collect_platform_data` | `platform_data_agent`: `platform_veri_*` | The standalone [`platform_data_worker`](../marketing-agent-assets/platform_data_worker) — a real, runnable worker, not a stub |
| `execute_publish` | `sosyal_medya_agent`: `worker_video_yayinla`/`worker_instagram_carousel_yayinla`/`worker_yayin_durumu_sorgula` | [`social-media-worker`](../marketing-agent-assets/social-media-worker), which is real and running today |

Two of the five (`execute_publish` and `collect_platform_data`) have a real
worker on the other end right now. The other three depend on an App; this
repository doesn't contain one, but a real App — Kara Tahta, at a sibling
checkout `../../karatahta2` — has the asset-pool contract actually wired into
its own `server.js` (`routes/assetPool.js`, see
[`asset-pool/examples/karatahta/README.md`](../marketing-agent-assets/asset-pool/examples/karatahta/README.md)
for exactly what was changed and how it was checked). That wiring was
verified against Kara Tahta's real code — auth, routing, and the
"fails closed with a clear error" path all confirmed by starting the actual
server and hitting it with `curl`/`bin/check.js` — but not against a live
listing, since this dev machine's Kara Tahta `.env` has no Supabase project
configured yet. Point `APP_INTERNAL_URL`/`APP_INTERNAL_TOKEN` at a Kara Tahta
instance with `ASSET_POOL_TOKEN` and real Supabase credentials set to make it
live; until then, or for any other App, every tool for these three fails with
a clear configuration error instead of fabricating data (see each section
below).

`social-media-worker`'s `publish_jobs` queue accepts exactly two
schema-valid actions: `video.publish` and `instagram.carousel`
(see [`schemas/publish_request.schema.json`](../marketing-agent-assets/schemas/publish_request.schema.json)).

`MarketingApp/araclar/worker_yayinlama_araclari.py` adds three tools used by
the `sosyal_medya_agent` sub-agent:

- `worker_video_yayinla` / `worker_instagram_carousel_yayinla` validate a
  request against the schema's constraints (HTTPS URLs, platform enum,
  length limits), **require approval** (see below) and insert a row into
  `publish_jobs` via the Supabase REST API. The worker itself performs the
  actual publish; this agent only queues a validated, approved job. Each
  also accepts a `media_ref` instead of a raw URL — the handle
  `medya_hazirla` returns (see "Preparing media for publish" below) — so a
  signed App URL never has to pass through the model as plain text.
- `worker_yayin_durumu_sorgula(job_id)` reads that row back — `status`,
  `results`, `error`, matching
  [`schemas/publish_result.schema.json`](../marketing-agent-assets/schemas/publish_result.schema.json).
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
[`../marketing-agent-assets/social-media-worker/migrations/002_publish_jobs_idempotency_key.sql`](../marketing-agent-assets/social-media-worker/migrations/002_publish_jobs_idempotency_key.sql)
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
[`schemas/asset.schema.json`](../marketing-agent-assets/schemas/asset.schema.json) — from **any
app** that implements the [asset-pool contract](../marketing-agent-assets/asset-pool/README.md):
`GET {APP_INTERNAL_URL}{APP_ASSETS_PATH}` and
`GET {APP_INTERNAL_URL}{APP_ASSETS_PATH}/{id}` (default path `/api/assets`),
bearer-token auth. The agent is not coupled to any particular app.

To automate your own app, implement those two endpoints — the
[`asset-pool/`](../marketing-agent-assets/asset-pool) kit is a dependency-free handler plus a
conformance checker (`node asset-pool/bin/check.js <url> --token …`) — then
set `APP_INTERNAL_URL` / `APP_INTERNAL_TOKEN` (and `APP_ASSETS_PATH` if you
mounted it elsewhere). [Kara Tahta](../marketing-agent-assets/asset-pool/examples/karatahta) is
included purely as a worked example of mapping a real app onto the contract.

**Honest scope:** this repository contains no live App. The kit and the Kara
Tahta example are tested against fakes and a local reference server, and the
agent's tools were exercised over real HTTP against `asset-pool`'s minimal
example — but the Kara Tahta example has not been run against a live Kara Tahta
deployment. Until `APP_INTERNAL_URL` is set, every call returns a clear
configuration error instead of silently failing or fabricating data.

These tools are read-only by design: no credentials, upload, or approval-state
mutation ever happens through them, per the responsibility map's "does not
own: direct secret access" rule for this agent. A successful listing is also
cached to `workspace/assets/app_asset_catalog.json` so `content_creator_agent`
and `sosyal_medya_agent` can reference the same asset URLs without re-querying
the App.

## Preparing media for publish (new)

`future_work.md` item #3 (`prepare_media`). Two tools in
[`MarketingApp/araclar/medya_araclari.py`](./MarketingApp/araclar/medya_araclari.py),
both on `asset_collector_agent`:

- `medya_dogrula(url, aksiyon, platformlar)` checks an arbitrary HTTPS URL
  against the exact constraints `social-media-worker` enforces — reachable,
  correct content type, a Content-Length when YouTube/TikTok's upload needs
  one, TikTok's 64 MB single-chunk cap, Instagram carousels' JPEG-only rule
  (see `social-media-worker/services/{youtubePublish,tiktokPublish,instagramPublish}.js`,
  cited in the module's own comments) — **before** a publish job is queued,
  not after `social-media-worker` rejects it.
- `medya_hazirla(asset_ids, aksiyon, platformlar, ttl_saniye)` does the same
  for App-approved assets: it calls the asset pool's optional
  `POST {id}/prepare` if the App implements it (falls back to the listed
  asset if not — see `asset-pool/README.md`), runs it through the same
  checks, and on success returns an opaque **`media_ref`** instead of the
  real URL.

That last point matters: `future_work.md`'s security rules say signed URLs
must never enter an LLM prompt. A prepared asset's URL is exactly that kind
of URL, so it's never handed to the model — `medya_hazirla` stores it in
[`environments/media_registry.py`](./MarketingApp/environments/media_registry.py)
(a small workspace-local file, chmod 600) and returns a `media_ref` handle
the model can safely see and pass along. `worker_video_yayinla` /
`worker_instagram_carousel_yayinla` accept `media_ref` as an alternative to
`video_url`/`image_urls` and resolve it themselves; a ref is scoped to the
exact `(action, platforms)` it was prepared for and expires with the
underlying URL (max 6h), so it can't be replayed for a different publish
than the one it was checked against. Any URL these tools log or print is
masked to `https://host/path?…` first.

Both tools fetch the media themselves to check it, which means SSRF is a
real concern for arbitrary URLs (`medya_dogrula`): every host is resolved
and every IP checked as globally routable (rejecting loopback/private/
link-local ranges) before each request, including after every redirect hop.
This narrows the window but doesn't close a DNS-rebinding race between the
check and the fetch — these tools are advisory, not a security boundary;
`social-media-worker` still validates independently when it actually
publishes.

## Requesting video generation (new)

`future_work.md` item #4 (`request_video_generation`) — the one item that
would otherwise mean a real architecture change (content_creator_agent
currently renders locally via Playwright/stock footage; this is the
alternative path of asking the App to render instead). Two tools in
[`MarketingApp/araclar/video_uretim_araclari.py`](./MarketingApp/araclar/video_uretim_araclari.py),
on `asset_collector_agent`:

- `video_uretimi_iste(brief, baslik, sure_saniye, yonelim, dil)` — `brief`
  is a plain-text description, explicitly **not** a command (the future_work.md
  wording: "the agent supplies a brief, not executable infrastructure
  commands"); code fences and control characters are rejected outright so a
  brief can't smuggle instructions. Two safety rails apply before anything
  is sent, because generation can be expensive and isn't easily undone:
  - **Approval**, via the same `approval_runtime` gate as publishing —
    `VIDEO_GENERATION_REQUIRES_APPROVAL` (default `true`) can turn it off
    for a deployment that has wired its own headless approval flow.
  - **A daily cap** (`VIDEO_GENERATION_MAX_PER_DAY`, default 3) counting
    distinct requests in the last 24h, tracked in a small workspace log.
  An `Idempotency-Key` (derived from the request content) also goes on the
  HTTP call itself, so a retried request never starts a second render on
  the App's side either.
- `video_uretimi_durumu(request_id)` polls `GET {video-requests}/{id}`.

**The result is a draft, not a publishable asset.** A `done` status's
`asset` is marked `approval: "pending"` unless the App has explicitly
approved it — and this agent treats "not in the asset pool yet"
(`app_asset_detay` returning 404) as exactly that: not approved. The
system prompt tells `asset_collector_agent` to say so plainly rather than
treat a finished render as ready to publish.

Same honest-scope rule as the rest of this section: without an App that
implements `POST {APP_INTERNAL_URL}{APP_VIDEO_REQUESTS_PATH}` (default
`/api/video-requests` — see `asset-pool/README.md`), both tools return a
clear "not implemented" error. [Kara Tahta](../marketing-agent-assets/asset-pool/examples/karatahta/videoSource.js)
is included as a worked example (Kara Tahta's own `/api/generate-lesson` /
`/api/jobs/:id`), tested against a fake backend, not a live one.

## Collecting platform data (new)

`future_work.md` item #2 (`collect_platform_data`) — the one capability
that needs a **second, standalone worker**, because it needs platform
credentials this agent must never hold. Three tools in
[`MarketingApp/araclar/platform_veri_araclari.py`](./MarketingApp/araclar/platform_veri_araclari.py),
now on their own sub-agent, `platform_data_agent` (kept separate from
`sosyal_medya_agent` so a purely read-only analysis task can run without
ever touching the browser-based social tools):

- `platform_veri_eylemleri(platform)` lists what can be collected.
- `platform_veri_topla(platform, eylem, parametreler, bekleme_saniye)`
  queues a request and waits (briefly) for the answer.
- `platform_veri_durumu(job_id)` polls it later if it didn't finish in time.

These insert into a new `platform_data_jobs` Supabase table (migration:
[`migrations/001_agent_jobs.sql`](./migrations/001_agent_jobs.sql)'s sibling
in [`../marketing-agent-assets/platform_data_worker/migrations/`](../marketing-agent-assets/platform_data_worker/migrations))
and read the result back — the agent process never holds a YouTube, Instagram,
TikTok, X, or Reddit credential. **[`platform_data_worker`](../marketing-agent-assets/platform_data_worker)
is the real thing here**, not a stub behind a future App: it's a standalone,
runnable worker (own `requirements.txt`, own `README.md`) that holds those
credentials, checks every request against a hand-written allowlist in each
platform's `toolboxes/*/manifest.yaml` (`data_collection.actions:` — every
write action is absent from that list by construction), and runs the one
approved read-only toolbox function that matches. The agent's own
pre-check duplicates those same rules for a fast local rejection, but the
worker's copy is the one that's actually enforced; a test in that worker's
suite (`test_agent_policy_parity.py`) keeps the two from drifting apart.

Without `platform_data_worker` running (or without `SUPABASE_URL`/
`SUPABASE_AGENT_KEY`/`SUPABASE_SECRET_KEY` set), a request just sits queued
and `platform_veri_topla` says so plainly rather than inventing metrics.

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
   bearer-token pattern as [`mcp_worker`](../marketing-agent-assets/mcp_worker): any MCP client
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
