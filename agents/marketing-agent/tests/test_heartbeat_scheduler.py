import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from MarketingApp.araclar import social_browser_workflow
from MarketingApp.environments import automation_runtime
from MarketingApp.environments import heartbeat


class DummyBaseModel:
    def __init__(self):
        self.calls = []
        self.wait_event = None

    async def text_query(self, user_text: str, **kwargs):
        self.calls.append(user_text)
        if self.wait_event is not None:
            await self.wait_event.wait()

        on_cevap = kwargs.get("on_cevap_metni")
        if on_cevap:
            await on_cevap("tamam")
        return b"", "tamam", [], ["tamam"]


class HeartbeatConfigTests(unittest.TestCase):
    def test_parse_config_supports_all_cron_shapes(self):
        parsed = heartbeat.parse_config_content(
            """
enabled: true
interval_minutes: 5
tasks:
  - id: startup_job
    name: Startup
    cron: "startup"
    gorev: "Hazirlik"
  - id: interval_job
    cron: "*/20"
    gorev: "Refresh"
  - id: daily_job
    cron: "11:45"
    gorev: "Gunluk"
"""
        )

        self.assertTrue(parsed["enabled"])
        self.assertEqual(parsed["interval_minutes"], 5)
        self.assertEqual(len(parsed["tasks"]), 3)
        self.assertEqual(parsed["tasks"][0].cron, "startup")
        self.assertEqual(parsed["tasks"][1].cron, "*/20")
        self.assertEqual(parsed["tasks"][2].cron, "11:45")

    def test_duplicate_ids_raise(self):
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.parse_config_content(
                """
enabled: true
tasks:
  - id: same
    cron: "*/20"
    gorev: "Bir"
  - id: same
    cron: "11:45"
    gorev: "Iki"
"""
            )

    def test_interval_cron_is_wall_clock_aligned(self):
        trigger = heartbeat._build_trigger("*/20")
        now = datetime(2026, 4, 14, 14, 7, 5, tzinfo=heartbeat._TIMEZONE)
        next_fire = trigger.get_next_fire_time(None, now)

        self.assertEqual(next_fire.hour, 14)
        self.assertEqual(next_fire.minute, 20)
        self.assertEqual(next_fire.second, 0)

    def test_daily_cron_is_exact_clock_time(self):
        trigger = heartbeat._build_trigger("11:45")
        now = datetime(2026, 4, 14, 11, 20, 0, tzinfo=heartbeat._TIMEZONE)
        next_fire = trigger.get_next_fire_time(None, now)

        self.assertEqual(next_fire.hour, 11)
        self.assertEqual(next_fire.minute, 45)
        self.assertEqual(next_fire.second, 0)


class HeartbeatServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await automation_runtime.reset_automation_runtime()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = os.path.join(self.temp_dir.name, "config")
        self.runtime_dir = os.path.join(self.temp_dir.name, "runtime")
        os.makedirs(self.config_dir, exist_ok=True)

        self.original_paths = (
            heartbeat._CONFIG_PATH,
            heartbeat._RUNTIME_DIR,
            heartbeat._JOBSTORE_PATH,
            heartbeat._RUNTIME_DB_PATH,
        )
        heartbeat._CONFIG_PATH = os.path.join(self.config_dir, "heartbeat_config.yaml")
        heartbeat._RUNTIME_DIR = self.runtime_dir
        heartbeat._JOBSTORE_PATH = os.path.join(self.runtime_dir, "apscheduler_jobs.sqlite")
        heartbeat._RUNTIME_DB_PATH = os.path.join(self.runtime_dir, "scheduler_runtime.sqlite")

    async def asyncTearDown(self):
        await automation_runtime.reset_automation_runtime()
        heartbeat._CONFIG_PATH, heartbeat._RUNTIME_DIR, heartbeat._JOBSTORE_PATH, heartbeat._RUNTIME_DB_PATH = self.original_paths
        self.temp_dir.cleanup()

    async def test_pause_state_persists_between_service_restarts(self):
        with open(heartbeat._CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(
                """
enabled: true
tasks:
  - id: startup_job
    cron: "startup"
    gorev: "Hazirlik"
  - id: interval_job
    cron: "*/30"
    gorev: "Refresh"
"""
            )

        service = heartbeat.HeartbeatService(DummyBaseModel())
        await service.start()
        await service.pause_job("interval_job")
        paused_snapshot = service.list_jobs()
        self.assertTrue(next(job for job in paused_snapshot if job["job_id"] == "interval_job")["paused"])
        await service.shutdown()

        service2 = heartbeat.HeartbeatService(DummyBaseModel())
        await service2.start()
        jobs = service2.list_jobs()
        interval_job = next(job for job in jobs if job["job_id"] == "interval_job")
        self.assertTrue(interval_job["paused"])
        await service2.shutdown()

    async def test_manual_run_conflicts_when_another_job_is_running(self):
        with open(heartbeat._CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(
                """
enabled: true
tasks:
  - id: interval_job
    cron: "*/30"
    gorev: "Refresh"
"""
            )

        base_model = DummyBaseModel()
        base_model.wait_event = asyncio.Event()
        service = heartbeat.HeartbeatService(base_model)
        await service.start()

        await service.run_job_now("interval_job")
        await asyncio.sleep(0.05)

        with self.assertRaises(RuntimeError):
            await service.run_job_now("interval_job")

        base_model.wait_event.set()
        await asyncio.sleep(0.05)
        await service.shutdown()

    async def test_manual_run_conflicts_when_external_automation_busy(self):
        with open(heartbeat._CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(
                """
enabled: true
tasks:
  - id: interval_job
    cron: "*/30"
    gorev: "Refresh"
"""
            )

        service = heartbeat.HeartbeatService(DummyBaseModel())
        await service.start()

        acquired, _snapshot = await automation_runtime.try_acquire_automation(
            "panel",
            job_id="panel-test",
            label="Panel test islemi",
            source="test",
        )
        self.assertTrue(acquired)

        with self.assertRaises(RuntimeError):
            await service.run_job_now("interval_job")

        await automation_runtime.release_automation("panel", job_id="panel-test")
        await service.shutdown()


class AutomationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await automation_runtime.reset_automation_runtime()

    async def asyncTearDown(self):
        await automation_runtime.reset_automation_runtime()

    async def test_coordinator_acquire_release_cycle(self):
        acquired, snapshot = await automation_runtime.try_acquire_automation(
            "heartbeat",
            job_id="job-1",
            label="Deneme",
            source="test",
        )
        self.assertTrue(acquired)
        self.assertTrue(snapshot["busy"])
        self.assertEqual(snapshot["owner"], "heartbeat")

        acquired2, snapshot2 = await automation_runtime.try_acquire_automation(
            "panel",
            job_id="job-2",
            label="Panel",
            source="test",
        )
        self.assertFalse(acquired2)
        self.assertEqual(snapshot2["owner"], "heartbeat")

        released = await automation_runtime.release_automation("heartbeat", job_id="job-1")
        self.assertTrue(released)
        self.assertFalse(automation_runtime.get_automation_snapshot()["busy"])


class SocialWorkflowLogicTests(unittest.TestCase):
    def test_submission_snapshot_pending_when_text_not_verified(self):
        result = social_browser_workflow._assess_submission_snapshot(
            {
                "body_text": "Akista baska seyler var",
                "composer_present": True,
                "composer_text": "Merhaba dunya",
                "alert_texts": [],
                "target_visible": False,
            },
            "Merhaba dunya",
        )

        self.assertEqual(result["verification_state"], "pending_verify")
        self.assertFalse(result["verified"])

    def test_submission_snapshot_errors_on_login_wall(self):
        result = social_browser_workflow._assess_submission_snapshot(
            {
                "body_text": "Log in to X and join the conversation",
                "composer_present": False,
                "composer_text": "",
                "alert_texts": [],
                "target_visible": False,
            },
            "Merhaba dunya",
        )

        self.assertEqual(result["verification_state"], "error")
        self.assertIn("login", result["error"].lower())

    def test_parse_thread_parts_supports_dash_separator_lines_with_spaces(self):
        parts = social_browser_workflow._parse_thread_parts("ilk parca\n  ---  \nikinci parca\n---\nucuncu parca")
        self.assertEqual(parts, ["ilk parca", "ikinci parca", "ucuncu parca"])

    def test_coerce_limit_accepts_string_values(self):
        self.assertEqual(social_browser_workflow._coerce_limit("10", default=5, minimum=1, maximum=30), 10)
        self.assertEqual(social_browser_workflow._coerce_limit("abc", default=5, minimum=1, maximum=30), 5)

    def test_mark_queue_item_maps_completed_alias_to_sent(self):
        with mock.patch.object(social_browser_workflow, "update_queue_item", return_value={"status": "sent"}) as update_mock:
            result = social_browser_workflow.mark_queue_item("x-123", "completed", note="tamam")

        update_mock.assert_called_once_with("x-123", status="sent", note="tamam")
        self.assertEqual(result["status"], "sent")

    def test_non_bmp_detector_finds_emoji(self):
        self.assertFalse(social_browser_workflow._contains_non_bmp("duz metin"))
        self.assertTrue(social_browser_workflow._contains_non_bmp("duz metin 🤖"))

    def test_notification_candidate_filters_system_card(self):
        result = social_browser_workflow._classify_notification_candidate(
            {
                "handle": "someone",
                "text": "Guzel post",
                "article_text": "someone liked your post",
                "reply_available": True,
            },
            own_handle="myaccount",
        )

        self.assertEqual(result["candidate_type"], "ignore")

    def test_notification_candidate_marks_reply_marker(self):
        result = social_browser_workflow._classify_notification_candidate(
            {
                "handle": "someone",
                "text": "Buna katiliyorum",
                "article_text": "someone replied to you Buna katiliyorum",
                "reply_available": True,
            },
            own_handle="myaccount",
        )

        self.assertEqual(result["candidate_type"], "reply")
        self.assertGreaterEqual(result["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
