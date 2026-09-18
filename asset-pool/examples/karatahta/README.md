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

[`assetSource.js`](./assetSource.js) is the only Kara Tahta-specific file. It
takes the app's functions as arguments rather than importing them, so it needs
nothing from the app's source tree. In the app:

1. Copy the whole `asset-pool/src/` directory, plus `assetSource.js` and
   (if you're also wiring video requests) `videoSource.js`, into e.g.
   `services/assetPool/`.
2. Add `routes/assetPool.js`:

   ```js
   import { createAssetPoolHandler } from '../services/assetPool/handler.js';
   import { createKaratahtaAssetSource } from '../services/assetPool/assetSource.js';
   import { listPublicCatalogLessons, getPublicLessonVideo } from '../services/supabaseStore.js';
   import { createStorageSignedUrl } from '../services/mediaStore.js';
   import { isYoutubeStoragePath } from '../services/youtubeSource.js';

   export const assetPoolHandler = createAssetPoolHandler({
     token: process.env.ASSET_POOL_TOKEN,
     ...createKaratahtaAssetSource({
       store: { listPublicCatalogLessons, getPublicLessonVideo },
       media: { createStorageSignedUrl },
       isYoutubeStoragePath,
       publishUrlTtlSeconds: Number(process.env.SOCIAL_PUBLISH_VIDEO_URL_TTL_SECONDS || 86400)
     })
   });
   ```

3. In `server.js`: `import { assetPoolHandler } from './routes/assetPool.js';` and
   `app.use('/api/assets', assetPoolHandler);` — and, if you also wired
   `videoRequestHandler`, `app.use('/api/video-requests', videoRequestHandler);`
4. Set `ASSET_POOL_TOKEN` (any long random string) in the app's environment and
   put the same value in the agent's `APP_INTERNAL_TOKEN`.
5. `node asset-pool/bin/check.js https://<your-app> --token "$ASSET_POOL_TOKEN" --prepare --video-requests`

Nothing in Kara Tahta's auth changes: the pool authenticates with its own token
(and, for video requests, the app's own scheduler token internally) and never
touches user sessions.

## What has and hasn't been verified

`npm test` runs `assetSource.js` against fakes shaped after Kara Tahta's
`supabaseStore.js`/`mediaStore.js` (lesson rows, `{ signedUrl, expiresAt }`),
and `videoSource.js` against a fake `/api/generate-lesson` + `/api/jobs/:id`
backend — both served through the real handlers and the real conformance
checker, all green (`test/karatahta-video.test.js`, plus the `prepareAsset`
cases in `test/karatahta.test.js`). Neither has been run against a live Kara
Tahta instance (that needs its Supabase project, storage bucket, and a real
scheduler token). One thing to confirm on first run: local-storage
deployments can produce `http://` signed URLs, which the handler will drop
(the checker's "every asset matches" line and the `X-Asset-Pool-Dropped`
header will show it) — set the app's public base URL to `https`.
