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
