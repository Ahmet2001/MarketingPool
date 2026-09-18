import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { runChecks } from '../bin/check.js';
import { createAssetPoolHandler } from '../src/index.js';
import { goodAsset, listen } from '../testkit/helpers.js';

const TOKEN = 'tok';
const byName = (results, needle) => results.find((r) => r.name.includes(needle));

test('a pool built with the handler passes every check', async () => {
  const assets = JSON.parse(await readFile(new URL('../examples/minimal/assets.example.json', import.meta.url), 'utf8'));
  const server = await listen(createAssetPoolHandler({
    token: TOKEN,
    listAssets: async ({ kind, limit }) => assets.filter((a) => !kind || a.kind === kind).slice(0, limit),
    getAsset: async (id) => assets.find((a) => a.id === id) || null
  }));
  try {
    const results = await runChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.deepEqual(results.filter((r) => r.status !== 'pass'), []);
    assert.ok(results.length >= 12);
  } finally {
    await server.close();
  }
});

test('flags an open, sloppy pool on the checks that matter', async () => {
  const sloppy = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'public, max-age=600');
    if (url.pathname === '/api/assets') {
      res.end(JSON.stringify({
        assets: [
          goodAsset({ id: 'dup' }),
          goodAsset({ id: 'dup', url: 'http://insecure.example.com/a.mp4' }),
          goodAsset({ id: 'old', expiresAt: '2001-01-01T00:00:00Z', internal_cost: 5 })
        ]
      }));
    } else {
      res.end('{}');
    }
  });
  await new Promise((resolve) => sloppy.listen(0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${sloppy.address().port}`;
  try {
    const results = await runChecks({ baseUrl, token: TOKEN });
    assert.equal(byName(results, 'without a token').status, 'fail');
    assert.equal(byName(results, 'wrong token').status, 'fail');
    assert.equal(byName(results, 'Cache-Control').status, 'warn');
    assert.equal(byName(results, 'matches asset.schema.json').status, 'fail');
    assert.equal(byName(results, 'ids are unique').status, 'fail');
    assert.equal(byName(results, 'already expired').status, 'fail');
    assert.equal(byName(results, 'unknown ?kind').status, 'fail');
  } finally {
    await new Promise((resolve) => sloppy.close(resolve));
  }
});

test('reports an unreachable server instead of throwing', async () => {
  const results = await runChecks({ baseUrl: 'http://127.0.0.1:1', token: TOKEN });
  assert.equal(results[0].status, 'fail');
});

test('says so when no token was supplied', async () => {
  const server = await listen(createAssetPoolHandler({ token: TOKEN, listAssets: async () => [], getAsset: async () => null }));
  try {
    const results = await runChecks({ baseUrl: server.baseUrl, token: '' });
    assert.equal(results.at(-1).status, 'fail');
    assert.match(results.at(-1).detail, /no token/);
  } finally {
    await server.close();
  }
});

test('an empty pool is a warning, not a failure', async () => {
  const server = await listen(createAssetPoolHandler({ token: TOKEN, listAssets: async () => [], getAsset: async () => null }));
  try {
    const results = await runChecks({ baseUrl: server.baseUrl, token: TOKEN });
    assert.equal(results.filter((r) => r.status === 'fail').length, 0);
    assert.equal(results.at(-1).status, 'warn');
  } finally {
    await server.close();
  }
});
