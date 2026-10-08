import assert from 'node:assert/strict';
import test from 'node:test';
import { createAssetPoolHandler } from '../src/index.js';
import { get, goodAsset, listen } from '../testkit/helpers.js';

const TOKEN = 's3cret';
const silent = () => {};

function pool(overrides = {}) {
  const assets = [
    goodAsset({ id: 'v1', kind: 'video' }),
    goodAsset({ id: 'i1', kind: 'image', url: 'https://cdn.example.com/i1.jpg' }),
    goodAsset({ id: 'i2', kind: 'image', url: 'https://cdn.example.com/i2.jpg' })
  ];
  return createAssetPoolHandler({
    token: TOKEN,
    onError: silent,
    listAssets: async () => assets,
    getAsset: async (id) => assets.find((a) => a.id === id) || null,
    ...overrides
  });
}

test('refuses everything (500) when no token or authenticate is configured', async () => {
  const server = await listen(pool({ token: '' }));
  try {
    assert.equal((await get(server.baseUrl, '/api/assets', TOKEN)).status, 500);
    assert.equal((await get(server.baseUrl, '/api/assets')).status, 500);
  } finally {
    await server.close();
  }
});

test('401 without or with a wrong token; never leaks the token', async () => {
  const server = await listen(pool());
  try {
    assert.equal((await get(server.baseUrl, '/api/assets')).status, 401);
    const wrong = await get(server.baseUrl, '/api/assets', 'nope');
    assert.equal(wrong.status, 401);
    assert.ok(!JSON.stringify(wrong.body).includes(TOKEN));
    assert.equal((await get(server.baseUrl, '/api/assets/v1', 'nope')).status, 401);
  } finally {
    await server.close();
  }
});

test('lists assets with no-store caching', async () => {
  const server = await listen(pool());
  try {
    const res = await get(server.baseUrl, '/api/assets', TOKEN);
    assert.equal(res.status, 200);
    assert.deepEqual(res.body.assets.map((a) => a.id), ['v1', 'i1', 'i2']);
    assert.match(res.headers.get('cache-control'), /no-store/);
  } finally {
    await server.close();
  }
});

test('enforces ?kind even when the app ignores it, and clamps ?limit', async () => {
  const server = await listen(pool());
  try {
    const kind = await get(server.baseUrl, '/api/assets?kind=image', TOKEN);
    assert.deepEqual(kind.body.assets.map((a) => a.id), ['i1', 'i2']);
    const limit = await get(server.baseUrl, '/api/assets?limit=1', TOKEN);
    assert.equal(limit.body.assets.length, 1);
  } finally {
    await server.close();
  }
});

test('passes the parsed query and default/max limit to listAssets', async () => {
  const seen = [];
  const server = await listen(pool({ listAssets: async (query) => { seen.push(query); return []; } }));
  try {
    await get(server.baseUrl, '/api/assets?kind=video&tag=%20launch%20', TOKEN);
    await get(server.baseUrl, '/api/assets?limit=9999', TOKEN);
    await get(server.baseUrl, '/api/assets', TOKEN);
    assert.deepEqual(seen[0], { kind: 'video', tag: 'launch', limit: 20 });
    assert.equal(seen[1].limit, 100);
    assert.equal(seen[2].limit, 20);
  } finally {
    await server.close();
  }
});

test('400 for bad kind, bad limit, and over-long tag', async () => {
  const server = await listen(pool());
  try {
    assert.equal((await get(server.baseUrl, '/api/assets?kind=gif', TOKEN)).status, 400);
    assert.equal((await get(server.baseUrl, '/api/assets?limit=0', TOKEN)).status, 400);
    assert.equal((await get(server.baseUrl, '/api/assets?limit=abc', TOKEN)).status, 400);
    assert.equal((await get(server.baseUrl, `/api/assets?tag=${'x'.repeat(201)}`, TOKEN)).status, 400);
  } finally {
    await server.close();
  }
});

test('drops non-conforming assets and reports how many', async () => {
  const server = await listen(pool({
    listAssets: async () => [
      goodAsset({ id: 'ok' }),
      goodAsset({ id: 'insecure', url: 'http://cdn.example.com/x.mp4' }),
      goodAsset({ id: 'badkind', kind: 'gif' }),
      goodAsset({ id: 'extra', private_note: 'strip me' })
    ]
  }));
  try {
    const res = await get(server.baseUrl, '/api/assets', TOKEN);
    assert.deepEqual(res.body.assets.map((a) => a.id), ['ok', 'extra']);
    assert.equal('private_note' in res.body.assets[1], false);
    assert.equal(res.headers.get('x-asset-pool-dropped'), '2');
  } finally {
    await server.close();
  }
});

test('detail: 200 bare asset, 404 unknown, decodes ids, 404 for deeper paths', async () => {
  const seenIds = [];
  const server = await listen(pool({
    getAsset: async (id) => { seenIds.push(id); return id === 'video:abc' ? goodAsset({ id }) : null; }
  }));
  try {
    const found = await get(server.baseUrl, '/api/assets/video%3Aabc', TOKEN);
    assert.equal(found.status, 200);
    assert.equal(found.body.id, 'video:abc');
    assert.deepEqual(seenIds, ['video:abc']);
    assert.equal((await get(server.baseUrl, '/api/assets/missing', TOKEN)).status, 404);
    assert.equal((await get(server.baseUrl, '/api/assets/a/b', TOKEN)).status, 404);
    assert.equal((await get(server.baseUrl, '/api/assets/%E0%A4%A', TOKEN)).status, 400);
  } finally {
    await server.close();
  }
});

test('detail: an app returning a non-conforming asset is a 500, not a leak', async () => {
  const server = await listen(pool({ getAsset: async () => goodAsset({ url: 'http://insecure.example.com/x' }) }));
  try {
    const res = await get(server.baseUrl, '/api/assets/x', TOKEN);
    assert.equal(res.status, 500);
    assert.ok(!JSON.stringify(res.body).includes('insecure.example.com'));
  } finally {
    await server.close();
  }
});

test('callback exceptions become an opaque 500 and are reported to onError', async () => {
  const errors = [];
  const server = await listen(pool({
    onError: (error) => errors.push(error.message),
    listAssets: async () => { throw new Error('db password is hunter2'); }
  }));
  try {
    const res = await get(server.baseUrl, '/api/assets', TOKEN);
    assert.equal(res.status, 500);
    assert.ok(!JSON.stringify(res.body).includes('hunter2'));
    assert.deepEqual(errors, ['db password is hunter2']);
  } finally {
    await server.close();
  }
});

test('405 for non-GET methods', async () => {
  const server = await listen(pool());
  try {
    const response = await fetch(`${server.baseUrl}/api/assets`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}` }
    });
    assert.equal(response.status, 405);
    assert.match(response.headers.get('allow'), /GET/);
  } finally {
    await server.close();
  }
});

test('authenticate() replaces the token and its result reaches the callbacks', async () => {
  let seenCtx;
  const server = await listen(createAssetPoolHandler({
    onError: silent,
    authenticate: async (req) => {
      if (req.headers['x-tenant'] !== 'acme') {
        const error = new Error('unknown tenant');
        error.statusCode = 403;
        throw error;
      }
      return { tenant: 'acme' };
    },
    listAssets: async (_query, ctx) => { seenCtx = ctx; return []; },
    getAsset: async () => null
  }));
  try {
    assert.equal((await get(server.baseUrl, '/api/assets', TOKEN)).status, 403);
    const ok = await fetch(`${server.baseUrl}/api/assets`, { headers: { 'X-Tenant': 'acme' } });
    assert.equal(ok.status, 200);
    assert.deepEqual(seenCtx, { tenant: 'acme' });
  } finally {
    await server.close();
  }
});

test('unrelated paths fall through to next() when mounted in a framework', async () => {
  const handler = pool();
  let nextCalled = false;
  await handler({ url: '/health', method: 'GET', headers: {} }, {}, () => { nextCalled = true; });
  assert.equal(nextCalled, true);
});

test('works when Express strips the mount path (req.baseUrl set)', async () => {
  const handler = pool();
  const chunks = {};
  const res = {
    statusCode: 0,
    setHeader() {},
    end(body) { chunks.body = JSON.parse(body); }
  };
  await handler({ url: '/i1', baseUrl: '/api/assets', method: 'GET', headers: { authorization: `Bearer ${TOKEN}` } }, res);
  assert.equal(res.statusCode, 200);
  assert.equal(chunks.body.id, 'i1');
});

test('honors a custom basePath', async () => {
  const server = await listen(pool({ basePath: '/pool/v1' }));
  try {
    assert.equal((await get(server.baseUrl, '/pool/v1', TOKEN)).status, 200);
    assert.equal((await get(server.baseUrl, '/api/assets', TOKEN)).status, 404);
  } finally {
    await server.close();
  }
});

test('createAssetPoolHandler validates its options', () => {
  assert.throws(() => createAssetPoolHandler({ token: 'x' }), TypeError);
});
