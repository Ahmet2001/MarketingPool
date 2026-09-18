"""Real policy + real manifests + the REAL youtube/instagram toolbox modules, with only the
network (`requests.request`) faked: proves a queued request reaches the platform API call the
manifest promises, with the params the policy normalized, and nothing else."""
import os
import unittest
from pathlib import Path
from unittest import mock

from platform_data_worker import worker
from platform_data_worker.executor import ToolboxExecutor
from platform_data_worker.policy import load_policy

REPO = Path(__file__).resolve().parents[2]


class FakeHttpResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok, self.text = payload, status, status < 400, str(payload)
        self.headers = {}

    def json(self):
        return self._payload


class Store:
    def __init__(self):
        self.finished, self.failed = [], []

    def finish(self, job_id, results):
        self.finished.append(results)

    def fail(self, job_id, error, results=None):
        self.failed.append((error, results))

    def count_recent(self, platform, action):
        return 1


class RealToolboxFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(REPO / "toolboxes")
        cls.executor = ToolboxExecutor(REPO / "toolboxes")

    def run_job(self, payload, http_payload, env):
        calls = []

        def fake_request(method, url, params=None, json=None, headers=None, timeout=None, **_):
            calls.append((method, url, dict(params or {}), dict(headers or {})))
            return FakeHttpResponse(http_payload)

        store = Store()
        with mock.patch.dict(os.environ, env), mock.patch("requests.request", side_effect=fake_request):
            worker.process_job({"id": "job-1", "payload": payload}, self.policy, self.executor, store)
        return calls, store

    def test_youtube_videos_reaches_the_data_api_with_normalized_params(self):
        calls, store = self.run_job(
            {"platform": "youtube", "action": "videos", "params": {"video_ids": "dQw4w9WgXcQ"}},
            {"items": [{"id": "dQw4w9WgXcQ", "statistics": {"viewCount": "42", "note": "key=AIza-fake-key-123456"}}]},
            {"YOUTUBE_API_KEY": "AIza-fake-key-123456"},
        )
        self.assertEqual(len(calls), 1)
        method, url, params, _ = calls[0]
        self.assertEqual((method, url), ("GET", "https://www.googleapis.com/youtube/v3/videos"))
        self.assertEqual(params["id"], "dQw4w9WgXcQ")
        self.assertEqual(store.failed, [])
        result = store.finished[0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["items"][0]["statistics"]["viewCount"], "42")
        self.assertNotIn("AIza-fake-key-123456", str(result))  # echoed back by the "platform", still redacted

    def test_a_write_action_named_in_the_payload_never_reaches_the_network(self):
        calls, store = self.run_job(
            {"platform": "youtube", "action": "upload", "params": {}}, {}, {"YOUTUBE_API_KEY": "AIza-fake-key-123456"})
        self.assertEqual(calls, [])
        self.assertEqual(len(store.failed), 1)

    def test_an_undeclared_param_never_reaches_the_network(self):
        calls, store = self.run_job(
            {"platform": "instagram", "action": "media", "params": {"limit": 3, "fields": "id,secret_field"}},
            {}, {"INSTAGRAM_ACCESS_TOKEN": "IGQ-fake-token-abcdef", "INSTAGRAM_USER_ID": "1784"})
        self.assertEqual(calls, [])
        self.assertIn("unknown param", store.failed[0][0])

    def test_instagram_media_uses_the_configured_account_and_default_fields_only(self):
        calls, store = self.run_job(
            {"platform": "instagram", "action": "media", "params": {"limit": 3}},
            {"data": [{"id": "1", "caption": "hello"}]},
            {"INSTAGRAM_ACCESS_TOKEN": "IGQ-fake-token-abcdef", "INSTAGRAM_USER_ID": "1784"})
        self.assertEqual(len(calls), 1)
        self.assertIn("/1784/media", calls[0][1])
        self.assertEqual(calls[0][2]["limit"], 3)
        self.assertTrue(store.finished and store.finished[0]["ok"])
        self.assertNotIn("IGQ-fake-token-abcdef", str(store.finished[0]))

    def test_platform_error_status_becomes_a_failed_job_with_the_reason(self):
        calls, store = self.run_job(
            {"platform": "youtube", "action": "videos", "params": {"video_ids": "dQw4w9WgXcQ"}},
            {"error": {"message": "quotaExceeded"}}, {"YOUTUBE_API_KEY": "AIza-fake-key-123456"})
        self.assertEqual(store.finished, [])
        self.assertIn("quotaExceeded", store.failed[0][0])


if __name__ == "__main__":
    unittest.main()
