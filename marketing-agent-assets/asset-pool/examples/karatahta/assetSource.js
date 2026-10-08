// Example: exposing Kara Tahta -- the app this repo's scheduler_worker and
// mcp_worker were extracted from -- through the asset-pool contract.
//
// This file is the ONLY Kara Tahta-specific part. It maps the app's own model
// (lessons -> lesson_videos + poster) onto Asset objects, and it receives the
// app's functions as arguments instead of importing them, so it has no
// dependency on Kara Tahta's source tree and can be unit-tested with fakes.
// See README.md for the 10-line wiring inside the app itself.
//
// Approval model: Kara Tahta's `lessons.is_public` flag ("show in the public
// catalog") is treated as the "approved for distribution" signal. Only public
// lessons with a finished, non-YouTube video are ever exposed, and no per-user
// identity is needed -- the pool can't leak a private lesson because it never
// queries one.

const SEP = ':';
export const VIDEO_PREFIX = 'video';
export const POSTER_PREFIX = 'poster';

const clip = (text, max) => String(text || '').slice(0, max);

function contentTypeFor(storagePath, fallback) {
  const lower = String(storagePath || '').toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.mp4')) return 'video/mp4';
  return fallback;
}

/**
 * @param {object} deps
 * @param {{ listPublicCatalogLessons: Function, getPublicLessonVideo: Function }} deps.store
 *        Kara Tahta's services/supabaseStore.js functions.
 * @param {{ createStorageSignedUrl: Function }} deps.media
 *        Kara Tahta's services/mediaStore.js signer -> { signedUrl, expiresAt }.
 * @param {(storagePath: string) => boolean} deps.isYoutubeStoragePath
 *        Kara Tahta's services/youtubeSource.js helper. Imported YouTube lessons
 *        have no downloadable file and may not be re-published.
 * @param {number} [deps.publishUrlTtlSeconds=86400]
 *        Lifetime of the signed URL handed out. It must outlive the time a
 *        queued publish job waits for a worker, so it mirrors Kara Tahta's
 *        SOCIAL_PUBLISH_VIDEO_URL_TTL_SECONDS (max 24h).
 * @returns {{ listAssets: Function, getAsset: Function, prepareAsset: Function }} pass
 *          straight to createAssetPoolHandler().
 */
export function createKaratahtaAssetSource({
  store,
  media,
  isYoutubeStoragePath,
  publishUrlTtlSeconds = 86400
}) {
  for (const [name, fn] of Object.entries({
    'store.listPublicCatalogLessons': store?.listPublicCatalogLessons,
    'store.getPublicLessonVideo': store?.getPublicLessonVideo,
    'media.createStorageSignedUrl': media?.createStorageSignedUrl,
    isYoutubeStoragePath
  })) {
    if (typeof fn !== 'function') throw new TypeError(`createKaratahtaAssetSource: ${name} must be a function`);
  }

  const sign = (storagePath, ttlSeconds = publishUrlTtlSeconds) => media.createStorageSignedUrl({
    bucket: 'videos',
    storagePath,
    expiresInSeconds: ttlSeconds
  });

  async function videoAsset(lesson, video, ttlSeconds) {
    if (!video?.video_storage_path || isYoutubeStoragePath(video.video_storage_path)) return null;
    const signed = await sign(video.video_storage_path, ttlSeconds);
    return {
      id: `${VIDEO_PREFIX}${SEP}${lesson.id}`,
      kind: 'video',
      url: signed.signedUrl,
      contentType: contentTypeFor(video.video_storage_path, 'video/mp4'),
      title: clip(lesson.title || lesson.topic, 240),
      expiresAt: signed.expiresAt,
      metadata: {
        source: 'karatahta',
        lessonId: lesson.id,
        topic: lesson.topic || null,
        durationSeconds: video.duration_seconds ?? null
      }
    };
  }

  async function posterAsset(lesson, video, ttlSeconds) {
    if (!video?.poster_storage_path) return null;
    const signed = await sign(video.poster_storage_path, ttlSeconds);
    const title = lesson.title || lesson.topic || 'Kara Tahta dersi';
    return {
      id: `${POSTER_PREFIX}${SEP}${lesson.id}`,
      kind: 'image',
      url: signed.signedUrl,
      contentType: contentTypeFor(video.poster_storage_path, 'image/jpeg'),
      title: clip(`${title} — kapak`, 240),
      altText: clip(`Kara Tahta dersi kapak görseli: ${title}`, 2000),
      expiresAt: signed.expiresAt,
      metadata: { source: 'karatahta', lessonId: lesson.id, topic: lesson.topic || null }
    };
  }

  // Resolves "video:<lessonId>" / "poster:<lessonId>" to an APPROVED, finished lesson,
  // or null. getPublicLessonVideo only ever returns lessons with is_public = true.
  async function findApproved(id) {
    const separator = id.indexOf(SEP);
    if (separator < 1) return null;
    const prefix = id.slice(0, separator);
    const lessonId = id.slice(separator + 1);
    if (!lessonId || ![VIDEO_PREFIX, POSTER_PREFIX].includes(prefix)) return null;
    const found = await store.getPublicLessonVideo({ lessonId });
    if (!found?.lesson || !found.video || found.video.status !== 'done') return null;
    return { prefix, lesson: found.lesson, video: found.video };
  }

  const matchesTag = (lesson, tag) => {
    const needle = tag.toLowerCase();
    return `${lesson.title || ''} ${lesson.topic || ''}`.toLowerCase().includes(needle);
  };

  return {
    async listAssets({ kind, tag, limit }) {
      // Each lesson yields up to two assets (video + poster), so `limit`
      // lessons is always enough to fill `limit` assets.
      const lessons = await store.listPublicCatalogLessons({ limit: Math.min(100, limit) });
      const wanted = lessons.filter((lesson) => !tag || matchesTag(lesson, tag));

      const settled = await Promise.allSettled(wanted.flatMap((lesson) => [
        !kind || kind === 'video' ? videoAsset(lesson, lesson.video) : null,
        !kind || kind === 'image' ? posterAsset(lesson, lesson.video) : null
      ].filter(Boolean)));

      // One lesson whose storage can't be signed right now must not take the
      // whole listing down; it simply isn't offered this time.
      return settled
        .filter((result) => result.status === 'fulfilled' && result.value)
        .map((result) => result.value)
        .slice(0, limit);
    },

    async getAsset(id) {
      const found = await findApproved(id);
      if (!found) return null;
      return found.prefix === VIDEO_PREFIX
        ? videoAsset(found.lesson, found.video)
        : posterAsset(found.lesson, found.video);
    },

    // POST {pool}/{id}/prepare: re-sign for the target with a lifetime that fits
    // it, or refuse with reasons. This example does no format conversion, so an
    // asset that is in the wrong format for the target is refused, not silently
    // published wrong. (A real app could convert here -- Kara Tahta itself
    // converts PNG cards to JPEG for its own Instagram publishing.)
    async prepareAsset(id, { target, ttlSeconds }) {
      const found = await findApproved(id);
      if (!found) return null;
      const ttl = Math.min(86400, ttlSeconds || publishUrlTtlSeconds);
      const reasons = [];

      if (found.prefix === VIDEO_PREFIX) {
        if (target.action !== 'video.publish') reasons.push(`a lesson video can only be prepared for video.publish, not ${target.action}`);
        if (!/\.mp4$/i.test(found.video.video_storage_path || '')) reasons.push('the stored video is not an .mp4 file');
      } else {
        if (target.action !== 'instagram.carousel') reasons.push(`a poster image can only be prepared for instagram.carousel, not ${target.action}`);
        if (!/\.jpe?g$/i.test(found.video.poster_storage_path || '')) {
          reasons.push('Instagram carousels accept JPEG only and this poster is not a JPEG (this example does not convert)');
        }
      }
      if (reasons.length) {
        const error = new Error(`asset "${id}" cannot be prepared for ${target.platform} ${target.action}`);
        error.statusCode = 422;
        error.reasons = reasons;
        throw error;
      }
      return found.prefix === VIDEO_PREFIX
        ? videoAsset(found.lesson, found.video, ttl)
        : posterAsset(found.lesson, found.video, ttl);
    }
  };
}
