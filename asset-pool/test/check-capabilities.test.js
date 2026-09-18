import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { runPrepareChecks, runVideoRequestChecks } from '../bin/check.js';
import { PrepareRefusal, createAssetPoolHandler, createVideoRequestHandler } from '../src/index.js';
import { goodAsset, listen } from '../testkit/helpers.js';

const TOKEN = 'tok';
const silent = () => {};
const byName = (results, needle) => results.find((r) => r.name.includes(needle));
const nonPass = (results) => results.filter((r) => !['pass', 'skip'].includes(r.status));

const video = goodAsset({ id: 'v1', kind: 'video' });
const image = goodAsset({ id: 'i1', kind: 'image', url: 'https://cdn.example.com/i1.jpg' });

function assetPool(prepareAsset) {
  return createAssetPoolHandler({
    token: TOKEN, onError: silent,
    listAssets: async () => [video, image],
    getAsset: async (id) => [video, image].find((a) => a.id === id) || null,
    ...(prepareAsset ? { prepareAsset } : {})
  });
}

function videoService() {
  const jobs = new Map();
  const byKey = new Map();
  return createVideoRequestHandler({
    token: TOKEN, onError: silent,
    async createVideoRequest(request, { idempotencyKey }) {
      if (idempotencyKey && byKey.has(idempotencyKey)) return jobs.get(byKey.get(idempotencyKey));
      const status = { requestId: `r${jobs.size + 1}`, status: 'queued' };
      jobs.set(status.requestId, status);
      if (idempotencyKey) byKey.set(idempotencyKey, status.requestId);
      return status;
    },
    async getVideoRequest(id) { return jobs.get(id) || null; }
  });
}

test('prepare probe: a conforming implementation passes', async () => {
  const server = await listen(assetPool(async (id) => (id === 'v1' ? goodAsset({ id, kind: 'video', expiresAt: '2099-01-01T00:00:00Z' }) : null)));
  try {
    const results = await runPrepareChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(nonPass(results), []);
    assert.ok(results.length >= 5);
  } finally {
    await server.close();
  }
});

test('prepare probe: an unimplemented capability is a skip, never a failure', async () => {
  const server = await listen(assetPool());
  try {
    const results = await runPrepareChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(results.map((r) => r.status), ['skip']);
    assert.match(results[0].detail, /501/);
  } finally {
    await server.close();
  }
});

test('prepare probe: a well-formed 422 refusal is fine, a malformed one is not', async () => {
  const good = await listen(assetPool(async () => { throw new PrepareRefusal('cannot', ['why']); }));
  const bad = await listen(assetPool(async () => { const e = new Error('cannot'); e.statusCode = 422; throw e; }));
  try {
    assert.equal(byName(await runPrepareChecks({ baseUrl: good.baseUrl, token: TOKEN }), '422').status, 'pass');
    assert.equal(byName(await runPrepareChecks({ baseUrl: bad.baseUrl, token: TOKEN }), '422').status, 'fail');
  } finally {
    await good.close();
    await bad.close();
  }
});

test('prepare probe: flags an implementation that skips auth and validation', async () => {
  const sloppy = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://x');
    if (req.method === 'GET' && url.pathname === '/api/assets') {
      res.end(JSON.stringify({ assets: [video] }));
    } else if (req.method === 'POST' && url.pathname.endsWith('/prepare')) {
      res.end(JSON.stringify(goodAsset({ id: 'v1', kind: 'video', url: 'https://cdn.example.com/x.mp4', expiresAt: '2001-01-01T00:00:00Z' })));
    } else {
      res.statusCode = 404;
      res.end('{}');
    }
  });
  await new Promise((resolve) => sloppy.listen(0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${sloppy.address().port}`;
  try {
    const results = await runPrepareChecks({ baseUrl, token: TOKEN });
    assert.equal(byName(results, 'without a token').status, 'fail');
    assert.equal(byName(results, '200 returns a valid Asset').status, 'fail');
    assert.equal(byName(results, 'ttlSeconds').status, 'fail');
    assert.equal(byName(results, 'without target').status, 'fail');
    assert.equal(byName(results, 'unknown id').status, 'fail');
  } finally {
    await new Promise((resolve) => sloppy.close(resolve));
  }
});

test('prepare probe: needs a token and an asset to work with', async () => {
  const server = await listen(assetPool(async () => video));
  const empty = await listen(createAssetPoolHandler({ token: TOKEN, listAssets: async () => [], getAsset: async () => null }));
  try {
    assert.equal((await runPrepareChecks({ baseUrl: server.baseUrl, token: '' }))[0].status, 'fail');
    assert.equal((await runPrepareChecks({ baseUrl: empty.baseUrl, token: TOKEN }))[0].status, 'skip');
  } finally {
    await server.close();
    await empty.close();
  }
});

test('video probe (default): checks refusals and validation and creates NOTHING', async () => {
  let created = 0;
  const inner = videoService();
  const server = await listen((req, res, next) => {
    if (req.method === 'POST') {
      const original = res.end.bind(res);
      res.end = (...args) => { if (res.statusCode === 202) created += 1; return original(...args); };
    }
    return inner(req, res, next);
  });
  try {
    const results = await runVideoRequestChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(nonPass(results).map((r) => r.status), []);
    assert.equal(byName(results, 'creating a request').status, 'skip');
    assert.equal(created, 0);
  } finally {
    await server.close();
  }
});

test('video probe (--video-brief): submits once, checks idempotency and polling', async () => {
  const server = await listen(videoService());
  try {
    const results = await runVideoRequestChecks({ baseUrl: server.baseUrl, token: TOKEN, videoBrief: 'A short, friendly clip about saving money.' });
    assert.equal(byName(results, 'same Idempotency-Key').status, 'pass');
    assert.equal(byName(results, 'GET /{id}').status, 'pass');
    assert.equal(byName(results, 'a real request was created').status, 'warn');
    assert.equal(results.filter((r) => r.status === 'fail').length, 0);
  } finally {
    await server.close();
  }
});

test('video probe: an app that ignores Idempotency-Key fails the idempotency check', async () => {
  let n = 0;
  const server = await listen(createVideoRequestHandler({
    token: TOKEN, onError: silent,
    async createVideoRequest() { n += 1; return { requestId: `r${n}`, status: 'queued' }; },
    async getVideoRequest(id) { return { requestId: id, status: 'queued' }; }
  }));
  try {
    const results = await runVideoRequestChecks({ baseUrl: server.baseUrl, token: TOKEN, videoBrief: 'A short, friendly clip about saving money.' });
    assert.equal(byName(results, 'same Idempotency-Key').status, 'fail');
  } finally {
    await server.close();
  }
});

test('video probe: an unimplemented endpoint is a skip; no token is a failure', async () => {
  const server = await listen(assetPool());
  try {
    const results = await runVideoRequestChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(results.map((r) => r.status), ['skip']);
    assert.equal((await runVideoRequestChecks({ baseUrl: server.baseUrl, token: '' }))[0].status, 'fail');
  } finally {
    await server.close();
  }
});

test('video probe: flags an open endpoint that accepts code briefs and unknown fields', async () => {
  const sloppy = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'POST') {
      res.statusCode = 202;
      res.end(JSON.stringify({ requestId: 'x', status: 'queued' }));
    } else {
      res.statusCode = 200;
      res.end(JSON.stringify({ requestId: 'x', status: 'queued' }));
    }
  });
  await new Promise((resolve) => sloppy.listen(0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${sloppy.address().port}`;
  try {
    const results = await runVideoRequestChecks({ baseUrl, token: TOKEN });
    for (const needle of ['without a token', 'too-short', 'containing code', 'unknown fields', 'unknown id']) {
      assert.equal(byName(results, needle).status, 'fail', needle);
    }
  } finally {
    await new Promise((resolve) => sloppy.close(resolve));
  }
});
