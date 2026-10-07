"""Offline integration of the installed inspection and beamforming Skills.

All values and approval records are SYNTHETIC/MOCK fixtures. They never
authorize real recordings or select physical defaults. No model, external
receiver, or line-spectrum detector is used. Run in the project's .venv.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
BEAMFORMING = PROJECT / "skills" / "underwater-beamforming"
INSPECTION = PROJECT / "skills" / "underwater-data-inspection"
RUN_ROOT = PROJECT / ".run" / "beamforming-integration"
RUN_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(RUN_ROOT / "matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")
for folder in (BEAMFORMING / "scripts", BEAMFORMING / "tests", INSPECTION / "scripts"):
    sys.path.insert(0, str(folder))

import numpy as np
from scipy.signal import get_window, periodogram

import acoustic_inspection.readers as readers
from acoustic_inspection.pipeline import execute as inspect
import analyze_results as post
import bypass_handoff as bypass
import execute as runner
import inspection_handoff as intake
from test_numerical import mock_confirm, numerical_fixture
from test_output_products import approve_post, settings

MOCK = "SYNTHETIC INTEGRATION FIXTURE / MOCK ONLY / NEVER REAL USER AUTHORIZATION"


def approve(config, module=intake):
    config["approval"] = {
        "status": "confirmed", "scope_sha256": module.fingerprint(config),
        "evidence": MOCK, "confirmation": {"method": "user", "reference": MOCK},
    }
    return config


class BeamformingIntegrationContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=RUN_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def cli(self, script, command, path, *, expected=0):
        process = subprocess.run(
            [sys.executable, "-B", "-W", "error::RuntimeWarning", str(script), command, str(path)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        return json.loads(process.stdout if process.stdout.strip() else process.stderr)

    def upstream(self, *, rate=True, role="sensor_array"):
        count = 1 if role == "single_sensor" else 3
        n = 4096
        rng = np.random.default_rng(20261004)
        t = np.arange(n) / 2000
        values = (rng.normal(scale=.1, size=(n, count)) + np.cos(2*np.pi*125*t)[:, None]).astype("float32")
        source = self.folder / "synthetic-input.npy"
        np.save(source, values, allow_pickle=False)
        source_sha = runner.file_digest(source)
        ids = [f"synthetic-sensor-{i}" for i in range(count)]
        config = {"mode": "check", "field": "data", "sample_axis": 0,
                  "channel_ids": ids, "start_sample": 5, "stop_sample": n-6,
                  "block_samples": 113}
        if rate:
            config["sample_rate_hz"] = 2000
        directory = self.folder / "inspection"
        report = inspect(source, directory, config, config_source=MOCK)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["checks"]), 21)
        self.assertEqual(runner.file_digest(source), source_sha)
        channels = [0] if count == 1 else [0, 2]
        request = {
            "handoff_version": "0.1",
            "inspection_result": {"path": str(directory/"result.json"),
                                  "sha256": intake.digest_file(directory/"result.json")},
            "sample_range": [11, n-11], "channel_indices": channels,
            "identity": {"data_role": role, "channel_ids": [ids[i] for i in channels],
                         "role_evidence": MOCK, "mapping_evidence": MOCK},
            "processing_history": {"values": ["synthetic fixture generation"], "evidence": MOCK},
            "time_reference": {"kind": "relative", "origin": "synthetic original source sample zero"},
            "units_policy": "preserve_report_value_or_unknown",
            "inspection_linkage": "accept_size_mtime_link_not_historical_content_hash",
            "limitations_acknowledgement": MOCK,
            "output": {"directory": str(self.folder/"export"), "dtype": "float64",
                       "conversion": "exact_numeric_no_scaling", "block_samples": 101,
                       "max_read_mib": 64, "max_artifact_bytes": 64*1024**2},
        }
        return source, values, source_sha, report, approve(request)

    def exported(self, **options):
        source, values, source_sha, report, request = self.upstream(**options)
        receipt = intake.prepare(request)
        manifest = json.loads(Path(receipt["handoff"]).read_text())
        self.assertEqual(runner.file_digest(source), source_sha)
        return source, values, source_sha, report, request, receipt, manifest

    def execution(self, *, spectra=True):
        upstream = self.exported()
        _, _, _, _, _, receipt, manifest = upstream
        config = numerical_fixture(self.folder)
        plan = config["plan"]
        plan["input"] = copy.deepcopy(manifest["input"])
        plan["input"]["source"]["path"] = str(Path(receipt["handoff"]).parent/"waveforms.npy")
        plan["input"]["sample_range"] = [5, manifest["input"]["shape"][0]-5]
        ids = manifest["input"]["channels"]
        plan["geometry"].update(channel_ids=ids, coordinates_m=[[0, 0, 0], [0, .1, 0]])
        plan["processing"]["channels"] = ids
        plan["cbf"]["element_weights"] = [1, 1]
        plan["output"].update(time_domain_beam_indices=[1], auxiliary_products=["psd"] if spectra else [])
        config["analysis"] = settings(band=plan["processing"]["band_hz"]) if spectra else None
        config["inspection_handoff"] = {"path": receipt["handoff"], "sha256": intake.digest_file(receipt["handoff"])}
        config["numerics"]["source_sha256"] = manifest["waveform"]["sha256"]
        mock_confirm(config)
        return config, upstream

    def forbid_waveform_and_beamforming(self):
        stack = ExitStack()
        for target, name in ((readers.Source, "read"), (runner.np, "load"), (runner.core, "analyze"),
                             (runner.core, "steering"), (runner.core, "mvdr_weights")):
            stack.enter_context(patch.object(target, name, side_effect=AssertionError(f"unexpected {name}")))
        return stack

    def test_public_handoff_cli_preserves_original_values_mapping_and_unapproved_draft(self):
        source, values, source_sha, report, request = self.upstream()
        path = self.folder/"handoff-request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        script = BEAMFORMING/"scripts"/"inspection_handoff.py"
        reviewed = self.cli(script, "review", request["inspection_result"]["path"])
        self.assertFalse(reviewed["can_beamform"])
        self.assertEqual(reviewed["checks"], report["checks"])
        digest = self.cli(script, "digest", path)
        self.assertFalse(digest["authorizes_export"])
        self.assertEqual(digest["scope_sha256"], intake.fingerprint(request))
        self.assertTrue(self.cli(script, "check", path)["can_attempt_export"])
        receipt = self.cli(script, "prepare", path)
        self.assertFalse(receipt["can_beamform"])
        exported = Path(request["output"]["directory"])
        np.testing.assert_array_equal(np.load(exported/"waveforms.npy"), values[11:-11][:, [0, 2]].astype("float64"))
        manifest = json.loads((exported/"handoff.json").read_text())
        self.assertEqual(manifest["source_sample_range"], [11, 4085])
        self.assertEqual(manifest["source_channel_indices"], [0, 2])
        self.assertEqual(manifest["input"]["units"], "unknown")
        self.assertEqual(manifest["not_checked"], report["not_checked"])
        draft = json.loads(Path(receipt["draft"]).read_text())
        self.assertIsNone(draft["approval"])
        self.assertEqual(draft["plan"]["parameter_records"], [])
        self.assertIsNone(draft["plan"]["direction_plan"])
        self.assertEqual(runner.file_digest(source), source_sha)

    def test_export_to_cbf_mvdr_retains_only_requested_beam_and_psd_with_original_time(self):
        config, upstream = self.execution()
        source, _, source_sha, report, _, _, _ = upstream
        result = runner.execute(config)
        destination = Path(config["plan"]["output"]["directory"])
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["original_source_sample_range"], [16, 4080])
        self.assertEqual(result["original_source_channel_indices"], [0, 2])
        self.assertEqual(result["first_sample_offset_seconds"], 16/2000)
        self.assertFalse(result["time_mapping"]["acquisition_continuity_verified"])
        self.assertEqual(result["coverage"]["requested_auxiliary_products"], ["psd"])
        self.assertEqual(result["upstream_inspection"]["checks"], report["checks"])
        self.assertEqual(result["beams"][0]["beam_id"], "beam_000001")
        self.assertEqual(result["beams"][0]["scan_column"], 1)
        self.assertEqual(result["beams"][0]["column"], 0)
        for algorithm in ("cbf", "mvdr"):
            waveform = np.load(destination/(algorithm+"_time.npy"))
            psd = np.load(destination/(algorithm+"_psd.npy"))
            self.assertEqual(waveform.shape, (4064, 1))
            self.assertEqual(waveform.dtype, np.dtype("float64"))
            self.assertEqual(psd.shape[1], 2, "spectra cover every calculated direction")
            self.assertTrue(np.isfinite(waveform).all())
            self.assertTrue(np.isfinite(psd).all())
            self.assertFalse((destination/(algorithm+"_time_frequency_psd.npy")).exists())
        self.assertTrue(result["presentation"]["figures"])
        for relative in result["presentation"]["figures"]:
            self.assertEqual((destination/relative).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        for artifact in result["artifacts"]:
            self.assertEqual(runner.file_digest(destination/artifact["path"]), artifact["sha256"])
        self.assertEqual(runner.file_digest(source), source_sha)
        self.assertEqual(result["handoff_status"], "blocked", "beamforming execution does not invoke detection automatically")

    def test_missing_sample_rate_blocks_export_without_reading_or_computing(self):
        _, _, _, report, request = self.upstream(rate=False)
        self.assertEqual(report["dataset"]["sample_rate_hz"]["state"], "missing")
        with self.forbid_waveform_and_beamforming():
            self.assertFalse(intake.check(request)["can_attempt_export"])
            with self.assertRaises(ValueError):
                intake.prepare(request)
        self.assertFalse(Path(request["output"]["directory"]).exists())

    def test_unapproved_draft_and_missing_direction_block_before_waveform_loading(self):
        config, upstream = self.execution(spectra=False)
        draft = json.loads(Path(upstream[5]["draft"]).read_text())
        missing_direction = copy.deepcopy(config)
        missing_direction["plan"]["direction_plan"] = None
        with self.forbid_waveform_and_beamforming():
            for blocked in (draft, missing_direction):
                with self.subTest(configuration="unapproved draft" if blocked is draft else "missing direction"):
                    self.assertFalse(runner.check(blocked)["can_attempt_execution"])
                    with self.assertRaises(runner.ExecutionBlocked):
                        runner.execute(blocked)
        self.assertFalse(Path(config["plan"]["output"]["directory"]).exists())

    def test_changed_inspection_digest_blocks_export_before_reading(self):
        _, _, _, _, request = self.upstream()
        path = Path(request["inspection_result"]["path"])
        path.write_bytes(path.read_bytes()+b"\n")
        with self.forbid_waveform_and_beamforming():
            self.assertFalse(intake.check(request)["can_attempt_export"])
            with self.assertRaises(ValueError):
                intake.prepare(request)
        self.assertFalse(Path(request["output"]["directory"]).exists())

    def test_changed_execution_scope_or_handoff_digest_blocks_before_algorithms(self):
        config, _ = self.execution(spectra=False)
        changed_scope = copy.deepcopy(config)
        changed_scope["plan"]["output"]["time_domain_beam_indices"] = [0]
        changed_handoff = copy.deepcopy(config)
        changed_handoff["inspection_handoff"]["sha256"] = "0"*64
        mock_confirm(changed_handoff)
        with self.forbid_waveform_and_beamforming():
            for invalid in (changed_scope, changed_handoff):
                with self.subTest(failure="scope" if invalid is changed_scope else "handoff digest"):
                    self.assertFalse(runner.check(invalid)["can_attempt_execution"])
                    with self.assertRaises(runner.ExecutionBlocked):
                        runner.execute(invalid)
        self.assertFalse(Path(config["plan"]["output"]["directory"]).exists())

    def test_saved_beam_postprocessing_uses_saved_column_and_preserves_original_time(self):
        config, _ = self.execution(spectra=False)
        main = runner.execute(config)
        source_directory = Path(config["plan"]["output"]["directory"])
        source_manifest = source_directory/"result.json"
        source_sha = runner.file_digest(source_manifest)
        request = approve_post({
            "product_version": "0.4.2",
            "source_result": {"path": str(source_manifest), "sha256": source_sha},
            "output_directory": str(self.folder/"post"), "algorithms": ["cbf"],
            "analysis_beam_ids": ["beam_000001"], "time_domain_beam_ids": [],
            "auxiliary_products": ["psd", "time_frequency"],
            "analysis": settings(band=config["plan"]["processing"]["band_hz"]),
            "max_working_bytes": 200000000, "max_artifact_bytes": 100000000, "title": MOCK,
        })
        with patch.object(runner.core, "analyze", side_effect=AssertionError("must not recompute beamforming")):
            result = post.execute(request)
        destination = Path(request["output_directory"])
        self.assertFalse(result["beamforming_recomputed"])
        self.assertEqual(result["spectral_beams"][0]["scan_column"], 1)
        self.assertEqual(result["spectral_beams"][0]["source_column"], 0)
        self.assertEqual(result["spectral_beams"][0]["spectral_column"], 0)
        self.assertEqual(result["original_source_sample_range"], main["original_source_sample_range"])
        self.assertEqual(result["first_sample_offset_seconds"], 16/2000)
        self.assertFalse(list(destination.glob("*_time.npy")))
        self.assertFalse((destination/"mvdr_psd.npy").exists())
        starts = np.load(destination/"analysis_frame_start_sample.npy")
        times = np.load(destination/"analysis_time_seconds.npy")
        np.testing.assert_allclose(times, 16/2000+(starts+63.5)/2000)
        waveform = np.load(source_directory/"cbf_time.npy")
        frequencies, expected = periodogram(
            waveform[int(starts[0]):int(starts[0])+128], fs=2000,
            window=get_window("hann", 128, fftbins=True), nfft=128,
            detrend=False, return_onesided=True, scaling="density", axis=0,
        )
        selected = (frequencies >= 20) & (frequencies <= 500)
        actual = np.load(destination/"cbf_time_frequency_psd.npy")
        np.testing.assert_allclose(actual[0], expected[selected], rtol=2e-13, atol=1e-16)
        self.assertEqual(runner.file_digest(source_manifest), source_sha)

    def test_single_sensor_bypass_preserves_unknown_validity_and_never_beamforms_or_detects(self):
        source, values, source_sha, _, _, receipt, manifest = self.exported(role="single_sensor")
        self.assertEqual(Path(receipt["draft"]).name, "bypass-request.json")
        self.assertFalse((Path(receipt["draft"]).parent/"execution-draft.json").exists())
        channel_id = manifest["input"]["channels"][0]
        request = approve({
            "bypass_version": "0.1",
            "source_handoff": {"path": receipt["handoff"], "sha256": intake.digest_file(receipt["handoff"])},
            "selected_channel_ids": [channel_id],
            "signal_metadata": [{"channel_id": channel_id, "algorithm": None, "direction": None, "evidence": MOCK}],
            "frequency_coverage": {"status": "unknown", "band_hz": None, "evidence": MOCK},
            "validity": {"status": "unknown", "sample_intervals": None, "evidence": MOCK},
            "unknown_metadata_policy": "preserve_unknown_for_transfer_only",
            "limitations_acknowledgement": MOCK,
            "output": {"directory": str(self.folder/"bypass"), "block_samples": 97,
                       "max_working_bytes": 64*1024**2, "max_artifact_bytes": 64*1024**2},
        })
        with patch.object(np.fft, "rfft", side_effect=AssertionError("no FFT in data transfer")), \
             patch.object(runner.core, "analyze", side_effect=AssertionError("no beamforming in bypass")):
            transferred = bypass.prepare(request, self.folder)
            accepted = bypass.receive(transferred["handoff"], transferred["sha256"])
        directory = Path(transferred["handoff"]).parent
        self.assertEqual(accepted["data_role"], "single_sensor")
        self.assertFalse(accepted["can_detect"])
        self.assertEqual(accepted["detection_status"], "not_run")
        self.assertIsNone(accepted["valid_sample_mask"])
        self.assertEqual(accepted["signals"][0]["algorithm_status"], "not_applicable")
        self.assertEqual(accepted["signals"][0]["direction_status"], "not_applicable")
        np.testing.assert_array_equal(np.load(directory/"signal_000000.npy")[:, 0], values[11:-11, 0])
        self.assertFalse((directory/"valid_sample_mask.npy").exists())
        self.assertFalse((directory/"detection-draft.json").exists())
        self.assertEqual(runner.file_digest(source), source_sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
