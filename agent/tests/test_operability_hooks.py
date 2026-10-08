"""Telemetri kancalari: BaseModel, SubModel ve heartbeat gercekten dogru run'a dogru veriyi yaziyor mu?"""

import _env  # noqa: F401  (her seyden once)

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

import _support as S


def completion(text, usage=None):
    """OpenAI uyumlu bir chat.completions cevabi."""
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def usage(prompt, completion_tokens):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion_tokens, total_tokens=prompt + completion_tokens)


class FakeCompletions:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(*responses):
    completions = FakeCompletions(*responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class HookCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        manager = S.fresh_telemetry()
        self.t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)


class BaseModelHookTests(HookCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from MarketingApp.llms import BaseModel

        self.model = BaseModel(api_key="test-key", model="test-model")

    async def test_log_message_is_persisted_and_survives_the_memory_ring_buffer(self):
        for i in range(150):  # bellek listesi 100'de kesiyor, kalici kayit kesmemeli
            self.model.log_message("sistem", f"satir {i}")
        self.assertEqual(len(self.model.logs), 100)
        messages = [e["message"] for e in self.t.recent_events(500)]
        self.assertEqual(len(messages), 150)
        self.assertEqual((messages[0], messages[-1]), ("satir 0", "satir 149"))

    async def test_text_query_records_a_run_with_usage_and_summary(self):
        client, completions = fake_client(completion("Merhaba dunya", usage(1200, 30)))
        self.model._client = client

        result = await self.model.text_query("Selam, bugun ne paylasalim?")

        self.assertEqual(result[1], "Merhaba dunya")
        run = self.t.recent_runs(1)[0]
        self.assertEqual((run["status"], run["source"], run["summary"]), ("ok", "direct", "Merhaba dunya"))
        self.assertEqual(run["label"], "Selam, bugun ne paylasalim?")
        self.assertEqual((run["llm_calls"], run["prompt_tokens"], run["completion_tokens"], run["total_tokens"]), (1, 1200, 30, 1230))
        rows = self.t.usage_summary(group_by="agent")["rows"]
        self.assertEqual([(r["key"], r["total"]) for r in rows], [("base", 1230)])
        self.assertEqual(self.t.usage_summary(group_by="model")["rows"][0]["key"], "test-model")

    async def test_source_comes_from_the_channel_context(self):
        client, _ = fake_client(completion("ok", usage(1, 1)))
        self.model._client = client
        self.t.set_source("discord")
        await self.model.text_query("x")
        self.assertEqual(self.t.recent_runs(1)[0]["source"], "discord")

    async def test_an_explicit_outer_run_owns_the_query(self):
        client, _ = fake_client(completion("ok", usage(10, 5)))
        self.model._client = client
        with self.t.run_scope("heartbeat", "Sabah post", job_id="post_slot") as run:
            await self.model.text_query("[HEARTBEAT OTOMATIK GOREV] ...")
        runs = self.t.recent_runs(10)
        self.assertEqual(len(runs), 1)  # ic ice cagri ikinci bir run acmamali
        self.assertEqual((runs[0]["source"], runs[0]["job_id"], runs[0]["total_tokens"]), ("heartbeat", "post_slot", 15))

    async def test_provider_failure_marks_the_run_as_error_and_still_raises(self):
        client, _ = fake_client(RuntimeError("Error code: 500"))
        self.model._client = client
        with self.assertRaises(RuntimeError):
            await self.model.text_query("x")
        run = self.t.recent_runs(1)[0]
        self.assertEqual(run["status"], "error")
        self.assertIn("500", run["error"])

    async def test_a_provider_without_usage_data_still_counts_the_call(self):
        client, _ = fake_client(completion("ok", usage=None))
        self.model._client = client
        await self.model.text_query("x")
        run = self.t.recent_runs(1)[0]
        self.assertEqual((run["llm_calls"], run["total_tokens"]), (1, 0))
        self.assertEqual(self.t.usage_summary()["totals"]["unknown_calls"], 1)

    async def test_audio_query_is_recorded_through_text_query_only_once(self):
        client, _ = fake_client(completion("ok", usage(1, 1)))
        self.model._client = client
        from unittest import mock

        with mock.patch("MarketingApp.llms.BaseModel._process_stt", return_value="sesli mesaj"):
            await self.model.audio_query(b"\x00\x00")
        self.assertEqual(len(self.t.recent_runs(10)), 1)


class SubModelHookTests(HookCase):
    def _submodel(self, client):
        from MarketingApp.llms.SubModels.base import SubModel

        class Probe(SubModel):
            async def run(self, gorev):
                return "x"

        sub = Probe(name="probe_agent", description="d", model_id="probe-model", api_key="k")
        sub._client = client
        return sub

    async def test_completion_usage_is_recorded_under_the_agent_name(self):
        client, _ = fake_client(completion("ok", usage(700, 70)))
        with self.t.run_scope("terminal", "x"):
            await self._submodel(client)._create_chat_completion_with_failover({"model": "probe-model", "messages": []})
        rows = self.t.usage_summary(group_by="agent")["rows"]
        self.assertEqual([(r["key"], r["total"]) for r in rows], [("probe_agent", 770)])
        self.assertEqual(self.t.usage_summary(group_by="model")["rows"][0]["key"], "probe-model")

    async def test_failed_call_records_no_usage_and_raises(self):
        client, _ = fake_client(ValueError("nope"))
        with self.assertRaises(ValueError):
            await self._submodel(client)._create_chat_completion_with_failover({"messages": []})
        self.assertEqual(self.t.usage_summary()["totals"]["calls"], 0)

    async def test_base_and_submodel_usage_land_in_the_same_run(self):
        client, _ = fake_client(completion("ok", usage(10, 1)))
        sub = self._submodel(fake_client(completion("ok", usage(20, 2)))[0])
        with self.t.run_scope("heartbeat", "tur"):
            await sub._create_chat_completion_with_failover({"messages": []})
            from MarketingApp.llms import BaseModel

            base = BaseModel(api_key="k", model="m")
            base._client = client
            await base.text_query("x")
        run = self.t.recent_runs(1)[0]
        self.assertEqual((run["llm_calls"], run["total_tokens"]), (2, 33))


class GeminiLiveAgentWiringTests(unittest.TestCase):
    """Live ajanlari OpenAI yolundan gecmez; tracker'in yerinde oldugunu kaynak duzeyinde kilitler."""

    def test_every_live_agent_observes_messages_and_flushes_in_finally(self):
        import inspect
        import re

        from MarketingApp.llms.SubModels import arastirma_agent, sistem_agent, vlm_agent

        for module in (arastirma_agent, sistem_agent, vlm_agent):
            source = inspect.getsource(module)
            name = module.__name__.rsplit(".", 1)[-1]
            self.assertIn("LiveUsageTracker(self.name, self.model_id)", source, name)
            self.assertIn("tracker.observe(message)", source, name)
            self.assertRegex(source, r"finally:\s*\n\s*tracker\.flush\(\)", name)
            # observe, receive dongusunun ICINDE olmali
            self.assertRegex(source, r"async for message in session\.receive\(\):\s*\n\s*tracker\.observe\(message\)", name)


class HeartbeatHistoryTests(HookCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from MarketingApp.environments import automation_runtime, heartbeat

        self.heartbeat = heartbeat
        await automation_runtime.reset_automation_runtime()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        runtime = os.path.join(self.temp.name, "runtime")
        self.saved = (heartbeat._CONFIG_PATH, heartbeat._RUNTIME_DIR, heartbeat._JOBSTORE_PATH, heartbeat._RUNTIME_DB_PATH)
        heartbeat._CONFIG_PATH = os.path.join(self.temp.name, "heartbeat_config.yaml")
        heartbeat._RUNTIME_DIR = runtime
        heartbeat._JOBSTORE_PATH = os.path.join(runtime, "jobs.sqlite")
        heartbeat._RUNTIME_DB_PATH = os.path.join(runtime, "runtime.sqlite")
        self.addCleanup(lambda: setattr_all(heartbeat, self.saved))
        with open(heartbeat._CONFIG_PATH, "w", encoding="utf-8") as handle:
            handle.write('enabled: true\ntasks:\n  - id: interval_job\n    name: Yenileme\n    cron: "*/30"\n    gorev: "Refresh"\n')

    def _service(self, base):
        return self.heartbeat.HeartbeatService(base)

    async def test_successful_job_writes_a_history_row_with_output_summary_and_usage(self):
        t = self.t

        class Base:
            async def text_query(self, user_text, **kwargs):
                t.record_usage("base", "m", usage(100, 20))
                await kwargs["on_cevap_metni"]("Post yayinlandi: test")
                return b"", "Post yayinlandi: test", [], ["Post yayinlandi: test"]

        service = self._service(Base())
        await service.start()
        await service.run_job_now("interval_job")
        await asyncio.sleep(0.3)
        await service.shutdown()

        runs = self.t.recent_runs(10, job_id="interval_job")
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual((run["status"], run["source"], run["label"]), ("ok", "heartbeat", "Yenileme"))
        self.assertIn("Post yayinlandi", run["summary"])
        self.assertEqual((run["llm_calls"], run["total_tokens"]), (1, 120))

    async def test_failing_job_is_recorded_as_error_with_the_message(self):
        class Base:
            async def text_query(self, *args, **kwargs):
                raise ValueError("model cevap vermedi")

        service = self._service(Base())
        await service.start()
        await service.run_job_now("interval_job")
        await asyncio.sleep(0.3)
        await service.shutdown()

        run = self.t.recent_runs(1, job_id="interval_job")[0]
        self.assertEqual(run["status"], "error")
        self.assertIn("model cevap vermedi", run["error"])

    async def test_history_keeps_every_run_unlike_the_single_row_job_runtime_table(self):
        class Base:
            async def text_query(self, *args, **kwargs):
                return b"", "tamam", [], ["tamam"]

        service = self._service(Base())
        await service.start()
        for _ in range(3):
            await service.run_job_now("interval_job")
            await asyncio.sleep(0.2)
        await service.shutdown()
        self.assertEqual(len(self.t.recent_runs(20, job_id="interval_job")), 3)

    async def test_job_skipped_because_automation_is_busy_is_still_recorded(self):
        from MarketingApp.environments import automation_runtime

        class Base:
            async def text_query(self, *args, **kwargs):
                return b"", "tamam", [], ["tamam"]

        service = self._service(Base())
        await service.start()
        await automation_runtime.try_acquire_automation("terminal", job_id="t1", label="sohbet", source="terminal")
        # run_job_now bu durumda RuntimeError verir; zamanlayici yolunu dogrudan _run_job ile simule et
        result = await service._run_job("interval_job", trigger_reason="schedule", notify_telegram=False)
        await automation_runtime.release_automation("terminal", job_id="t1")
        await service.shutdown()

        self.assertEqual(result["status"], "skipped")
        run = self.t.recent_runs(1, job_id="interval_job")[0]
        self.assertEqual(run["status"], "skipped")
        self.assertIn("terminal", run["error"])

    async def test_retry_attempts_are_logged_as_events(self):
        attempts = {"n": 0}

        class Base:
            async def text_query(self, *args, **kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("Error code: 503 service unavailable")
                return b"", "tamam", [], ["tamam"]

        from unittest import mock

        service = self._service(Base())
        await service.start()
        with mock.patch.object(self.heartbeat, "_RETRY_DELAYS_SECONDS", (0, 0, 0)):
            await service._run_job("interval_job", trigger_reason="manual", notify_telegram=False)
        await service.shutdown()

        events = [e["message"] for e in self.t.recent_events(50, type_="heartbeat")]
        self.assertTrue(any("gecici model hatasi" in m and "deneme 1/3" in m for m in events), events)
        run = self.t.recent_runs(1, job_id="interval_job")[0]
        self.assertEqual(run["status"], "ok")  # ikinci deneme basarili: tek run, iki deneme


def setattr_all(module, saved):
    module._CONFIG_PATH, module._RUNTIME_DIR, module._JOBSTORE_PATH, module._RUNTIME_DB_PATH = saved


if __name__ == "__main__":
    unittest.main()
