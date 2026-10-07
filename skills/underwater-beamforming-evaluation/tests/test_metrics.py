"""Synthetic numerical tests; no values in this file are real-data defaults."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

try:
    import matplotlib  # noqa: F401
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("beamforming_metrics", ROOT / "scripts" / "beamforming_metrics.py")
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


class MetricTests(unittest.TestCase):
    def test_db_mean_reduction_uses_linear_power(self):
        reduced, scale = metrics.reduce_spectrum(np.array([[0.0], [10.0]]), "mean", "db")
        self.assertEqual(scale, "power")
        self.assertAlmostEqual(reduced[0], 5.5)
        self.assertAlmostEqual(metrics.to_db(reduced, scale)[0], 10 * np.log10(5.5))

    def test_db_sum_reduction_uses_linear_power(self):
        reduced, scale = metrics.reduce_spectrum(np.array([[0.0], [10.0]]), "sum", "db")
        self.assertEqual(scale, "power")
        self.assertAlmostEqual(reduced[0], 11.0)

    def test_max_reduction_preserves_scale(self):
        reduced, scale = metrics.reduce_spectrum(np.array([[0.0, 3.0], [2.0, 1.0]]), "max", "db")
        np.testing.assert_allclose(reduced, [2.0, 3.0])
        self.assertEqual(scale, "db")

    def test_assignment_maximizes_cardinality_before_error(self):
        # Greedy nearest-pair selection matches truth=4 to estimate=3 first and
        # loses truth=0.  The correct maximum-cardinality result has two pairs.
        matches, missing, false = metrics.match_bearings([0.0, 4.0], [3.0, 6.0], 4.0)
        self.assertEqual(len(matches), 2)
        self.assertEqual(missing, [])
        self.assertEqual(false, [])
        self.assertEqual([(m["truth_deg"], m["estimate_deg"]) for m in matches], [(0.0, 3.0), (4.0, 6.0)])

    def test_assignment_wraps_angles(self):
        matches, _, _ = metrics.match_bearings([179.0], [-179.0], 3.0)
        self.assertEqual(matches[0]["abs_error_deg"], 2.0)

    def test_assignment_rejects_invalid_gate(self):
        with self.assertRaises(ValueError):
            metrics.match_bearings([0.0], [0.0], -1.0)

    def test_doa_metrics_counts_misses_and_false_alarms(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            np.save(tmp / "est.npy", np.array([[3.0, 6.0], [np.nan, np.nan]]))
            np.save(tmp / "truth.npy", np.array([[0.0, 4.0], [10.0, np.nan]]))
            result = metrics.doa_metrics(argparse.Namespace(
                estimates=str(tmp / "est.npy"), truth=str(tmp / "truth.npy"), gate_deg=4.0,
                max_frame_output=20))
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["miss_count"], 1)
        self.assertEqual(result["false_alarm_count"], 0)
        self.assertAlmostEqual(result["detection_probability"], 2 / 3)

    def test_spectrum_metrics_reports_peak_and_truth_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            np.save(tmp / "power.npy", np.array([1.0, 2.0, 10.0, 2.0, 1.0]))
            np.save(tmp / "angles.npy", np.array([-2.0, -1.0, 0.0, 1.0, 2.0]))
            result = metrics.spectrum_metrics(argparse.Namespace(
                power=str(tmp / "power.npy"), angles=str(tmp / "angles.npy"), scale="power",
                reduce="max", mainlobe_exclusion_deg=1.0, false_peak_threshold_db=12.0,
                truth_deg="0", top_k=3))
        self.assertEqual(result["peak_angle_deg"], 0.0)
        self.assertEqual(result["truth_matches"][0]["abs_error_deg"], 0.0)

    def test_signal_metrics_requires_baseline_for_improvement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            signal = np.r_[np.ones(10), np.full(10, 2.0)]
            np.save(tmp / "signal.npy", signal)
            result = metrics.signal_metrics(argparse.Namespace(
                signal=str(tmp / "signal.npy"), fs=10.0, column=0,
                target_segment="1:2", noise_segment="0:1", interference_segment=None,
                baseline=None, reference=None, detrend="none", eps=1e-12))
        self.assertAlmostEqual(result["segment_snr_db"], 10 * np.log10(4.0))
        self.assertNotIn("snr_improvement_db", result)

    def test_time_frequency_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            matrix = np.ones((3, 4))
            matrix[:, 1] = 100.0
            np.save(tmp / "tf.npy", matrix)
            np.save(tmp / "freq.npy", np.array([10.0, 20.0, 30.0, 40.0]))
            result = metrics.time_frequency_metrics(argparse.Namespace(
                matrix=str(tmp / "tf.npy"), times=None, freqs=str(tmp / "freq.npy"), scale="power",
                target_band="20:20", noise_band="30:40", interference_band=None, baseline=None,
                presence_threshold_db=6.0, floor_percentile=50.0, max_frame_output=20, eps=1e-12))
        self.assertEqual(result["line_presence_fraction"], 1.0)
        self.assertEqual(result["line_break_count"], 0)

    def test_frequency_bearing_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            matrix = np.array([[1, 2, 20, 2, 1], [1, 3, 30, 3, 1], [1, 2, 25, 2, 1]], dtype=float)
            np.save(tmp / "fb.npy", matrix)
            np.save(tmp / "freq.npy", np.array([100.0, 110.0, 120.0]))
            np.save(tmp / "angle.npy", np.array([-2.0, -1.0, 0.0, 1.0, 2.0]))
            result = metrics.freq_bearing_metrics(argparse.Namespace(
                matrix=str(tmp / "fb.npy"), freqs=str(tmp / "freq.npy"), angles=str(tmp / "angle.npy"),
                scale="power", freq_band="100:120", fuse="power-sum", truth_deg=None,
                mainlobe_exclusion_deg=1.0, false_peak_threshold_db=12.0, top_k=3,
                max_frequency_output=20))
        self.assertEqual(result["peak_bearing_mean_deg"], 0.0)
        self.assertEqual(result["fused_spectrum"]["peak_angle_deg"], 0.0)
        self.assertIsNone(result["per_frequency_peak_error_rmse_deg"])

    def test_btr_no_truth_is_descriptive_ridge_not_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            matrix = np.ones((4, 5), dtype=float)
            matrix[np.arange(4), [1, 2, 2, 3]] = 100.0
            np.save(tmp / "btr.npy", matrix)
            np.save(tmp / "time.npy", np.arange(4, dtype=float))
            np.save(tmp / "angle.npy", np.array([-2.0, -1.0, 0.0, 1.0, 2.0]))
            result = metrics.btr_metrics(argparse.Namespace(
                matrix=str(tmp / "btr.npy"), times=str(tmp / "time.npy"), angles=str(tmp / "angle.npy"),
                scale="power", truth_track=None, gate_deg=1.0, top_k=3,
                relative_threshold_db=12.0, max_jump_deg=1.0, background_exclusion_deg=1.0,
                secondary_peak_threshold_db=6.0, max_frame_output=20))
        self.assertFalse(result["truth_available"])
        self.assertEqual(result["mode"], "ridge-extraction")
        self.assertEqual(result["primary_track_frame_fraction"], 1.0)
        self.assertNotIn("rmse_deg", result)

    def test_spectrum_output_band_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            np.save(tmp / "spectrum.npy", np.array([1.0, 10.0, 1.0, 1.0]))
            np.save(tmp / "freq.npy", np.array([10.0, 20.0, 30.0, 40.0]))
            result = metrics.spectrum_output_metrics(argparse.Namespace(
                spectrum=str(tmp / "spectrum.npy"), freqs=str(tmp / "freq.npy"), column=0,
                scale="power", target_band="20:20", noise_band="30:40",
                interference_band=None, baseline=None, floor_percentile=50.0, eps=1e-12))
        self.assertEqual(result["global_peak_freq"], 20.0)
        self.assertAlmostEqual(result["band_snr_db"], 10 * np.log10(10.0 / 2.0))
        self.assertNotIn("target_band_enhancement_db", result)

    def _write_compare(self, directory: Path, missing_second=False):
        with (directory / "metrics.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["algorithm", "rmse", "runtime", "continuity"])
            writer.writerow(["A", "1.0", "10", "0.9"])
            writer.writerow(["B", "2.0", "" if missing_second else "20", "0.8"])
        with (directory / "spec.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["metric", "direction", "weight", "acceptable_max", "critical"])
            writer.writerow(["rmse", "lower", "1", "2", "true"])
            writer.writerow(["runtime", "lower", "1", "30", "false"])
            writer.writerow(["continuity", "higher", "1", "", "false"])

    def test_engineering_missing_threshold_value_is_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._write_compare(tmp, missing_second=True)
            result = metrics.compare_metrics(argparse.Namespace(
                metrics=str(tmp / "metrics.csv"), spec=str(tmp / "spec.csv"), mode="engineering"))
        by_algorithm = {x["algorithm"]: x for x in result["engineering_acceptance"]["decisions"]}
        self.assertEqual(by_algorithm["A"]["decision"], "通过")
        self.assertEqual(by_algorithm["B"]["decision"], "信息不足")

    def test_metric_spec_rejects_duplicate_and_negative_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.csv"
            path.write_text("metric,direction,weight\na,higher,1\na,lower,1\n")
            with self.assertRaises(ValueError):
                metrics.load_metric_specs(str(path))
            path.write_text("metric,direction,weight\na,higher,-1\n")
            with self.assertRaises(ValueError):
                metrics.load_metric_specs(str(path))

    @unittest.skipUnless(HAS_MATPLOTLIB, "matplotlib is optional")
    def test_plot_commands_generate_inspectable_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._write_compare(tmp)
            compare = metrics.compare_metrics(argparse.Namespace(
                metrics=str(tmp / "metrics.csv"), spec=str(tmp / "spec.csv"), mode="dual"))
            (tmp / "compare.json").write_text(json.dumps(compare))
            plot_dir = tmp / "compare-plots"
            result = metrics.plot_compare(argparse.Namespace(
                compare_json=str(tmp / "compare.json"), output_dir=str(plot_dir), dpi=80,
                skip_metric_plots=False))
            self.assertTrue(result["files"])
            self.assertTrue(all(Path(path).is_file() for path in result["files"]))

            pareto_path = tmp / "pareto.png"
            pareto = metrics.plot_pareto(argparse.Namespace(
                metrics=str(tmp / "metrics.csv"), spec=str(tmp / "spec.csv"), x="runtime", y="rmse",
                output=str(pareto_path), scenario=None, label_points=True, dpi=80))
            self.assertTrue(pareto_path.is_file())
            self.assertTrue(Path(pareto["files"]["json"]).is_file())

            scenario_metrics = tmp / "scenario.csv"
            scenario_metrics.write_text(
                "algorithm,snr_db,rmse,runtime,continuity\nA,-10,3,10,0.7\nA,0,1,10,0.9\nB,-10,4,20,0.6\nB,0,2,20,0.8\n")
            curve_path = tmp / "curve.png"
            curve = metrics.plot_scenario_curves(argparse.Namespace(
                metrics=str(scenario_metrics), spec=str(tmp / "spec.csv"), x="snr_db", y="rmse",
                output=str(curve_path), scenario=None, x_order=None, aggregate="mean", dpi=80))
            self.assertTrue(curve_path.is_file())
            self.assertTrue(Path(curve["files"]["json"]).is_file())

            radar_path = tmp / "radar.png"
            radar = metrics.plot_radar(argparse.Namespace(
                metrics=str(tmp / "metrics.csv"), spec=str(tmp / "spec.csv"), output=str(radar_path),
                include_metrics="rmse,runtime,continuity", scenario=None, max_candidates=8, dpi=80))
            self.assertTrue(radar_path.is_file())
            self.assertTrue(Path(radar["files"]["json"]).is_file())

    def test_cli_emits_strict_json_for_spectrum(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            np.save(tmp / "power.npy", np.array([1.0, 4.0, 1.0]))
            process = subprocess.run([
                sys.executable, str(ROOT / "scripts" / "beamforming_metrics.py"), "spectrum",
                "--power", str(tmp / "power.npy"), "--angles=-1,0,1", "--scale", "power",
            ], check=True, capture_output=True, text=True)
            result = json.loads(process.stdout)
        self.assertEqual(result["peak_angle_deg"], 0.0)


if __name__ == "__main__":
    unittest.main()
