"""Feature states must follow evidence, scope and actual implementation."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from acoustic_inspection.coverage import CATALOG, attach_coverage
from acoustic_inspection.pipeline import execute
from acoustic_inspection.readers import Source


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coverage-test-")
        self.root = Path(self.temp.name)
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def run_data(self, data, config=None, probe_only=False):
        self.serial += 1
        source = self.root/f"input{self.serial}.npy"
        np.save(source, data)
        out = self.root/f"result{self.serial}"
        result = execute(source, out, config, probe_only=probe_only)
        return result, {c["id"]: c for c in result["checks"]}, out

    def tones(self, n=128, c=2):
        t = np.arange(n)
        return np.column_stack([np.sin(t*.1*(i+1)) for i in range(c)])

    def analysis(self, **kwargs):
        return dict(sample_axis=0, mode="analyze", sample_rate_hz=100,
                    nperseg=16, **kwargs)

    def test_check_success_is_not_all_capabilities_complete(self):
        r, c, _ = self.run_data(self.tones(), {"sample_axis": 0})
        self.assertEqual(r["status"], "completed")
        self.assertFalse(r["coverage_summary"]["all_listed_checks_complete"])
        self.assertEqual(len(c), len(CATALOG))
        self.assertEqual(c["integrity.nonfinite"]["status"], "completed")
        self.assertEqual(c["channel_quality.geometry"]["status"], "blocked")
        self.assertEqual(c["standardization.units"]["status"], "blocked")
        self.assertEqual(c["integrity.acquisition_continuity"]["status"], "not_implemented")
        self.assertEqual(c["analysis.psd"]["status"], "not_run")
        self.assertEqual(r["stages"]["channel_quality"]["assessment_status"], "partial")
        self.assertEqual(sum(r["coverage_summary"]["counts"].values()), len(CATALOG))

    def test_probe_does_not_claim_read_or_numeric_checks(self):
        r, c, _ = self.run_data(self.tones(), probe_only=True)
        self.assertEqual(c["probe.container"]["status"], "completed")
        for key in ("reading.samples", "standardization.units", "integrity.nonfinite", "analysis.psd"):
            self.assertEqual(c[key]["status"], "not_run", key)
        self.assertEqual(c["channel_quality.clipping"]["status"], "not_implemented")

    def test_read_mode_keeps_statistics_not_run(self):
        r, c, _ = self.run_data(self.tones(), {"mode": "read", "sample_axis": 0})
        self.assertEqual(c["reading.samples"]["status"], "completed")
        self.assertEqual(c["channel_quality.statistics"]["status"], "not_run")
        self.assertEqual(c["analysis.waveform"]["status"], "not_run")

    def test_ambiguous_axis_blocks_requested_downstream_checks(self):
        r, c, _ = self.run_data(self.tones(), {"mode": "analyze"})
        self.assertEqual(c["reading.selection"]["status"], "blocked")
        self.assertEqual(c["integrity.nonfinite"]["status"], "blocked")
        self.assertEqual(c["analysis.psd"]["status"], "blocked")
        self.assertNotIn("quality", r)

    def test_missing_fs_preserves_completed_quality(self):
        r, c, _ = self.run_data(self.tones(), {"sample_axis": 0, "mode": "analyze"})
        self.assertEqual(r["status"], "partial")
        self.assertEqual(c["integrity.nonfinite"]["status"], "completed")
        self.assertEqual(c["standardization.sample_rate"]["status"], "blocked")
        self.assertEqual(c["analysis.psd"]["status"], "blocked")
        self.assertTrue(c["standardization.sample_rate"]["required_input"])

    def test_confirmed_metadata_does_not_enable_unimplemented_diagnostics(self):
        cfg = dict(sample_axis=0, sample_rate_hz=100, units="known raw encoding",
                   channel_ids=["sensor-A", "sensor-B"], array_geometry_m=[[0,0,0], [0,0,1]])
        r, c, _ = self.run_data(self.tones(), cfg)
        for key in ("standardization.units", "standardization.sample_rate",
                    "channel_quality.identity", "channel_quality.geometry"):
            self.assertEqual(c[key]["status"], "completed")
        for key in ("channel_quality.clipping", "channel_quality.synchronization", "channel_quality.calibration"):
            self.assertEqual(c[key]["status"], "not_implemented")

    def test_completed_subrange_not_misreported_as_whole_source(self):
        r, c, _ = self.run_data(self.tones(128, 3),
                               self.analysis(start_sample=16, stop_sample=80, channels=[0,2]))
        cov = c["analysis.psd"]["coverage"]
        self.assertEqual(c["analysis.psd"]["status"], "completed")
        self.assertTrue(cov["complete_requested_range"])
        self.assertFalse(cov["complete_source_range"])
        self.assertEqual(cov["source_sample_count"], 128)
        self.assertEqual(cov["source_channel_count"], 3)
        self.assertEqual(cov["sample_range"], [16,80])
        self.assertEqual(cov["channel_indices"], [0,2])

    def test_budget_limited_analysis_reported_partial(self):
        r, c, _ = self.run_data(self.tones(128, 3),
                               self.analysis(analysis_max_samples=64, analysis_max_channels=2))
        self.assertEqual(c["reading.samples"]["status"], "completed")
        self.assertEqual(c["analysis.psd"]["status"], "partial")
        self.assertEqual(c["channel_quality.correlation"]["status"], "partial")
        self.assertEqual(c["analysis.psd"]["coverage"]["sample_range"], [0,64])
        self.assertEqual(c["analysis.psd"]["coverage"]["channel_indices"], [0,1])

    def test_unused_window_tail_reported_in_spectral_scope(self):
        r, c, _ = self.run_data(self.tones(130), self.analysis())
        self.assertEqual(c["analysis.waveform"]["status"], "completed")
        self.assertEqual(c["analysis.psd"]["status"], "partial")
        self.assertEqual(c["analysis.spectrogram"]["coverage"]["sample_range"], [0,128])
        self.assertEqual(c["channel_quality.coherence"]["status"], "partial")

    def test_one_channel_pair_metrics_not_applicable(self):
        r, c, _ = self.run_data(self.tones(c=1), self.analysis())
        self.assertEqual(c["channel_quality.correlation"]["status"], "not_applicable")
        self.assertEqual(c["channel_quality.coherence"]["requested_pair_count"], 0)

    def test_constant_channel_does_not_pass_pair_checks(self):
        x = np.column_stack([np.ones(128), self.tones()[:,0]])
        r, c, _ = self.run_data(x, self.analysis())
        self.assertEqual(c["channel_quality.correlation"]["status"], "blocked")
        self.assertEqual(c["channel_quality.coherence"]["completed_pair_count"], 0)
        self.assertEqual(c["analysis.psd"]["status"], "completed")

    def test_single_window_correlation_and_coherence_have_distinct_states(self):
        r, c, _ = self.run_data(self.tones(16), self.analysis())
        self.assertEqual(c["channel_quality.correlation"]["status"], "completed")
        self.assertEqual(c["channel_quality.coherence"]["status"], "blocked")

    def test_invalid_channel_counts_missing_pairs(self):
        x = self.tones(c=3)
        x[3,2] = np.nan
        r, c, _ = self.run_data(x, self.analysis())
        self.assertEqual(c["analysis.psd"]["status"], "partial")
        self.assertEqual(c["analysis.psd"]["coverage"]["channel_indices"], [0,1])
        self.assertEqual(c["channel_quality.coherence"]["requested_pair_count"], 3)
        self.assertEqual(c["channel_quality.coherence"]["completed_pair_count"], 1)
        self.assertEqual(c["channel_quality.coherence"]["status"], "partial")

    def test_nonfinite_coherence_product_not_counted_as_complete(self):
        r, c, _ = self.run_data(self.tones(), self.analysis())
        r["analysis"]["pairs"][0]["coherence_nonfinite_bins"] = 2
        attach_coverage(r)
        c = {i["id"]: i for i in r["checks"]}
        self.assertEqual(c["channel_quality.coherence"]["status"], "blocked")
        self.assertEqual(c["channel_quality.correlation"]["status"], "completed")

    def test_source_change_invalidates_previous_success_states(self):
        original = Source.read
        def touch_after_read(source, *args):
            value = original(source, *args)
            import os
            st = source.path.stat()
            os.utime(source.path, ns=(st.st_atime_ns, st.st_mtime_ns+100))
            return value
        with patch.object(Source, "read", touch_after_read):
            r, c, _ = self.run_data(self.tones(), {"sample_axis": 0})
        self.assertEqual(r["status"], "failed")
        self.assertEqual(c["integrity.nonfinite"]["status"], "invalidated")
        self.assertEqual(c["integrity.source_stability"]["status"], "failed")
        self.assertEqual(r["readiness"]["sample_checks"], "invalidated")
        self.assertFalse(any(x["status"] == "completed" for x in c.values()))

    def test_csv_and_json_share_evidence_and_scope(self):
        r, c, out = self.run_data(self.tones(), self.analysis())
        with (out/"feature_status.csv").open(encoding="utf-8-sig", newline="") as f:
            exported = {row["id"]:row for row in csv.DictReader(f)}
        self.assertEqual(set(exported), set(c))
        for key, row in c.items():
            self.assertEqual(exported[key]["status"], row["status"])
            if "coverage" in row:
                self.assertEqual(json.loads(exported[key]["coverage"]), row["coverage"])
        self.assertEqual(json.loads((out/"result.json").read_text())["checks"], r["checks"])
        report = (out/"report.md").read_text()
        # Verify computed pair evidence is visible, not only stored in NPZ.
        self.assertIn(r["analysis"]["pairs"][0]["coherence_product"], report)
        self.assertIn("feature_status.csv", report)

    def test_missing_file_keeps_complete_inventory_without_fake_results(self):
        r = execute(self.root/"missing.npy", self.root/"missing-out")
        c = {row["id"]:row for row in r["checks"]}
        self.assertEqual(r["status"], "failed")
        self.assertEqual(c["probe.container"]["status"], "failed")
        self.assertEqual(c["analysis.psd"]["status"], "not_run")
        self.assertFalse(any(v["status"] == "completed" for v in c.values()))


if __name__ == "__main__":
    unittest.main()
