from __future__ import annotations

import math
import unittest

import scripts.run_v6_load_acceptance as load


class StateQueryPerformanceProtocolTests(unittest.TestCase):
    def _evaluate(self, cold, warm):
        evaluator = getattr(load, "evaluate_state_query_samples", None)
        self.assertIsNotNone(
            evaluator,
            "stable state-query protocol must expose evaluate_state_query_samples",
        )
        return evaluator(cold, warm)

    def test_requires_exactly_five_warm_samples_and_uses_median(self) -> None:
        self.assertEqual(getattr(load, "STATE_QUERY_WARM_SAMPLES", None), 5)
        result = self._evaluate(0.42, [0.08, 0.06, 0.07, 0.09, 0.05])
        self.assertTrue(result["valid"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["warm_sample_count"], 5)
        self.assertEqual(result["warm_median_seconds"], 0.07)
        self.assertEqual(result["warm_max_seconds"], 0.09)

    def test_rejects_sustained_slow_median(self) -> None:
        result = self._evaluate(0.2, [0.61, 0.62, 0.63, 0.64, 0.65])
        self.assertTrue(result["valid"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["median_target_passed"])
        self.assertTrue(result["tail_target_passed"])

    def test_rejects_severe_tail_outlier(self) -> None:
        self.assertEqual(getattr(load, "STATE_QUERY_TAIL_SECONDS", None), 1.0)
        result = self._evaluate(0.2, [0.08, 0.09, 0.10, 0.11, 1.20])
        self.assertTrue(result["valid"])
        self.assertFalse(result["passed"])
        self.assertTrue(result["median_target_passed"])
        self.assertFalse(result["tail_target_passed"])

    def test_fails_closed_on_invalid_measurements(self) -> None:
        cases = [
            (math.nan, [0.1] * 5),
            (0.1, [0.1, 0.1, math.inf, 0.1, 0.1]),
            (0.1, [0.1, 0.1, -0.01, 0.1, 0.1]),
            (0.1, [0.1, 0.1, 0.1]),
        ]
        for cold, warm in cases:
            with self.subTest(cold=cold, warm=warm):
                result = self._evaluate(cold, warm)
                self.assertFalse(result["valid"])
                self.assertFalse(result["passed"])
                self.assertFalse(result["median_target_passed"])
                self.assertFalse(result["tail_target_passed"])

    def test_spec_targets_are_not_relaxed(self) -> None:
        self.assertEqual(load.TARGETS["state_query_seconds"], 0.5)
        self.assertEqual(getattr(load, "STATE_QUERY_TAIL_SECONDS", None), 1.0)
        self.assertEqual(getattr(load, "STATE_QUERY_WARM_SAMPLES", None), 5)


if __name__ == "__main__":
    unittest.main()
