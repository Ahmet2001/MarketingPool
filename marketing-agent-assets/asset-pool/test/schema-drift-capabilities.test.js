import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import * as c from '../src/contracts.js';

const load = async (name) => JSON.parse(await readFile(new URL(`../../schemas/${name}.schema.json`, import.meta.url), 'utf8'));

test('media_prepare_request schema matches the constants', async () => {
  const s = await load('media_prepare_request');
  assert.deepEqual([...c.PREPARE_PLATFORMS], s.properties.target.properties.platform.enum);
  assert.deepEqual([...c.PREPARE_ACTIONS], s.properties.target.properties.action.enum);
  assert.equal(c.PREPARE_TTL.min, s.properties.ttlSeconds.minimum);
  assert.equal(c.PREPARE_TTL.max, s.properties.ttlSeconds.maximum);
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ['target']);
});

test('video_generation_request schema matches the constants', async () => {
  const s = await load('video_generation_request');
  assert.deepEqual([...c.VIDEO_REQUEST_FIELDS].sort(), Object.keys(s.properties).sort());
  assert.equal(c.VIDEO_BRIEF.min, s.properties.brief.minLength);
  assert.equal(c.VIDEO_BRIEF.max, s.properties.brief.maxLength);
  assert.equal(c.VIDEO_TITLE_MAX, s.properties.title.maxLength);
  assert.equal(c.VIDEO_DURATION.min, s.properties.durationSeconds.minimum);
  assert.equal(c.VIDEO_DURATION.max, s.properties.durationSeconds.maximum);
  assert.deepEqual([...c.VIDEO_ORIENTATIONS], s.properties.orientation.enum);
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ['brief']);
});

test('video_generation_status schema matches the constants', async () => {
  const s = await load('video_generation_status');
  assert.deepEqual([...c.VIDEO_STATUS_FIELDS].sort(), Object.keys(s.properties).sort());
  assert.deepEqual([...c.VIDEO_STATUSES], s.properties.status.enum);
  assert.deepEqual([...c.VIDEO_APPROVALS], s.properties.approval.enum);
  assert.equal(s.properties.asset.$ref, 'asset.schema.json');
  assert.deepEqual([...s.required].sort(), ['requestId', 'status']);
});
