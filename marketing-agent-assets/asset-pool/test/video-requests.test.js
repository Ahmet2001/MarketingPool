import assert from 'node:assert/strict';
import test from 'node:test';
import { createVideoRequestHandler, parseVideoRequest, validateVideoStatus } from '../src/index.js';
import { goodAsset, listen } from '../testkit/helpers.js';

const TOKEN = 'tok';
const silent = () => {};
const BRIEF = 'A 30 second explainer about how compound interest works, friendly tone.';
const NUL = String.fromCharCode(0);

async function req(baseUrl, method, path, { body, token = TOKEN, headers = {}, raw } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json', ...headers },
    body: raw !== undefined ? raw : body === undefined ? undefined : JSON.stringify(body)
  });
  let json = null;
  try { json = await response.json(); } catch { json = null; }
  return { status: response.status, body: json, headers: response.headers };
}

function service(overrides = {}) {
  const jobs = new Map();
  const byKey = new Map();
  return {
    jobs,
    handler: createVideoRequestHandler({
      token: TOKEN,
      onError: silent,
      async createVideoRequest(request, { idempotencyKey }) {
        if (idempotencyKey && byKey.has(idempotencyKey)) return jobs.get(byKey.get(idempotencyKey));
        const requestId = `r${jobs.size + 1}`;
        const status = { requestId, status: 'queued', request };
        jobs.set(requestId, status);
        if (idempotencyKey) byKey.set(idempotencyKey, requestId);
        return status;
      },
      async getVideoRequest(id) { return jobs.get(id) || null; },
      ...overrides
    })
  };
}

test('POST creates a request (202) and GET reads it back', async () => {
  const { handler } = service();
  const server = await listen(handler);
  try {
    const created = await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF, durationSeconds: 30 } });
    assert.equal(created.status, 202);
    assert.deepEqual(created.body, { requestId: 'r1', status: 'queued' });
    assert.match(created.headers.get('cache-control'), /no-store/);
    const got = await req(server.baseUrl, 'GET', '/api/video-requests/r1');
    assert.equal(got.status, 200);
    assert.equal(got.body.requestId, 'r1');
    assert.equal((await req(server.baseUrl, 'GET', '/api/video-requests/nope')).status, 404);
  } finally {
    await server.close();
  }
});

test('the parsed request and Idempotency-Key reach the app; the same key returns the same request', async () => {
  const seen = [];
  const { handler } = service();
  const wrapped = createVideoRequestHandler({
    token: TOKEN, onError: silent,
    async createVideoRequest(request, meta) { seen.push([request, meta]); return { requestId: 'r-fixed', status: 'queued' }; },
    async getVideoRequest() { return null; }
  });
  const server = await listen(wrapped);
  const idem = await listen(handler);
  try {
    await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: `  ${BRIEF}  `, orientation: 'vertical', language: 'pt-BR' }, headers: { 'Idempotency-Key': 'abc123' } });
    await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF } });
    assert.deepEqual(seen[0], [{ brief: BRIEF, orientation: 'vertical', language: 'pt-BR' }, { idempotencyKey: 'abc123' }]);
    assert.equal(seen[1][1].idempotencyKey, null);

    const a = await req(idem.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF }, headers: { 'Idempotency-Key': 'k1' } });
    const b = await req(idem.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF }, headers: { 'Idempotency-Key': 'k1' } });
    assert.equal(a.body.requestId, b.body.requestId);
  } finally {
    await server.close();
    await idem.close();
  }
});

test('auth: 401 without/with a wrong token, 500 when nothing is configured', async () => {
  const { handler } = service();
  const server = await listen(handler);
  const open = await listen(createVideoRequestHandler({ onError: silent, createVideoRequest() {}, getVideoRequest() {} }));
  try {
    assert.equal((await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF }, token: '' })).status, 401);
    assert.equal((await req(server.baseUrl, 'GET', '/api/video-requests/r1', { token: 'wrong' })).status, 401);
    assert.equal((await req(open.baseUrl, 'GET', '/api/video-requests/r1')).status, 500);
  } finally {
    await server.close();
    await open.close();
  }
});

test('brief validation: too short/long, non-string, code, control chars, unknown fields', async () => {
  const { handler, jobs } = service();
  const server = await listen(handler);
  const post = (body, opts = {}) => req(server.baseUrl, 'POST', '/api/video-requests', { body, ...opts });
  try {
    assert.equal((await post({ brief: 'short' })).status, 400);
    assert.equal((await post({ brief: 'x'.repeat(2001) })).status, 400);
    assert.equal((await post({ brief: 12345678901234 })).status, 400);
    assert.equal((await post({})).status, 400);
    assert.equal((await post({ brief: `${BRIEF}\n\`\`\`sh\nrm -rf /\n\`\`\`` })).status, 400);
    assert.equal((await post({ brief: `${BRIEF}${NUL}` })).status, 400);
    assert.equal((await post({ brief: BRIEF, command: 'ffmpeg -i x' })).status, 400);
    assert.equal((await post({ brief: BRIEF, durationSeconds: 2 })).status, 400);
    assert.equal((await post({ brief: BRIEF, durationSeconds: 30.5 })).status, 400);
    assert.equal((await post({ brief: BRIEF, orientation: 'square' })).status, 400);
    assert.equal((await post({ brief: BRIEF, language: 'english' })).status, 400);
    assert.equal((await post({ brief: BRIEF, title: 'x'.repeat(101) })).status, 400);
    assert.equal((await post({ brief: BRIEF, metadata: [] })).status, 400);
    assert.equal((await post(undefined, { raw: '{oops' })).status, 400);
    assert.equal((await post({ brief: BRIEF }, { headers: { 'Idempotency-Key': 'k'.repeat(201) } })).status, 400);
    assert.equal(jobs.size, 0, 'no request may be created by an invalid body');
    assert.equal((await post({ brief: BRIEF, title: 'T', durationSeconds: 60, orientation: 'horizontal', language: 'en', metadata: { a: 1 } })).status, 202);
  } finally {
    await server.close();
  }
});

test('status documents are validated; an invalid asset is dropped and counted', async () => {
  const assetOk = goodAsset({ id: 'video:1', kind: 'video' });
  const { handler, jobs } = service();
  jobs.set('d1', { requestId: 'd1', status: 'done', approval: 'pending', progress: { current: 3, total: 3, message: 'done' }, asset: assetOk, internal: 'strip' });
  jobs.set('d2', { requestId: 'd2', status: 'done', asset: goodAsset({ url: 'http://insecure.example.com/x.mp4' }) });
  jobs.set('bad', { requestId: 'bad', status: 'exploded' });
  const server = await listen(handler);
  try {
    const ok = await req(server.baseUrl, 'GET', '/api/video-requests/d1');
    assert.equal(ok.status, 200);
    assert.equal(ok.body.asset.id, 'video:1');
    assert.equal('internal' in ok.body, false);
    assert.equal(ok.body.approval, 'pending');
    const dropped = await req(server.baseUrl, 'GET', '/api/video-requests/d2');
    assert.equal(dropped.status, 200);
    assert.equal('asset' in dropped.body, false);
    assert.equal(dropped.headers.get('x-asset-pool-dropped'), '1');
    assert.equal((await req(server.baseUrl, 'GET', '/api/video-requests/bad')).status, 500);
  } finally {
    await server.close();
  }
});

test('methods and paths: only POST on the collection, only GET on an item', async () => {
  const { handler } = service();
  const server = await listen(handler);
  try {
    assert.equal((await req(server.baseUrl, 'GET', '/api/video-requests')).status, 405);
    assert.equal((await req(server.baseUrl, 'POST', '/api/video-requests/r1', { body: { brief: BRIEF } })).status, 405);
    assert.equal((await req(server.baseUrl, 'GET', '/api/video-requests/a/b')).status, 404);
    assert.equal((await req(server.baseUrl, 'GET', '/somewhere/else')).status, 404);
  } finally {
    await server.close();
  }
});

test('app exceptions are opaque 500s', async () => {
  const errors = [];
  const server = await listen(createVideoRequestHandler({
    token: TOKEN, onError: (e) => errors.push(e.message),
    createVideoRequest() { throw new Error('render farm password is hunter2'); },
    getVideoRequest() { return null; }
  }));
  try {
    const res = await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF } });
    assert.equal(res.status, 500);
    assert.ok(!JSON.stringify(res.body).includes('hunter2'));
    assert.deepEqual(errors, ['render farm password is hunter2']);
  } finally {
    await server.close();
  }
});

test('the app can refuse with its own 4xx (e.g. quota) and the message passes through', async () => {
  const server = await listen(createVideoRequestHandler({
    token: TOKEN, onError: silent,
    createVideoRequest() { const e = new Error('free-trial quota used up'); e.statusCode = 429; throw e; },
    getVideoRequest() { return null; }
  }));
  try {
    const res = await req(server.baseUrl, 'POST', '/api/video-requests', { body: { brief: BRIEF } });
    assert.deepEqual([res.status, res.body.error], [429, 'free-trial quota used up']);
  } finally {
    await server.close();
  }
});

test('helpers: parseVideoRequest / validateVideoStatus', () => {
  assert.deepEqual(parseVideoRequest({ brief: BRIEF }), { brief: BRIEF });
  assert.equal(validateVideoStatus({ requestId: 'x', status: 'running', progress: { current: -1 } }).status, null);
  assert.equal(validateVideoStatus({ requestId: 'x', status: 'running', progress: { current: 1, total: 4, message: 'm' } }).status.progress.total, 4);
  assert.equal(validateVideoStatus(null).status, null);
  assert.throws(() => createVideoRequestHandler({}), TypeError);
});
