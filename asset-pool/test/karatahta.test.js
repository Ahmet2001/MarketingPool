import assert from 'node:assert/strict';
import test from 'node:test';
import { runChecks } from '../bin/check.js';
import { createAssetPoolHandler } from '../src/index.js';
import { createKaratahtaAssetSource } from '../examples/karatahta/assetSource.js';
import { get, listen } from '../testkit/helpers.js';

const TOKEN = 'tok';

// Fakes shaped like Kara Tahta's services/supabaseStore.js + mediaStore.js.
const lessons = [
  {
    id: 'L1', title: 'Türev nedir?', topic: 'Matematik / Türev',
    video: { id: 'V1', status: 'done', video_storage_path: 'railway:u1/L1/final.mp4', poster_storage_path: 'railway:u1/L1/poster.jpg', duration_seconds: 312 }
  },
  {
    id: 'L2', title: 'Newton yasaları', topic: 'Fizik',
    video: { id: 'V2', status: 'done', video_storage_path: 'railway:u1/L2/final.mp4', poster_storage_path: null, duration_seconds: 200 }
  },
  {
    id: 'L3', title: 'YouTube içe aktarım', topic: 'Kimya',
    video: { id: 'V3', status: 'done', video_storage_path: 'youtube:abc123', poster_storage_path: 'railway:u1/L3/poster.png' }
  }
];

function fakes({ failSigning = () => false } = {}) {
  const calls = { listLimit: [], signed: [] };
  return {
    calls,
    deps: {
      store: {
        listPublicCatalogLessons: async ({ limit }) => { calls.listLimit.push(limit); return lessons; },
        getPublicLessonVideo: async ({ lessonId }) => {
          const lesson = lessons.find((l) => l.id === lessonId);
          return lesson ? { lesson: { id: lesson.id, title: lesson.title, topic: lesson.topic }, video: lesson.video } : null;
        }
      },
      media: {
        createStorageSignedUrl: async ({ storagePath, expiresInSeconds }) => {
          calls.signed.push({ storagePath, expiresInSeconds });
          if (failSigning(storagePath)) throw new Error('storage unavailable');
          return {
            signedUrl: `https://bucket.example.com/${storagePath}?sig=abc`,
            expiresAt: new Date(Date.now() + expiresInSeconds * 1000).toISOString()
          };
        }
      },
      isYoutubeStoragePath: (p) => String(p).startsWith('youtube:')
    }
  };
}

test('lists videos and posters, skipping YouTube imports\' videos but keeping their poster', async () => {
  const { deps } = fakes();
  const { listAssets } = createKaratahtaAssetSource(deps);
  const assets = await listAssets({ kind: '', tag: '', limit: 20 });
  assert.deepEqual(assets.map((a) => a.id).sort(), ['poster:L1', 'poster:L3', 'video:L1', 'video:L2']);
  const video = assets.find((a) => a.id === 'video:L1');
  assert.equal(video.kind, 'video');
  assert.equal(video.contentType, 'video/mp4');
  assert.equal(video.metadata.durationSeconds, 312);
  assert.equal(assets.find((a) => a.id === 'poster:L3').contentType, 'image/png');
});

test('signs with the long publish TTL so queued publish jobs stay valid', async () => {
  const { deps, calls } = fakes();
  await createKaratahtaAssetSource(deps).listAssets({ kind: 'video', tag: '', limit: 5 });
  assert.ok(calls.signed.length > 0);
  assert.ok(calls.signed.every((c) => c.expiresInSeconds === 86400));
});

test('kind and tag filters', async () => {
  const { deps } = fakes();
  const source = createKaratahtaAssetSource(deps);
  assert.deepEqual((await source.listAssets({ kind: 'image', tag: '', limit: 20 })).map((a) => a.id).sort(), ['poster:L1', 'poster:L3']);
  assert.deepEqual((await source.listAssets({ kind: '', tag: 'fizik', limit: 20 })).map((a) => a.id), ['video:L2']);
});

test('limit caps the result and the lessons fetched', async () => {
  const { deps, calls } = fakes();
  const assets = await createKaratahtaAssetSource(deps).listAssets({ kind: '', tag: '', limit: 2 });
  assert.equal(assets.length, 2);
  assert.equal(calls.listLimit[0], 2);
});

test('one asset that cannot be signed does not sink the listing', async () => {
  const { deps } = fakes({ failSigning: (p) => p.includes('L2') });
  const assets = await createKaratahtaAssetSource(deps).listAssets({ kind: '', tag: '', limit: 20 });
  assert.ok(assets.some((a) => a.id === 'video:L1'));
  assert.ok(!assets.some((a) => a.id === 'video:L2'));
});

test('getAsset resolves video and poster ids and rejects everything else', async () => {
  const { deps } = fakes();
  const { getAsset } = createKaratahtaAssetSource(deps);
  assert.equal((await getAsset('video:L1')).kind, 'video');
  assert.equal((await getAsset('poster:L1')).kind, 'image');
  assert.equal(await getAsset('poster:L2'), null); // no poster on this lesson
  assert.equal(await getAsset('video:L3'), null); // YouTube import
  assert.equal(await getAsset('video:nope'), null);
  assert.equal(await getAsset('L1'), null);
  assert.equal(await getAsset('lesson:L1'), null);
  assert.equal(await getAsset(':L1'), null);
});

test('getAsset hides videos that are not finished rendering', async () => {
  const { deps } = fakes();
  deps.store.getPublicLessonVideo = async () => ({ lesson: { id: 'L9', title: 't' }, video: { status: 'rendering', video_storage_path: 'railway:x.mp4' } });
  assert.equal(await createKaratahtaAssetSource(deps).getAsset('video:L9'), null);
});

test('titles and alt text respect the schema length limits', async () => {
  const { deps } = fakes();
  deps.store.listPublicCatalogLessons = async () => [{ ...lessons[0], title: 'x'.repeat(500) }];
  const assets = await createKaratahtaAssetSource(deps).listAssets({ kind: '', tag: '', limit: 5 });
  assert.ok(assets.every((a) => a.title.length <= 240));
});

test('refuses to build without the app functions it needs', () => {
  assert.throws(() => createKaratahtaAssetSource({}), TypeError);
  const { deps } = fakes();
  assert.throws(() => createKaratahtaAssetSource({ ...deps, isYoutubeStoragePath: undefined }), TypeError);
});

test('the Kara Tahta example, served through the handler, passes the conformance checker', async () => {
  const { deps } = fakes();
  const server = await listen(createAssetPoolHandler({ token: TOKEN, ...createKaratahtaAssetSource(deps) }));
  try {
    const results = await runChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(results.filter((r) => r.status !== 'pass'), []);
    const detail = await get(server.baseUrl, `/api/assets/${encodeURIComponent('video:L1')}`, TOKEN);
    assert.equal(detail.status, 200);
    assert.match(detail.body.url, /^https:\/\//);
  } finally {
    await server.close();
  }
});
