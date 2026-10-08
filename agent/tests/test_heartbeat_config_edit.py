"""Heartbeat config'ini metin seviyesinde duzenleme: YAML anchor'lari ve yorumlar korunmali."""

import _env  # noqa: F401  (her seyden once)

import os
import tempfile
import unittest
from unittest import mock

from _env import REPO
from MarketingApp.environments import heartbeat

REAL_CONFIG = (REPO / "MarketingApp" / "config" / "heartbeat_config.yaml").read_text(encoding="utf-8")


class AddTaskTests(unittest.TestCase):
    def test_added_task_parses_and_existing_ones_are_untouched(self):
        before = heartbeat.parse_config_content(REAL_CONFIG)
        updated, task_id = heartbeat.add_task_to_content(
            REAL_CONFIG, gorev="Gunluk ozet cikar.\nSonucu yaz.", cron="08:30", name="Gunluk ozet"
        )
        after = heartbeat.parse_config_content(updated)
        self.assertEqual(len(after["tasks"]), len(before["tasks"]) + 1)
        added = next(t for t in after["tasks"] if t.task_id == task_id)
        self.assertEqual((added.cron, added.name), ("08:30", "Gunluk ozet"))
        self.assertEqual(added.gorev, "Gunluk ozet cikar. Sonucu yaz.")  # folded (>) blok: satirlar birlesir
        self.assertEqual([t.task_id for t in after["tasks"][:-1]], [t.task_id for t in before["tasks"]])

    def test_yaml_anchors_and_comments_survive(self):
        updated, _ = heartbeat.add_task_to_content(REAL_CONFIG, gorev="x", cron="startup")
        self.assertIn("&post_gorevi", updated)
        self.assertEqual(updated.count("*post_gorevi"), REAL_CONFIG.count("*post_gorevi"))
        self.assertTrue(updated.lstrip().startswith("## Heartbeat"))
        # alias'lar acilmadi: 12 gorev hala ayni metni paylasiyor
        parsed = heartbeat.parse_config_content(updated)
        shared = [t.gorev for t in parsed["tasks"] if t.task_id.startswith("post_slot_")]
        self.assertEqual(len(set(shared)), 1)

    def test_add_then_remove_restores_the_original_byte_for_byte(self):
        updated, task_id = heartbeat.add_task_to_content(REAL_CONFIG, gorev="x", cron="*/45", name="N")
        restored = heartbeat.remove_task_from_content(updated, task_id)
        self.assertEqual(restored.strip(), REAL_CONFIG.strip())

    def test_generated_ids_never_collide(self):
        content = REAL_CONFIG
        seen = set()
        for _ in range(3):
            content, task_id = heartbeat.add_task_to_content(content, gorev="x", cron="*/5", name="ayni ad")
            seen.add(task_id)
        self.assertEqual(len(seen), 3)

    def test_explicit_id_is_used_and_duplicates_rejected(self):
        updated, task_id = heartbeat.add_task_to_content(REAL_CONFIG, gorev="x", cron="*/5", task_id="benim_isim")
        self.assertEqual(task_id, "benim_isim")
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.add_task_to_content(updated, gorev="x", cron="*/5", task_id="benim_isim")

    def test_invalid_input_is_rejected_before_anything_is_written(self):
        for kwargs in (
            dict(gorev="x", cron="carsamba"),
            dict(gorev="x", cron="25:00"),
            dict(gorev="   ", cron="08:00"),
            dict(gorev="x", cron="08:00", task_id="bosluklu id"),
        ):
            with self.assertRaises(heartbeat.HeartbeatConfigError, msg=str(kwargs)):
                heartbeat.add_task_to_content(REAL_CONFIG, **kwargs)

    def test_special_characters_in_name_and_cron_stay_valid_yaml(self):
        updated, task_id = heartbeat.add_task_to_content(
            REAL_CONFIG, gorev="x", cron="startup", name='Tirnakli "ad": ve # yorum gibi'
        )
        added = next(t for t in heartbeat.parse_config_content(updated)["tasks"] if t.task_id == task_id)
        self.assertEqual(added.name, 'Tirnakli "ad": ve # yorum gibi')

    def test_disabled_flag_is_written(self):
        updated, task_id = heartbeat.add_task_to_content(REAL_CONFIG, gorev="x", cron="*/5", enabled=False)
        added = next(t for t in heartbeat.parse_config_content(updated)["tasks"] if t.task_id == task_id)
        self.assertFalse(added.enabled)

    def test_works_on_a_minimal_config_and_requires_a_tasks_key(self):
        minimal = "enabled: true\ntasks:\n  - id: a\n    cron: '*/5'\n    gorev: x\n"
        updated, _ = heartbeat.add_task_to_content(minimal, gorev="y", cron="*/6", task_id="b")
        self.assertEqual([t.task_id for t in heartbeat.parse_config_content(updated)["tasks"]], ["a", "b"])
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.add_task_to_content("enabled: true\n", gorev="y", cron="*/6")


class RemoveTaskTests(unittest.TestCase):
    def test_only_the_target_is_removed(self):
        before = [t.task_id for t in heartbeat.parse_config_content(REAL_CONFIG)["tasks"]]
        updated = heartbeat.remove_task_from_content(REAL_CONFIG, "market_refresh_20m")
        after = [t.task_id for t in heartbeat.parse_config_content(updated)["tasks"]]
        self.assertEqual(after, [t for t in before if t != "market_refresh_20m"])

    def test_removing_an_alias_user_keeps_the_anchor_definition(self):
        updated = heartbeat.remove_task_from_content(REAL_CONFIG, "post_slot_0905")
        self.assertIn("&post_gorevi", updated)
        parsed = heartbeat.parse_config_content(updated)
        self.assertEqual(len([t for t in parsed["tasks"] if t.task_id.startswith("post_slot_")]), 11)

    def test_unknown_task_is_an_error(self):
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.remove_task_from_content(REAL_CONFIG, "yok_boyle_bir_gorev")

    def test_a_task_without_an_explicit_id_line_is_refused_not_guessed(self):
        content = "tasks:\n  - name: Adsiz\n    cron: '*/5'\n    gorev: x\n"
        auto_id = heartbeat.parse_config_content(content)["tasks"][0].task_id
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.remove_task_from_content(content, auto_id)


class WriteConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "heartbeat_config.yaml")
        patcher = mock.patch.object(heartbeat, "_CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_content_is_written_atomically(self):
        summary = heartbeat.write_config_content(REAL_CONFIG)
        self.assertTrue(summary["valid"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), REAL_CONFIG)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_invalid_content_is_refused_and_the_old_file_is_kept(self):
        heartbeat.write_config_content(REAL_CONFIG)
        with self.assertRaises(heartbeat.HeartbeatConfigError):
            heartbeat.write_config_content("tasks:\n  - cron: bozuk\n")
        self.assertEqual(open(self.path, encoding="utf-8").read(), REAL_CONFIG)

    def test_enabled_toggle_edits_only_that_line(self):
        off = heartbeat.set_enabled_in_content(REAL_CONFIG, False)
        on = heartbeat.set_enabled_in_content(off, True)
        self.assertIn("enabled: false", off.split("tasks:")[0])
        self.assertIn("enabled: true", on.split("tasks:")[0])
        self.assertEqual(off.replace("enabled: false", "enabled: X", 1), on.replace("enabled: true", "enabled: X", 1))


if __name__ == "__main__":
    unittest.main()
