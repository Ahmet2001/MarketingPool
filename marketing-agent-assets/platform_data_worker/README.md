# Platform Data Worker

A standalone worker that holds platform credentials (YouTube, Instagram,
TikTok, X, Reddit) so `agent` never has to: it claims
`{platform, action, params}` requests from a Supabase queue, checks each one
against a **manifest allowlist**, runs the one approved, read-only toolbox
function that matches, and writes a normalized result back. This is the
`collect_platform_data` piece of [`future_work.md`](../future_work.md)'s
planned worker environment interface.

```text
marketing-agent ──insert──▶ platform_data_jobs ──claim──▶ platform_data_worker
   (writes {platform,                                        │ validates against
    action, params},                                         │ toolboxes/*/manifest.yaml,
    reads results)                                            │ runs the toolbox with
                                                                │ ITS OWN credentials
                          ◀────────────── results ─────────────┘
```

## Why an allowlist, not "run any toolbox function"

[`toolboxes/`](../toolboxes) ships a full API surface per platform, publish
actions included. Nothing here executes a toolbox function by name from a
request. Each platform's `manifest.yaml` has a `data_collection.actions:`
section — a hand-written, versioned list of exactly which `get_`/`search_`/
`list_` functions may run, with per-parameter type/enum/pattern/length rules
and an hourly rate limit. An action or parameter that isn't declared there
does not exist as far as a request is concerned; every write action is
absent by construction, not filtered out at request time.

[`policy.py`](./policy.py) loads and enforces that allowlist; the marketing
agent runs the same rules as a fast client-side pre-check
(`MarketingApp/araclar/platform_veri_araclari.py`) but the worker is the one
whose verdict counts — `tests/test_agent_policy_parity.py` keeps the two in
sync against the real manifests, and `tests/test_manifest_drift.py` fails
the moment a manifest names a function that doesn't exist, isn't
read-shaped, or takes different parameters than declared.

## Quick start

```bash
cd platform_data_worker
cp .env.example .env
pip install -r requirements.txt
```

Apply [`migrations/001_platform_data_jobs.sql`](./migrations/001_platform_data_jobs.sql)
to the same Supabase project `social-media-worker`/`agent`
use (same `SUPABASE_URL`/`SUPABASE_SECRET_KEY`), configure credentials only
for the platforms you're collecting from, then:

```bash
python -m platform_data_worker.worker
```

It polls `platform_data_jobs` every `PLATFORM_DATA_POLL_MS` (default 5s),
draining the whole queue before waiting again.

## What a job looks like

Payload matches [`schemas/platform_data_request.schema.json`](../schemas/platform_data_request.schema.json):

```json
{ "platform": "youtube", "action": "comment_threads", "params": { "video_id_or_url": "…", "max_results": 50 } }
```

Result matches [`schemas/platform_data_result.schema.json`](../schemas/platform_data_result.schema.json):
`status` (`done`/`failed`), `results.data` (whatever the toolbox function
returned), `results.truncated` if the answer was shrunk to fit
`PLATFORM_DATA_MAX_RESULT_BYTES`, `results.error` on failure. Any
environment-variable-shaped secret value is redacted from both the result
and any error message before it's written to the row — a platform SDK
echoing a token back in an error string can't leak it into the queue.

`credentialRef` (multi-account routing) is accepted by the schema but this
worker refuses it today — one credential set per platform, configured in its
own environment. A job naming a `credentialRef` fails clearly rather than
silently answering with the wrong account's data.

## Honest scope

- Every declared parameter is re-validated here even though the agent
  already checked it — the agent's copy is a convenience, not the authority.
- Rate limiting counts recent `platform_data_jobs` rows per
  `(platform, action)`; it is best-effort (a race between two workers could
  both admit one job over the limit) and resets are a rolling 24h window,
  not calendar-aligned.
- No pagination helpers: a `max_results`/`limit` param is passed straight to
  the toolbox function's own default. Fetching "everything" is not a shape
  this worker offers.

## Tests

```bash
python -m unittest discover -s tests -t ..
```

Runs entirely against the real `toolboxes/*/manifest.yaml` files and (for
`test_integration.py`) the real toolbox modules, with only the network layer
(`requests.request`) faked — so a manifest change that breaks the contract
with its toolbox fails here before it ever reaches a live credential.
