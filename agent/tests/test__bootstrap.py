"""Alfabetik olarak ilk yuklenen test modulu: izole ortami herkesten once kurar.

'test__' (iki alt cizgi) 'test_a...' den once siralanir; unittest discover modulleri
siralı import eder. Bu dosya bozulursa diger testler kullanicinin gercek workspace'ine yazabilir.
"""

import _env  # noqa: F401  (siralamaya duyarli: bu satir MarketingApp importlarindan once kalmali)
import unittest
from pathlib import Path


class IsolationTests(unittest.TestCase):
    def test_workspace_and_config_point_into_the_temp_root(self):
        from MarketingApp import paths

        root = _env.ROOT.resolve()
        self.assertTrue(Path(paths.WORKSPACE_DIR).resolve().is_relative_to(root))
        self.assertTrue(Path(paths.CONFIG_DIR).resolve().is_relative_to(root))

    def test_real_workspace_is_untouched(self):
        real = (_env.REPO / "MarketingApp" / "workspace").resolve()
        self.assertNotEqual(Path(_env.WORKSPACE_DIR).resolve(), real)


if __name__ == "__main__":
    unittest.main()
