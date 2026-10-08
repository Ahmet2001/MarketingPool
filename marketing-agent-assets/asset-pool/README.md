# Asset pool

The app-side half of three of the marketing agent's capabilities from
[`future_work.md`](../future_work.md)'s planned worker environment interface:
`collect_assets` (required), and `prepare_media` / `request_video_generation`
(both optional). Any app can expose its **approved** media — videos, images,
audio, documents — through a small set of endpoints; the agent's
`asset_collector_agent` reads/prepares them, and the agent's content and
publish tools then work with the returned HTTPS URLs.

```text
your app ──GET /api/assets────────▶ asset_collector_agent ──▶ content_creator_agent
(you decide     │ POST .../prepare                        └──▶ worker_video_yayinla → social-media-worker
 what's         │ (optional)
 approved)      └─POST /api/video-requests (optional) ◀── video_uretimi_iste
                                                            (a brief, not a command)
```

This directory is a small, dependency-free kit for building those endpoints, a
conformance checker to prove you built them right, and two examples. It is
deliberately **not tied to any one app**: [Kara Tahta](./examples/karatahta) is
included only as a worked example of mapping a real app onto the contract.

## The contract

`GET {base}/api/assets` — list (default `/api/assets`; the agent's
`APP_ASSETS_PATH` can point anywhere else)

| Query | Meaning |
| --- | --- |
| `kind` | `video`, `image`, `audio` or `document`. Anything else → `400`. |
| `tag` | Free-text filter, interpreted by the app (title, tags, topic…). Max 200 chars. |
| `limit` | Positive integer, default 20, capped at 100. Not a positive integer → `400`. |

→ `200 {"assets": [Asset, …]}`

`GET {base}/api/assets/{id}` — one asset

→ `200 Asset` (the bare object) · `404 {"error": …}` if it doesn't exist **or isn't approved**

Every request carries `Authorization: Bearer <token>`. Missing or wrong token →
`401`/`403`. Errors are always `{"error": "message"}`.

An **Asset** is exactly [`schemas/asset.schema.json`](../schemas/asset.schema.json):

```json
{
  "id": "video:3f9c…",
  "kind": "video",
  "url": "https://cdn.example.com/launch.mp4?sig=…",
  "contentType": "video/mp4",
  "title": "Launch teaser",
  "altText": "optional, ≤ 2000 chars",
  "expiresAt": "2026-09-19T12:00:00Z",
  "metadata": { "anything": "the app wants the agent to see" }
}
```

Only `id`, `kind` and `url` are required; unknown fields are not allowed.

Two more capabilities are optional — implement either, both, or neither
depending on what your app can offer:

`POST {base}/{id}/prepare` — media preparation (`prepare_media`). Body
[`media_prepare_request.schema.json`](../schemas/media_prepare_request.schema.json):

```json
{ "target": { "platform": "youtube", "action": "video.publish" }, "ttlSeconds": 3600 }
```

`target.action` is `video.publish` or `instagram.carousel` (the two the
worker actually supports — see the root [README](../README.md)).
→ `200 Asset` re-signed/converted and ready for that target · `404` unknown
id · `422 { "error", "reasons": [...] }` when the asset can't be made to fit
(wrong format, wrong aspect ratio — say so, don't guess) · `501` if you don't
implement this (the agent falls back to using the asset as originally
listed). Not implementing `prepare` is fine as long as `GET {id}` already
returns something publishable.

`POST {video-requests}` / `GET {video-requests}/{id}` — video generation
(`request_video_generation`, default path `/api/video-requests`). The agent
sends a plain-text **brief**, never a command:

```json
{ "brief": "A 30 second explainer about compound interest, friendly tone.", "durationSeconds": 30 }
```

Body [`video_generation_request.schema.json`](../schemas/video_generation_request.schema.json)
→ `202` status document, matching [`video_generation_status.schema.json`](../schemas/video_generation_status.schema.json):
`{ requestId, status: queued|running|done|failed, progress?, asset?, approval?, error? }`.
Send an `Idempotency-Key` header on every request; the same key must return
the **same** `requestId` instead of starting a second render — a network
retry must never double-bill. A `done` status's `asset` is a **draft**:
mark it `approval: "pending"` until you've actually approved it, and don't
serve it from `GET {pool}/{id}` before then — the asset pool is where your
approval decision lives, and the agent treats "not there yet" as "not
approved yet". `501`/`404`/`405` on this route means the capability isn't
implemented; the agent won't ask for a video and will look for an existing
approved asset instead.

## What implementers must guarantee

The agent treats whatever the pool returns as *approved for use*. So:

- **Approval is yours.** Decide what "approved" means in your app (a `published`
  flag, a review state, a folder) and only ever return those assets. If the pool
  can return it, the agent may put it in a publish request.
- **`url` is HTTPS**, read-only, and — if signed — lives long enough for a
  queued publish job to still fetch it. A worker may pick a job up hours after
  the agent asked; set `expiresAt` honestly and size the TTL for that, not for a
  browser tab. (The kit refuses `http://` outright.)
- **No secrets.** Nothing in `url`, `title`, `altText` or `metadata` may be a
  credential, an API key or another user's data — `metadata` is shown to an LLM.
- **Stable, opaque ids** that keep working for `GET /{id}`.
- **Read-only.** The pool never uploads, approves or deletes. Those stay in your app.
- **Fail closed.** An unset token must refuse everything, never serve openly.

## Build one

**A. In an app that already runs Express or `node:http`** — copy the `src/`
directory next to your code (no dependencies of its own) and mount the handler:

```js
import { createAssetPoolHandler } from './assetPool/handler.js';

app.use('/api/assets', createAssetPoolHandler({
  token: process.env.ASSET_POOL_TOKEN,
  async listAssets({ kind, tag, limit }, ctx) {
    return db.approvedAssets({ kind, tag, limit });   // return objects shaped like Asset
  },
  async getAsset(id, ctx) {
    return db.approvedAsset(id);                      // or null → 404
  }
}));
```

The handler does the boring, easy-to-get-wrong parts for you: constant-time
token check, query validation, `kind` enforcement even if your query ignores it,
`limit` capping, `Cache-Control: private, no-store`, opaque 500s (an exception
message never reaches the caller), and contract validation of everything you
return — undeclared fields are stripped, and non-conforming assets (say an
`http://` URL) are dropped and counted in an `X-Asset-Pool-Dropped` header
rather than forwarded. To resolve *who is asking* from something richer than a
shared token, pass `authenticate(req)` instead of `token`; whatever it returns
reaches `listAssets`/`getAsset` as `ctx`.

**B. From scratch** — [`examples/minimal/server.js`](./examples/minimal/server.js)
is a whole working pool over a JSON file in a few dozen lines. Copy it and swap the
two functions for your storage.

**C. In another language** — the contract above is all there is. Implement it
and let the checker tell you if you got it right.

`prepare` and the video-generation endpoints follow the same two paths: mount
`createAssetPoolHandler({ ..., prepareAsset })` (adds the route only if you
pass `prepareAsset`) and, separately, `createVideoRequestHandler({ token,
createVideoRequest, getVideoRequest })` at whatever path you like.

## Prove it

```bash
node bin/check.js https://your-app.example.com --token "$ASSET_POOL_TOKEN"
# also probe the optional capabilities:
node bin/check.js https://your-app.example.com --token "$ASSET_POOL_TOKEN" --prepare --video-requests
# self-test against the bundled example:
ASSET_POOL_TOKEN=change-me npm run example:minimal &
node bin/check.js http://127.0.0.1:8095 --token change-me
```

It checks that an unauthenticated or wrong-token request is refused, every asset
validates strictly against the schema, ids are unique, nothing is already
expired, `?limit` and `?kind` behave, an unknown `?kind` is a `400`, `GET /{id}`
returns the same asset (and `404` for a missing one), and that responses aren't
cacheable by shared proxies. Exit code `1` on any failure (warnings and skips
don't fail the run); `--json` for CI.

`--prepare` and `--video-requests` are opt-in and report `skip` (not `fail`)
when the app hasn't implemented that capability, so they're safe to run
against a pool that only serves assets. `--video-requests` alone never
creates anything; add `--video-brief "..."` to also submit one real request
and verify `Idempotency-Key` handling — only do that against an app you're
fine having actually start (and possibly bill) a render.

## Point the agent at it

In `agent/.env`:

```bash
APP_INTERNAL_URL=https://your-app.example.com
APP_INTERNAL_TOKEN=<the same shared secret>
APP_ASSETS_PATH=/api/assets              # only if you mounted it elsewhere
APP_VIDEO_REQUESTS_PATH=/api/video-requests  # only if you implement it and mounted it elsewhere
```

`asset_collector_agent` then has `app_asset_listele`/`app_asset_detay`
(listing), `medya_hazirla`/`medya_dogrula` (calls `prepare` when you
implement it), and `video_uretimi_iste`/`video_uretimi_durumu` (video
generation, gated by an approval step and a daily cap — see the agent's
`AGENT.md`). A successful listing is cached in the agent workspace so other
agents reuse the URLs. One pool per agent process — to automate several
apps, run one agent worker per app. See the agent's
[`AGENT.md`](../../agent/AGENT.md).

## Examples

| Example | What it shows |
| --- | --- |
| [`examples/minimal`](./examples/minimal) | The smallest possible pool: a JSON file behind the contract. |
| [`examples/karatahta`](./examples/karatahta) | Mapping a real app (lessons, videos, posters, signed storage URLs, its own video-generation API) onto the contract, with the wiring for that app. |

## Development

```bash
npm test     # node --test, no install needed
```

`src/assetSchema.js` mirrors the JSON schema by hand so the kit has no
dependencies; `test/schema-drift.test.js` fails if the two ever disagree — edit
[`schemas/asset.schema.json`](../schemas/asset.schema.json) first.
