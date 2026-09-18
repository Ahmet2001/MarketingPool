import unittest
from unittest import mock

import requests

from platform_data_worker import worker
from platform_data_worker.jobstore import QueueError, SupabaseQueue
from platform_data_worker.policy import ActionSpec, ParamSpec, Policy


class FakeStore:
    def __init__(self, queued=None, recent=0):
        self.queued = list(queued or [])
        self.recent = recent
        self.finished, self.failed = [], []

    def claim_next(self):
        return self.queued.pop(0) if self.queued else None

    def finish(self, job_id, results):
        self.finished.append((job_id, results))

    def fail(self, job_id, error, results=None):
        self.failed.append((job_id, error, results))

    def count_recent(self, platform, action):
        return self.recent


class FakeExecutor:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"ok": True, "platform": "youtube", "action": "videos", "data": {"items": []}, "truncated": False}

    def run(self, spec, params):
        self.calls.append((spec.action_id, params))
        return self.result


def policy():
    spec = ActionSpec(
        platform="youtube", action_id="videos", function="get_youtube_api_videos", description="",
        params={"video_ids": ParamSpec(name="video_ids", type="string", required=True, max_length=50)},
        rate_limit_per_hour=2,
    )
    return Policy({("youtube", "videos"): spec})


def job(**payload):
    return {"id": "j1", "payload": {"platform": "youtube", "action": "videos", "params": {"video_ids": "abc"}, **payload}}


class ProcessJobTests(unittest.TestCase):
    def run_job(self, j, store=None, executor=None):
        store, executor = store or FakeStore(), executor or FakeExecutor()
        outcome = worker.process_job(j, policy(), executor, store)
        return outcome, store, executor

    def test_happy_path_finishes_the_job_with_the_result(self):
        outcome, store, executor = self.run_job(job())
        self.assertEqual(outcome, "done")
        self.assertEqual(executor.calls, [("videos", {"video_ids": "abc"})])
        self.assertEqual(store.finished[0][0], "j1")
        self.assertEqual(store.failed, [])

    def test_unapproved_action_is_refused_and_never_executed(self):
        outcome, store, executor = self.run_job(job(action="upload"))
        self.assertEqual(outcome, "failed")
        self.assertEqual(executor.calls, [])
        self.assertIn("not a manifest-approved", store.failed[0][1])

    def test_bad_params_are_refused_and_never_executed(self):
        outcome, store, executor = self.run_job(job(params={"video_ids": "x" * 60}))
        self.assertEqual((outcome, executor.calls), ("failed", []))
        outcome, store, executor = self.run_job(job(params={"video_ids": "a", "part": "snippet"}))
        self.assertEqual((outcome, executor.calls), ("failed", []))

    def test_credential_ref_is_refused_rather_than_silently_ignored(self):
        outcome, store, executor = self.run_job(job(credentialRef="brand-b"))
        self.assertEqual((outcome, executor.calls), ("failed", []))
        self.assertIn("credentialRef", store.failed[0][1])

    def test_unexpected_payload_fields_are_refused(self):
        outcome, store, executor = self.run_job(job(shell="rm -rf /"))
        self.assertEqual((outcome, executor.calls), ("failed", []))

    def test_rate_limit_counts_this_job_and_refuses_over_the_limit(self):
        outcome, store, executor = self.run_job(job(), store=FakeStore(recent=2))
        self.assertEqual(outcome, "done")  # 2 <= limit 2 (this job included)
        outcome, store, executor = self.run_job(job(), store=FakeStore(recent=3))
        self.assertEqual((outcome, executor.calls), ("failed", []))
        self.assertIn("rate limit", store.failed[0][1])

    def test_platform_failure_marks_the_job_failed_and_keeps_the_result(self):
        result = {"ok": False, "platform": "youtube", "action": "videos", "data": None, "truncated": False, "error": "quota exceeded"}
        outcome, store, _ = self.run_job(job(), executor=FakeExecutor(result))
        self.assertEqual(outcome, "failed")
        self.assertEqual(store.failed[0][1], "quota exceeded")
        self.assertEqual(store.failed[0][2]["error"], "quota exceeded")

    def test_non_dict_payload_is_a_refusal_not_a_crash(self):
        outcome, store, _ = self.run_job({"id": "j2", "payload": "nonsense"})
        self.assertEqual(outcome, "failed")


class RunOnceTests(unittest.TestCase):
    def test_empty_queue_returns_false(self):
        self.assertFalse(worker.run_once(policy(), FakeExecutor(), FakeStore()))

    def test_a_crashing_job_is_failed_not_left_processing(self):
        store = FakeStore(queued=[job()])
        executor = FakeExecutor()
        executor.run = mock.Mock(side_effect=RuntimeError("kaboom"))
        self.assertTrue(worker.run_once(policy(), executor, store))
        self.assertEqual(store.failed[0][0], "j1")
        self.assertIn("worker error", store.failed[0][1])

    def test_drains_multiple_jobs(self):
        store = FakeStore(queued=[job(), job()])
        n = 0
        while worker.run_once(policy(), FakeExecutor(), store):
            n += 1
        self.assertEqual(n, 2)


class Resp:
    def __init__(self, payload=None, headers=None, status=200):
        self._payload, self.headers, self.status_code = payload, headers or {}, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class JobStoreTests(unittest.TestCase):
    def store(self, http):
        return SupabaseQueue(url="https://p.supabase.co/", key="svc", session=http)

    def test_requires_configuration(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(QueueError):
            SupabaseQueue()

    def test_claim_finish_fail_shapes(self):
        http = mock.Mock()
        http.request.return_value = Resp({"id": "j9", "payload": {}})
        store = self.store(http)
        self.assertEqual(store.claim_next()["id"], "j9")
        method, url = http.request.call_args.args[:2]
        self.assertEqual((method, url), ("POST", "https://p.supabase.co/rest/v1/rpc/claim_platform_data_job"))
        self.assertEqual(http.request.call_args.kwargs["headers"]["apikey"], "svc")

        http.request.return_value = Resp({})
        store.finish("j9", {"ok": True})
        kw = http.request.call_args.kwargs
        self.assertEqual(kw["params"], {"id": "eq.j9"})
        self.assertEqual((kw["json"]["status"], kw["json"]["results"]), ("done", {"ok": True}))
        store.fail("j9", "e" * 5000, {"ok": False})
        kw = http.request.call_args.kwargs
        self.assertEqual(kw["json"]["status"], "failed")
        self.assertEqual(len(kw["json"]["error"]), 2000)

    def test_claim_returns_none_for_an_empty_queue(self):
        http = mock.Mock()
        http.request.return_value = Resp(None)
        self.assertIsNone(self.store(http).claim_next())

    def test_count_recent_reads_content_range(self):
        http = mock.Mock()
        http.request.return_value = Resp([], headers={"Content-Range": "0-0/7"})
        self.assertEqual(self.store(http).count_recent("youtube", "videos"), 7)
        kw = http.request.call_args.kwargs
        self.assertEqual(kw["headers"]["Prefer"], "count=exact")
        self.assertEqual(kw["params"]["payload->>platform"], "eq.youtube")
        self.assertEqual(kw["params"]["status"], "in.(processing,done)")
        http.request.return_value = Resp([], headers={"Content-Range": "*/0"})
        self.assertEqual(self.store(http).count_recent("youtube", "videos"), 0)

    def test_http_errors_become_queue_errors(self):
        http = mock.Mock()
        http.request.return_value = Resp({}, status=500)
        with self.assertRaises(QueueError):
            self.store(http).claim_next()


if __name__ == "__main__":
    unittest.main()
