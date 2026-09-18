import assert from 'node:assert/strict';
import test from 'node:test';
import { runVideoRequestChecks } from '../bin/check.js';
import { createVideoRequestHandler } from '../src/index.js';
import { createKaratahtaAssetSource } from '../examples/karatahta/assetSource.js';
import { createAssetPoolHandler } from '../src/index.js';
import { createKaratahtaVideoSource } from '../examples/karatahta/videoSource.js';
import { listen } from '../testkit/helpers.js';

const TOKEN = 'pool-token';
const BRIEF = 'A friendly two minute explainer about the Pythagorean theorem for beginners.';

/** A fake Kara Tahta backend: POST /api/generate-lesson + GET /api/jobs/:id. */
function fakeBackend() {
  const calls = [];
  const jobs = new Map();
  let counter = 0;
  const respond = (status, data) => ({ status, json: async () => data });
  const fetchImpl = async (url, init = {}) => {
    const { pathname } = new URL(url);
    calls.push({ method: init.method, pathname, headers: init.headers, body: init.body ? JSON.parse(init.body) : undefined });
    if (init.headers['X-Scheduler-Token'] !== 'sched-secret') return respond(401, { error: 'no' });
    if (init.method === 'POST' && pathname === '/api/generate-lesson') {
      counter += 1;
      const job = { id: `job-${counter}`, lessonId: `lesson-${counter}`, status: 'queued', progress: 0, total: 4, message: 'queued' };
      jobs.set(job.id, job);
      return respond(202, job);
    }
    const match = pathname.match(/^\/api\/jobs\/(.+)$/);
    if (init.method === 'GET' && match) {
      const job = jobs.get(decodeURIComponent(match[1]));
      return job ? respond(200, job) : respond(404, { error: 'Job bulunamadi.' });
    }
    return respond(404, {});
  };
  return { calls, jobs, fetchImpl };
}

const source = (backend, extra = {}) => createKaratahtaVideoSource({ backendUrl: 'http://karatahta.local/', token: 'sched-secret', fetchImpl: backend.fetchImpl, ...extra });

test('creating a request maps the brief onto /api/generate-lesson with the scheduler token', async () => {
  const backend = fakeBackend();
  const status = await source(backend).createVideoRequest(
    { brief: BRIEF, orientation: 'vertical', durationSeconds: 100, title: 'ignored', language: 'tr', metadata: { studentLevel: 'advanced' } },
    { idempotencyKey: null }
  );
  assert.deepEqual(status, { requestId: 'job-1', status: 'queued', progress: { current: 0, total: 4, message: 'queued' } });
  const [call] = backend.calls;
  assert.equal(call.pathname, '/api/generate-lesson');
  assert.equal(call.headers['X-Scheduler-Token'], 'sched-secret');
  assert.deepEqual(call.body, { topic: BRIEF, orientation: 'vertical', target_video_minutes: 1.5, student_level: 'advanced' });
});

test('duration is rounded to half minutes within Kara Tahta\'s 0.5-20 range', async () => {
  const minutes = async (durationSeconds) => {
    const backend = fakeBackend();
    await source(backend).createVideoRequest({ brief: BRIEF, durationSeconds }, {});
    return backend.calls[0].body.target_video_minutes;
  };
  assert.equal(await minutes(5), 0.5);
  assert.equal(await minutes(90), 1.5);
  assert.equal(await minutes(1200), 20);
});

test('an unknown student level is not forwarded', async () => {
  const backend = fakeBackend();
  await source(backend).createVideoRequest({ brief: BRIEF, metadata: { studentLevel: 'wizard' } }, {});
  assert.equal('student_level' in backend.calls[0].body, false);
});

test('the same Idempotency-Key never starts a second render; it expires after the TTL', async () => {
  const backend = fakeBackend();
  let clock = 1_000;
  const s = source(backend, { now: () => clock, idempotencyTtlMs: 5_000 });
  const a = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k1' });
  const b = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k1' });
  assert.equal(a.requestId, b.requestId);
  assert.equal(backend.calls.filter((c) => c.method === 'POST').length, 1);
  const other = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k2' });
  assert.notEqual(other.requestId, a.requestId);
  clock += 6_000;
  const later = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k1' });
  assert.notEqual(later.requestId, a.requestId);
});

test('an idempotency hit whose job vanished on the app side starts over', async () => {
  const backend = fakeBackend();
  const s = source(backend);
  const a = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k1' });
  backend.jobs.delete(a.requestId);
  const b = await s.createVideoRequest({ brief: BRIEF }, { idempotencyKey: 'k1' });
  assert.notEqual(a.requestId, b.requestId);
});

test('status mapping: in-flight states are running, done carries a DRAFT asset, failed carries the error', async () => {
  const backend = fakeBackend();
  const s = source(backend);
  const { requestId } = await s.createVideoRequest({ brief: BRIEF }, {});

  backend.jobs.get(requestId).status = 'concat';
  assert.equal((await s.getVideoRequest(requestId)).status, 'running');

  Object.assign(backend.jobs.get(requestId), {
    status: 'done', progress: 4, current: undefined, result: { videoUrl: 'https://cdn.example.com/final.mp4?sig=1' }, plan: { title: 'Pisagor teoremi' }
  });
  const done = await s.getVideoRequest(requestId);
  assert.equal(done.status, 'done');
  assert.equal(done.approval, 'pending');
  assert.deepEqual(done.asset, {
    id: 'video:lesson-1', kind: 'video', url: 'https://cdn.example.com/final.mp4?sig=1', contentType: 'video/mp4',
    title: 'Pisagor teoremi', metadata: { source: 'karatahta', lessonId: 'lesson-1', draft: true }
  });

  Object.assign(backend.jobs.get(requestId), { status: 'failed', error: 'Manim crashed', result: undefined });
  const failed = await s.getVideoRequest(requestId);
  assert.deepEqual([failed.status, failed.error], ['failed', 'Manim crashed']);
});

test('a finished video on a non-https URL is reported done without an asset', async () => {
  const backend = fakeBackend();
  const s = source(backend);
  const { requestId } = await s.createVideoRequest({ brief: BRIEF }, {});
  Object.assign(backend.jobs.get(requestId), { status: 'done', result: { videoUrl: 'http://localhost:3000/media/x.mp4' } });
  const done = await s.getVideoRequest(requestId);
  assert.equal(done.status, 'done');
  assert.equal('asset' in done, false);
});

test('backend errors map to sensible statuses', async () => {
  const backend = fakeBackend();
  const bad = createKaratahtaVideoSource({ backendUrl: 'http://k', token: 'wrong', fetchImpl: backend.fetchImpl });
  await assert.rejects(() => bad.createVideoRequest({ brief: BRIEF }, {}), (e) => e.statusCode === 502 && /token/.test(e.message));
  await assert.rejects(() => bad.getVideoRequest('x'), (e) => e.statusCode === 502);

  const quota = createKaratahtaVideoSource({ backendUrl: 'http://k', token: 't', fetchImpl: async () => ({ status: 429, json: async () => ({ error: 'free-trial quota used up' }) }) });
  await assert.rejects(() => quota.createVideoRequest({ brief: BRIEF }, {}), (e) => e.statusCode === 429 && /quota/.test(e.message));

  const down = createKaratahtaVideoSource({ backendUrl: 'http://k', token: 't', fetchImpl: async () => { throw new Error('ECONNREFUSED'); } });
  await assert.rejects(() => down.getVideoRequest('x'), (e) => e.statusCode === 502 && /unreachable/.test(e.message));

  assert.equal(await source(backend).getVideoRequest('does-not-exist'), null);
});

test('construction requires the backend url and token', () => {
  assert.throws(() => createKaratahtaVideoSource({ backendUrl: '', token: 't' }), TypeError);
  assert.throws(() => createKaratahtaVideoSource({ backendUrl: 'http://k', token: '' }), TypeError);
});

test('served through the handler, the Kara Tahta video source passes the conformance checker (incl. a real submission)', async () => {
  const backend = fakeBackend();
  const server = await listen(createVideoRequestHandler({ token: TOKEN, ...source(backend) }));
  try {
    const results = await runVideoRequestChecks({ baseUrl: server.baseUrl, token: TOKEN, videoBrief: BRIEF });
    assert.deepEqual(results.filter((r) => r.status === 'fail'), []);
    assert.equal(results.find((r) => r.name.includes('same Idempotency-Key')).status, 'pass');
    assert.equal(backend.calls.filter((c) => c.method === 'POST').length, 1, 'exactly one render was started for the whole probe');
  } finally {
    await server.close();
  }
});

test('the Kara Tahta asset source\'s prepare refuses unfit formats and passes the prepare probe', async () => {
  const { runPrepareChecks } = await import('../bin/check.js');
  const lessons = [{ id: 'L1', title: 'T', topic: 'X', video: { id: 'V', status: 'done', video_storage_path: 'railway:a/final.mp4', poster_storage_path: 'railway:a/poster.png' } }];
  const deps = {
    store: { listPublicCatalogLessons: async () => lessons, getPublicLessonVideo: async ({ lessonId }) => (lessons.find((l) => l.id === lessonId) ? { lesson: lessons[0], video: lessons[0].video } : null) },
    media: { createStorageSignedUrl: async ({ storagePath, expiresInSeconds }) => ({ signedUrl: `https://b.example.com/${storagePath}`, expiresAt: new Date(Date.now() + expiresInSeconds * 1000).toISOString(), ttl: expiresInSeconds }) },
    isYoutubeStoragePath: () => false
  };
  const src = createKaratahtaAssetSource(deps);
  const req = (platform, action, ttlSeconds) => ({ target: { platform, action }, ...(ttlSeconds ? { ttlSeconds } : {}) });

  const prepared = await src.prepareAsset('video:L1', req('youtube', 'video.publish', 600));
  assert.equal(prepared.kind, 'video');
  assert.ok(Date.parse(prepared.expiresAt) - Date.now() <= 600_000 + 1000, 'the requested (short) lifetime is honored');

  await assert.rejects(() => src.prepareAsset('video:L1', req('instagram', 'instagram.carousel')), (e) => e.statusCode === 422 && e.reasons.length >= 1);
  await assert.rejects(() => src.prepareAsset('poster:L1', req('instagram', 'instagram.carousel')), (e) => e.statusCode === 422 && /JPEG/.test(e.reasons.join(' ')));
  await assert.rejects(() => src.prepareAsset('poster:L1', req('youtube', 'video.publish')), (e) => e.statusCode === 422);
  assert.equal(await src.prepareAsset('video:nope', req('youtube', 'video.publish')), null);

  const server = await listen(createAssetPoolHandler({ token: TOKEN, onError: () => {}, ...src }));
  try {
    const results = await runPrepareChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(results.filter((r) => r.status === 'fail'), []);
    assert.equal(results.find((r) => r.name.includes('200 returns a valid Asset')).status, 'pass');
  } finally {
    await server.close();
  }
});
