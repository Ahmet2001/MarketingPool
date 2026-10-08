// Example: Kara Tahta as a "request video generation" provider.
//
// Kara Tahta already renders narrated lesson videos through its own HTTP API
// (POST /api/generate-lesson, then GET /api/jobs/:id -- the same calls
// mcp_worker makes). This adapter puts the asset-pool video-request contract in
// front of that API, so an agent can ask for a video with a plain brief and
// poll for the result without knowing anything about Kara Tahta.
//
// It only speaks HTTP to the app (authenticated with the app's scheduler shared
// secret), so it runs equally well mounted inside Kara Tahta (pointing at
// http://127.0.0.1:PORT) or as a separate sidecar service.
//
// What Kara Tahta can't do, and how the contract absorbs it:
//   * No idempotency support -> this adapter remembers Idempotency-Keys itself
//     (in memory, 24h). That protects against retries within one process; it
//     does NOT survive a restart or span replicas. A production adapter should
//     keep the key -> requestId map in a database.
//   * `title` and `language` in a request are accepted but ignored: Kara Tahta
//     derives both from the topic.
//   * A finished lesson is private until its owner makes it public, so the
//     `asset` in a `done` status is a DRAFT (approval: "pending"). It becomes
//     publishable only once it also appears in the asset pool.

const HOUR_MS = 60 * 60 * 1000;
const LEVELS = ['beginner', 'intermediate', 'advanced'];

const statusError = (statusCode, message) => Object.assign(new Error(message), { statusCode });

function toMinutes(durationSeconds) {
  return Math.min(20, Math.max(0.5, Math.round((durationSeconds / 60) * 2) / 2));
}

/** Kara Tahta job status -> contract status. */
function mapStatus(status) {
  if (status === 'queued' || status === 'done' || status === 'failed') return status;
  return 'running'; // 'running', 'concat', and anything else in flight
}

/**
 * @param {object} deps
 * @param {string} deps.backendUrl  Kara Tahta's base URL.
 * @param {string} deps.token       Its SCHEDULER_INTERNAL_TOKEN (sent as X-Scheduler-Token);
 *                                  the app resolves it to the scheduler user server-side.
 * @param {Function} [deps.fetchImpl=fetch]
 * @param {number} [deps.idempotencyTtlMs=24h]
 * @param {() => number} [deps.now=Date.now]
 * @returns {{ createVideoRequest: Function, getVideoRequest: Function }} pass to createVideoRequestHandler()
 */
export function createKaratahtaVideoSource({
  backendUrl,
  token,
  fetchImpl = fetch,
  idempotencyTtlMs = 24 * HOUR_MS,
  now = Date.now
}) {
  const base = String(backendUrl || '').replace(/\/+$/, '');
  if (!base || !token) throw new TypeError('createKaratahtaVideoSource requires backendUrl and token');

  const seen = new Map(); // idempotency key -> { requestId, at }

  function prune() {
    for (const [key, entry] of seen) if (now() - entry.at > idempotencyTtlMs) seen.delete(key);
  }

  async function call(method, path, body) {
    let response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-Scheduler-Token': token },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(20000)
      });
    } catch (error) {
      throw statusError(502, `Kara Tahta is unreachable: ${error.message}`);
    }
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    return { status: response.status, data };
  }

  function toStatusDocument(job) {
    const doc = { requestId: String(job.id), status: mapStatus(job.status) };

    const progress = {};
    if (Number.isInteger(job.progress) && job.progress >= 0) progress.current = job.progress;
    if (Number.isInteger(job.total) && job.total >= 0) progress.total = job.total;
    const message = typeof job.message === 'string' ? job.message : typeof job.current === 'string' ? job.current : '';
    if (message) progress.message = message.slice(0, 500);
    if (Object.keys(progress).length) doc.progress = progress;

    if (doc.status === 'failed') doc.error = String(job.error || 'video generation failed').slice(0, 2000);

    if (doc.status === 'done') {
      doc.approval = 'pending';
      const videoUrl = job.result?.videoUrl;
      if (job.lessonId && typeof videoUrl === 'string' && videoUrl.startsWith('https://')) {
        doc.asset = {
          id: `video:${job.lessonId}`,
          kind: 'video',
          url: videoUrl,
          contentType: 'video/mp4',
          title: String(job.plan?.title || 'Kara Tahta dersi').slice(0, 240),
          metadata: { source: 'karatahta', lessonId: job.lessonId, draft: true }
        };
      }
    }
    return doc;
  }

  async function getVideoRequest(requestId) {
    const { status, data } = await call('GET', `/api/jobs/${encodeURIComponent(requestId)}`);
    if (status === 404) return null;
    if (status === 401 || status === 403) throw statusError(502, 'Kara Tahta rejected the scheduler token');
    if (status !== 200 || !data) throw statusError(502, `Kara Tahta answered HTTP ${status} for the job`);
    return toStatusDocument({ ...data, id: data.id ?? requestId });
  }

  async function createVideoRequest(request, { idempotencyKey } = {}) {
    prune();
    if (idempotencyKey && seen.has(idempotencyKey)) {
      const existing = await getVideoRequest(seen.get(idempotencyKey).requestId);
      if (existing) return existing;
      seen.delete(idempotencyKey); // the job is gone on the app's side: start over
    }

    const body = { topic: request.brief };
    if (request.orientation) body.orientation = request.orientation;
    if (request.durationSeconds) body.target_video_minutes = toMinutes(request.durationSeconds);
    if (LEVELS.includes(request.metadata?.studentLevel)) body.student_level = request.metadata.studentLevel;

    const { status, data } = await call('POST', '/api/generate-lesson', body);
    if (status === 401 || status === 403) throw statusError(502, 'Kara Tahta rejected the scheduler token');
    if (status === 429 || status === 402) throw statusError(429, data?.error || 'Kara Tahta refused the request (quota)');
    if (status === 400) throw statusError(400, data?.error || 'Kara Tahta rejected the brief');
    if (![200, 201, 202].includes(status) || !data?.id) {
      throw statusError(502, data?.error || `Kara Tahta answered HTTP ${status} when starting the video`);
    }

    if (idempotencyKey) seen.set(idempotencyKey, { requestId: String(data.id), at: now() });
    return toStatusDocument(data);
  }

  return { createVideoRequest, getVideoRequest };
}
