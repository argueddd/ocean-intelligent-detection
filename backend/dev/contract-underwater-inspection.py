"""Independent forward tests of the installed Skill's public CLI.

Run with the project's .venv/bin/python. Fixtures are synthetic and temporary;
source bytes are checked before/after every operation. No model is called.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

import h5py
import numpy as np


PROJECT = Path(__file__).resolve().parents[2]
SKILL = PROJECT / "skills" / "underwater-data-inspection"
CLI = SKILL / "scripts" / "inspect_data.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnderwaterForwardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ocean-inspection-forward-")
        self.root = Path(self.temporary.name)
        self.serial = 0
        self.assertTrue(CLI.is_file(), f"Install the Skill under {SKILL} first")

    def tearDown(self):
        self.temporary.cleanup()

    def npy(self, values, name="recording.npy"):
        source = self.root / name
        np.save(source, values)
        return source

    def pcm(self, values, width, fs=2048):
        self.serial += 1
        source = self.root / f"PCM {width} bytes {self.serial}.wav"
        x = np.asarray(values)
        if x.ndim == 1:
            x = x[:, None]
        with wave.open(str(source), "wb") as handle:
            handle.setnchannels(x.shape[1])
            handle.setsampwidth(width)
            handle.setframerate(fs)
            handle.writeframes(x.astype({1: "u1", 2: "<i2", 4: "<i4"}[width]).tobytes())
        return source

    def run_cli(self, source, config=None, action="run", expected_exit=0):
        self.serial += 1
        out = self.root / f"结果 {self.serial}"
        args = [sys.executable, str(CLI), action, str(source), "--out", str(out)]
        if config is not None:
            config_path = self.root / f"配置 {self.serial}.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            args.extend(["--config", str(config_path)])
        before = digest(source)
        completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, expected_exit, completed.stdout + completed.stderr)
        self.assertEqual(digest(source), before, "The Skill must never repair or overwrite source data")
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(completed.stdout)["status"], result["status"])
        # JSON must use null for unavailable numeric values, never NaN/Inf tokens.
        json.loads((out / "result.json").read_text(), parse_constant=lambda x: self.fail(x))
        return result, {row["id"]: row for row in result["checks"]}, out

    def test_pcm8_and_pcm32_preserve_numeric_encoding_and_selected_order(self):
        for width, values in (
            (1, np.array([[0, 128], [128, 255], [255, 0], [128, 128]], dtype=np.uint8)),
            (4, np.array([[-2147483648, 17], [0, -17], [2147483647, 123], [1, -123]], dtype=np.int32)),
        ):
            with self.subTest(width=width):
                source = self.pcm(values, width)
                result, checks, _ = self.run_cli(source, {"block_samples": 1, "channel_ids": ["A", "B"]})
                self.assertEqual(result["dataset"]["original_dtype"], str(values.dtype))
                self.assertFalse(result["dataset"]["source_values_modified"])
                for index, row in enumerate(result["quality"]["channels"]):
                    x = values[:, index].astype(np.float64)
                    self.assertEqual(row["channel_id"], ["A", "B"][index])
                    self.assertEqual(row["zero_count"], int(np.count_nonzero(x == 0)))
                    self.assertAlmostEqual(row["mean"], float(x.mean()), places=7)
                    self.assertAlmostEqual(row["rms"], float(np.sqrt(np.mean(x*x))), places=6)
                self.assertEqual(checks["channel_quality.clipping"]["status"], "not_implemented")

    def test_dc_two_tones_and_frequency_band_do_not_filter_or_normalize_waveform(self):
        fs = 2048
        time = np.arange(2048) / fs
        values = 17 + 2*np.sin(2*np.pi*128*time) + 3*np.sin(2*np.pi*512*time)
        source = self.npy(values, "中文 waveform.npy")
        result, checks, out = self.run_cli(source, {
            "mode": "analyze", "sample_axis": 0, "sample_rate_hz": fs,
            "nperseg": 256, "band_hz": [100, 160], "units": "ADC counts",
        })
        channel = result["analysis"]["channels"][0]
        self.assertEqual(channel["strongest_bin_hz"], 128)
        self.assertAlmostEqual(channel["full_band_psd_integral"], (2**2+3**2)/2, places=8)
        self.assertAlmostEqual(result["quality"]["channels"][0]["mean"], 17, places=10)
        with np.load(out / "analysis_products.npz", allow_pickle=False) as products:
            np.testing.assert_array_equal(products["waveform"][:, 0], values)
            self.assertTrue(np.all((products["frequency_hz"] >= 100) & (products["frequency_hz"] <= 160)))
            # The saved cropped PSD contains the 128 Hz tone only; the full-band
            # power includes the 512 Hz tone, proving that no bandpass was applied.
            self.assertAlmostEqual(float(products["psd_ch0"].sum()*8), 2, places=8)
        self.assertEqual(checks["standardization.units"]["status"], "completed")
        self.assertEqual(checks["channel_quality.calibration"]["status"], "not_implemented")

    def test_known_antiphase_pair_has_evidence_without_polarity_fault_claim(self):
        fs = 1024
        tone = np.sin(2*np.pi*96*np.arange(1024)/fs)
        source = self.npy(np.column_stack([tone, -tone]))
        result, checks, out = self.run_cli(source, {
            "mode": "analyze", "sample_axis": 0, "sample_rate_hz": fs, "nperseg": 128,
            "channel_ids": ["sensor-left", "sensor-right"], "units": "raw ADC",
        })
        pair = result["analysis"]["pairs"][0]
        self.assertAlmostEqual(pair["correlation"], -1, places=12)
        with np.load(out / "analysis_products.npz", allow_pickle=False) as products:
            frequency_index = int(np.flatnonzero(products["frequency_hz"] == 96)[0])
            self.assertAlmostEqual(float(products[pair["coherence_product"]][frequency_index]), 1, places=10)
            np.testing.assert_array_equal(products["waveform"], np.column_stack([tone, -tone]))
        self.assertEqual(checks["channel_quality.calibration"]["status"], "not_implemented")
        self.assertEqual(checks["channel_quality.synchronization"]["status"], "not_implemented")

    def test_nonfinite_outside_analysis_budget_is_still_found_by_full_quality_check(self):
        fs = 1024
        tone = np.sin(2*np.pi*96*np.arange(1024)/fs)
        values = np.column_stack([tone, tone])
        values[900:905, 1] = np.nan
        source = self.npy(values)
        result, checks, out = self.run_cli(source, {
            "mode": "analyze", "sample_axis": 0, "sample_rate_hz": fs,
            "analysis_max_samples": 256, "nperseg": 128, "block_samples": 13,
        })
        bad = result["quality"]["channels"][1]
        self.assertEqual(bad["sample_count"], 1024)
        self.assertEqual(bad["finite_count"], 1019)
        self.assertEqual(bad["nonfinite_ranges"], [[900, 905]])
        self.assertEqual(checks["integrity.nonfinite"]["status"], "completed")
        self.assertEqual(checks["analysis.psd"]["status"], "partial")
        self.assertEqual(checks["analysis.psd"]["coverage"]["sample_range"], [0, 256])
        self.assertEqual([row["status"] for row in result["analysis"]["channels"]], ["completed", "completed"])
        with np.load(out / "analysis_products.npz", allow_pickle=False) as products:
            np.testing.assert_array_equal(products["waveform"], values[:256])

    def test_block_sizes_do_not_change_run_positions_or_finite_denominators(self):
        values = np.array([99, 99, 0, 0, 0, 0, 0, np.nan, np.inf, -np.inf, 3, 3, 3, 3, 3, 3, -7, 9], dtype=float)
        source = self.npy(values)
        rows = []
        for block in (1, 2, 7, 64):
            result, _, _ = self.run_cli(source, {
                "sample_axis": 0, "start_sample": 2, "stop_sample": 17, "block_samples": block,
            })
            rows.append(result["quality"]["channels"][0])
        for row in rows:
            self.assertEqual(row["sample_count"], 15)
            self.assertEqual(row["finite_count"], 12)
            self.assertEqual(row["nonfinite_ranges"], [[7, 10]])
            self.assertEqual(row["longest_zero_run"], {"start_sample": 2, "stop_sample": 7, "length": 5})
            self.assertEqual(row["longest_constant_run"], {"start_sample": 10, "stop_sample": 16, "length": 6})
            finite = values[2:17][np.isfinite(values[2:17])]
            self.assertAlmostEqual(row["mean"], float(finite.mean()), places=12)
            self.assertAlmostEqual(row["std_population"], float(finite.std()), places=12)
            self.assertAlmostEqual(row["rms"], float(np.sqrt(np.mean(finite**2))), places=12)

    def test_explicit_wav_header_resolution_preserves_both_sources_and_reason(self):
        source = self.pcm(np.arange(16, dtype=np.int16), 2, fs=2048)
        result, _, _ = self.run_cli(source, {
            "sample_rate_hz": 1024,
            "sample_rate_resolution": {"use": "file", "reason": "Fixture header is the explicitly confirmed rate."},
        })
        rate = result["dataset"]["sample_rate_hz"]
        self.assertEqual(rate["value"], 2048)
        self.assertEqual(rate["state"], "confirmed")
        self.assertEqual([item["value"] for item in rate["sources"]], [2048, 1024])
        self.assertEqual(rate["resolution"]["use"], "file")
        self.assertIn("explicitly confirmed", rate["resolution"]["reason"])
        result, _, _ = self.run_cli(source, {
            "sample_rate_hz": 2048,
            "sample_rate_resolution": {"use": "file", "reason": "There is no conflict."},
        }, expected_exit=2)
        self.assertIn("unneeded_resolution", [issue["code"] for issue in result["issues"]])

    def test_cli_rejects_nonstandard_json_numeric_constants_before_execution(self):
        source = self.npy(np.ones(32))
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                config = self.root / f"invalid-{token}.json"
                config.write_text('{"sample_axis":0,"sample_rate_hz":'+token+'}', encoding="utf-8")
                out = self.root / f"out-{token}"
                before = digest(source)
                completed = subprocess.run([sys.executable, str(CLI), "run", str(source),
                    "--config", str(config), "--out", str(out)], capture_output=True, text=True, timeout=30)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("Invalid JSON numeric constant", completed.stderr)
                self.assertFalse(out.exists())
                self.assertEqual(digest(source), before)

    def test_empty_axes_are_blocked_and_single_sample_checks_are_not_spectral_analysis(self):
        for shape in ((0,), (0, 2), (3, 0)):
            with self.subTest(shape=shape):
                source = self.npy(np.empty(shape), f"empty-{len(shape)}-{shape[0]}.npy")
                result, _, _ = self.run_cli(source, {"sample_axis": 0}, expected_exit=2)
                self.assertIn("empty_data", [issue["code"] for issue in result["issues"]])
                self.assertNotIn("quality", result)
        source = self.npy(np.array([-32768], dtype=np.int16), "single.npy")
        result, checks, _ = self.run_cli(source, {
            "sample_axis": 0, "mode": "analyze", "sample_rate_hz": 2048,
        }, expected_exit=2)
        self.assertEqual(result["quality"]["channels"][0]["rms"], 32768)
        self.assertEqual(checks["integrity.nonfinite"]["status"], "completed")
        self.assertEqual(checks["analysis.psd"]["status"], "blocked")
        self.assertNotIn("analysis", result)

    def test_hdf5_external_and_virtual_storage_are_not_followed(self):
        outside = self.root / "other.h5"
        with h5py.File(outside, "w") as handle:
            handle.create_dataset("remote", data=np.arange(32, dtype=np.float32))
        outside_before = digest(outside)
        source = self.root / "links.h5"
        with h5py.File(source, "w", libver="latest") as handle:
            handle.create_dataset("local", data=np.arange(32, dtype=np.float32))
            handle["external_link"] = h5py.ExternalLink(str(outside), "/remote")
            layout = h5py.VirtualLayout(shape=(32,), dtype=np.float32)
            layout[:] = h5py.VirtualSource(str(outside), "/remote", shape=(32,))
            handle.create_virtual_dataset("virtual", layout)
            handle.create_dataset("external_storage", shape=(32,), dtype="f4", external=[("missing.raw", 0, h5py.h5f.UNLIMITED)])
        result, _, _ = self.run_cli(source, action="probe")
        fields = {row["field"]: row for row in result["probe"]["fields"]}
        self.assertNotIn("/external_link", fields)
        for name in ("/virtual", "/external_storage"):
            self.assertFalse(fields[name]["supported"])
            rejected, _, _ = self.run_cli(source, {"field": name, "sample_axis": 0}, expected_exit=2)
            self.assertIn("unsupported_array", [issue["code"] for issue in rejected["issues"]])
            self.assertNotIn("quality", rejected)
        self.assertEqual(digest(outside), outside_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
