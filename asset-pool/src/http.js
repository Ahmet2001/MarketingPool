import { timingSafeEqual } from 'node:crypto';

export class HttpError extends Error {
  constructor(status, message, extra = {}) {
    super(message);
    this.statusCode = status;
    Object.assign(this, extra);
  }
}

/**
 * Throw this from prepareAsset to say "I understand the request but this asset
 * can't be made ready for that target" -> 422 { error, reasons }.
 */
export class PrepareRefusal extends HttpError {
  constructor(message, reasons = []) {
    super(422, message, { reasons });
  }
}

export function send(res, status, body, headers = {}) {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  // URLs in these responses are usually short-lived signed URLs; never let a proxy keep them.
  res.setHeader('Cache-Control', 'private, no-store');
  for (const [name, value] of Object.entries(headers)) res.setHeader(name, value);
  res.end(payload);
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a));
  const right = Buffer.from(String(b));
  return left.length === right.length && timingSafeEqual(left, right);
}

export function bearerToken(req) {
  const match = String(req.headers?.authorization || '').match(/^Bearer\s+(.+)$/i);
  return match ? match[1].trim() : '';
}

/**
 * `authenticate(req)` -> ctx, or throws an error carrying `.statusCode`.
 * Without `authenticate`, a shared `token` is compared in constant time; with
 * neither, every request is refused (500) so a pool never runs open by accident.
 */
export function makeAuthenticator({ token = '', authenticate } = {}) {
  if (authenticate) return async (req) => authenticate(req);
  const secret = String(token || '').trim();
  return async (req) => {
    if (!secret) throw new HttpError(500, 'asset pool token is not configured');
    const provided = bearerToken(req);
    if (!provided || !safeEqual(provided, secret)) {
      throw new HttpError(401, 'missing or invalid Authorization: Bearer <token>');
    }
    return {};
  };
}

/** Path relative to the mount point, or null when the request isn't for this handler. */
export function relativePath(req, basePath) {
  const { pathname } = new URL(req.url || '/', 'http://asset-pool.local');
  if (pathname === basePath || pathname.startsWith(`${basePath}/`)) return pathname.slice(basePath.length);
  if (req.baseUrl) return pathname; // Express already stripped the mount path
  return null;
}

export function searchParamsOf(req) {
  return new URL(req.url || '/', 'http://asset-pool.local').searchParams;
}

/** Reads a small JSON body from a raw request, or uses one a framework already parsed. */
export async function readJsonBody(req, maxBytes = 16 * 1024) {
  if (req.body !== undefined && req.body !== null && typeof req.body === 'object') return req.body;
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxBytes) throw new HttpError(413, `request body must be at most ${maxBytes} bytes`);
    chunks.push(chunk);
  }
  if (size === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new HttpError(400, 'request body must be valid JSON');
  }
}

export function decodeId(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    throw new HttpError(400, 'malformed id');
  }
}

/** Maps any thrown value to an HTTP response; 5xx messages never leak internals. */
export function sendError(res, error, onError) {
  const status = Number.isInteger(error?.statusCode) ? error.statusCode : 500;
  if (status >= 500) {
    if (!(error instanceof HttpError)) onError(error);
    return send(res, status, { error: error instanceof HttpError ? error.message : 'internal error' });
  }
  const body = { error: error.message };
  if (Array.isArray(error.reasons)) body.reasons = error.reasons.map(String).slice(0, 20);
  return send(res, status, body);
}
