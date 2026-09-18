import assert from 'node:assert/strict';
import test from 'node:test';
import { PrepareRefusal, createAssetPoolHandler, parsePrepareRequest } from '../src/index.js';
import { goodAsset, listen } from '../testkit/helpers.js';

const TOKEN = 'tok';
const silent = () => {};
const video = goodAsset({ id: 'v1', kind: 'video' });
const image = goodAsset({ id: 'i1', kind: 'image', url: 'https://cdn.example.com/i1.jpg' });

async function post(baseUrl, path, body, { token = TOKEN, raw } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
    body: raw !== undefined ? raw : JSON.stringify(body)
  });
  let json = null;
  try { json = await response.json(); } catch { json = null; }
  return { status: response.status, body: json };
}

const target = (platform, action) => ({ target: { platform, action } });

function pool(prepareAsset) {
  return createAssetPoolHandler({
    token: TOKEN,
    onError: silent,
    listAssets: async () => [video, image],
    getAsset: async (id) => [video, image].find((a) => a.id === id) || null,
    ...(prepareAsset ? { prepareAsset } : {})
  });
}

test('prepare is 501 when the app does not implement it (auth still enforced first)', async () => {
  const server = await listen(pool());
  try {
    assert.equal((await post(server.baseUrl, '/api/assets/v1/prepare', target('youtube', 'video.publish'))).status, 501);
    assert.equal((await post(server.baseUrl, '/api/assets/v1/prepare', target('youtube', 'video.publish'), { token: '' })).status, 401);
  } finally {
    await server.close();
  }
});

test('prepare passes the parsed request and returns the validated asset', async () => {
  const seen = [];
  const server = await listen(pool(async (id, request) => {
    seen.push([id, request]);
    return goodAsset({ id, kind: 'video', url: 'https://cdn.example.com/fresh.mp4?sig=1', expiresAt: '2030-01-01T00:00:00Z', internal: 'strip' });
  }));
  try {
    const res = await post(server.baseUrl, '/api/assets/v1/prepare', { target: { platform: 'tiktok', action: 'video.publish' }, ttlSeconds: 3600 });
    assert.equal(res.status, 200);
    assert.equal(res.body.url, 'https://cdn.example.com/fresh.mp4?sig=1');
    assert.equal('internal' in res.body, false);
    assert.deepEqual(seen, [['v1', { target: { platform: 'tiktok', action: 'video.publish' }, ttlSeconds: 3600 }]]);
  } finally {
    await server.close();
  }
});

test('prepare: 404 for an unknown asset, 422 with reasons for a refusal', async () => {
  const server = await listen(pool(async (id) => {
    if (id === 'missing') return null;
    throw new PrepareRefusal('cannot prepare', ['poster is PNG', 'instagram needs JPEG']);
  }));
  try {
    assert.equal((await post(server.baseUrl, '/api/assets/missing/prepare', target('instagram', 'instagram.carousel'))).status, 404);
    const refused = await post(server.baseUrl, '/api/assets/i1/prepare', target('instagram', 'instagram.carousel'));
    assert.equal(refused.status, 422);
    assert.deepEqual(refused.body.reasons, ['poster is PNG', 'instagram needs JPEG']);
  } finally {
    await server.close();
  }
});

test('prepare: a duck-typed 422 (error with statusCode+reasons) works without importing the kit', async () => {
  const server = await listen(pool(async () => {
    const error = new Error('nope');
    error.statusCode = 422;
    error.reasons = ['because'];
    throw error;
  }));
  try {
    const res = await post(server.baseUrl, '/api/assets/v1/prepare', target('youtube', 'video.publish'));
    assert.deepEqual([res.status, res.body.reasons], [422, ['because']]);
  } finally {
    await server.close();
  }
});

test('prepare: a returned asset of the wrong kind for the target is a 500, not a mis-publish', async () => {
  const server = await listen(pool(async () => image));
  try {
    assert.equal((await post(server.baseUrl, '/api/assets/i1/prepare', target('youtube', 'video.publish'))).status, 500);
    assert.equal((await post(server.baseUrl, '/api/assets/i1/prepare', target('instagram', 'instagram.carousel'))).status, 200);
  } finally {
    await server.close();
  }
});

test('prepare: a returned non-https asset is a 500', async () => {
  const server = await listen(pool(async () => goodAsset({ url: 'http://insecure.example.com/x.mp4' })));
  try {
    assert.equal((await post(server.baseUrl, '/api/assets/v1/prepare', target('youtube', 'video.publish'))).status, 500);
  } finally {
    await server.close();
  }
});

test('prepare: request validation', async () => {
  const server = await listen(pool(async () => video));
  const p = (body, opts) => post(server.baseUrl, '/api/assets/v1/prepare', body, opts);
  try {
    assert.equal((await p({})).status, 400);
    assert.equal((await p(target('linkedin', 'video.publish'))).status, 400);
    assert.equal((await p(target('youtube', 'gif.publish'))).status, 400);
    assert.equal((await p(target('youtube', 'instagram.carousel'))).status, 400);
    assert.equal((await p({ ...target('youtube', 'video.publish'), ttlSeconds: 5 })).status, 400);
    assert.equal((await p({ ...target('youtube', 'video.publish'), ttlSeconds: 86401 })).status, 400);
    assert.equal((await p({ ...target('youtube', 'video.publish'), ttlSeconds: 90.5 })).status, 400);
    assert.equal((await p({ ...target('youtube', 'video.publish'), extra: 1 })).status, 400);
    assert.equal((await p({ target: { platform: 'youtube', action: 'video.publish', extra: 1 } })).status, 400);
    assert.equal((await p(null, { raw: '{not json' })).status, 400);
    assert.equal((await p(null, { raw: JSON.stringify({ pad: 'x'.repeat(20000) }) })).status, 413);
    assert.equal((await p({ ...target('youtube', 'video.publish'), ttlSeconds: 60 })).status, 200);
  } finally {
    await server.close();
  }
});

test('prepare: only POST on the prepare route; GET on it is 405; POST elsewhere is 405', async () => {
  const server = await listen(pool(async () => video));
  try {
    const get = await fetch(`${server.baseUrl}/api/assets/v1/prepare`, { headers: { Authorization: `Bearer ${TOKEN}` } });
    assert.equal(get.status, 405);
    assert.match(get.headers.get('allow'), /POST/);
    assert.equal((await post(server.baseUrl, '/api/assets/v1', target('youtube', 'video.publish'))).status, 405);
  } finally {
    await server.close();
  }
});

test('parsePrepareRequest normalizes a valid body', () => {
  assert.deepEqual(parsePrepareRequest({ target: { platform: 'instagram', action: 'instagram.carousel' } }), { target: { platform: 'instagram', action: 'instagram.carousel' } });
});

test('a non-function prepareAsset is a construction error', () => {
  assert.throws(() => createAssetPoolHandler({ token: 'x', listAssets() {}, getAsset() {}, prepareAsset: 'nope' }), TypeError);
});

test('prepare works with an Express-style pre-parsed body', async () => {
  const handler = pool(async () => video);
  const out = {};
  const res = { statusCode: 0, setHeader() {}, end(body) { out.body = JSON.parse(body); } };
  await handler({ url: '/v1/prepare', baseUrl: '/api/assets', method: 'POST', headers: { authorization: `Bearer ${TOKEN}` }, body: target('youtube', 'video.publish') }, res);
  assert.equal(res.statusCode, 200);
  assert.equal(out.body.id, 'v1');
});
