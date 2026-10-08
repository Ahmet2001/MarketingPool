# Example: Kara Tahta

Kara Tahta is the app this repository's [`scheduler_worker`](../../../scheduler_worker)
and [`mcp_worker`](../../../mcp_worker) were extracted from: it renders lesson
videos and card carousels. This directory shows how it (or any app with a
similar shape) maps onto the [asset-pool contract](../../README.md). **It is an
example, not a dependency** — nothing else in this repo imports it, and your app
should follow the same recipe with your own tables.

## What is exposed

| Kara Tahta | Asset | Id |
| --- | --- | --- |
| A lesson's finished video | `kind: "video"` | `video:<lessonId>` |
| That lesson's poster image | `kind: "image"` (with `altText`) | `poster:<lessonId>` |

**Approval = `lessons.is_public`.** Kara Tahta already has a "show in the public
catalog" switch that its owner flips on purpose; the pool treats that as the
approval signal and only ever queries public lessons, so a private lesson can't
leak — it is never read. Also left out, deliberately:

- **YouTube imports** — no downloadable file, and Kara Tahta itself refuses to re-publish them.
- **Lessons that aren't done rendering.**
- **Card sessions** — cards are rendered on demand as data URLs and published
  through the app's own `/api/cards/sessions/:id/publish-instagram`, so there is
  no stable HTTPS asset to hand over.

Signed URLs are minted with the *publish* lifetime (24h, matching Kara Tahta's
`SOCIAL_PUBLISH_VIDEO_URL_TTL_SECONDS`), not the 1h player lifetime, because a
queued publish job may be picked up long after the agent listed the asset.
`expiresAt` carries the real expiry.

`assetSource.js` also implements `prepare_media` (`POST .../prepare`): it
re-signs with whatever `ttlSeconds` was asked for, but does no format
conversion, so it **refuses** (`422`, with reasons) a poster that isn't a
JPEG for `instagram.carousel` rather than publishing it wrong — Kara Tahta's
own `instagramPublish.js` only accepts JPEG there. A real app could convert
here instead of refusing; this example intentionally keeps that decision
visible rather than hiding it.

## Requesting a new video: `videoSource.js`

[`videoSource.js`](./videoSource.js) implements `request_video_generation`
by calling Kara Tahta's own `POST /api/generate-lesson` / `GET /api/jobs/:id`
— the same two calls [`mcp_worker`](../../../mcp_worker) makes — authenticated
with the scheduler shared secret (`SCHEDULER_INTERNAL_TOKEN`, the same
mechanism [`scheduler_worker`](../../../scheduler_worker) uses). A `done`
job's video is reported as a **draft** (`approval: "pending"`): Kara Tahta
lessons are private until their owner makes them public, and that's the same
`is_public` flag `assetSource.js` treats as approval above — so the asset
only becomes usable once it independently shows up via `GET /api/assets`.

Two things worth knowing if you adopt this as-is:

- **Idempotency is in-memory only.** Kara Tahta's `/api/generate-lesson` has
  no retry-safety of its own, so `videoSource.js` remembers
  `Idempotency-Key -> requestId` itself (24h). That survives one process but
  not a restart or multiple replicas — a real deployment should persist that
  mapping (e.g. in Kara Tahta's own database) instead.
- `title`/`language` in a request are accepted by the contract but ignored
  here: Kara Tahta derives both from the topic itself.

Wire it the same way as `assetSource.js` (see below), reusing the app's
scheduler token:

```js
import { createVideoRequestHandler } from '../services/assetPool/videoRequests.js';
import { createKaratahtaVideoSource } from '../services/assetPool/videoSource.js';

export const videoRequestHandler = createVideoRequestHandler({
  token: process.env.ASSET_POOL_TOKEN,
  ...createKaratahtaVideoSource({
    backendUrl: process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:3000',
    token: process.env.SCHEDULER_INTERNAL_TOKEN
  })
});
```

## Wire it into Kara Tahta

This is actually wired into the real Kara Tahta app at
`/home/rifat/Masaüstü/karatahta2` (not just described here) — the recipe
below is exactly what was done, so you can diff against it:

1. `asset-pool/src/*.js`, plus `assetSource.js` and `videoSource.js`, copied
   as-is into `karatahta2/services/assetPool/`.
2. [`karatahta2/routes/assetPool.js`](../../../../karatahta2/routes/assetPool.js
   in a sibling checkout — this repo doesn't vendor Kara Tahta's source)
   wires them to the app's real functions:

   ```js
   import { createAssetPoolHandler } from '../services/assetPool/handler.js';
   import { createVideoRequestHandler } from '../services/assetPool/videoRequests.js';
   import { createKaratahtaAssetSource } from '../services/assetPool/assetSource.js';
   import { createKaratahtaVideoSource } from '../services/assetPool/videoSource.js';
   import { listPublicCatalogLessons, getPublicLessonVideo } from '../services/supabaseStore.js';
   import { createStorageSignedUrl } from '../services/mediaStore.js';
   import { isYoutubeStoragePath } from '../services/youtubeSource.js';

   const assetPoolToken = String(process.env.ASSET_POOL_TOKEN || '').trim();

   export const assetPoolHandler = createAssetPoolHandler({
     token: assetPoolToken,
     ...createKaratahtaAssetSource({
       store: { listPublicCatalogLessons, getPublicLessonVideo },
       media: { createStorageSignedUrl },
       isYoutubeStoragePath,
       publishUrlTtlSeconds: Number(process.env.SOCIAL_PUBLISH_VIDEO_URL_TTL_SECONDS || 86400)
     })
   });

   // Optional: only mount video-requests if the scheduler secret this
   // adapter needs to call the app's own /api/generate-lesson is configured.
   const schedulerToken = String(process.env.SCHEDULER_INTERNAL_TOKEN || '').trim();
   export const videoRequestHandler = schedulerToken
     ? createVideoRequestHandler({
         token: assetPoolToken,
         ...createKaratahtaVideoSource({
           backendUrl: process.env.PUBLIC_BASE_URL || `http://127.0.0.1:${process.env.PORT || 3000}`,
           token: schedulerToken
         })
       })
     : null;
   ```

3. In `server.js`, next to the app's other routers:

   ```js
   import { assetPoolHandler, videoRequestHandler } from './routes/assetPool.js';
   // ...
   app.use(assetPoolHandler);
   if (videoRequestHandler) app.use(videoRequestHandler);
   ```

4. `ASSET_POOL_TOKEN` added to `karatahta2/.env.example` next to
   `SCHEDULER_INTERNAL_TOKEN`/`SCHEDULER_USER_ID` — set it to any long random
   string in the app's real `.env` and put the same value in the agent's
   `APP_INTERNAL_TOKEN`.
5. One fix the wiring surfaced that isn't obvious from Kara Tahta's API alone:
   `POST /api/generate-lesson` silently ignores `target_video_minutes` unless
   the request also sets `duration_touched: true` (see
   `buildTraditionalPlannerRequest` in `server.js`) — `videoSource.js` sends
   both together.

Nothing in Kara Tahta's auth changes: the pool authenticates with its own token
(and, for video requests, the app's own scheduler token internally) and never
touches user sessions. `GET /api/assets`/`GET /api/video-requests` don't
collide with anything Kara Tahta already serves (checked: no existing route
under either path).

## What has and hasn't been verified

`npm test` (in this repo) runs `assetSource.js` and `videoSource.js` against
fakes shaped after Kara Tahta's real functions, through the real handlers and
the real conformance checker — all green.

Beyond that, the actual wiring above was exercised against Kara Tahta's real
code, not just fakes: `node --check` on every copied/new file, a direct
in-process call of `assetPoolHandler`/`videoRequestHandler` with a fake
request (wrong token → `401`; right token, no Supabase configured → opaque
`500`, not a crash; a video-request POST → real `topic`/`duration_touched`
body built and a real `fetch` attempted at Kara Tahta's own
`/api/generate-lesson`, failing with a clean `502` since nothing was
listening), and then the real `karatahta2/server.js` process started end to
end (`PORT=8877 ASSET_POOL_TOKEN=... node server.js`) and hit over real HTTP
with `curl` and with `asset-pool/bin/check.js`: auth checks passed, and the
list check failed exactly as expected (`Supabase ayarlari eksik` — Kara
Tahta's dev `.env` on this machine has no `SUPABASE_URL`/service key), which
is the correct "fail closed and say why" behavior, not a wiring bug.

**Not verified**: an actual listing/prepare/generation against a live
Supabase project and Railway/local storage bucket — that needs real
credentials this machine doesn't have. One thing to confirm on first run with
real credentials: local-storage deployments can produce `http://` signed
URLs, which the handler will drop (the checker's "every asset matches" line
and the `X-Asset-Pool-Dropped` header will show it) — set the app's public
base URL to `https`.
