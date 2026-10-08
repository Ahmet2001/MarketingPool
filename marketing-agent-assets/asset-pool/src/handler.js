import { validateAsset, ASSET_KINDS } from './assetSchema.js';
import { PREPARE_ACTIONS, PREPARE_PLATFORMS, PREPARE_TTL } from './contracts.js';
import {
  HttpError,
  decodeId,
  makeAuthenticator,
  readJsonBody,
  relativePath,
  searchParamsOf,
  send,
  sendError
} from './http.js';

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

function parseListQuery(searchParams, { defaultLimit, maxLimit }) {
  const kind = searchParams.get('kind') || '';
  if (kind && !ASSET_KINDS.includes(kind)) {
    throw new HttpError(400, `kind must be one of ${ASSET_KINDS.join(', ')}`);
  }
  const tag = (searchParams.get('tag') || '').trim();
  if (tag.length > 200) throw new HttpError(400, 'tag must be at most 200 characters');

  let limit = defaultLimit;
  if (searchParams.has('limit')) {
    const raw = searchParams.get('limit');
    if (!/^\d+$/.test(raw) || Number(raw) < 1) throw new HttpError(400, 'limit must be a positive integer');
    limit = Math.min(Number(raw), maxLimit);
  }
  return { kind, tag, limit };
}

/** Validates the body of POST {pool}/{id}/prepare (schemas/media_prepare_request.schema.json). */
export function parsePrepareRequest(body) {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    throw new HttpError(400, 'body must be an object');
  }
  for (const key of Object.keys(body)) {
    if (!['target', 'ttlSeconds'].includes(key)) throw new HttpError(400, `unknown property "${key}"`);
  }
  const { target } = body;
  if (target === null || typeof target !== 'object' || Array.isArray(target)) {
    throw new HttpError(400, 'target must be an object');
  }
  for (const key of Object.keys(target)) {
    if (!['platform', 'action'].includes(key)) throw new HttpError(400, `unknown property "target.${key}"`);
  }
  if (!PREPARE_PLATFORMS.includes(target.platform)) {
    throw new HttpError(400, `target.platform must be one of ${PREPARE_PLATFORMS.join(', ')}`);
  }
  if (!PREPARE_ACTIONS.includes(target.action)) {
    throw new HttpError(400, `target.action must be one of ${PREPARE_ACTIONS.join(', ')}`);
  }
  if (target.action === 'instagram.carousel' && target.platform !== 'instagram') {
    throw new HttpError(400, 'instagram.carousel can only target platform "instagram"');
  }
  const request = { target: { platform: target.platform, action: target.action } };
  if (body.ttlSeconds !== undefined) {
    if (!Number.isInteger(body.ttlSeconds) || body.ttlSeconds < PREPARE_TTL.min || body.ttlSeconds > PREPARE_TTL.max) {
      throw new HttpError(400, `ttlSeconds must be an integer between ${PREPARE_TTL.min} and ${PREPARE_TTL.max}`);
    }
    request.ttlSeconds = body.ttlSeconds;
  }
  return request;
}

/**
 * Builds a request handler that serves the asset-pool contract:
 *
 *   GET  {basePath}?kind=&tag=&limit=   ->  200 { "assets": [Asset, ...] }
 *   GET  {basePath}/{id}                ->  200 Asset   |  404 { "error": ... }
 *   POST {basePath}/{id}/prepare        ->  200 Asset (ready for the target)  (optional)
 *                                           404 unknown id | 422 { error, reasons } | 501 not supported
 *
 * Works as Express middleware (`app.use('/api/assets', handler)`) and as a
 * plain `http.createServer` listener; it depends on nothing but Node.
 *
 * Options
 *   listAssets({ kind, tag, limit }, ctx)   -> Asset-like[]    (required)
 *   getAsset(id, ctx)                       -> Asset-like|null (required)
 *   prepareAsset(id, request, ctx)          -> Asset-like|null (optional; enables the prepare route)
 *                                              `request` is { target: { platform, action }, ttlSeconds? }.
 *                                              Throw PrepareRefusal(message, reasons) to answer 422.
 *   token          shared secret; callers send `Authorization: Bearer <token>`.
 *                  If neither `token` nor `authenticate` is set, EVERY request
 *                  is refused with 500 -- the pool never runs open by accident.
 *   authenticate   optional async (req) => ctx, throw an error carrying
 *                  `.statusCode` (e.g. 401/403) to refuse. Replaces `token`;
 *                  whatever it returns is passed to the callbacks, which is how
 *                  an app resolves "who is asking" server-side.
 *   basePath       default "/api/assets"
 *   onError        (error) => void, default console.error
 *
 * Whatever the callbacks return is validated against the contract
 * (schemas/asset.schema.json): undeclared fields are stripped and non-conforming
 * assets (e.g. an http:// URL) are dropped rather than forwarded. The number
 * dropped is reported in the `X-Asset-Pool-Dropped` response header.
 */
export function createAssetPoolHandler({
  listAssets,
  getAsset,
  prepareAsset,
  token = '',
  authenticate,
  basePath = '/api/assets',
  defaultLimit = DEFAULT_LIMIT,
  maxLimit = MAX_LIMIT,
  onError = (error) => console.error('[asset-pool]', error)
} = {}) {
  if (typeof listAssets !== 'function' || typeof getAsset !== 'function') {
    throw new TypeError('createAssetPoolHandler requires listAssets and getAsset functions');
  }
  if (prepareAsset !== undefined && typeof prepareAsset !== 'function') {
    throw new TypeError('prepareAsset must be a function when provided');
  }
  const resolveContext = makeAuthenticator({ token, authenticate });

  return async function assetPoolHandler(req, res, next) {
    try {
      const relative = relativePath(req, basePath);
      if (relative === null) {
        if (typeof next === 'function') return next();
        return send(res, 404, { error: 'not found' });
      }
      const segments = relative.split('/').filter(Boolean);
      const isPrepare = segments.length === 2 && segments[1] === 'prepare';

      const allowed = isPrepare ? ['POST'] : ['GET', 'HEAD'];
      if (!allowed.includes(req.method)) {
        return send(res, 405, { error: 'method not allowed' }, { Allow: allowed.join(', ') });
      }

      const ctx = await resolveContext(req);

      if (segments.length === 0) {
        const query = parseListQuery(searchParamsOf(req), { defaultLimit, maxLimit });
        const raw = await listAssets(query, ctx);
        if (!Array.isArray(raw)) throw new Error('listAssets must return an array');

        const assets = [];
        let dropped = 0;
        for (const item of raw) {
          const { asset } = validateAsset(item);
          if (!asset || (query.kind && asset.kind !== query.kind)) {
            dropped += 1;
          } else if (assets.length < query.limit) {
            assets.push(asset);
          }
        }
        return send(res, 200, { assets }, dropped ? { 'X-Asset-Pool-Dropped': String(dropped) } : {});
      }

      if (segments.length === 1) {
        const id = decodeId(segments[0]);
        const raw = await getAsset(id, ctx);
        if (raw === null || raw === undefined) return send(res, 404, { error: 'asset not found' });
        const { asset, errors } = validateAsset(raw);
        if (!asset) {
          onError(new Error(`asset "${id}" violates the contract: ${errors.join('; ')}`));
          return send(res, 500, { error: 'asset failed contract validation', details: errors });
        }
        return send(res, 200, asset);
      }

      if (isPrepare) {
        if (!prepareAsset) return send(res, 501, { error: 'prepare is not supported by this pool' });
        const id = decodeId(segments[0]);
        const request = parsePrepareRequest(await readJsonBody(req));
        const raw = await prepareAsset(id, request, ctx);
        if (raw === null || raw === undefined) return send(res, 404, { error: 'asset not found' });
        const { asset, errors } = validateAsset(raw);
        if (!asset) {
          onError(new Error(`prepared asset "${id}" violates the contract: ${errors.join('; ')}`));
          return send(res, 500, { error: 'prepared asset failed contract validation', details: errors });
        }
        const wantsImage = request.target.action === 'instagram.carousel';
        if ((wantsImage && asset.kind !== 'image') || (!wantsImage && asset.kind !== 'video')) {
          onError(new Error(`prepared asset "${id}" is a ${asset.kind}, which does not fit ${request.target.action}`));
          return send(res, 500, { error: 'prepared asset does not fit the requested target' });
        }
        return send(res, 200, asset);
      }

      return send(res, 404, { error: 'not found' });
    } catch (error) {
      return sendError(res, error, onError);
    }
  };
}
