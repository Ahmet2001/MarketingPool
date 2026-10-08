"""Bot yetkilendirmesi ve uzaktan yonetim komutlari (Telegram / Discord).

Bu testler guvenlik sinirini kilitler: yetkisiz kullanici hicbir sey calistiramaz, admin bile
uzaktan kod yukleyemez, yikici komutlar acik onay olmadan calismaz.
"""

import _env  # noqa: F401  (her seyden once)

import asyncio
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

import _support as S
from _env import ROOT, WORKSPACE_DIR
from MarketingApp.environments import access, remote_commands

_ENV_KEYS = ("TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ADMIN_IDS", "DISCORD_ALLOWED_USER_IDS", "DISCORD_ADMIN_IDS")


@contextmanager
def env(**values):
    """Yalnizca verilen erisim degiskenleri tanimli olsun (digerleri silinir)."""
    with mock.patch.dict(os.environ, {}, clear=False):
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({key: str(value) for key, value in values.items()})
        yield


class AccessTests(unittest.TestCase):
    def test_id_lists_accept_commas_spaces_and_semicolons_and_ignore_garbage(self):
        with env(TELEGRAM_ALLOWED_USER_IDS="1, 2;3  4,abc,,5"):
            self.assertEqual(access.allowed_ids("telegram"), {1, 2, 3, 4, 5})
            self.assertTrue(any("abc" in w for w in access.startup_warnings("telegram")))

    def test_without_an_allowlist_chat_stays_open_for_backward_compatibility(self):
        with env():
            self.assertTrue(access.is_open("telegram"))
            self.assertTrue(access.is_allowed("telegram", 123))
            self.assertTrue(access.is_allowed("telegram", None))

    def test_with_an_allowlist_only_members_and_admins_may_chat(self):
        with env(TELEGRAM_ALLOWED_USER_IDS="10,11", TELEGRAM_ADMIN_IDS="99"):
            self.assertFalse(access.is_open("telegram"))
            self.assertTrue(access.is_allowed("telegram", 10))
            self.assertTrue(access.is_allowed("telegram", 99))  # admin allowlist'te olmasa da sohbet edebilir
            self.assertFalse(access.is_allowed("telegram", 12))
            self.assertFalse(access.is_allowed("telegram", None))  # kullanicisiz update (kanal postu vb.) reddedilir

    def test_admin_is_never_implied_by_the_chat_allowlist(self):
        with env(TELEGRAM_ALLOWED_USER_IDS="10"):
            self.assertFalse(access.is_admin("telegram", 10))
        with env():
            self.assertFalse(access.is_admin("telegram", 10))
            self.assertFalse(access.is_admin("telegram", None))

    def test_admin_lists_do_not_close_chat(self):
        with env(TELEGRAM_ADMIN_IDS="99"):
            self.assertTrue(access.is_allowed("telegram", 5))

    def test_channels_are_independent(self):
        with env(TELEGRAM_ADMIN_IDS="1", DISCORD_ADMIN_IDS="2"):
            self.assertTrue(access.is_admin("telegram", 1))
            self.assertFalse(access.is_admin("discord", 1))
            self.assertTrue(access.is_admin("discord", 2))
        with self.assertRaises(ValueError):
            access.is_admin("whatsapp", 1)

    def test_startup_warnings_describe_the_exposure(self):
        with env():
            text = " ".join(access.startup_warnings("discord"))
            self.assertIn("HERKESE ACIK", text)
            self.assertIn("KAPALI", text)
        with env(DISCORD_ALLOWED_USER_IDS="1", DISCORD_ADMIN_IDS="1"):
            self.assertEqual(access.startup_warnings("discord"), [])

    def test_the_environment_is_read_on_every_call(self):
        with env(TELEGRAM_ADMIN_IDS="1"):
            self.assertTrue(access.is_admin("telegram", 1))
        with env():
            self.assertFalse(access.is_admin("telegram", 1))


class RemoteAllowlistTests(unittest.TestCase):
    def check(self, line):
        import shlex

        return remote_commands.check_allowed(shlex.split(line))

    def test_management_and_read_only_commands_are_allowed(self):
        for line in (
            "/agents", "/agent sosyal_medya_agent off", "/agent x toggle", "/agent list", "/agent show x",
            "/agent create x --tools a,b", "/agent edit x --add-tools a", "/agent copy a b", '/agent test a "gorev"',
            "/agent delete x --yes", "/tools --risk high", "/tool web_arama off", "/tool list", "/tool show x",
            "/errors", "/logs 5", "/runs", "/run abc123", "/usage --by model", "/heartbeat",
            '/heartbeat add --cron "*/5" --gorev "x"', "/heartbeat remove x --yes", "/heartbeat log", "/reload",
        ):
            self.assertIsNone(self.check(line), line)

    def test_remote_code_loading_is_blocked_even_for_admins(self):
        for line in ("/tool create x --file f.py", '/tool create x --code "def x(): pass"', "/tool create --file f.py --all",
                     "/tool edit x --code y", "/tool delete x --yes", "/tool show x --code"):
            self.assertIn("uzaktan", self.check(line), line)

    def test_filesystem_and_source_writing_commands_are_blocked(self):
        for line in ("/agent pack install /tmp/x", "/agent pack export x --out /tmp/y", "/agent pack list",
                     "/agent create x --builtin", "/agent create --tools a --builtin y"):
            self.assertIsNotNone(self.check(line), line)

    def test_destructive_commands_need_an_explicit_yes(self):
        self.assertIn("--yes", self.check("/agent delete x"))
        self.assertIn("--yes", self.check("/heartbeat remove x"))
        self.assertIsNone(self.check("/agent delete x --yes"))

    def test_matching_is_case_insensitive(self):
        self.assertIsNotNone(self.check("/TOOL CREATE x"))
        self.assertIsNotNone(self.check("/Agent Pack install /x"))
        self.assertIsNotNone(self.check("/agent create x --BUILTIN"))
        self.assertIsNone(self.check("/AGENT delete x --YES"))

    def test_terminal_only_and_unknown_commands_are_refused(self):
        for line in ("/exit", "/quit", "/clear", "/history", "/status", "/bash", "/agentx create"):
            self.assertIn("uzaktan calistirilamaz", self.check(line), line)


class NormalizeTests(unittest.TestCase):
    def test_undoes_smart_punctuation_from_phone_keyboards(self):
        self.assertEqual(remote_commands.normalize_line("/agent create x —model y"), "/agent create x --model y")
        self.assertEqual(remote_commands.normalize_line("/agent create x –tools a"), "/agent create x --tools a")
        self.assertEqual(remote_commands.normalize_line("/agent create x --desc “Selam dunya”"), '/agent create x --desc "Selam dunya"')
        self.assertEqual(remote_commands.normalize_line("/agent create x --desc ‘a’"), "/agent create x --desc 'a'")

    def test_only_dashes_before_a_letter_are_touched(self):
        self.assertEqual(remote_commands.normalize_line('/agent create x --desc "a — b"'), '/agent create x --desc "a — b"')

    def test_group_chat_bot_suffix_is_removed(self):
        self.assertEqual(remote_commands.normalize_line("/agent@EthgentBot create x"), "/agent create x")
        self.assertEqual(remote_commands.normalize_line("  /usage@Ethgent_Bot --by model "), "/usage --by model")

    def test_a_dash_smuggled_flag_still_hits_the_allowlist(self):
        import shlex

        line = remote_commands.normalize_line("/agent create x —builtin")
        self.assertIsNotNone(remote_commands.check_allowed(shlex.split(line)))


class SplitMessageTests(unittest.TestCase):
    def test_chunks_respect_the_limit_and_reassemble(self):
        text = "\n".join(f"satir {i}" * 5 for i in range(200))
        chunks = remote_commands.split_message(text, 500)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual("".join(chunks), text)

    def test_a_single_overlong_line_is_hard_split(self):
        chunks = remote_commands.split_message("x" * 1050, 400)
        self.assertEqual([len(c) for c in chunks], [400, 400, 250])

    def test_lines_are_kept_whole_when_possible(self):
        chunks = remote_commands.split_message("aaaa\nbbbb\ncccc\n", 10)
        self.assertEqual(chunks, ["aaaa\nbbbb\n", "cccc\n"])

    def test_empty_input_yields_one_empty_chunk(self):
        self.assertEqual(remote_commands.split_message("", 100), [""])


class RunRemoteCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from MarketingApp.environments import automation_runtime

        S.reset_state()
        await automation_runtime.reset_automation_runtime()
        self.addCleanup(S.patch_model_env())
        manager = S.fresh_telemetry()
        self.t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.base = S.FakeBase()

    async def run_remote(self, line, channel="telegram", actor=42):
        return await remote_commands.run_remote_command(self.base, line, channel=channel, actor=actor)

    def _audit(self):
        return [e["message"] for e in self.t.recent_events(50, type_="remote")]

    async def test_allowed_command_runs_and_returns_plain_text(self):
        out = await self.run_remote("/errors")
        self.assertIn("Config hatalari (0)", out)
        self.assertNotIn("\x1b[", out)  # renk kodu yok: sohbet uygulamalari gosteremez

    async def test_every_execution_and_refusal_is_audited_with_channel_and_actor(self):
        await self.run_remote("/errors", channel="discord", actor=777)
        await self.run_remote("/tool create x --code y", channel="discord", actor=777)
        audit = self._audit()
        self.assertTrue(any("discord:777 calistirdi: /errors" in m for m in audit), audit)
        self.assertTrue(any("discord:777 REDDEDILDI" in m and "/tool create" in m for m in audit), audit)

    async def test_blocked_tool_creation_really_does_nothing(self):
        out = await self.run_remote('/tool create arka_kapi --code "def arka_kapi():\n    return 1" --desc x')
        self.assertIn("⛔", out)
        self.assertIsNone(next((t for t in __import__("MarketingApp.llms.agent_studio", fromlist=["x"]).load_custom_tools_config()["custom_tools"]
                                if t["name"] == "arka_kapi"), None))
        self.assertFalse((WORKSPACE_DIR / "custom_tools" / "arka_kapi.py").exists())

    async def test_delete_never_prompts_it_is_refused_without_yes_and_runs_with_it(self):
        await self.run_remote("/agent create silinecek --tools workspace_oku")
        refused = await self.run_remote("/agent delete silinecek")
        self.assertIn("--yes", refused)
        from MarketingApp.llms import agent_studio

        names = lambda: [a["name"] for a in agent_studio.load_agents_config()["agents"]]
        self.assertIn("silinecek", names())
        self.assertIn("silindi", await self.run_remote("/agent delete silinecek --yes"))
        self.assertNotIn("silinecek", names())

    async def test_a_confirmation_prompt_reached_by_any_path_is_denied(self):
        await self.run_remote("/agent create yasayan --tools workspace_oku")
        out = await self.run_remote("/agent delete yasayan --yes")  # --yes atlar; onay yolunu dogrudan dene:
        self.assertIn("silindi", out)
        self.assertEqual(remote_commands._deny_input("Onayliyor musun? [e/H]: "), "")

    async def test_phone_keyboard_punctuation_works_end_to_end(self):
        out = await self.run_remote('/agent create telefon_ajan —tools workspace_oku —desc “Telefondan olustu”')
        self.assertIn("olusturuldu", out)
        from MarketingApp.llms import agent_studio

        agent = next(a for a in agent_studio.load_agents_config()["agents"] if a["name"] == "telefon_ajan")
        self.assertEqual((agent["tools"], agent["description"]), (["workspace_oku"], "Telefondan olustu"))

    async def test_a_command_that_raises_is_reported_not_propagated(self):
        def boom():
            raise RuntimeError("reload cokti")

        self.base.reload_agent_studio = boom
        out = await self.run_remote("/reload")
        self.assertIn("reload cokti", out)

    async def test_unbalanced_quotes_and_empty_input(self):
        self.assertIn("Komut okunamadi", await self.run_remote('/agent create x --desc "acik'))
        self.assertEqual(await self.run_remote("   "), "")

    async def test_huge_output_is_truncated(self):
        for i in range(300):
            self.t.record_event("sistem", f"{i:03d} " + "x" * 190)
        out = await self.run_remote("/logs 500")
        self.assertLessEqual(len(out), remote_commands._MAX_OUTPUT_CHARS + 50)
        self.assertIn("kisaltildi", out)

    async def test_runs_started_remotely_carry_the_channel_as_source(self):
        async def runner(gorev):
            return "ok"

        self.base._submodel_func_map["rapor"] = runner
        await self.run_remote('/agent test rapor "x"', channel="discord")
        self.assertEqual(self.t.recent_runs(1)[0]["source"], "discord")

    async def test_the_remote_terminal_never_touches_the_real_chat_history(self):
        await self.run_remote("/errors")
        self.assertFalse((WORKSPACE_DIR / ".system" / "remote_commands_unused.json").exists())


# ---------------------------------------------------------------------------- Telegram

def tg_update(user_id, text):
    reply = AsyncMock()
    message = SimpleNamespace(text=text, reply_text=reply)
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(effective_user=user, effective_message=message, message=message), reply


class TelegramGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from MarketingApp.environments import telegram

        self.tg = telegram
        manager = S.fresh_telemetry()
        self.t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.addCleanup(self.t.set_source, "direct")

    async def test_open_mode_lets_everyone_through_and_tags_the_channel(self):
        with env():
            update, _ = tg_update(1, "merhaba")
            self.assertIsNone(await self.tg.auth_gate(update, None))
            self.assertEqual(self.t.current_source(), "telegram")

    async def test_strangers_are_stopped_and_the_attempt_is_logged(self):
        from telegram.ext import ApplicationHandlerStop

        with env(TELEGRAM_ALLOWED_USER_IDS="10,11"):
            update, reply = tg_update(666, "merhaba")
            with self.assertRaises(ApplicationHandlerStop):
                await self.tg.auth_gate(update, None)
            reply.assert_not_called()  # yabancilara hicbir cevap verilmez
            self.assertTrue(any("telegram:666 yetkisiz erisim" in e["message"] for e in self.t.recent_events(type_="remote")))

    async def test_members_admins_and_id_lookups_pass(self):
        with env(TELEGRAM_ALLOWED_USER_IDS="10", TELEGRAM_ADMIN_IDS="99"):
            for user_id, text in ((10, "selam"), (99, "selam"), (666, "/id"), (666, "/id@EthgentBot")):
                update, _ = tg_update(user_id, text)
                self.assertIsNone(await self.tg.auth_gate(update, None), (user_id, text))

    async def test_updates_without_a_user_are_stopped_when_an_allowlist_exists(self):
        from telegram.ext import ApplicationHandlerStop

        with env(TELEGRAM_ALLOWED_USER_IDS="10"):
            update, _ = tg_update(None, "kanal postu")
            with self.assertRaises(ApplicationHandlerStop):
                await self.tg.auth_gate(update, None)

    async def test_id_command_replies_with_the_callers_id(self):
        update, reply = tg_update(4242, "/id")
        await self.tg.id_command(update, None)
        self.assertIn("4242", reply.call_args.args[0])

    async def test_admin_command_refuses_non_admins_and_logs_it(self):
        with env(TELEGRAM_ADMIN_IDS="99"):
            update, reply = tg_update(5, "/agent create x --tools a")
            with mock.patch.object(self.tg, "_base_model", S.FakeBase()):
                await self.tg.admin_command(update, None)
            self.assertIn("yetkin yok", reply.call_args.args[0])
            self.assertTrue(any("telegram:5 yonetim komutu denedi" in e["message"] for e in self.t.recent_events(type_="remote")))

    async def test_admin_command_runs_for_admins_and_splits_long_replies(self):
        S.reset_state()
        self.addCleanup(S.patch_model_env())
        for i in range(120):
            self.t.record_event("sistem", f"{i:03d} " + "y" * 150)
        with env(TELEGRAM_ADMIN_IDS="99"), mock.patch.object(self.tg, "_base_model", S.FakeBase()):
            update, reply = tg_update(99, "/logs 500")
            await self.tg.admin_command(update, None)
        self.assertGreater(reply.await_count, 1)
        self.assertTrue(all(len(call.args[0]) <= self.tg._TELEGRAM_MESSAGE_LIMIT for call in reply.await_args_list))

    async def test_an_admin_still_cannot_upload_code_remotely(self):
        with env(TELEGRAM_ADMIN_IDS="99"), mock.patch.object(self.tg, "_base_model", S.FakeBase()):
            update, reply = tg_update(99, '/tool create x --code "def x(): pass"')
            await self.tg.admin_command(update, None)
        self.assertIn("uzaktan kapali", reply.call_args.args[0])

    async def test_handler_registration_reflects_the_configuration(self):
        class Stop(Exception):
            pass

        class FakeApp:
            def __init__(self):
                self.handlers = []

            def add_handler(self, handler, group=0):
                self.handlers.append((handler, group))

            def add_error_handler(self, handler):
                pass

            async def __aenter__(self):
                raise Stop

            async def __aexit__(self, *exc):
                return False

        async def register(**variables):
            app = FakeApp()
            builder = SimpleNamespace(token=lambda _t: builder, build=lambda: app)
            with env(**variables), mock.patch.object(self.tg, "ApplicationBuilder", lambda: builder), \
                    mock.patch.object(self.tg, "_base_model", S.FakeBase()), \
                    mock.patch.object(self.tg, "_genel_araclar", []):
                with self.assertRaises(Stop):
                    await self.tg.run_telegram_bot("123:TEST")
            return app.handlers

        def kinds(handlers):
            gate = [g for h, g in handlers if type(h).__name__ == "TypeHandler"]
            commands = {c for h, _ in handlers if type(h).__name__ == "CommandHandler" for c in h.commands}
            return gate, commands

        gate, commands = kinds(await register())
        self.assertEqual(gate, [-1])  # kapi, tum handler'lardan (grup 0) once calisir
        self.assertIn("id", commands)
        self.assertNotIn("agent", commands)  # ADMIN tanimli degil: yonetim komutlari hic kayitli degil

        _, commands = kinds(await register(TELEGRAM_ADMIN_IDS="99"))
        self.assertTrue({"agent", "tool", "heartbeat", "usage", "runs", "logs"} <= commands)
        self.assertFalse({"exit", "clear"} & commands)


# ------------------------------------------------------------------------------ Discord

class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def dc_message(user_id, content):
    channel = SimpleNamespace(id=5, send=AsyncMock(), typing=lambda: _Typing())
    return SimpleNamespace(author=SimpleNamespace(id=user_id), content=content, channel=channel, attachments=[], guild=None)


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from MarketingApp.environments import discord_bot

        self.dc = discord_bot
        S.reset_state()
        self.addCleanup(S.patch_model_env())
        manager = S.fresh_telemetry()
        self.t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.addCleanup(self.t.set_source, "direct")
        self.base = S.FakeBase()
        self.addCleanup(setattr, self.dc, "_base_model", self.dc._base_model)
        self.dc._base_model = self.base

    async def _capture_handlers(self):
        events = {}

        class FakeBot:
            user = SimpleNamespace(id=999, name="bot")
            guilds = []
            process_commands = AsyncMock()

            def __init__(self, *a, **kw):
                pass

            def event(self, fn):
                events[fn.__name__] = fn
                return fn

            def command(self, **kw):
                return lambda fn: fn

            async def start(self, token):
                raise RuntimeError("test: baglanma")

        with mock.patch.object(self.dc.commands, "Bot", FakeBot):
            await self.dc.run_discord_bot("token", self.base)
        return events["on_message"], FakeBot

    async def test_admin_commands_reply_in_a_code_block_and_defang_backticks(self):
        with env(DISCORD_ADMIN_IDS="7"):
            message = dc_message(7, "!errors")
            handled = await self.dc._handle_admin_command(message)
        self.assertTrue(handled)
        sent = message.channel.send.call_args.args[0]
        self.assertTrue(sent.startswith("```\n") and sent.endswith("\n```"))
        self.assertIn("Config hatalari", sent)

    async def test_non_admins_are_refused_and_logged(self):
        with env(DISCORD_ADMIN_IDS="7"):
            message = dc_message(8, "!agent create x --tools a")
            self.assertTrue(await self.dc._handle_admin_command(message))
        self.assertIn("yetkin yok", message.channel.send.call_args.args[0])
        self.assertTrue(any("discord:8 yonetim komutu denedi" in e["message"] for e in self.t.recent_events(type_="remote")))

    async def test_only_known_management_commands_are_intercepted(self):
        with env(DISCORD_ADMIN_IDS="7"):
            for content in ("!durum", "!yardim", "merhaba", "!", "!bilinmeyen x", ""):
                self.assertFalse(await self.dc._handle_admin_command(dc_message(7, content)), content)

    async def test_on_message_gate_ignores_strangers_and_answers_id_lookups(self):
        on_message, bot = await self._capture_handlers()
        chat = AsyncMock(return_value=SimpleNamespace(cevap_metinleri=["merhaba"], dogrudan_ciktilar=[], metin="", ses_bytes=None))
        with env(DISCORD_ALLOWED_USER_IDS="1", DISCORD_ADMIN_IDS="7"), mock.patch.object(self.dc, "mesaj_isle", chat):
            stranger = dc_message(666, "selam bot")
            await on_message(stranger)
            chat.assert_not_called()
            stranger.channel.send.assert_not_called()  # yabanciya cevap yok
            self.assertTrue(any("discord:666 yetkisiz erisim" in e["message"] for e in self.t.recent_events(type_="remote")))

            lookup = dc_message(666, "!id")
            await on_message(lookup)
            self.assertIn("666", lookup.channel.send.call_args.args[0])

            member = dc_message(1, "selam bot")
            await on_message(member)
            chat.assert_awaited_once()

            admin = dc_message(7, "!errors")
            await on_message(admin)
            self.assertIn("Config hatalari", admin.channel.send.call_args.args[0])
            self.assertEqual(chat.await_count, 1)  # yonetim komutu modele gitmez

    async def test_open_mode_keeps_the_old_behaviour(self):
        on_message, bot = await self._capture_handlers()
        chat = AsyncMock(return_value=SimpleNamespace(cevap_metinleri=["merhaba"], dogrudan_ciktilar=[], metin="", ses_bytes=None))
        with env(), mock.patch.object(self.dc, "mesaj_isle", chat):
            await on_message(dc_message(31337, "selam"))
        chat.assert_awaited_once()


class ChannelRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_tags_the_source_so_usage_lands_on_the_right_channel(self):
        from MarketingApp.environments import kanal_router

        manager = S.fresh_telemetry()
        t = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.addCleanup(t.set_source, "direct")
        seen = {}

        class Base:
            async def text_query(self, text, **kwargs):
                seen["source"] = t.current_source()
                return b"", "ok", [], ["ok"]

        await kanal_router.mesaj_isle(kanal_router.KanalMesaji(kaynak="discord", kullanici_id="1", metin="x"), Base())
        self.assertEqual(seen["source"], "discord")


if __name__ == "__main__":
    unittest.main()
