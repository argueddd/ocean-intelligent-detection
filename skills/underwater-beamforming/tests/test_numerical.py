"""Synthetic truths and MOCK approvals only; never authorizes any real dataset."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import beamforming_core as core
import execute as runner
import preflight
from test_preflight import fixture, confirm_fixture


def mock_confirm(config):
    confirm_fixture(config["plan"])
    config["approval"] = {
        "status": "confirmed", "scope_sha256": runner.fingerprint(config),
        "evidence": "SYNTHETIC TEST ONLY; NOT REAL USER AUTHORIZATION",
        "confirmation": {"method": "user", "reference": "MOCK TEST ONLY"}}
    return config


def numerical_fixture(folder):
    p = fixture(folder)
    p["schema_version"] = "0.4"
    p["output"].update(beam_selection="explicit_indices", time_domain_beam_indices=[0, 1])
    rng = np.random.default_rng(3103)
    x = rng.normal(scale=0.1, size=(4096, 3))
    t = np.arange(len(x)) / 2000
    x += np.cos(2 * np.pi * 125 * t)[:, None]
    source = folder / "synthetic.npy"
    np.save(source, x, allow_pickle=False)
    stat = source.stat()
    p["input"]["source"] = {"path": str(source), "field": "__array__",
                            "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    p["input"]["shape"] = list(x.shape)
    p["input"]["sample_range"] = [0, len(x)]
    p["input"]["units"] = "synthetic amplitude"
    p["geometry"]["coordinates_m"] = [[0, 0, 0], [0, 0.05, 0], [0, 0.1, 0]]
    p["direction_plan"]["directions_deg"] = [[0], [20]]
    return mock_confirm({
        "execution_version": "0.4", "plan": p, "analysis": None,
        "numerics": {
            "reader": "npy_real_2d", "compute_precision": "float64",
            "source_sha256": runner.file_digest(source),
            "direction_mapping": "look_vector_cos_sin_v1",
            "direction_basis": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "stft_profile": "unscaled_rfft_wola_v1", "edge_bins": "zero",
            "covariance_schedule": "offline_trailing_bootstrap_v1",
            "max_delay_to_window_ratio": 0.1,
            "response_tolerance": 1e-9, "coverage_tolerance": 1e-12,
            "max_working_bytes": 200000000, "max_artifact_bytes": 100000000,
        }})


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.transform = {
            "window": "hann", "window_periodic": True, "window_samples": 128,
            "hop_samples": 32, "nfft": 256, "boundary": "zeros", "synthesis": "dual_window"}
        self.rng = np.random.default_rng(23)

    def test_roundtrip_all_windows_padding_and_synthesis(self):
        x = self.rng.normal(size=(1001, 3))
        for win in ("hann", "hamming", "boxcar"):
            for boundary in ("zeros", "reflect"):
                for periodic in (True, False):
                    for synthesis in ("dual_window", "overlap_add"):
                        with self.subTest(win=win, boundary=boundary, periodic=periodic, synthesis=synthesis):
                            self.transform.update(window=win, boundary=boundary,
                                                  window_periodic=periodic, synthesis=synthesis)
                            z, starts = core.analyze(x, self.transform)
                            y = core.synthesize(z, starts, len(x), self.transform, 1e-12)
                            np.testing.assert_allclose(y, x, atol=2e-14, rtol=1e-13)

    def test_odd_fft_nondivisible_window_hop_roundtrip(self):
        self.transform.update(window_samples=101, hop_samples=29, nfft=137)
        x = self.rng.normal(size=(777, 1))
        z, starts = core.analyze(x, self.transform)
        np.testing.assert_allclose(core.synthesize(z, starts, len(x), self.transform, 1e-12), x, atol=2e-14)

    def test_no_padding_hamming_exact_coverage(self):
        self.transform.update(window="hamming", boundary="no_padding", nfft=128)
        x = self.rng.normal(size=(512, 1))
        z, starts = core.analyze(x, self.transform)
        np.testing.assert_allclose(core.synthesize(z, starts, len(x), self.transform, 1e-12), x, atol=1e-13)

    def test_no_padding_hann_uncovered_endpoint_fails(self):
        self.transform["boundary"] = "no_padding"
        x = self.rng.normal(size=(512, 1))
        z, starts = core.analyze(x, self.transform)
        with self.assertRaises(core.NumericalError):
            core.synthesize(z, starts, len(x), self.transform, 1e-12)

    def test_uncovered_tail_fails(self):
        self.transform.update(window="hamming", boundary="no_padding")
        x = self.rng.normal(size=(513, 1))
        z, starts = core.analyze(x, self.transform)
        with self.assertRaises(core.NumericalError):
            core.synthesize(z, starts, len(x), self.transform, 1e-12)

    def test_zero_overlap_hann_not_invertible(self):
        self.transform["hop_samples"] = 128
        x = np.ones((512, 1))
        z, starts = core.analyze(x, self.transform)
        with self.assertRaises(core.NumericalError):
            core.synthesize(z, starts, len(x), self.transform, 1e-12)

    def test_dc_and_nyquist_roundtrip(self):
        t = np.arange(1024)
        x = np.column_stack((np.ones(1024), (-1.0) ** t))
        z, starts = core.analyze(x, self.transform)
        np.testing.assert_allclose(core.synthesize(z, starts, len(x), self.transform, 1e-12), x, atol=1e-13)

    def test_impulses_and_first_last_samples_roundtrip(self):
        x = np.zeros((1001, 1))
        x[[0, 500, 1000]] = [[1], [-2], [3]]
        z, starts = core.analyze(x, self.transform)
        np.testing.assert_allclose(core.synthesize(z, starts, len(x), self.transform, 1e-12), x, atol=1e-14)

    def test_nan_input_rejected(self):
        with self.assertRaises(core.NumericalError):
            core.analyze(np.full((200, 2), np.nan), self.transform)

    def test_directions_and_decimal_grid_order(self):
        grid = {"mode": "grid", "grid_axes": [
            {"start_deg": -0.3, "stop_deg": 0.3, "step_deg": 0.3, "include_stop": True},
            {"start_deg": 0, "stop_deg": 20, "step_deg": 10, "include_stop": False}]}
        np.testing.assert_allclose(core.expand_directions(grid),
                                   [[-0.3, 0], [-0.3, 10], [0, 0], [0, 10], [0.3, 0], [0.3, 10]])
        vec = core.direction_vectors(np.array([[0, 0], [90, 0], [0, 90]]),
                                     np.eye(3), "azimuth_elevation")
        np.testing.assert_allclose(vec, np.eye(3), atol=1e-15)

    def test_cbf_sign_and_unit_response_independent_truth(self):
        f, speed = 200, 1500
        coordinates = np.array([[0, 0, 0], [0, 1, 0], [0, 2, 0]])
        angle = 30 * np.pi / 180
        # Independent analytic phase: closer positive-y sensor receives earlier.
        truth = np.exp(2j * np.pi * f * coordinates[:, 1] * np.sin(angle) / speed)
        vectors = core.direction_vectors(np.array([[30], [-30]]), np.eye(3), "array_angle")
        a, _ = core.steering(np.array([f]), coordinates, [0, 0, 0], vectors, speed)
        w = core.cbf_weights(a, [1, 2, 1])[0]
        np.testing.assert_allclose(w[:, 0].conj() @ truth, 1, atol=1e-14)
        self.assertLess(abs(w[:, 1].conj() @ truth), 0.85)
        np.testing.assert_allclose(np.sum(w.conj() * a[0], axis=0), 1, atol=1e-14)

    def test_reference_position_phase(self):
        f = np.array([100.0])
        a, delays = core.steering(f, [[0, 0, 0], [0, 1, 0]], [0, 0.5, 0],
                                  np.array([[0, 1, 0]]), 1000)
        np.testing.assert_allclose(delays[:, 0], [0.0005, -0.0005])
        np.testing.assert_allclose(a[0, :, 0], np.exp(-2j * np.pi * 100 * np.array([0.0005, -0.0005])))

    def test_cbf_time_reconstruction_known_plane_wave(self):
        fs, f, speed, angle = 2048, 128, 1500, 25 * np.pi / 180
        t = np.arange(8192) / fs
        yy = np.array([0, 0.4, 0.8, 1.2])
        x = np.cos(2 * np.pi * f * (t[:, None] + yy[None, :] * np.sin(angle) / speed))
        self.transform.update(window_samples=512, hop_samples=128, nfft=512)
        z, starts = core.analyze(x, self.transform)
        coordinates = np.column_stack((np.zeros(4), yy, np.zeros(4)))
        vector = np.array([[np.cos(angle), np.sin(angle), 0]])
        response, _ = core.steering(np.fft.rfftfreq(512, 1 / fs), coordinates, [0, 0, 0], vector, speed)
        weights = core.cbf_weights(response, [1, 1, 1, 1])
        weights[[0, -1]] = 0
        beam = np.einsum("fcb,tfc->tfb", weights.conj(), z)
        out = core.synthesize(beam, starts, len(x), self.transform, 1e-12)[:, 0]
        np.testing.assert_allclose(out[1024:-1024], np.cos(2 * np.pi * f * t[1024:-1024]), atol=2e-4)

    def mvdr_settings(self):
        return {"min_snapshots": 8, "center_snapshots": False,
                "diagonal_loading": {"mode": "trace_relative", "value": 1e-4},
                "max_condition_number": 1e8}

    def test_mvdr_independent_interference_suppression_and_unit_response(self):
        sensor = np.arange(6)
        target = np.exp(1j * np.pi * sensor * np.sin(np.deg2rad(20)))
        interferer = np.exp(1j * np.pi * sensor * np.sin(np.deg2rad(-35)))
        signals = (self.rng.normal(size=(3000, 2)) + 1j * self.rng.normal(size=(3000, 2))) / np.sqrt(2)
        noise = (self.rng.normal(size=(3000, 6)) + 1j * self.rng.normal(size=(3000, 6))) * 0.05
        snapshots = signals[:, :1] * target + 10 * signals[:, 1:] * interferer + noise
        w, condition, delta, residual = core.mvdr_weights(snapshots, target[:, None], self.mvdr_settings(), 1e-9)
        np.testing.assert_allclose(w[:, 0].conj() @ target, 1, atol=1e-12)
        cbf = target / len(target)
        self.assertLess(abs(w[:, 0].conj() @ interferer), abs(cbf.conj() @ interferer) / 10)
        self.assertGreater(delta, 0)
        self.assertLess(condition, 1e8)
        self.assertLess(residual, 1e-9)

    def test_mvdr_singular_no_fallback(self):
        settings = self.mvdr_settings()
        settings["diagonal_loading"] = {"mode": "none", "value": 0}
        with self.assertRaises(core.NumericalError):
            core.mvdr_weights(np.ones((16, 3)), np.ones((3, 1)), settings, 1e-9)

    def test_mvdr_relative_loading_cannot_fix_zero_energy(self):
        with self.assertRaises(core.NumericalError):
            core.mvdr_weights(np.zeros((16, 3)), np.ones((3, 1)), self.mvdr_settings(), 1e-9)

    def test_mvdr_absolute_loading_and_centering(self):
        settings = self.mvdr_settings()
        settings.update(center_snapshots=True, diagonal_loading={"mode": "absolute", "value": 2})
        w, condition, delta, residual = core.mvdr_weights(np.ones((16, 3)), np.ones((3, 1)), settings, 1e-9)
        np.testing.assert_allclose(w[:, 0], 1 / 3)
        self.assertEqual(delta, 2)
        self.assertAlmostEqual(condition, 1)

    def test_mvdr_condition_threshold_stop(self):
        settings = self.mvdr_settings()
        settings["max_condition_number"] = 1.1
        with self.assertRaises(core.NumericalError):
            core.mvdr_weights(np.ones((16, 3)), np.ones((3, 1)), settings, 1e-9)

    def test_mvdr_actual_snapshot_limit(self):
        with self.assertRaises(core.NumericalError):
            core.mvdr_weights(np.ones((2, 3)), np.ones((3, 1)), self.mvdr_settings(), 1e-9)

    def test_offline_bootstrap_and_trailing_windows(self):
        starts = np.arange(0, 1000, 100)
        self.assertEqual(core.training_window(starts, 200, 0, 4), (0, 4))
        self.assertEqual(core.training_window(starts, 200, 650, 4), (1, 5))
        self.assertEqual(core.training_window(starts, 200, 2000, 4), (6, 10))

    def test_boundary_validity_mask(self):
        mask = core.conservative_mask(1000, np.array([-64, 0, 64, 960]), 128, 2.1)
        self.assertFalse(mask[:131].any())
        self.assertFalse(mask[869:].any())
        self.assertTrue(mask[131:869].all())


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beamforming-numerical-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = numerical_fixture(self.folder)
        self.plan = self.config["plan"]
        self.source = Path(self.plan["input"]["source"]["path"])
        self.dest = Path(self.plan["output"]["directory"])

    def check(self, confirm=True):
        if confirm:
            mock_confirm(self.config)
        return runner.check(self.config, self.folder)

    def cbf_only(self):
        self.plan["algorithms"] = ["cbf"]
        del self.plan["mvdr"]
        self.config["numerics"]["covariance_schedule"] = "not_applicable"

    def test_check_is_read_only_and_does_not_load_source(self):
        before = copy.deepcopy(self.config)
        with patch.object(Path, "open", side_effect=AssertionError("waveform read")):
            r = self.check(False)
        self.assertTrue(r["can_attempt_execution"], r["issues"])
        self.assertEqual(self.config, before)
        self.assertFalse(self.dest.exists())

    def test_end_to_end_both_algorithms_saved_with_provenance(self):
        before = self.source.read_bytes()
        r = runner.execute(self.config, self.folder)
        self.assertEqual(r["execution_status"], "completed")
        self.assertEqual(self.source.read_bytes(), before)
        for alg in ("cbf", "mvdr"):
            x = np.load(self.dest / (alg + "_time.npy"))
            self.assertEqual(x.shape, (4096, 2))
            self.assertEqual(x.dtype, np.float64)
            self.assertTrue(np.isfinite(x).all())
            self.assertTrue(np.isrealobj(x))
        self.assertEqual(r["data_role"], "beamformed")
        self.assertEqual(r["source_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(r["handoff_status"], "blocked")
        self.assertEqual(r["downstream_integration"], "not_integrated")
        self.assertTrue(r["valid_sample_intervals"])
        self.assertEqual(np.load(self.dest / "mvdr_weights.npy").shape[-2:], (3, 2))
        self.assertLess(r["stft_identity_max_abs_error"], 1e-12)
        for item in r["artifacts"]:
            self.assertEqual(runner.file_digest(self.dest / item["path"]), item["sha256"])

    def test_missing_parameter_blocks_before_any_read(self):
        del self.plan["direction_plan"]
        with patch.object(runner, "file_digest", side_effect=AssertionError("must not read")):
            with self.assertRaises(runner.ExecutionBlocked):
                runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())

    def test_unconfirmed_numerics_blocks(self):
        del self.config["approval"]
        self.assertFalse(self.check(False)["can_attempt_execution"])

    def test_changed_numerics_stales_confirmation(self):
        self.config["numerics"]["edge_bins"] = "require_real_steering"
        self.assertIn("STALE_EXECUTION_CONFIRMATION", {x["code"] for x in self.check(False)["issues"]})

    def test_unknown_fields_never_ignored(self):
        self.config["numerics"]["guess"] = 1
        self.assertFalse(self.check()["can_attempt_execution"])

    def test_requested_spectrum_without_analysis_blocks(self):
        self.plan["output"]["auxiliary_products"] = ["psd"]
        self.assertFalse(self.check()["can_attempt_execution"])

    def test_unsupported_failure_policy_blocks(self):
        self.plan["mvdr"]["failure_policy"] = "mark_invalid"
        self.assertFalse(self.check()["can_attempt_execution"])

    def test_memory_and_artifact_budgets_block_before_loading(self):
        for key in ("max_working_bytes", "max_artifact_bytes"):
            with self.subTest(key=key):
                c = copy.deepcopy(self.config)
                c["numerics"][key] = 1
                mock_confirm(c)
                with patch.object(np, "load", side_effect=AssertionError("must not load")):
                    with self.assertRaises(runner.ExecutionBlocked):
                        runner.execute(c, self.folder)

    def test_nonorthogonal_basis_not_repaired(self):
        self.config["numerics"]["direction_basis"][1] = [0.1, 1, 0]
        self.assertFalse(self.check()["can_attempt_execution"])

    def test_approximation_limit_blocks(self):
        self.config["numerics"]["max_delay_to_window_ratio"] = 1e-10
        self.assertFalse(self.check()["can_attempt_execution"])

    def test_hash_mismatch_blocks_no_output(self):
        self.config["numerics"]["source_sha256"] = "a" * 64
        mock_confirm(self.config)
        with self.assertRaisesRegex(core.NumericalError, "摘要"):
            runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())

    def replace_source(self, data):
        np.save(self.source, data, allow_pickle=False)
        stat = self.source.stat()
        self.plan["input"]["source"].update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        self.config["numerics"]["source_sha256"] = runner.file_digest(self.source)
        mock_confirm(self.config)

    def test_actual_shape_mismatch_not_transposed(self):
        self.replace_source(np.ones((3, 4096)))
        with self.assertRaisesRegex(core.NumericalError, "形状"):
            runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())

    def test_actual_dtype_mismatch_not_coerced(self):
        self.replace_source(np.ones((4096, 3), dtype=np.float32))
        with self.assertRaisesRegex(core.NumericalError, "dtype"):
            runner.execute(self.config, self.folder)

    def test_actual_nan_no_repair(self):
        x = np.ones((4096, 3))
        x[100, 1] = np.nan
        self.replace_source(x)
        with self.assertRaisesRegex(core.NumericalError, "NaN"):
            runner.execute(self.config, self.folder)

    def test_existing_output_never_overwritten(self):
        self.dest.mkdir()
        sentinel = self.dest / "user-content.txt"
        sentinel.write_text("preserve")
        with self.assertRaises(runner.ExecutionBlocked):
            runner.execute(self.config, self.folder)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_grid_produces_every_direction_in_order(self):
        self.cbf_only()
        d = self.plan["direction_plan"]
        del d["directions_deg"]
        d.update(mode="grid", grid_axes=[{"start_deg": -20, "stop_deg": 20,
                                         "step_deg": 10, "include_stop": True}],
                 grid_order="first_axis_slowest")
        mock_confirm(self.config)
        result = runner.execute(self.config, self.folder)
        self.assertEqual(result["directions_deg"], [[-20], [-10], [0], [10], [20]])
        self.assertEqual(np.load(self.dest / "cbf_time.npy").shape, (4096, 2))
        self.assertEqual(len(result["scan_beams"]), 5)
        self.assertEqual([b["scan_column"] for b in result["beams"]], [0, 1])

    def test_real_edge_policy_rejects_complex_nyquist(self):
        self.cbf_only()
        self.plan["processing"]["band_hz"] = [0, 1000]
        self.plan["transform"]["out_of_band"] = "full_band"
        self.config["numerics"]["edge_bins"] = "require_real_steering"
        mock_confirm(self.config)
        with self.assertRaisesRegex(core.NumericalError, "端点频率"):
            runner.execute(self.config, self.folder)

    def test_broadside_full_band_cbf_preserves_waveform_scale(self):
        self.cbf_only()
        self.plan["direction_plan"]["directions_deg"] = [[0]]
        self.plan["output"]["time_domain_beam_indices"] = [0]
        self.plan["processing"]["band_hz"] = [0, 1000]
        self.plan["transform"]["out_of_band"] = "full_band"
        self.config["numerics"]["edge_bins"] = "require_real_steering"
        mock_confirm(self.config)
        runner.execute(self.config, self.folder)
        np.testing.assert_allclose(np.load(self.dest / "cbf_time.npy")[:, 0],
                                   np.load(self.source).mean(axis=1), atol=2e-14)

    def test_specified_training_range_and_processing_offset(self):
        self.plan["input"]["sample_range"] = [1024, 4096]
        self.plan["mvdr"]["training"] = {"mode": "specified_range", "sample_range": [0, 4096]}
        mock_confirm(self.config)
        result = runner.execute(self.config, self.folder)
        self.assertEqual(result["first_sample_offset_seconds"], 1024 / 2000)
        self.assertEqual(result["source_sample_range"], [1024, 4096])
        self.assertEqual(np.load(self.dest / "mvdr_time.npy").shape, (3072, 2))
        self.assertEqual(np.load(self.dest / "mvdr_training_frame_start_sample.npy")[0], 0)

    def test_cli_check_and_run(self):
        self.cbf_only()
        mock_confirm(self.config)
        path = self.folder / "config.json"
        path.write_text(json.dumps(self.config))
        script = str(Path(runner.__file__))
        check = subprocess.run([sys.executable, "-B", script, "check", str(path)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)
        self.assertFalse(self.dest.exists())
        run = subprocess.run([sys.executable, "-B", script, "run", str(path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["execution_status"], "completed")

    def test_write_failure_has_no_completion_manifest(self):
        self.cbf_only()
        mock_confirm(self.config)
        with patch.object(np, "save", side_effect=OSError("simulated disk full")):
            with self.assertRaises(OSError):
                runner.execute(self.config, self.folder)
        self.assertFalse((self.dest / "result.json").exists())
        self.assertEqual(json.loads((self.dest / "failure.json").read_text())["execution_status"], "failed")

    def test_singular_mvdr_does_not_publish_cbf_partial_success(self):
        self.replace_source(np.ones((4096, 3)))
        self.plan["mvdr"]["diagonal_loading"] = {"mode": "none", "value": 0}
        mock_confirm(self.config)
        with self.assertRaises(core.NumericalError):
            runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
