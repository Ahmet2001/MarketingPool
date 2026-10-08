import _env  # noqa: F401  (her seyden once)

import asyncio
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import _support as S
from _env import CONFIG_DIR


class TelemetryCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        manager = S.fresh_telemetry()
        self.t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.addCleanup((CONFIG_DIR / "pricing.yaml").unlink, missing_ok=True)


class RunScopeTests(TelemetryCase):
    async def test_ok_run_records_summary_source_job_and_duration(self):
        with self.t.run_scope("terminal", "merhaba", job_id="j1", detail="chat") as run:
            run.set_summary("cevap")
        row = self.t.recent_runs(1)[0]
        self.assertEqual((row["status"], row["source"], row["job_id"], row["summary"]), ("ok", "terminal", "j1", "cevap"))
        self.assertIsNotNone(row["finished_at"])
        self.assertGreaterEqual(row["duration_ms"], 0)

    async def test_exception_marks_error_and_propagates(self):
        with self.assertRaises(RuntimeError):
            with self.t.run_scope("terminal", "x"):
                raise RuntimeError("patladi")
        row = self.t.recent_runs(1)[0]
        self.assertEqual((row["status"], row["error"]), ("error", "patladi"))

    async def test_handle_fail_and_skip_mark_status_without_raising(self):
        with self.t.run_scope("terminal", "a") as run:
            run.fail("model hatasi")
        with self.t.run_scope("terminal", "b") as run:
            run.skip("baska job calisiyor")
        by_label = {r["label"]: r for r in self.t.recent_runs(10)}
        self.assertEqual((by_label["a"]["status"], by_label["a"]["error"]), ("error", "model hatasi"))
        self.assertEqual(by_label["b"]["status"], "skipped")

    async def test_cancellation_is_recorded_as_cancelled(self):
        async def work():
            with self.t.run_scope("heartbeat", "uzun is"):
                await asyncio.sleep(30)

        task = asyncio.create_task(work())
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.t.recent_runs(1)[0]["status"], "cancelled")

    async def test_nested_scope_joins_the_parent_run(self):
        with self.t.run_scope("heartbeat", "dis", job_id="j") as outer:
            with self.t.run_scope("direct", "ic") as inner:
                self.assertFalse(inner.owned)
                self.assertEqual(inner.run_id, outer.run_id)
        runs = self.t.recent_runs(10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["source"], "heartbeat")

    async def test_context_is_cleared_after_scope_exit(self):
        with self.t.run_scope("terminal", "x"):
            self.assertIsNotNone(self.t.current_run_id())
        self.assertIsNone(self.t.current_run_id())

    async def test_events_and_usage_attach_to_active_run_across_threads(self):
        with self.t.run_scope("heartbeat", "tur") as run:
            self.t.record_event("sistem", "ana thread")
            await asyncio.to_thread(self.t.record_event, "sistem", "worker thread")
            await asyncio.to_thread(
                self.t.record_usage, "sosyal_medya_agent", "m", SimpleNamespace(prompt_tokens=5, completion_tokens=1, total_tokens=6)
            )
        events = self.t.recent_events(run_id=run.run_id)
        self.assertEqual([e["message"] for e in events], ["ana thread", "worker thread"])
        self.assertEqual(self.t.recent_runs(1)[0]["total_tokens"], 6)

    async def test_startup_recovers_runs_left_running_by_a_crash(self):
        run_id = self.t.start_run("heartbeat", "yarim kaldi")
        self.assertEqual(self.t.recent_runs(1)[0]["status"], "running")
        self.t._initialized_path = None  # yeni process gibi yeniden baslat
        row = self.t.find_runs(run_id)[0]
        self.assertEqual(row["status"], "interrupted")

    async def test_record_run_writes_an_already_finished_run(self):
        self.t.record_run("heartbeat", "Atlanan", status="skipped", job_id="x", error="mesgul")
        row = self.t.recent_runs(1)[0]
        self.assertEqual((row["status"], row["error"], row["job_id"]), ("skipped", "mesgul", "x"))


class UsageTests(TelemetryCase):
    def test_extract_usage_handles_openai_gemini_dict_and_garbage(self):
        ex = self.t._extract_usage
        self.assertEqual(ex(SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12)), (10, 2, 12))
        self.assertEqual(ex(SimpleNamespace(prompt_token_count=7, response_token_count=3, total_token_count=11)), (7, 3, 11))
        self.assertEqual(ex({"prompt_tokens": 4, "completion_tokens": 1}), (4, 1, 5))  # total yoksa toplanir
        self.assertIsNone(ex(None))
        self.assertIsNone(ex(SimpleNamespace(prompt_tokens=None, completion_tokens=None, total_tokens=None)))
        self.assertIsNone(ex(SimpleNamespace(unrelated=1)))

    async def test_call_without_usage_is_counted_but_has_no_tokens(self):
        with self.t.run_scope("terminal", "x"):
            self.t.record_usage("base", "m", None)
        row = self.t.recent_runs(1)[0]
        self.assertEqual((row["llm_calls"], row["total_tokens"]), (1, 0))
        summary = self.t.usage_summary(group_by="agent")
        self.assertEqual(summary["totals"]["unknown_calls"], 1)

    async def test_summary_groupings_and_totals(self):
        u = lambda p, c: SimpleNamespace(prompt_tokens=p, completion_tokens=c, total_tokens=p + c)
        with self.t.run_scope("heartbeat", "a"):
            self.t.record_usage("base", "m1", u(100, 10))
            self.t.record_usage("sosyal", "m2", u(50, 5))
        with self.t.run_scope("telegram", "b"):
            self.t.record_usage("base", "m1", u(20, 2))
        self.t.record_usage("base", "m1", u(1, 1))  # kosu disi

        by_agent = {r["key"]: r for r in self.t.usage_summary(group_by="agent")["rows"]}
        self.assertEqual((by_agent["base"]["calls"], by_agent["base"]["total"]), (3, 134))
        self.assertEqual(by_agent["sosyal"]["total"], 55)

        by_source = {r["key"]: r["total"] for r in self.t.usage_summary(group_by="source")["rows"]}
        self.assertEqual(by_source, {"heartbeat": 165, "telegram": 22, "(kosu disi)": 2})

        by_model = {r["key"]: r["calls"] for r in self.t.usage_summary(group_by="model")["rows"]}
        self.assertEqual(by_model, {"m1": 3, "m2": 1})

        day = self.t.usage_summary(group_by="day")["rows"]
        self.assertEqual(len(day), 1)
        self.assertEqual(day[0]["key"], datetime.now().strftime("%Y-%m-%d"))

        totals = self.t.usage_summary(group_by="run")["totals"]
        self.assertEqual((totals["calls"], totals["total"]), (4, 189))

    async def test_since_excludes_older_rows_and_bad_group_is_rejected(self):
        self.t.record_usage("base", "m", SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))
        future = self.t.parse_since("2099-01-01")
        self.assertEqual(self.t.usage_summary(future)["rows"], [])
        with self.assertRaises(ValueError):
            self.t.usage_summary(group_by="nonsense")

    async def test_live_tracker_writes_one_row_with_the_last_metadata(self):
        tracker = self.t.LiveUsageTracker("arastirma_agent", "gemini-live")
        for total in (10, 40, 90):  # kumulatif senaryo: en son deger dogru toplam
            tracker.observe(SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=total - 5, response_token_count=5, total_token_count=total)))
        tracker.observe(SimpleNamespace(usage_metadata=None))  # metadata'siz mesaj sonucu bozmamali
        with self.t.run_scope("terminal", "x"):
            tracker.flush()
        rows = self.t.usage_summary(group_by="agent")["rows"]
        self.assertEqual([(r["key"], r["calls"], r["total"]) for r in rows], [("arastirma_agent", 1, 90)])

    async def test_live_tracker_counts_the_call_even_without_metadata(self):
        tracker = self.t.LiveUsageTracker("vlm_agent", "gemini-live")
        tracker.observe(SimpleNamespace(usage_metadata=None))
        tracker.flush()
        totals = self.t.usage_summary(group_by="agent")["totals"]
        self.assertEqual((totals["calls"], totals["unknown_calls"], totals["total"]), (1, 1, 0))


class PricingTests(TelemetryCase):
    def _write_pricing(self, text):
        (CONFIG_DIR / "pricing.yaml").write_text(text, encoding="utf-8")

    async def test_cost_only_for_priced_models_and_reasoning_tokens_bill_as_output(self):
        self._write_pricing("models:\n  priced-model: {input: 1.0, output: 10.0}\n")
        # completion 100 gorunuyor ama total-prompt = 500: 400 dusunme tokeni de cikti fiyatindan
        self.t.record_usage("a", "priced-model", SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=100, total_tokens=1_000_500))
        self.t.record_usage("b", "unpriced-model", SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20))
        report = self.t.usage_summary(group_by="agent")
        rows = {r["key"]: r for r in report["rows"]}
        self.assertTrue(report["pricing_loaded"])
        self.assertAlmostEqual(rows["a"]["cost"], 1.0 + 500 / 1_000_000 * 10.0, places=6)
        self.assertFalse(rows["b"]["priced"])
        self.assertEqual(report["unpriced_models"], ["unpriced-model"])

    async def test_no_pricing_file_means_no_cost_and_never_invents_prices(self):
        self.t.record_usage("a", "m", SimpleNamespace(prompt_tokens=10**6, completion_tokens=10**6, total_tokens=2 * 10**6))
        report = self.t.usage_summary()
        self.assertFalse(report["pricing_loaded"])
        self.assertEqual(report["totals"]["cost"], 0.0)

    async def test_malformed_pricing_entries_are_skipped(self):
        self._write_pricing("models:\n  good: {input: 1, output: 2}\n  bad: {input: x}\n  worse: 5\n")
        self.assertEqual(list(self.t.load_pricing()), ["good"])
        self._write_pricing(": : not yaml [")
        self.assertEqual(self.t.load_pricing(), {})


class ConcurrencyTests(TelemetryCase):
    async def test_many_threads_writing_at_once_lose_nothing_and_raise_nothing(self):
        def burst(worker):
            for i in range(50):
                self.t.record_event("sistem", f"w{worker}-{i}")
                self.t.record_usage("a", "m", None)

        await asyncio.gather(*(asyncio.to_thread(burst, w) for w in range(8)))
        health = self.t.health()
        self.assertTrue(health["ok"], health["last_error"])
        self.assertEqual((health["events"], health["usage_rows"]), (400, 400))

    async def test_a_broken_connection_recovers_on_the_next_call(self):
        self.t.record_event("sistem", "once")
        self.t._conn.close()  # baglanti disaridan olurse (disk hatasi, iptal) sistem toparlanmali
        self.t.record_event("sistem", "kayip olabilir")
        self.t.record_event("sistem", "sonra")
        self.assertIn("sonra", [e["message"] for e in self.t.recent_events()])


class QueryTests(TelemetryCase):
    async def test_event_filters_and_like_wildcards_are_escaped(self):
        self.t.record_event("sistem", "100% tamam")
        self.t.record_event("sistem", "abc")
        self.t.record_event("hata", "a_b x")
        messages = lambda **kw: [e["message"] for e in self.t.recent_events(**kw)]
        self.assertEqual(messages(grep="%"), ["100% tamam"])
        self.assertEqual(messages(grep="_"), ["a_b x"])
        self.assertEqual(messages(type_="hata"), ["a_b x"])
        self.assertEqual(messages(limit=2), ["abc", "a_b x"])  # en yeni 2, kronolojik

    async def test_long_messages_are_clipped(self):
        self.t.record_event("sistem", "x" * 5000)
        self.assertLessEqual(len(self.t.recent_events(1)[0]["message"]), 2000)

    async def test_recent_runs_filters(self):
        self.t.record_run("heartbeat", "a", status="ok", job_id="j1")
        self.t.record_run("heartbeat", "b", status="error", job_id="j2")
        self.t.record_run("telegram", "c", status="ok")
        self.assertEqual([r["label"] for r in self.t.recent_runs(source="heartbeat", status="error")], ["b"])
        self.assertEqual([r["label"] for r in self.t.recent_runs(job_id="j1")], ["a"])
        self.assertEqual(len(self.t.recent_runs(limit=2)), 2)

    async def test_find_runs_by_prefix_and_garbage_input(self):
        run_id = self.t.start_run("terminal", "x")
        self.assertEqual(self.t.find_runs(run_id[:5])[0]["run_id"], run_id)
        self.assertEqual(self.t.find_runs("zzzz"), [])  # hex olmayan karakterler atilir -> bos
        self.assertEqual(self.t.find_runs("' OR 1=1 --"), [])


class TimeParsingTests(TelemetryCase):
    def _parse(self, value):
        return datetime.strptime(self.t.parse_since(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def test_relative_values(self):
        now = datetime.now(timezone.utc)
        for text, delta in (("30m", timedelta(minutes=30)), ("2h", timedelta(hours=2)), ("7d", timedelta(days=7)), ("1w", timedelta(weeks=1))):
            self.assertLess(abs((now - delta) - self._parse(text)), timedelta(seconds=5), text)

    def test_local_dates_are_interpreted_as_local_time(self):
        expected = datetime(2026, 9, 1).astimezone().astimezone(timezone.utc)
        self.assertEqual(self._parse("2026-09-01"), expected)
        expected = datetime(2026, 9, 1, 8, 30).astimezone().astimezone(timezone.utc)
        self.assertEqual(self._parse("2026-09-01 08:30"), expected)

    def test_today_is_local_midnight(self):
        local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        self.assertEqual(self._parse("today"), local_midnight.astimezone(timezone.utc))

    def test_empty_is_none_and_garbage_raises(self):
        self.assertIsNone(self.t.parse_since(""))
        self.assertIsNone(self.t.parse_since(None))
        for bad in ("dun", "24 saat", "2026-13-40", "-5h"):
            with self.assertRaises(ValueError, msg=bad):
                self.t.parse_since(bad)


class RetentionAndHealthTests(TelemetryCase):
    def _insert_old(self, days):
        self.t.health()  # semayi olustur (dogrudan sqlite acmadan once tablolar var olmali)
        stamp = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.t.DB_PATH) as conn:
            conn.execute("INSERT INTO events (ts, type, message) VALUES (?, 'sistem', 'eski')", (stamp,))
            conn.execute("INSERT INTO llm_usage (ts, agent, model, total_tokens) VALUES (?, 'a', 'm', 1)", (stamp,))
            conn.execute("INSERT INTO runs (run_id, source, started_at, status) VALUES ('old1', 'x', ?, 'ok')", (stamp,))
            conn.execute("INSERT INTO runs (run_id, source, started_at, status) VALUES ('stuck', 'x', ?, 'running')", (stamp,))

    async def test_prune_removes_only_expired_rows_and_keeps_running_ones(self):
        self.t.record_event("sistem", "taze")
        self._insert_old(days=40)
        removed = self.t.prune(days=30)
        self.assertEqual((removed["events"], removed["llm_usage"], removed["runs"]), (1, 1, 1))
        self.assertEqual([e["message"] for e in self.t.recent_events()], ["taze"])
        self.assertEqual([r["run_id"] for r in self.t.recent_runs()], ["stuck"])

    async def test_zero_or_negative_retention_keeps_everything(self):
        self._insert_old(days=400)
        self.assertEqual(self.t.prune(days=0), {})
        self.assertEqual(len(self.t.recent_events()), 1)

    async def test_retention_reads_the_environment(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"ETHGENT_TELEMETRY_RETENTION_DAYS": "7"}):
            self.assertEqual(self.t.retention_days(), 7)
        with mock.patch.dict(os.environ, {"ETHGENT_TELEMETRY_RETENTION_DAYS": "abc"}):
            self.assertEqual(self.t.retention_days(), 30)

    async def test_health_reports_counts(self):
        self.t.record_event("sistem", "x")
        with self.t.run_scope("terminal", "y"):
            pass
        health = self.t.health()
        self.assertTrue(health["ok"])
        self.assertEqual((health["events"], health["runs"]), (1, 1))

    async def test_writes_never_raise_when_the_store_is_unusable(self):
        self.t.DB_PATH = "/proc/nonexistent-dir/telemetry.sqlite"
        self.t._initialized_path = None
        # hicbiri exception firlatmamali: gozlemlenebilirlik is akisini bozmamali
        self.t.record_event("sistem", "x")
        self.t.record_usage("a", "m", None)
        self.t.finish_run(None, "ok")
        with self.t.run_scope("terminal", "y") as run:
            run.set_summary("z")
        health = self.t.health()
        self.assertFalse(health["ok"])
        self.assertTrue(health["last_error"])


if __name__ == "__main__":
    unittest.main()
