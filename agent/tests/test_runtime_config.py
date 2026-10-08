"""runtime_config.py: provider/model env cozumleme (gemini, moonshot, ve bilinmeyen provider'lar)."""

import _env  # noqa: F401  (her seyden once)

import os
import unittest
from unittest import mock


def rc():
    from MarketingApp.llms import runtime_config

    return runtime_config


class ProviderEnvPrefixTests(unittest.TestCase):
    def test_simple_name_is_uppercased(self):
        self.assertEqual(rc().provider_env_prefix("deepseek"), "DEEPSEEK")

    def test_punctuation_becomes_underscores(self):
        self.assertEqual(rc().provider_env_prefix("my-cool.provider"), "MY_COOL_PROVIDER")

    def test_empty_name_falls_back_to_provider(self):
        self.assertEqual(rc().provider_env_prefix(""), "PROVIDER")


class ProviderApiKeyEnvNameTests(unittest.TestCase):
    def test_gemini_keeps_its_historical_name(self):
        self.assertEqual(rc().provider_api_key_env_name("gemini"), "GEMINI_API_KEY")

    def test_moonshot_keeps_its_historical_name(self):
        self.assertEqual(rc().provider_api_key_env_name("moonshot"), "MOONSHOT_API_KEY")

    def test_unknown_provider_gets_a_generated_name(self):
        self.assertEqual(rc().provider_api_key_env_name("deepseek"), "DEEPSEEK_API_KEY")

    def test_defaults_to_the_currently_configured_provider(self):
        with mock.patch.dict(os.environ, {"MODEL_PROVIDER": "groq"}, clear=False):
            self.assertEqual(rc().provider_api_key_env_name(), "GROQ_API_KEY")


class ApiKeyResolutionTests(unittest.TestCase):
    def test_gemini_reads_gemini_api_key(self):
        with mock.patch.dict(os.environ, {"MODEL_PROVIDER": "gemini", "GEMINI_API_KEY": "g1"}, clear=False):
            self.assertEqual(rc().get_model_api_key(), "g1")

    def test_moonshot_falls_back_to_kimi_api_key(self):
        env = {"MODEL_PROVIDER": "moonshot", "MOONSHOT_API_KEY": "", "KIMI_API_KEY": "k1"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_model_api_key(), "k1")

    def test_unknown_provider_reads_its_generated_env_var(self):
        env = {"MODEL_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "d1"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_model_api_key(), "d1")

    def test_generic_model_api_key_overrides_any_provider(self):
        env = {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "generic", "DEEPSEEK_API_KEY": "specific"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_model_api_key(), "generic")

    def test_unknown_provider_key_list_deduplicates_and_skips_blank(self):
        env = {
            "MODEL_PROVIDER": "deepseek",
            "MODEL_API_KEY": "",
            "DEEPSEEK_API_KEY": "d1",
            "DEEPSEEK_API_KEY_SECONDARY": "d1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_model_api_keys(), ["d1"])


class BaseUrlResolutionTests(unittest.TestCase):
    def test_explicit_override_wins_over_everything(self):
        env = {"MODEL_PROVIDER": "gemini", "OPENAI_COMPAT_BASE_URL": "https://custom.example/"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_openai_compat_base_url(), "https://custom.example/")

    def test_unknown_provider_reads_its_generated_base_url_var(self):
        env = {"MODEL_PROVIDER": "deepseek", "OPENAI_COMPAT_BASE_URL": "", "DEEPSEEK_BASE_URL": "https://api.deepseek.com"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_openai_compat_base_url(), "https://api.deepseek.com")

    def test_unknown_provider_without_any_base_url_is_empty(self):
        env = {"MODEL_PROVIDER": "deepseek", "OPENAI_COMPAT_BASE_URL": "", "DEEPSEEK_BASE_URL": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(rc().get_openai_compat_base_url(), "")


if __name__ == "__main__":
    unittest.main()
