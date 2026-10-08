import assert from 'node:assert/strict';
import test from 'node:test';
import { validateAsset } from '../src/assetSchema.js';
import { goodAsset } from '../testkit/helpers.js';

test('accepts a minimal asset', () => {
  const { asset, errors } = validateAsset(goodAsset());
  assert.deepEqual(errors, []);
  assert.equal(asset.id, 'a1');
});

test('rejects non-https, bad kind, empty id, non-objects', () => {
  assert.ok(validateAsset(goodAsset({ url: 'http://cdn.example.com/a.mp4' })).errors.length);
  assert.ok(validateAsset(goodAsset({ url: 'https://' })).errors.length);
  assert.ok(validateAsset(goodAsset({ kind: 'gif' })).errors.length);
  assert.ok(validateAsset(goodAsset({ id: '' })).errors.length);
  assert.ok(validateAsset(null).errors.length);
  assert.ok(validateAsset([]).errors.length);
});

test('enforces length limits and types', () => {
  assert.ok(validateAsset(goodAsset({ title: 'x'.repeat(241) })).errors.length);
  assert.ok(validateAsset(goodAsset({ altText: 'x'.repeat(2001) })).errors.length);
  assert.ok(validateAsset(goodAsset({ metadata: [] })).errors.length);
  assert.ok(validateAsset(goodAsset({ metadata: null })).errors.length);
  assert.ok(validateAsset(goodAsset({ contentType: 5 })).errors.length);
});

test('expiresAt must be a real RFC 3339 date-time', () => {
  assert.deepEqual(validateAsset(goodAsset({ expiresAt: '2030-01-01T00:00:00Z' })).errors, []);
  assert.deepEqual(validateAsset(goodAsset({ expiresAt: '2030-01-01T00:00:00.123+03:00' })).errors, []);
  assert.ok(validateAsset(goodAsset({ expiresAt: 'tomorrow' })).errors.length);
  assert.ok(validateAsset(goodAsset({ expiresAt: '2030-13-45T00:00:00Z' })).errors.length);
  assert.ok(validateAsset(goodAsset({ expiresAt: '2030-01-01' })).errors.length);
});

test('unknown properties: stripped by default, errors in strict mode', () => {
  const lenient = validateAsset(goodAsset({ secret: 'x' }));
  assert.equal('secret' in lenient.asset, false);
  const strict = validateAsset(goodAsset({ secret: 'x' }), { strict: true });
  assert.equal(strict.asset, null);
  assert.match(strict.errors[0], /secret/);
});
