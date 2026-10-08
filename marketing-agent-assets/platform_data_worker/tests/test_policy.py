import tempfile
import unittest
from pathlib import Path

from platform_data_worker.policy import PolicyError, load_policy

REPO = Path(__file__).resolve().parents[2]


class RealManifestPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(REPO / "toolboxes")

    def test_every_platform_contributes_actions(self):
        platforms = {spec.platform for spec in self.policy.actions()}
        self.assertEqual(platforms, {"youtube", "instagram", "tiktok", "x", "reddit"})

    def test_unlisted_and_write_actions_do_not_exist(self):
        for platform, action in [
            ("youtube", "upload"), ("instagram", "publish"), ("x", "publish_post"),
            ("reddit", "inbox"), ("youtube", "comment"), ("tiktok", "post_status"),
        ]:
            with self.assertRaises(PolicyError, msg=f"{platform}.{action}"):
                self.policy.get(platform, action)

    def test_unknown_platform_is_refused(self):
        with self.assertRaises(PolicyError):
            self.policy.get("linkedin", "profile")

    def test_valid_request_is_normalized(self):
        spec, params = self.policy.validate("youtube", "comment_threads", {"video_id_or_url": " dQw4w9WgXcQ ", "max_results": "25"})
        self.assertEqual(spec.function, "get_youtube_api_comment_threads")
        self.assertEqual(params, {"video_id_or_url": "dQw4w9WgXcQ", "max_results": 25})
        self.assertTrue(spec.personal_data)

    def test_unknown_params_are_rejected_not_ignored(self):
        with self.assertRaisesRegex(PolicyError, "unknown param"):
            self.policy.validate("instagram", "media", {"limit": 5, "fields": "id,caption,secret"})
        with self.assertRaisesRegex(PolicyError, "unknown param"):
            self.policy.validate("instagram", "profile", {"user_id": "someone-else"})

    def test_required_and_one_of(self):
        with self.assertRaisesRegex(PolicyError, "required"):
            self.policy.validate("youtube", "videos", {})
        with self.assertRaisesRegex(PolicyError, "at least one of"):
            self.policy.validate("x", "user", {})
        with self.assertRaisesRegex(PolicyError, "at least one of"):
            self.policy.validate("youtube", "channels", {"mine": False})
        self.policy.validate("youtube", "channels", {"mine": True})
        self.policy.validate("x", "user", {"username": "@openai"})

    def test_types_ranges_enums_and_patterns(self):
        v = self.policy.validate
        with self.assertRaisesRegex(PolicyError, "<="):
            v("instagram", "media", {"limit": 101})
        with self.assertRaisesRegex(PolicyError, ">="):
            v("instagram", "media", {"limit": 0})
        with self.assertRaisesRegex(PolicyError, "integer"):
            v("instagram", "media", {"limit": True})
        with self.assertRaisesRegex(PolicyError, "integer"):
            v("instagram", "media", {"limit": "many"})
        with self.assertRaisesRegex(PolicyError, "one of"):
            v("instagram", "account_insights", {"period": "decade"})
        with self.assertRaisesRegex(PolicyError, "invalid format"):
            v("instagram", "media_details", {"media_id": "1; DROP TABLE"})
        with self.assertRaisesRegex(PolicyError, "invalid format"):
            v("youtube", "analytics", {"start_date": "yesterday", "end_date": "2026-01-02"})
        with self.assertRaisesRegex(PolicyError, "must be a string"):
            v("youtube", "search", {"query": 12345})
        with self.assertRaisesRegex(PolicyError, "at most"):
            v("youtube", "search", {"query": "x" * 201})
        self.assertEqual(v("x", "user_posts", {"username": "openai", "exclude_replies": "true"})[1]["exclude_replies"], True)
        with self.assertRaisesRegex(PolicyError, "boolean"):
            v("x", "user_posts", {"username": "openai", "exclude_replies": "maybe"})

    def test_zero_is_a_real_value(self):
        _, params = self.policy.validate("tiktok", "videos", {"cursor": 0})
        self.assertEqual(params, {"cursor": 0})

    def test_params_must_be_an_object(self):
        with self.assertRaisesRegex(PolicyError, "object"):
            self.policy.validate("tiktok", "videos", ["cursor"])


class MalformedManifestTests(unittest.TestCase):
    def load(self, section: str):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "youtube"
            d.mkdir()
            (d / "manifest.yaml").write_text("name: t\ndata_collection:\n  actions:\n" + section, encoding="utf-8")
            return load_policy(tmp)

    def test_write_shaped_function_is_refused_at_load(self):
        with self.assertRaisesRegex(PolicyError, "not a get_/search_/list_"):
            self.load("    upload:\n      function: upload_youtube_api_video\n      params: {}\n")

    def test_bad_param_type_and_bad_one_of_are_refused(self):
        with self.assertRaisesRegex(PolicyError, "type must be"):
            self.load("    a1:\n      function: get_x\n      params:\n        q: {type: object}\n")
        with self.assertRaisesRegex(PolicyError, "undeclared param"):
            self.load("    a1:\n      function: get_x\n      require_one_of: [nope]\n      params: {}\n")

    def test_bad_rate_limit_and_unknown_spec_key(self):
        with self.assertRaisesRegex(PolicyError, "rate_limit"):
            self.load("    a1:\n      function: get_x\n      rate_limit_per_hour: 0\n      params: {}\n")
        with self.assertRaisesRegex(PolicyError, "unknown spec key"):
            self.load("    a1:\n      function: get_x\n      params:\n        q: {type: string, maxlength: 5}\n")

    def test_missing_section_means_no_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "x"
            d.mkdir()
            (d / "manifest.yaml").write_text("name: t\n", encoding="utf-8")
            self.assertEqual(load_policy(tmp).actions(), [])


if __name__ == "__main__":
    unittest.main()
