"""Deterministic mathematical tests, not H0 experiments or sea-trial validation."""

from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal, localcontext
import inspect
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cfar_theory as ct


class CFARTheoryTests(unittest.TestCase):
    def assertRelative(self, actual, expected, tolerance=1e-12):
        self.assertLessEqual(abs(actual - expected) / abs(expected), tolerance)

    def test_ca_n1_closed_form(self):
        for p in (0.8, 0.2, 1e-4, 1e-150):
            with self.subTest(p=p):
                self.assertRelative(ct.ca_coefficient_iid_exponential(p, 1).alpha,
                                    1.0 / p - 1.0)

    def test_ca_decimal_formula(self):
        with localcontext() as ctx:
            ctx.prec = 80
            for n in (2, 17, 1024):
                for p in (0.25, 1e-6, 1e-120):
                    with self.subTest(n=n, p=p):
                        d = Decimal.from_float(p)
                        expected = Decimal(n) * ((-d.ln() / Decimal(n)).exp() - 1)
                        self.assertRelative(ct.ca_coefficient_iid_exponential(p, n).alpha,
                                            float(expected))

    def test_os_rank1_closed_form(self):
        for n in (1, 8, 128):
            for p in (0.4, 1e-8):
                with self.subTest(n=n, p=p):
                    r = ct.os_coefficient_iid_exponential(p, n, 1)
                    self.assertRelative(r.alpha, n * (1.0 / p - 1.0))
                    self.assertEqual(r.solver_iterations, 0)

    def test_os_n2_rank2_independent_quadratic_solution(self):
        with localcontext() as ctx:
            ctx.prec = 100
            for p in (math.nextafter(1.0, 0.0), 0.5, 1e-6, 1e-100, 5e-324):
                with self.subTest(p=p):
                    inv_p = 1 / Decimal.from_float(p)
                    expected = 4 * (inv_p - 1) / ((1 + 8 * inv_p).sqrt() + 3)
                    self.assertRelative(ct.os_coefficient_iid_exponential(p, 2, 2).alpha,
                                        float(expected))

    def test_os_decimal_product_at_solved_coefficient(self):
        # Independent high-precision product, rather than the solver's log-sum.
        with localcontext() as ctx:
            ctx.prec = 80
            for n, k, p in ((16, 3, .02), (32, 24, 1e-6), (128, 128, 1e-100)):
                with self.subTest(n=n, k=k, p=p):
                    result = ct.os_coefficient_iid_exponential(p, n, k)
                    a = Decimal.from_float(result.alpha)
                    product = Decimal(1)
                    for rate in range(n - k + 1, n + 1):
                        product *= Decimal(rate) / (Decimal(rate) + a)
                    target = Decimal.from_float(p).ln()
                    residual = abs((product.ln() - target) / target)
                    self.assertLess(float(residual), 3e-13)

    def test_ca_and_os_agree_for_single_reference(self):
        for p in (.95, .01, 1e-100):
            self.assertEqual(ct.ca_coefficient_iid_exponential(p, 1).alpha,
                             ct.os_coefficient_iid_exponential(p, 1, 1).alpha)

    def test_ca_round_trip_grid(self):
        for n in (1, 2, 8, 257, ct.MAX_REFERENCES):
            for p in (.999, .5, .01, 1e-20, 1e-200):
                with self.subTest(n=n, p=p):
                    r = ct.ca_coefficient_iid_exponential(p, n)
                    self.assertRelative(ct.ca_log_pfa_iid_exponential(r.alpha, n),
                                        math.log(p), 3e-13)

    def test_os_round_trip_grid(self):
        for n in (2, 8, 32):
            for k in (1, n // 2, n):
                for p in (.999, .5, .01, 1e-20, 1e-200):
                    with self.subTest(n=n, k=k, p=p):
                        r = ct.os_coefficient_iid_exponential(p, n, k)
                        self.assertRelative(ct.os_log_pfa_iid_exponential(r.alpha, n, k),
                                            math.log(p), 3e-13)

    def test_near_one_probability_not_rounded_to_zero_alpha(self):
        p = math.nextafter(1.0, 0.0)
        for r in (ct.ca_coefficient_iid_exponential(p, 100),
                  ct.os_coefficient_iid_exponential(p, 100, 75)):
            self.assertGreater(r.alpha, 0)
            self.assertRelative(r.reconstructed_log_pfa, math.log(p), 3e-13)

    def test_subnormal_probability_with_finite_coefficient(self):
        for r in (ct.ca_coefficient_iid_exponential(5e-324, 2),
                  ct.os_coefficient_iid_exponential(5e-324, 16, 12)):
            self.assertTrue(math.isfinite(r.alpha))
            self.assertRelative(r.reconstructed_log_pfa, math.log(5e-324), 3e-13)

    def test_ca_unrepresentable_coefficient_is_failure(self):
        with self.assertRaises(ct.CFARNumericalError):
            ct.ca_coefficient_iid_exponential(5e-324, 1)

    def test_os_unrepresentable_coefficient_is_failure(self):
        with self.assertRaises(ct.CFARNumericalError):
            ct.os_coefficient_iid_exponential(5e-324, 32, 1)

    def test_os_iteration_failure_has_no_ca_fallback(self):
        with patch.object(ct, "MAX_BISECTION_ITERATIONS", 1):
            with self.assertRaises(ct.CFARNumericalError):
                ct.os_coefficient_iid_exponential(1e-6, 32, 24)

    def test_residual_failure_does_not_return_a_coefficient(self):
        with patch.object(ct, "_ca_log_pfa", return_value=-1.0):
            with self.assertRaises(ct.CFARNumericalError):
                ct.ca_coefficient_iid_exponential(.1, 8)

    def test_smaller_probability_requires_larger_coefficient(self):
        for method in (lambda p: ct.ca_coefficient_iid_exponential(p, 32),
                       lambda p: ct.os_coefficient_iid_exponential(p, 32, 24)):
            values = [method(p).alpha for p in (.1, .01, 1e-4, 1e-8)]
            self.assertTrue(all(a < b for a, b in zip(values, values[1:])))

    def test_larger_os_rank_requires_smaller_coefficient(self):
        values = [ct.os_coefficient_iid_exponential(.01, 16, k).alpha
                  for k in (1, 4, 8, 12, 16)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))

    def test_ca_mean_coefficient_not_sum_coefficient(self):
        r = ct.ca_coefficient_iid_exponential(.001, 32)
        self.assertRelative((1 + r.alpha / 32) ** -32, .001)
        self.assertGreater(abs((1 + r.alpha) ** -32 - .001), .0009)

    def test_zero_alpha_returns_log_probability_zero(self):
        self.assertEqual(ct.ca_log_pfa_iid_exponential(0, 10), 0)
        self.assertEqual(ct.os_log_pfa_iid_exponential(0, 10, 7), 0)

    def test_log_probability_handles_largest_finite_alpha(self):
        for value in (ct.ca_log_pfa_iid_exponential(sys.float_info.max, 16),
                      ct.os_log_pfa_iid_exponential(sys.float_info.max, 16, 12)):
            self.assertTrue(math.isfinite(value))
            self.assertLess(value, 0)

    def test_positive_alpha_log_underflow_is_failure_not_probability_one(self):
        with self.assertRaises(ct.CFARNumericalError):
            ct.ca_log_pfa_iid_exponential(5e-324, 100)
        with self.assertRaises(ct.CFARNumericalError):
            ct.os_log_pfa_iid_exponential(5e-324, 100, 10)

    def test_os_partial_term_underflow_is_not_silently_dropped(self):
        with self.assertRaises(ct.CFARNumericalError):
            ct.os_log_pfa_iid_exponential(5e-324, 2, 2)

    def test_invalid_probabilities_rejected(self):
        for p in (None, True, False, "0.01", 0, 1, -0.1, 2, float("nan"),
                  float("inf"), float("-inf"), 10 ** 1000, [0.01]):
            for fn in (lambda x: ct.ca_coefficient_iid_exponential(x, 16),
                       lambda x: ct.os_coefficient_iid_exponential(x, 16, 12)):
                with self.subTest(p=repr(p)):
                    with self.assertRaises(ct.CFARParameterError):
                        fn(p)

    def test_invalid_reference_counts_rejected(self):
        for n in (None, True, 0, -1, 8.0, "8", ct.MAX_REFERENCES + 1):
            for fn in (lambda x: ct.ca_coefficient_iid_exponential(.01, x),
                       lambda x: ct.os_coefficient_iid_exponential(.01, x, 1)):
                with self.subTest(n=n):
                    with self.assertRaises(ct.CFARParameterError):
                        fn(n)

    def test_invalid_ranks_not_clipped_or_interpolated(self):
        for k in (None, True, 0, -1, 17, 12.0, .75, "12"):
            with self.subTest(k=k):
                with self.assertRaises(ct.CFARParameterError):
                    ct.os_coefficient_iid_exponential(.01, 16, k)

    def test_invalid_alphas_rejected(self):
        for a in (None, True, "1", -1, float("inf"), float("nan"), 10 ** 1000):
            for fn in (lambda x: ct.ca_log_pfa_iid_exponential(x, 8),
                       lambda x: ct.os_log_pfa_iid_exponential(x, 8, 6)):
                with self.subTest(a=repr(a)):
                    with self.assertRaises(ct.CFARParameterError):
                        fn(a)

    def test_no_default_scientific_arguments(self):
        for fn in (ct.ca_coefficient_iid_exponential, ct.os_coefficient_iid_exponential,
                   ct.ca_log_pfa_iid_exponential, ct.os_log_pfa_iid_exponential):
            self.assertTrue(all(p.default is inspect.Parameter.empty
                                for p in inspect.signature(fn).parameters.values()))

    def test_result_is_immutable(self):
        r = ct.ca_coefficient_iid_exponential(.01, 16)
        with self.assertRaises(FrozenInstanceError):
            r.alpha = 0

    def test_result_has_explicit_model_and_numeric_evidence(self):
        r = ct.os_coefficient_iid_exponential(.01, 16, 12)
        self.assertEqual((r.method, r.p_cell, r.n_reference, r.rank), ("OS", .01, 16, 12))
        self.assertEqual(r.model, "iid_exponential_cut_and_references")
        self.assertEqual(r.implementation_version, ct.IMPLEMENTATION_VERSION)
        self.assertLessEqual(r.relative_log_probability_residual,
                             r.log_probability_relative_tolerance)
        self.assertLessEqual(r.absolute_log_probability_residual,
                             r.log_probability_absolute_tolerance)
        self.assertEqual(json.loads(json.dumps(asdict(r), allow_nan=False))["alpha"], r.alpha)

    def test_os_at_reference_count_resource_boundary(self):
        r = ct.os_coefficient_iid_exponential(.01, ct.MAX_REFERENCES, 75_000)
        self.assertGreater(r.alpha, 0)
        self.assertLessEqual(r.absolute_log_probability_residual,
                             ct.LOG_PROBABILITY_ABSOLUTE_TOLERANCE)

    def test_ca_has_no_os_rank(self):
        self.assertIsNone(ct.ca_coefficient_iid_exponential(.1, 4).rank)


if __name__ == "__main__":
    unittest.main()
