#!/usr/bin/env node
// Conformance checker: point it at any app's asset pool and it reports whether
// the app honors the contract the marketing agent relies on.
//
//   node bin/check.js https://my-app.example.com --token "$ASSET_POOL_TOKEN"
//   node bin/check.js http://127.0.0.1:8095 --token change-me --path /api/assets
//
// Optional capabilities are probed only when you ask:
//   --prepare                    POST {path}/{id}/prepare  (media preparation)
//   --video-requests             the video-generation endpoints (never creates a request)
//   --video-path /api/video-requests
//   --video-brief "A 30s ..."    ALSO submit one real request and check idempotency
//                                (this may start -- and bill -- a real render)
//
// Exit code is 1 if any check fails (warnings and skips don't fail the run).
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { ASSET_KINDS, validateAsset } from '../src/assetSchema.js';
import { VIDEO_STATUS_FIELDS } from '../src/contracts.js';
import { validateVideoStatus } from '../src/videoRequests.js';

const FIVE_MINUTES_MS = 5 * 60 * 1000;

function joinUrl(baseUrl, path) {
  return `${String(baseUrl).replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`;
}

async function getJson(fetchImpl, url, token) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetchImpl(url, { headers, redirect: 'manual' });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { status: response.status, headers: response.headers, body };
}

async function sendJson(fetchImpl, method, url, token, body, headers = {}) {
  const requestHeaders = { Accept: 'application/json', 'Content-Type': 'application/json', ...headers };
  if (token) requestHeaders.Authorization = `Bearer ${token}`;
  const response = await fetchImpl(url, {
    method,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'manual'
  });
  let parsed = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  return { status: response.status, headers: response.headers, body: parsed };
}

const NOT_IMPLEMENTED = [404, 405, 501];

/**
 * Runs every check and returns `[{ name, status: 'pass'|'fail'|'warn', detail }]`.
 * `fetchImpl` is injectable for tests.
 */
export async function runChecks({ baseUrl, token = '', path = '/api/assets', fetchImpl = fetch }) {
  const results = [];
  const record = (name, status, detail = '') => results.push({ name, status, detail });
  const listUrl = joinUrl(baseUrl, path);

  // --- auth -----------------------------------------------------------------
  try {
    const anonymous = await getJson(fetchImpl, listUrl, '');
    if ([401, 403].includes(anonymous.status)) record('auth: refuses requests without a token', 'pass');
    else record('auth: refuses requests without a token', 'fail', `got HTTP ${anonymous.status}; the pool must not be open`);

    const wrong = await getJson(fetchImpl, listUrl, 'definitely-not-the-token');
    if ([401, 403].includes(wrong.status)) record('auth: refuses a wrong token', 'pass');
    else record('auth: refuses a wrong token', 'fail', `got HTTP ${wrong.status}`);
  } catch (error) {
    record('auth: server reachable', 'fail', error.message);
    return results;
  }

  if (!token) {
    record('list/detail checks', 'fail', 'no token supplied (--token or ASSET_POOL_TOKEN), so authenticated checks were skipped');
    return results;
  }

  // --- list -----------------------------------------------------------------
  const list = await getJson(fetchImpl, listUrl, token);
  if (list.status !== 200) {
    record('list: 200 with a valid token', 'fail', `got HTTP ${list.status}`);
    return results;
  }
  record('list: 200 with a valid token', 'pass');

  const cacheControl = list.headers.get('cache-control') || '';
  if (/\bpublic\b/i.test(cacheControl) || !/(no-store|private)/i.test(cacheControl)) {
    record('list: Cache-Control keeps signed URLs out of shared caches', 'warn', `Cache-Control was "${cacheControl || 'absent'}"; use "private, no-store"`);
  } else {
    record('list: Cache-Control keeps signed URLs out of shared caches', 'pass');
  }

  let assets;
  if (Array.isArray(list.body)) {
    record('list: body shape', 'warn', 'bare array; the contract specifies {"assets":[...]} (the reference agent accepts both)');
    assets = list.body;
  } else if (list.body && Array.isArray(list.body.assets)) {
    record('list: body shape', 'pass');
    assets = list.body.assets;
  } else {
    record('list: body shape', 'fail', 'expected {"assets":[...]}');
    return results;
  }

  const invalid = [];
  assets.forEach((item, index) => {
    const { errors } = validateAsset(item, { strict: true });
    if (errors.length) invalid.push(`${item?.id ?? `#${index}`}: ${errors.join('; ')}`);
  });
  if (invalid.length) record('list: every asset matches asset.schema.json', 'fail', invalid.slice(0, 5).join(' | '));
  else record('list: every asset matches asset.schema.json', 'pass', `${assets.length} asset(s)`);

  const ids = assets.map((asset) => asset?.id);
  if (new Set(ids).size === ids.length) record('list: ids are unique', 'pass');
  else record('list: ids are unique', 'fail');

  const now = Date.now();
  const expired = assets.filter((a) => a?.expiresAt && Date.parse(a.expiresAt) <= now).map((a) => a.id);
  const expiringSoon = assets.filter((a) => a?.expiresAt && Date.parse(a.expiresAt) > now && Date.parse(a.expiresAt) - now < FIVE_MINUTES_MS).map((a) => a.id);
  if (expired.length) record('list: no asset is already expired', 'fail', expired.slice(0, 5).join(', '));
  else if (expiringSoon.length) record('list: no asset is already expired', 'warn', `expires within 5 minutes: ${expiringSoon.slice(0, 5).join(', ')}`);
  else record('list: no asset is already expired', 'pass');

  const limited = await getJson(fetchImpl, `${listUrl}?limit=1`, token);
  const limitedAssets = Array.isArray(limited.body) ? limited.body : limited.body?.assets;
  if (limited.status === 200 && Array.isArray(limitedAssets) && limitedAssets.length <= 1) record('list: ?limit is honored', 'pass');
  else record('list: ?limit is honored', 'fail', `HTTP ${limited.status}, ${Array.isArray(limitedAssets) ? limitedAssets.length : '?'} item(s) for limit=1`);

  const bogus = await getJson(fetchImpl, `${listUrl}?kind=not-a-kind`, token);
  if (bogus.status === 400) record('list: unknown ?kind is rejected with 400', 'pass');
  else record('list: unknown ?kind is rejected with 400', 'fail', `got HTTP ${bogus.status}`);

  if (assets.length === 0) {
    record('kind filter and detail checks', 'warn', 'the pool is empty, so ?kind filtering and GET /{id} could not be exercised');
    return results;
  }

  const kindToTry = assets.find((a) => ASSET_KINDS.includes(a?.kind))?.kind;
  if (kindToTry) {
    const filtered = await getJson(fetchImpl, `${listUrl}?kind=${kindToTry}`, token);
    const filteredAssets = Array.isArray(filtered.body) ? filtered.body : filtered.body?.assets;
    const allMatch = Array.isArray(filteredAssets) && filteredAssets.length > 0 && filteredAssets.every((a) => a.kind === kindToTry);
    if (filtered.status === 200 && allMatch) record(`list: ?kind=${kindToTry} returns only ${kindToTry} assets`, 'pass');
    else record(`list: ?kind=${kindToTry} returns only ${kindToTry} assets`, 'fail', `HTTP ${filtered.status}`);
  }

  // --- detail ---------------------------------------------------------------
  const first = assets[0];
  const detail = await getJson(fetchImpl, `${listUrl}/${encodeURIComponent(first.id)}`, token);
  const detailAsset = detail.body?.asset ?? detail.body;
  if (detail.status !== 200) {
    record('detail: GET /{id} returns the asset', 'fail', `HTTP ${detail.status} for "${first.id}"`);
  } else {
    const { errors } = validateAsset(detailAsset, { strict: true });
    if (errors.length) record('detail: GET /{id} returns the asset', 'fail', errors.join('; '));
    else if (detailAsset.id !== first.id) record('detail: GET /{id} returns the asset', 'fail', `asked for "${first.id}", got "${detailAsset.id}"`);
    else record('detail: GET /{id} returns the asset', 'pass');
    if (detail.body && 'asset' in detail.body && !('id' in detail.body)) {
      record('detail: body shape', 'warn', 'wrapped in {"asset":...}; the contract specifies the bare Asset object (the reference agent accepts both)');
    }
  }

  const missing = await getJson(fetchImpl, `${listUrl}/__no_such_asset__`, token);
  if (missing.status === 404) record('detail: unknown id returns 404', 'pass');
  else record('detail: unknown id returns 404', 'fail', `got HTTP ${missing.status}`);

  return results;
}

/** Probes POST {path}/{id}/prepare. An unimplemented (optional) capability is a skip, not a failure. */
export async function runPrepareChecks({ baseUrl, token = '', path = '/api/assets', fetchImpl = fetch }) {
  const results = [];
  const record = (name, status, detail = '') => results.push({ name, status, detail });
  const listUrl = joinUrl(baseUrl, path);

  if (!token) return [{ name: 'prepare: checks', status: 'fail', detail: 'no token supplied' }];
  const list = await getJson(fetchImpl, listUrl, token);
  const assets = Array.isArray(list.body) ? list.body : list.body?.assets;
  if (list.status !== 200 || !Array.isArray(assets) || assets.length === 0) {
    return [{ name: 'prepare: checks', status: 'skip', detail: 'the pool returned no assets to prepare' }];
  }
  const video = assets.find((a) => a?.kind === 'video');
  const image = assets.find((a) => a?.kind === 'image');
  const asset = video || image;
  if (!asset) return [{ name: 'prepare: checks', status: 'skip', detail: 'no video or image asset to prepare' }];
  const target = video
    ? { platform: 'youtube', action: 'video.publish' }
    : { platform: 'instagram', action: 'instagram.carousel' };
  const url = `${listUrl}/${encodeURIComponent(asset.id)}/prepare`;

  const prepared = await sendJson(fetchImpl, 'POST', url, token, { target });
  if (NOT_IMPLEMENTED.includes(prepared.status)) {
    return [{ name: 'prepare: optional capability', status: 'skip', detail: `not implemented (HTTP ${prepared.status})` }];
  }

  const anonymous = await sendJson(fetchImpl, 'POST', url, '', { target });
  if ([401, 403].includes(anonymous.status)) record('prepare: refuses requests without a token', 'pass');
  else record('prepare: refuses requests without a token', 'fail', `got HTTP ${anonymous.status}`);

  if (prepared.status === 200) {
    const { errors } = validateAsset(prepared.body, { strict: true });
    const wantsImage = target.action === 'instagram.carousel';
    if (errors.length) record('prepare: 200 returns a valid Asset', 'fail', errors.join('; '));
    else if ((wantsImage && prepared.body.kind !== 'image') || (!wantsImage && prepared.body.kind !== 'video')) {
      record('prepare: 200 returns a valid Asset', 'fail', `a ${prepared.body.kind} does not fit ${target.action}`);
    } else if (prepared.body.expiresAt && Date.parse(prepared.body.expiresAt) <= Date.now()) {
      record('prepare: 200 returns a valid Asset', 'fail', 'expiresAt is already in the past');
    } else {
      record('prepare: 200 returns a valid Asset', 'pass');
    }
  } else if (prepared.status === 422) {
    if (typeof prepared.body?.error === 'string' && Array.isArray(prepared.body?.reasons)) {
      record('prepare: 422 refusal is well-formed', 'pass', prepared.body.reasons.join('; '));
    } else {
      record('prepare: 422 refusal is well-formed', 'fail', 'expected {"error": string, "reasons": [...]}');
    }
  } else {
    record('prepare: answers 200 or 422', 'fail', `got HTTP ${prepared.status}`);
  }

  const badTtl = await sendJson(fetchImpl, 'POST', url, token, { target, ttlSeconds: 5 });
  if (badTtl.status === 400) record('prepare: out-of-range ttlSeconds is rejected with 400', 'pass');
  else record('prepare: out-of-range ttlSeconds is rejected with 400', 'fail', `got HTTP ${badTtl.status}`);

  const empty = await sendJson(fetchImpl, 'POST', url, token, {});
  if (empty.status === 400) record('prepare: a body without target is rejected with 400', 'pass');
  else record('prepare: a body without target is rejected with 400', 'fail', `got HTTP ${empty.status}`);

  const missing = await sendJson(fetchImpl, 'POST', `${listUrl}/__no_such_asset__/prepare`, token, { target });
  if (missing.status === 404) record('prepare: unknown id returns 404', 'pass');
  else record('prepare: unknown id returns 404', 'fail', `got HTTP ${missing.status}`);
  return results;
}

function strictStatusErrors(body) {
  const { errors } = validateVideoStatus(body);
  const extra = body && typeof body === 'object' ? Object.keys(body).filter((k) => !VIDEO_STATUS_FIELDS.includes(k)) : [];
  const assetErrors = body?.asset ? validateAsset(body.asset, { strict: true }).errors : [];
  return [...errors, ...extra.map((k) => `unknown property "${k}"`), ...assetErrors.map((e) => `asset: ${e}`)];
}

/**
 * Probes the video-generation endpoints. By default NOTHING is created: it only
 * checks refusals and validation. With `videoBrief` it also submits one real
 * request (twice, with the same Idempotency-Key) -- that can start a render.
 */
export async function runVideoRequestChecks({
  baseUrl, token = '', videoPath = '/api/video-requests', videoBrief = '', fetchImpl = fetch
}) {
  const results = [];
  const record = (name, status, detail = '') => results.push({ name, status, detail });
  const root = joinUrl(baseUrl, videoPath);
  const goodBrief = 'Connectivity check: a friendly ten second clip about saving money.';

  if (!token) return [{ name: 'video-requests: checks', status: 'fail', detail: 'no token supplied' }];

  const anonymous = await sendJson(fetchImpl, 'POST', root, '', { brief: goodBrief });
  if (NOT_IMPLEMENTED.includes(anonymous.status)) {
    return [{ name: 'video-requests: optional capability', status: 'skip', detail: `not implemented (HTTP ${anonymous.status})` }];
  }
  if ([401, 403].includes(anonymous.status)) record('video-requests: refuses requests without a token', 'pass');
  else record('video-requests: refuses requests without a token', 'fail', `got HTTP ${anonymous.status}; the endpoint must not be open`);

  const tooShort = await sendJson(fetchImpl, 'POST', root, token, { brief: 'short' });
  if (tooShort.status === 400) record('video-requests: a too-short brief is rejected with 400', 'pass');
  else record('video-requests: a too-short brief is rejected with 400', 'fail', `got HTTP ${tooShort.status}`);

  const code = await sendJson(fetchImpl, 'POST', root, token, { brief: `${goodBrief}\n\`\`\`sh\nrm -rf /\n\`\`\`` });
  if (code.status === 400) record('video-requests: a brief containing code is rejected with 400', 'pass');
  else record('video-requests: a brief containing code is rejected with 400', 'fail', `got HTTP ${code.status}; a brief must be treated as data`);

  const unknownField = await sendJson(fetchImpl, 'POST', root, token, { brief: goodBrief, command: 'ffmpeg -i x' });
  if (unknownField.status === 400) record('video-requests: unknown fields are rejected with 400', 'pass');
  else record('video-requests: unknown fields are rejected with 400', 'fail', `got HTTP ${unknownField.status}`);

  const missing = await getJson(fetchImpl, `${root}/__no_such_request__`, token);
  if (missing.status === 404) record('video-requests: unknown id returns 404', 'pass');
  else record('video-requests: unknown id returns 404', 'fail', `got HTTP ${missing.status}`);

  if (!videoBrief) {
    record('video-requests: creating a request', 'skip', 'pass --video-brief "..." to submit one real request (may be billable)');
    return results;
  }

  const key = randomUUID();
  const first = await sendJson(fetchImpl, 'POST', root, token, { brief: videoBrief }, { 'Idempotency-Key': key });
  if (![200, 202].includes(first.status)) {
    record('video-requests: POST returns 202 with a status document', 'fail', `got HTTP ${first.status}: ${first.body?.error || ''}`);
    return results;
  }
  const firstErrors = strictStatusErrors(first.body);
  if (firstErrors.length) record('video-requests: POST returns 202 with a status document', 'fail', firstErrors.join('; '));
  else record('video-requests: POST returns 202 with a status document', 'pass', `requestId ${first.body.requestId}`);
  record('video-requests: a real request was created', 'warn', `requestId ${first.body?.requestId}; it may render and be billed`);

  const second = await sendJson(fetchImpl, 'POST', root, token, { brief: videoBrief }, { 'Idempotency-Key': key });
  if ([200, 202].includes(second.status) && second.body?.requestId === first.body?.requestId) {
    record('video-requests: the same Idempotency-Key returns the same request', 'pass');
  } else {
    record('video-requests: the same Idempotency-Key returns the same request', 'fail', `got ${second.body?.requestId ?? `HTTP ${second.status}`}; a retry must never start a second render`);
  }

  const polled = await getJson(fetchImpl, `${root}/${encodeURIComponent(first.body.requestId)}`, token);
  const polledErrors = polled.status === 200 ? strictStatusErrors(polled.body) : [`HTTP ${polled.status}`];
  if (polledErrors.length) record('video-requests: GET /{id} returns the status document', 'fail', polledErrors.join('; '));
  else record('video-requests: GET /{id} returns the status document', 'pass', `status ${polled.body.status}`);
  return results;
}

function parseArgs(argv) {
  const args = {
    baseUrl: '',
    token: process.env.ASSET_POOL_TOKEN || '',
    path: '/api/assets',
    json: false,
    prepare: false,
    videoRequests: false,
    videoPath: '/api/video-requests',
    videoBrief: ''
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--token') args.token = argv[++i] || '';
    else if (arg === '--path') args.path = argv[++i] || args.path;
    else if (arg === '--json') args.json = true;
    else if (arg === '--prepare') args.prepare = true;
    else if (arg === '--video-requests') args.videoRequests = true;
    else if (arg === '--video-path') args.videoPath = argv[++i] || args.videoPath;
    else if (arg === '--video-brief') { args.videoBrief = argv[++i] || ''; args.videoRequests = true; }
    else if (!arg.startsWith('--') && !args.baseUrl) args.baseUrl = arg;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.baseUrl) {
    console.error('usage: node bin/check.js <baseUrl> [--token T] [--path /api/assets] [--json] [--prepare] [--video-requests [--video-path P] [--video-brief TEXT]]');
    process.exit(2);
  }
  const results = await runChecks(args);
  if (args.prepare) results.push(...await runPrepareChecks(args));
  if (args.videoRequests) results.push(...await runVideoRequestChecks(args));
  if (args.json) {
    console.log(JSON.stringify(results, null, 2));
  } else {
    const icon = { pass: '✓', fail: '✗', warn: '!', skip: '-' };
    for (const { name, status, detail } of results) {
      console.log(`${icon[status]} ${name}${detail ? ` — ${detail}` : ''}`);
    }
    const failed = results.filter((r) => r.status === 'fail').length;
    const warned = results.filter((r) => r.status === 'warn').length;
    const skipped = results.filter((r) => r.status === 'skip').length;
    console.log(`\n${failed ? 'NOT conformant' : 'Conformant'}: ${results.length} checks, ${failed} failed, ${warned} warning(s)${skipped ? `, ${skipped} skipped` : ''}.`);
  }
  process.exit(results.some((r) => r.status === 'fail') ? 1 : 0);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
