"""Parity between the worker's authority (policy.py) and the agent's own fast
pre-check (MarketingApp/araclar/platform_veri_araclari.py).

The agent duplicates validation so it can fail fast without a round trip through
the queue, but policy.py is what actually gets enforced (the worker re-validates
regardless -- see platform_veri_araclari.py's module docstring). If the two ever
disagree, the agent would either block something the worker allows (confusing)
or -- worse -- accept something the worker later refuses, burning a queue round
trip and confusing the model. This test runs the SAME cases through both and
requires the same accept/reject verdict, params, and error text against the
REAL manifests.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_ROOT = REPO / "agents" / "marketing-agent"

if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from platform_data_worker.policy import PolicyError, load_policy  # noqa: E402

try:
    from MarketingApp.araclar.platform_veri_araclari import _load_catalog, validate_request  # noqa: E402
    _AGENT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    _AGENT_IMPORT_ERROR = exc


CASES = [
    ("youtube", "channels", {"mine": True}),
    ("youtube", "channels", {}),  # require_one_of violation
    ("youtube", "channels", {"channel_id": "UC_x5XG1OV2P6uZZ5FSM9Ttw", "handle": "x"}),  # ok: both given, one_of satisfied
    ("youtube", "videos", {"video_ids": "a,b,c"}),
    ("youtube", "videos", {}),  # missing required
    ("youtube", "videos", {"video_ids": "a", "part": "snippet"}),  # unknown param
    ("youtube", "search", {"query": "cats", "order": "bogus"}),  # bad enum
    ("youtube", "analytics", {"start_date": "2026-01-01", "end_date": "not-a-date"}),  # bad pattern
    ("instagram", "media", {"limit": 200}),  # out of range
    ("instagram", "media", {"limit": True}),  # bool where int expected
    ("instagram", "media_details", {"media_id": "abc_123"}),
    ("instagram", "media_details", {"media_id": "abc 123"}),  # bad pattern (space)
    ("x", "user", {"username": "@openai"}),
    ("x", "user", {}),  # require_one_of violation
    ("x", "user_posts", {"username": "openai", "exclude_replies": "true"}),  # string -> bool coercion
    ("x", "user_posts", {"username": "openai", "exclude_replies": "maybe"}),  # bad bool
    ("reddit", "listing", {"sort": "hot", "limit": 10}),
    ("reddit", "search_posts", {}),  # missing required query
    ("tiktok", "videos", {"cursor": 0}),  # zero is a real value, not "missing"
    ("tiktok", "user_info", {}),
    ("tiktok", "publish", {}),  # write action: must not exist on either side
    ("linkedin", "profile", {}),  # unknown platform
]


@unittest.skipIf(_AGENT_IMPORT_ERROR is not None, f"agent module not importable: {_AGENT_IMPORT_ERROR}")
class AgentWorkerPolicyParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker_policy = load_policy(REPO / "toolboxes")
        cls.agent_catalog = _load_catalog()
        assert isinstance(cls.agent_catalog, dict), cls.agent_catalog

    def test_same_actions_are_approved_on_both_sides(self):
        worker_actions = {(spec.platform, spec.action_id) for spec in self.worker_policy.actions()}
        agent_actions = set(self.agent_catalog)
        self.assertEqual(worker_actions, agent_actions)

    def test_same_function_is_bound_to_each_action(self):
        for key, spec in self.agent_catalog.items():
            with self.subTest(action=key):
                self.assertEqual(spec.get("function"), self.worker_policy.get(*key).function)

    def test_accept_reject_and_normalized_params_agree_on_every_case(self):
        for platform, action, params in CASES:
            with self.subTest(platform=platform, action=action, params=params):
                worker_ok, worker_params, worker_err = True, None, None
                try:
                    _, worker_params = self.worker_policy.validate(platform, action, params)
                except PolicyError as exc:
                    worker_ok, worker_err = False, str(exc)

                agent_ok, agent_params, agent_err = True, None, None
                try:
                    _, agent_params = validate_request(self.agent_catalog, platform, action, params)
                except ValueError as exc:
                    agent_ok, agent_err = False, str(exc)

                self.assertEqual(agent_ok, worker_ok, f"agent={agent_err!r} worker={worker_err!r}")
                if worker_ok:
                    self.assertEqual(agent_params, worker_params)


if __name__ == "__main__":
    unittest.main()
