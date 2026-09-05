from __future__ import annotations

import importlib.util
import unittest


class C279ZeroMutationPreflightTddTest(unittest.TestCase):
    def test_preflight_module_exists(self) -> None:
        spec = importlib.util.find_spec("scripts.run_v64_c279_zero_mutation_preflight")
        self.assertIsNotNone(
            spec,
            "zero-mutation C279 preflight implementation is missing",
        )


if __name__ == "__main__":
    unittest.main()
