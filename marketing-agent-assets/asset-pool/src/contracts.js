// Constants for the capability contracts beyond assets. They mirror
// ../../schemas/{media_prepare_request,video_generation_request,video_generation_status}.schema.json
// by hand (no JSON-schema dependency); test/schema-drift.test.js fails on drift.

export const PREPARE_PLATFORMS = Object.freeze(['instagram', 'youtube', 'tiktok']);
export const PREPARE_ACTIONS = Object.freeze(['video.publish', 'instagram.carousel']);
export const PREPARE_TTL = Object.freeze({ min: 60, max: 86400 });

export const VIDEO_BRIEF = Object.freeze({ min: 10, max: 2000 });
export const VIDEO_TITLE_MAX = 100;
export const VIDEO_DURATION = Object.freeze({ min: 5, max: 1200 });
export const VIDEO_ORIENTATIONS = Object.freeze(['horizontal', 'vertical']);
export const VIDEO_REQUEST_FIELDS = Object.freeze(['brief', 'title', 'durationSeconds', 'orientation', 'language', 'metadata']);
export const VIDEO_STATUSES = Object.freeze(['queued', 'running', 'done', 'failed']);
export const VIDEO_APPROVALS = Object.freeze(['pending', 'approved']);
export const VIDEO_STATUS_FIELDS = Object.freeze(['requestId', 'status', 'progress', 'asset', 'approval', 'error']);
