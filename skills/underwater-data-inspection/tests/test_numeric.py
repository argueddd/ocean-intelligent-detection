"""Quality statistics keep raw units across float64 amplitude ranges."""
import hashlib
import math
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acoustic_inspection.pipeline import execute
from acoustic_inspection.quality import ChannelStats
from acoustic_inspection.readers import InputRequired


class NumericStatisticsTests(unittest.TestCase):
    def stats(self, samples, block, start=0):
        stats = ChannelStats(2, "sensor-C")
        for offset in range(0, len(samples), block):
            stats.feed(samples[offset:offset + block], start + offset)
        return stats.result()

    def assert_relative(self, actual, expected):
        self.assertTrue(math.isfinite(actual), repr(actual))
        if expected == 0:
            self.assertEqual(actual, 0)
        else:
            self.assertTrue(math.isclose(actual, expected, rel_tol=2e-14, abs_tol=0),
                            f"{actual!r} != {expected!r}")

    def decimal_moments(self, samples):
        with localcontext() as context:
            context.prec = 1200
            values = [Decimal.from_float(float(sample)) for sample in samples]
            mean = sum(values) / len(values)
            variance = sum((sample - mean) ** 2 for sample in values) / len(values)
            return float(mean), float(variance.sqrt())

    def test_exact_int64_high_dc_variance_below_float64_integer_limit(self):
        for samples in (np.array([2**53 - 2, 2**53 - 1], dtype=np.int64),
                        np.arange(2**53 - 4, 2**53, dtype=np.int64)):
            expected_mean, expected = self.decimal_moments(samples)
            for block in (1, 2, len(samples)):
                with self.subTest(samples=samples.tolist(), block=block):
                    result = self.stats(samples, block)
                    self.assertEqual(result["mean"], expected_mean)
                    self.assert_relative(result["std_population"], expected)

    def test_high_dc_float_small_variance_matches_decimal_across_blocks(self):
        samples = 1e12 + np.array([-0.01, -0.002, 0., 0.004, 0.012, -0.003, 0.001])
        expected_mean, expected = self.decimal_moments(samples)
        for block in (1, 2, 3, len(samples)):
            with self.subTest(block=block):
                result = self.stats(samples, block)
                self.assertEqual(result["mean"], expected_mean)
                self.assert_relative(result["std_population"], expected)

    def test_adjacent_float64_max_values_preserve_small_relative_variance(self):
        largest = np.finfo(np.float64).max
        samples = np.array([np.nextafter(largest, 0.), largest])
        expected_mean, expected = self.decimal_moments(samples)
        for block in (1, 2):
            with self.subTest(block=block):
                result = self.stats(samples, block)
                self.assertEqual(result["mean"], expected_mean)
                self.assert_relative(result["std_population"], expected)

    def test_tiny_constant_has_nonzero_rms_and_zero_std(self):
        samples = np.full(257, 1e-200)
        for block in (1, 7, len(samples)):
            with self.subTest(block=block):
                result = self.stats(samples, block)
                self.assert_relative(result["mean"], 1e-200)
                self.assert_relative(result["rms"], 1e-200)
                self.assertEqual(result["std_population"], 0)
                self.assertEqual(result["longest_constant_run"],
                                 dict(start_sample=0, stop_sample=257, length=257))

    def test_tiny_mixed_samples_keep_finite_denominator_and_positions(self):
        amplitudes = np.array([1., 1., 0., 0., np.nan, np.nan, 2., -2.,
                               np.inf, -np.inf, -1., 3.])
        samples = amplitudes * 1e-200
        original = samples.tobytes()
        finite = amplitudes[np.isfinite(amplitudes)]
        for block in (1, 2, 5, len(samples)):
            with self.subTest(block=block):
                result = self.stats(samples, block, start=17)
                self.assert_relative(result["mean"], float(finite.mean()) * 1e-200)
                self.assert_relative(result["std_population"], float(finite.std()) * 1e-200)
                self.assert_relative(result["rms"], float(np.sqrt(np.mean(finite ** 2))) * 1e-200)
                self.assertEqual(result["statistics_denominator"], "finite_count")
                self.assertEqual(result["finite_count"], 8)
                self.assertEqual(result["sample_count"], 12)
                self.assertEqual(result["zero_count"], 2)
                self.assertEqual(result["nonfinite_ranges"], [[21, 23], [25, 27]])
                self.assertEqual(result["longest_zero_run"],
                                 dict(start_sample=19, stop_sample=21, length=2))
        self.assertEqual(samples.tobytes(), original)

    def test_block_and_scale_changes_preserve_statistics(self):
        amplitudes = np.array([0., 0.01, 0.01, -0.02, 1., 1., 0., 0.,
                               20., -10., -10., 0.03, 0.03])
        for scale in (1e-200, 1e200):
            samples = amplitudes * scale
            for block in (1, 3, 4, 8, len(samples)):
                with self.subTest(scale=scale, block=block):
                    result = self.stats(samples, block)
                    self.assert_relative(result["mean"], float(amplitudes.mean()) * scale)
                    self.assert_relative(result["std_population"], float(amplitudes.std()) * scale)
                    self.assert_relative(result["rms"], float(np.sqrt(np.mean(amplitudes ** 2))) * scale)

    def test_large_constant_avoids_sum_and_square_overflow(self):
        samples = np.full(9, 1e308)
        for block in (1, 3, len(samples)):
            with self.subTest(block=block):
                result = self.stats(samples, block)
                self.assert_relative(result["mean"], 1e308)
                self.assert_relative(result["rms"], 1e308)
                self.assertEqual(result["std_population"], 0)

    def test_large_signed_values_keep_representable_std_and_rms(self):
        amplitudes = np.array([-3., -1., 1., 3.])
        for block in (1, 2, len(amplitudes)):
            with self.subTest(block=block):
                result = self.stats(amplitudes * 1e200, block)
                self.assert_relative(result["mean"], 0.)
                self.assert_relative(result["std_population"], math.sqrt(5) * 1e200)
                self.assert_relative(result["rms"], math.sqrt(5) * 1e200)

    def test_float64_maximum_has_finite_representable_output(self):
        largest = np.finfo(np.float64).max
        samples = np.array([-largest, largest])
        for block in (1, 2):
            with self.subTest(block=block):
                result = self.stats(samples, block)
                self.assert_relative(result["mean"], 0.)
                self.assert_relative(result["std_population"], largest)
                self.assert_relative(result["rms"], largest)

    def test_unrepresentable_nonzero_statistic_is_numeric_range(self):
        smallest = np.nextafter(0., 1.)
        for block in (1, 2):
            with self.subTest(block=block):
                with self.assertRaises(InputRequired) as error:
                    self.stats(np.array([0., smallest]), block)
                self.assertEqual(error.exception.code, "numeric_range")

    def test_pipeline_preserves_source_and_original_units(self):
        with tempfile.TemporaryDirectory(prefix="numeric-inspection-") as folder:
            root = Path(folder)
            source = root / "tiny.npy"
            np.save(source, np.array([1., 2., -1., 0.]) * 1e-200)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = execute(source, root / "out", dict(sample_axis=0, block_samples=2, units="V"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["dataset"]["units"]["value"], "V")
            self.assertFalse(result["dataset"]["source_values_modified"])
            self.assertFalse(any("normaliz" in transformation or "scal" in transformation
                                 for transformation in result["dataset"]["transformations"]))
            self.assert_relative(result["quality"]["channels"][0]["rms"], math.sqrt(1.5) * 1e-200)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
