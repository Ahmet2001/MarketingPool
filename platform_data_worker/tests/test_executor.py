import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from platform_data_worker.executor import ToolboxExecutor
from platform_data_worker.policy import ActionSpec, ParamSpec

TOOLBOX = textwrap.dedent('''
    import os
    def get_demo_api_items(query: str, limit: int = 10):
        if query == "bad":
            raise ValueError("query is invalid")
        if query == "boom":
            raise RuntimeError("upstream exploded, token=" + os.environ.get("DEMO_API_TOKEN", ""))
        if query == "leak":
            return {"ok": True, "items": [{"echo": os.environ.get("DEMO_API_TOKEN")}]}
        if query == "apifail":
            return {"ok": False, "status_code": 403, "error": "quota exceeded", "response": {"error": {"message": "quota"}}}
        if query == "big":
            items = [{"i": i, "pad": "x" * 200} for i in range(400)]
            return {"ok": True, "items": items, "response": {"items": items}, "count": 400}
        return {"ok": True, "items": [{"q": query, "limit": limit}], "count": 1}

    def get_demo_api_other():
        return {"ok": True}

    def helper_not_read():
        return {"ok": True}
''')


def make_spec(function="get_demo_api_items", params=("query", "limit")):
    return ActionSpec(
        platform="demo", action_id="items", function=function, description="",
        params={name: ParamSpec(name=name, type="string") for name in params},
    )


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        api = Path(self.tmp.name) / "demo" / "api"
        api.mkdir(parents=True)
        (api / "toolbox.py").write_text(TOOLBOX, encoding="utf-8")
        self.executor = ToolboxExecutor(self.tmp.name, max_result_bytes=20_000)
        patcher = mock.patch.dict(os.environ, {"DEMO_API_TOKEN": "sk-super-secret-value"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_runs_the_named_function_with_params(self):
        result = self.executor.run(make_spec(), {"query": "cats", "limit": 3})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["items"], [{"q": "cats", "limit": 3}])
        self.assertEqual((result["platform"], result["action"], result["truncated"]), ("demo", "items", False))

    def test_toolbox_value_error_becomes_a_clean_failure(self):
        result = self.executor.run(make_spec(), {"query": "bad"})
        self.assertFalse(result["ok"])
        self.assertIn("invalid parameters: query is invalid", result["error"])

    def test_unexpected_exception_is_contained_and_secrets_are_redacted(self):
        result = self.executor.run(make_spec(), {"query": "boom"})
        self.assertFalse(result["ok"])
        self.assertIn("RuntimeError", result["error"])
        self.assertNotIn("sk-super-secret-value", result["error"])
        self.assertIn("[redacted]", result["error"])

    def test_secrets_in_successful_payloads_are_redacted_too(self):
        result = self.executor.run(make_spec(), {"query": "leak"})
        self.assertEqual(result["data"]["items"], [{"echo": "[redacted]"}])

    def test_platform_level_failure_is_ok_false_with_the_reason(self):
        result = self.executor.run(make_spec(), {"query": "apifail"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "quota exceeded")

    def test_big_results_are_shrunk_under_the_limit(self):
        result = self.executor.run(make_spec(), {"query": "big"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertNotIn("response", result["data"])
        self.assertGreater(len(result["data"]["items"]), 0)
        self.assertLess(len(result["data"]["items"]), 400)
        import json
        self.assertLessEqual(len(json.dumps(result["data"]).encode()), 20_000)

    def test_refuses_non_read_functions_even_if_a_manifest_names_one(self):
        result = self.executor.run(make_spec(function="helper_not_read"), {})
        self.assertFalse(result["ok"])
        self.assertIn("non-read", result["error"])

    def test_missing_function_or_toolbox_is_a_failure_not_a_crash(self):
        self.assertIn("no function", self.executor.run(make_spec(function="get_demo_api_missing"), {})["error"])
        spec = make_spec()
        spec = ActionSpec(**{**spec.__dict__, "platform": "nowhere"})
        self.assertIn("not found", self.executor.run(spec, {})["error"])

    def test_manifest_param_that_is_not_a_function_parameter_is_caught(self):
        result = self.executor.run(make_spec(), {"query": "cats", "nonexistent": "x"})
        self.assertFalse(result["ok"])
        self.assertIn("out of date", result["error"])

    def test_function_from_another_module_is_not_accepted(self):
        (Path(self.tmp.name) / "demo" / "api" / "toolbox.py").write_text(
            "from os.path import join as get_demo_api_join\n", encoding="utf-8")
        executor = ToolboxExecutor(self.tmp.name)
        result = executor.run(make_spec(function="get_demo_api_join", params=()), {})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
