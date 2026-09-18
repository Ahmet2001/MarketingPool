"""The manifests are hand-written allowlists over hand-written toolboxes. These
tests fail the moment either side moves without the other, using the REAL files."""
import importlib.util
import inspect
import re
import unittest
from pathlib import Path

from platform_data_worker.policy import READ_FUNCTION, load_policy

REPO = Path(__file__).resolve().parents[2]
WRITE_WORDS = re.compile(r"(publish|delete|create|update|upload|reply|comment_youtube|like|subscribe|follow|send|set_|add_|rate_|unsubscribe|repost|quote|bookmark)")


def load_toolbox(platform):
    spec = importlib.util.spec_from_file_location(f"drift_{platform}", REPO / "toolboxes" / platform / "api" / "toolbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestMatchesToolboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(REPO / "toolboxes")
        cls.modules = {p: load_toolbox(p) for p in ("youtube", "instagram", "tiktok", "x", "reddit")}

    def test_every_allowlisted_function_exists_and_is_read_shaped(self):
        for spec in self.policy.actions():
            with self.subTest(action=f"{spec.platform}.{spec.action_id}"):
                self.assertRegex(spec.function, READ_FUNCTION)
                self.assertFalse(WRITE_WORDS.search(spec.function), f"{spec.function} looks like a write action")
                function = getattr(self.modules[spec.platform], spec.function, None)
                self.assertTrue(callable(function), f"{spec.function} missing from {spec.platform} toolbox")

    def test_declared_params_are_real_parameters_and_required_ones_match(self):
        for spec in self.policy.actions():
            with self.subTest(action=f"{spec.platform}.{spec.action_id}"):
                parameters = inspect.signature(getattr(self.modules[spec.platform], spec.function)).parameters
                for name, param in spec.params.items():
                    self.assertIn(name, parameters, f"{name} is not a parameter of {spec.function}")
                    if param.required:
                        self.assertIs(parameters[name].default, inspect.Parameter.empty,
                                      f"{name} is required in the manifest but optional in {spec.function}")
                for name, parameter in parameters.items():
                    if parameter.default is inspect.Parameter.empty:
                        self.assertTrue(spec.params.get(name) and spec.params[name].required,
                                        f"{spec.function} requires '{name}' but the manifest does not")

    DUMMIES = {
        "video_id_or_url": "dQw4w9WgXcQ", "video_ids": "dQw4w9WgXcQ", "query": "q", "media_id": "123",
        "post_id_or_url": "abc123", "tweet_id_or_url": "1234567890", "playlist_id": "PL123",
        "start_date": "2026-01-01", "end_date": "2026-01-02", "username": "someone", "handle": "someone",
    }

    def _call(self, spec, params):
        """Returns the ValueError the toolbox's own validation raised, or None. Anything else
        (no credentials, no network) means the parameters got past validation."""
        try:
            getattr(self.modules[spec.platform], spec.function)(**params)
        except ValueError as exc:
            return exc
        except Exception:
            pass
        return None

    def test_every_manifest_enum_value_passes_the_toolbox_own_validation(self):
        checked = 0
        for spec in self.policy.actions():
            base = {n: self.DUMMIES[n] for n, p in spec.params.items() if p.required}
            if spec.require_one_of:
                base[next(n for n in spec.require_one_of if spec.params[n].type == "string")] = "someone"
            for name, param in spec.params.items():
                if not param.enum:
                    continue
                if self._call(spec, {**base, name: param.enum[0]}) is not None:
                    continue  # the dummy baseline itself isn't valid for this action; can't judge
                for value in param.enum:
                    with self.subTest(action=f"{spec.platform}.{spec.action_id}", param=name, value=value):
                        error = self._call(spec, {**base, name: value})
                        self.assertIsNone(error, f"manifest allows {name}={value!r} but the toolbox rejects it: {error}")
                        checked += 1
        self.assertGreater(checked, 20, "enum check silently covered almost nothing")

    def test_require_one_of_groups_use_declared_params(self):
        for spec in self.policy.actions():
            for name in spec.require_one_of:
                self.assertIn(name, spec.params)


if __name__ == "__main__":
    unittest.main()
