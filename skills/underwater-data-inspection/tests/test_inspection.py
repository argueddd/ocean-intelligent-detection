"""Behavioral tests using only generated, non-user fixtures."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

import h5py
import numpy as np
from scipy.io import savemat, wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from acoustic_inspection.pipeline import execute, validate_config, exit_code
from acoustic_inspection.readers import Source, probe, select_field


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acoustic-test-")
        self.root = Path(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def run_data(self, path, config=None, probe_only=False):
        self.counter += 1
        out = self.root/f"run{self.counter}"
        r = execute(path, out, config, probe_only=probe_only)
        json.loads((out/"result.json").read_text())
        return r, out

    def npy(self, data):
        p = self.root/f"input{self.counter}.npy"
        np.save(p, data)
        return p

    def test_probe_does_not_choose_field_or_axis(self):
        p = self.root/"ambiguous.npz"
        np.savez(p, data=np.zeros((3, 200)), acoustic=np.zeros((200, 3)))
        r, out = self.run_data(p, probe_only=True)
        self.assertEqual(len(r["probe"]["fields"]), 2)
        self.assertNotIn("dataset", r)
        r, _ = self.run_data(p, {"sample_axis": 0})
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["issues"][-1]["code"], "field_required")

    def test_even_unique_named_field_needs_confirmation(self):
        p = self.root/"single.mat"
        savemat(p, {"sound": np.ones((20, 2))})
        r, _ = self.run_data(p, {"sample_axis": 0})
        self.assertEqual(r["issues"][-1]["code"], "field_required")

    def test_shape_does_not_imply_axis(self):
        r, _ = self.run_data(self.npy(np.ones((3, 500))))
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["issues"][-1]["code"], "sample_axis_required")
        self.assertNotIn("quality", r)

    def test_explicit_transpose_preserves_values_and_source(self):
        x = np.arange(60, dtype=np.int16).reshape(3, 20)
        p = self.npy(x)
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        cfg = validate_config({"sample_axis": 1, "start_sample": 2, "stop_sample": 19, "channels": [0, 2]})
        info = probe(p)
        s = Source(p, info, select_field(info, cfg), cfg)
        try:
            view = s.read(2, 19, [0, 2])
            np.testing.assert_array_equal(view, x[[0, 2], 2:19].T)
            self.assertEqual(view.dtype, x.dtype)
        finally:
            s.close()
        r, _ = self.run_data(p, cfg)
        self.assertEqual(r["dataset"]["view_shape"], [17, 2])
        self.assertEqual(before, hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(r["quality"]["channels"][0]["mean"], np.mean(x[0, 2:19]))

    def test_missing_fs_retains_quality_and_blocks_spectra(self):
        r, out = self.run_data(self.npy(np.arange(64.0)), {"sample_axis": 0, "mode": "analyze"})
        self.assertEqual(r["status"], "partial")
        self.assertIn("quality", r)
        self.assertEqual(r["stages"]["analysis"]["status"], "blocked")
        self.assertFalse((out/"analysis_products.npz").exists())
        self.assertIsNone(r["dataset"]["duration_s"])

    def test_missing_units_not_fabricated(self):
        r, _ = self.run_data(self.npy(np.arange(10)), {"sample_axis": 0})
        self.assertIsNone(r["dataset"]["units"]["value"])
        self.assertEqual(r["dataset"]["channel_identity"]["state"], "missing")

    def test_zero_and_constant_runs_cross_blocks(self):
        x = np.arange(40.0)
        x[3:21] = 0
        x[25:37] = 7
        r, _ = self.run_data(self.npy(x), {"sample_axis": 0, "block_samples": 5, "start_sample": 2, "stop_sample": 39})
        row = r["quality"]["channels"][0]
        self.assertEqual(row["longest_zero_run"], dict(start_sample=3, stop_sample=21, length=18))
        self.assertEqual(row["longest_constant_run"]["length"], 18)
        self.assertAlmostEqual(row["mean"], np.mean(x[2:39]))
        self.assertAlmostEqual(row["std_population"], np.std(x[2:39]))
        self.assertAlmostEqual(row["rms"], np.sqrt(np.mean(x[2:39]**2)))

    def test_nonfinite_counts_and_runs(self):
        x = np.array([0., 0., np.nan, 0., 0., 0., np.inf, -np.inf])
        r, out = self.run_data(self.npy(x), {"sample_axis": 0, "block_samples": 2})
        s = r["quality"]["channels"][0]
        self.assertEqual((s["finite_count"], s["nan_count"], s["positive_inf_count"], s["negative_inf_count"]), (5, 1, 1, 1))
        self.assertEqual(s["longest_zero_run"]["length"], 3)
        self.assertEqual(s["longest_zero_run"]["start_sample"], 3)
        self.assertEqual(s["rms"], 0)
        self.assertNotIn(": NaN", (out/"result.json").read_text())

    def test_nonfinite_ranges_cross_blocks_and_explicit_limit(self):
        x = np.ones(1000)
        x[3:19] = np.nan
        x[25:29] = np.inf
        x[40::2] = np.nan
        r, _ = self.run_data(self.npy(x), {"sample_axis": 0, "block_samples": 5})
        row = r["quality"]["channels"][0]
        self.assertEqual(row["nonfinite_ranges"][:2], [[3, 19], [25, 29]])
        self.assertEqual(len(row["nonfinite_ranges"]), 100)
        self.assertEqual(row["nonfinite_range_count"], 482)
        self.assertTrue(row["nonfinite_ranges_truncated"])

    def test_source_changed_invalidates_results(self):
        p = self.npy(np.arange(64.))
        original = Source.read
        changed = False
        def changing_read(source, start, stop, channels):
            nonlocal changed
            data = original(source, start, stop, channels)
            if not changed:
                import os
                st = p.stat()
                os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns+1000000000))
                changed = True
            return data
        with patch.object(Source, "read", changing_read):
            r, _ = self.run_data(p, {"sample_axis": 0, "block_samples": 8})
        self.assertEqual(r["status"], "failed")
        self.assertFalse(r["results_valid"])
        self.assertEqual(r["issues"][-1]["code"], "source_changed")

    def test_all_nonfinite_has_no_invented_statistics(self):
        r, _ = self.run_data(self.npy(np.full(10, np.nan)), {"sample_axis": 0})
        row = r["quality"]["channels"][0]
        self.assertIsNone(row["mean"])
        self.assertIsNone(row["rms"])
        self.assertEqual(row["longest_constant_run"]["length"], 0)

    def test_hdf5_named_rate_is_only_used_when_explicit(self):
        p = self.root/"record.h5"
        with h5py.File(p, "w") as f:
            f["waveform"] = np.zeros((2, 64))
            f["fs"] = 2048.0
        cfg = {"field": "/waveform", "sample_axis": 1}
        r, _ = self.run_data(p, cfg)
        self.assertIsNone(r["dataset"]["sample_rate_hz"]["value"])
        r, _ = self.run_data(p, {**cfg, "sample_rate_field": "/fs"})
        self.assertEqual(r["dataset"]["sample_rate_hz"]["value"], 2048)

    def wav(self):
        p = self.root/"sample.wav"
        x = (np.sin(np.arange(1000)*.1)*1000).astype("<i2")
        with wave.open(str(p), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(2000)
            f.writeframes(x.tobytes())
        return p, x

    def test_wav_header_and_exact_integer_read(self):
        p, x = self.wav()
        r, _ = self.run_data(p, {"block_samples": 7})
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["dataset"]["sample_rate_hz"]["value"], 2000)
        self.assertAlmostEqual(r["quality"]["channels"][0]["mean"], np.mean(x))
        self.assertEqual(r["dataset"]["original_dtype"], "int16")

    def test_fs_conflict_blocks_analysis_but_keeps_checks(self):
        p, _ = self.wav()
        r, out = self.run_data(p, {"mode": "analyze", "sample_rate_hz": 1000})
        self.assertEqual(r["dataset"]["sample_rate_hz"]["state"], "conflict")
        self.assertEqual(r["status"], "partial")
        self.assertIn("quality", r)
        self.assertFalse((out/"psd.png").exists())

    def test_explicit_fs_resolution_preserves_both_sources(self):
        p, _ = self.wav()
        r, _ = self.run_data(p, {"sample_rate_hz": 1000,
                                "sample_rate_resolution": {"use": "user", "reason": "Fixture header deliberately incorrect."}})
        self.assertEqual(r["dataset"]["sample_rate_hz"]["value"], 1000)
        self.assertEqual(len(r["dataset"]["sample_rate_hz"]["sources"]), 2)

    def test_mat_and_npz_consistent_statistics(self):
        x = np.arange(200, dtype=np.float32).reshape(100, 2)
        for suffix in (".mat", ".npz"):
            p = self.root/("container"+suffix)
            if suffix == ".mat":
                savemat(p, {"data": x, "rate": 2000.})
            else:
                np.savez_compressed(p, data=x, rate=np.array(2000.))
            r, _ = self.run_data(p, {"field": "data", "sample_axis": 0, "sample_rate_field": "rate", "block_samples": 3})
            self.assertEqual(r["status"], "completed")
            self.assertEqual(r["dataset"]["sample_rate_hz"]["value"], 2000.)
            self.assertAlmostEqual(r["quality"]["channels"][1]["rms"], np.sqrt(np.mean(x[:, 1].astype(float)**2)))

    def test_no_squeeze_no_real_part_conversion(self):
        for x in (np.ones((4, 5, 1)), np.ones((10, 2), dtype=complex), np.array([object()], dtype=object)):
            p = self.npy(x)
            r, _ = self.run_data(p, {"sample_axis": 0})
            self.assertEqual(r["status"], "needs_input")
            self.assertNotIn("quality", r)

    def test_large_integer_precision_is_explicit(self):
        r, _ = self.run_data(self.npy(np.array([2**60, 2**60+1], dtype=np.int64)), {"sample_axis": 0})
        self.assertEqual(r["issues"][-1]["code"], "integer_precision")
        self.assertNotIn("quality", r)

    def test_memory_budget_stops_npz_decoding(self):
        p = self.root/"compressed.npz"
        np.savez_compressed(p, sound=np.zeros((10000, 10)))
        r, _ = self.run_data(p, {"field": "sound", "sample_axis": 0, "max_read_mib": .01})
        self.assertEqual(r["issues"][-1]["code"], "memory_budget")

    def test_channel_and_geometry_mismatch_not_repaired(self):
        p = self.npy(np.ones((32, 3)))
        for cfg in ({"channels": [2, 0]}, {"channel_ids": ["A", "B"]}, {"array_geometry_m": [[0, 0, 0]]}):
            r, _ = self.run_data(p, {"sample_axis": 0, **cfg})
            self.assertEqual(r["status"], "needs_input")
            self.assertNotIn("quality", r)

    def test_config_typo_bool_fs_and_bad_slice_rejected(self):
        p = self.npy(np.ones(32))
        for cfg in ({"sample_rate": 2000}, {"sample_rate_hz": True}, {"sample_axis": True},
                    {"stop_sample": 40}, {"nperseg": 0}, {"overlap_fraction": 1}):
            r, _ = self.run_data(p, {"sample_axis": 0, **cfg})
            self.assertEqual(r["status"], "needs_input")

    def test_output_overwrite_refused(self):
        p = self.npy(np.ones(16))
        r, out = self.run_data(p, {"sample_axis": 0})
        before = (out/"result.json").read_bytes()
        with self.assertRaises(FileExistsError):
            execute(p, out, {"sample_axis": 0})
        self.assertEqual(before, (out/"result.json").read_bytes())

    def test_known_tone_power_and_actual_analysis_coverage(self):
        fs = 2048
        t = np.arange(9000)/fs
        x = np.column_stack([np.sin(2*np.pi*128*t), 2*np.sin(2*np.pi*128*t), np.zeros(len(t))])
        p = self.npy(x)
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        r, out = self.run_data(p, {"sample_axis": 0, "mode": "analyze", "sample_rate_hz": fs,
                                  "start_sample": 100, "analysis_max_samples": 4097,
                                  "analysis_max_channels": 2, "nperseg": 512, "block_samples": 37})
        self.assertEqual(r["status"], "completed", r["issues"])
        self.assertEqual(r["quality"]["coverage"]["sample_range"], [100, 9000])
        a = r["analysis"]
        self.assertEqual(a["coverage"]["sample_range"], [100, 4197])
        self.assertFalse(a["coverage"]["complete_requested_range"])
        self.assertEqual(a["coverage"]["unused_tail_samples"], 1)
        self.assertEqual(a["channels"][0]["strongest_bin_hz"], 128)
        self.assertAlmostEqual(a["channels"][0]["full_band_psd_integral"], .5, places=8)
        self.assertAlmostEqual(a["channels"][1]["full_band_psd_integral"], 2., places=8)
        with np.load(out/"analysis_products.npz") as z:
            self.assertAlmostEqual(z["frame_time_s"][0], (100+256)/fs)
            np.testing.assert_array_equal(z["waveform"], x[100:4197, :2])
            self.assertEqual(z["tf_psd_ch0"].shape[1], 15)
        self.assertGreater((out/"psd.png").stat().st_size, 1000)
        self.assertEqual(before, hashlib.sha256(p.read_bytes()).hexdigest())

    def test_invalid_analysis_channel_skipped_without_filling(self):
        x = np.column_stack([np.sin(np.arange(64)), np.ones(64)])
        x[3, 0] = np.nan
        r, out = self.run_data(self.npy(x), {"sample_axis": 0, "mode": "analyze", "sample_rate_hz": 100, "nperseg": 16})
        self.assertEqual(r["status"], "partial")
        self.assertEqual(r["analysis"]["channels"][0]["status"], "skipped")
        with np.load(out/"analysis_products.npz") as z:
            self.assertTrue(np.isnan(z["waveform"][3, 0]))
            self.assertNotIn("psd_ch0", z.files)
            self.assertIn("psd_ch1", z.files)

    def test_short_window_band_and_long_window_block(self):
        p = self.npy(np.ones(32))
        for extra in ({"band_hz": [0, 600]}, {"nperseg": 64}):
            r, _ = self.run_data(p, {"sample_axis": 0, "sample_rate_hz": 1000, "mode": "analyze", **extra})
            self.assertEqual(r["status"], "partial")
            self.assertIn("quality", r)

    def test_single_segment_does_not_claim_coherence(self):
        x = np.column_stack([np.sin(np.arange(16)), np.cos(np.arange(16))])
        r, out = self.run_data(self.npy(x), {"sample_axis": 0, "sample_rate_hz": 100, "mode": "analyze", "nperseg": 16})
        self.assertEqual(r["status"], "completed", r["issues"])
        self.assertIn("coherence_reason", r["analysis"]["pairs"][0])
        with np.load(out/"analysis_products.npz") as z:
            self.assertFalse(any(name.startswith("coherence_") for name in z.files))

    def test_float_wav_explicitly_unsupported(self):
        p = self.root/"float.wav"
        wavfile.write(p, 1000, np.zeros(32, dtype=np.float32))
        r, _ = self.run_data(p, probe_only=True)
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["issues"][-1]["code"], "unsupported_wav")

    def test_cli_duplicate_json_and_exit_status(self):
        p = self.npy(np.ones(64))
        c = self.root/"duplicate.json"
        c.write_text('{"sample_axis":0,"sample_axis":1}')
        proc = subprocess.run([sys.executable, str(ROOT/"scripts/inspect_data.py"), "run",
                               str(p), "--config", str(c), "--out", str(self.root/"cli")],
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Duplicate JSON key", proc.stderr)
        proc = subprocess.run([sys.executable, str(ROOT/"scripts/inspect_data.py"), "run",
                               str(p), "--out", str(self.root/"cli-missing")], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
