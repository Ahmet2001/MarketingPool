import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { ASSET_FIELDS, ASSET_KINDS, ASSET_LIMITS } from '../src/assetSchema.js';

// schemas/asset.schema.json is the source of truth; src/assetSchema.js mirrors
// it without a JSON-schema dependency. This test keeps them from drifting.
const schema = JSON.parse(await readFile(new URL('../../schemas/asset.schema.json', import.meta.url), 'utf8'));

test('kinds match the schema enum', () => {
  assert.deepEqual([...ASSET_KINDS], schema.properties.kind.enum);
});

test('declared fields match the schema properties', () => {
  assert.deepEqual([...ASSET_FIELDS].sort(), Object.keys(schema.properties).sort());
});

test('length limits match the schema', () => {
  assert.equal(ASSET_LIMITS.title, schema.properties.title.maxLength);
  assert.equal(ASSET_LIMITS.altText, schema.properties.altText.maxLength);
});

test('schema still forbids additional properties and requires id/kind/url', () => {
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual([...schema.required].sort(), ['id', 'kind', 'url']);
});

test('schema still pins url to https', () => {
  assert.equal(schema.properties.url.pattern, '^https://');
});
