// Mirrors ../../schemas/asset.schema.json in plain JS so this kit needs no
// dependencies. test/schema-drift.test.js fails if the two ever disagree, so
// edit the JSON schema first and this file second.

export const ASSET_KINDS = Object.freeze(['video', 'image', 'audio', 'document']);

export const ASSET_FIELDS = Object.freeze([
  'id', 'kind', 'url', 'contentType', 'title', 'altText', 'expiresAt', 'metadata'
]);

export const ASSET_LIMITS = Object.freeze({ title: 240, altText: 2000 });

const RFC3339 = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

function isNonEmptyString(value) {
  return typeof value === 'string' && value.length > 0;
}

function isHttpsUrl(value) {
  if (typeof value !== 'string' || !/^https:\/\//.test(value)) return false;
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Validates one asset against the contract.
 *
 * - `strict: true` (used by the conformance checker) also reports properties
 *   the schema doesn't declare, since the schema sets additionalProperties:false.
 * - `strict: false` (used by the request handler) silently drops them, so an
 *   app can hand over its own rows without hand-picking fields first.
 *
 * Returns `{ asset, errors }`; `asset` is null whenever `errors` is non-empty.
 */
export function validateAsset(raw, { strict = false } = {}) {
  const errors = [];
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { asset: null, errors: ['asset must be an object'] };
  }

  if (!isNonEmptyString(raw.id)) errors.push('id must be a non-empty string');
  if (!ASSET_KINDS.includes(raw.kind)) errors.push(`kind must be one of ${ASSET_KINDS.join(', ')}`);
  if (!isHttpsUrl(raw.url)) errors.push('url must be an https:// URL');

  if (raw.contentType !== undefined && typeof raw.contentType !== 'string') {
    errors.push('contentType must be a string');
  }
  if (raw.title !== undefined) {
    if (typeof raw.title !== 'string') errors.push('title must be a string');
    else if (raw.title.length > ASSET_LIMITS.title) errors.push(`title must be at most ${ASSET_LIMITS.title} characters`);
  }
  if (raw.altText !== undefined) {
    if (typeof raw.altText !== 'string') errors.push('altText must be a string');
    else if (raw.altText.length > ASSET_LIMITS.altText) errors.push(`altText must be at most ${ASSET_LIMITS.altText} characters`);
  }
  if (raw.expiresAt !== undefined) {
    if (typeof raw.expiresAt !== 'string' || !RFC3339.test(raw.expiresAt) || Number.isNaN(Date.parse(raw.expiresAt))) {
      errors.push('expiresAt must be an RFC 3339 date-time string');
    }
  }
  if (raw.metadata !== undefined) {
    if (raw.metadata === null || typeof raw.metadata !== 'object' || Array.isArray(raw.metadata)) {
      errors.push('metadata must be an object');
    }
  }

  if (strict) {
    for (const key of Object.keys(raw)) {
      if (!ASSET_FIELDS.includes(key)) errors.push(`unknown property "${key}" (schema sets additionalProperties:false)`);
    }
  }

  if (errors.length) return { asset: null, errors };

  const asset = {};
  for (const field of ASSET_FIELDS) {
    if (raw[field] !== undefined) asset[field] = raw[field];
  }
  return { asset, errors: [] };
}
