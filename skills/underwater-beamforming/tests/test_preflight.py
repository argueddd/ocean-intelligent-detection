"""Synthetic manifest fixtures, never real-data parameter recommendations."""
import copy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight


def fixture(folder):
    source = folder / "synthetic-manifest-source.bin"
    source.write_bytes(b"UNIT TEST METADATA FIXTURE ONLY; NOT A WAVEFORM")
    stat = source.stat()
    return {
        "schema_version": "0.2",
        "input": {
            "source": {"path": str(source), "field": "data", "size_bytes": stat.st_size,
                       "mtime_ns": stat.st_mtime_ns},
            "representation": "time_waveform_real", "data_role": "sensor_array",
            "axes": ["sample", "channel"], "shape": [16000, 3], "dtype": "float64",
            "sample_rate_hz": 2000, "sample_range": [0, 16000],
            "channels": ["a", "b", "c"], "units": "unknown",
            "time_reference": {"kind": "relative", "origin": "test source sample 0 = 0 s"},
            "processing_history": [],
        },
        "algorithms": ["cbf", "mvdr"],
        "geometry": {
            "channel_ids": ["a", "b", "c"], "coordinates_m": [[0, 0, 0], [0, 1, 0], [0, 2, 0]],
            "coordinate_system": {"name": "test_frame", "origin": "test sensor a",
                                  "x_positive": "test x", "y_positive": "test y",
                                  "z_positive": "test z", "handedness": "right"},
            "reference_m": [0, 0, 0], "model_kind": "nominal",
            "model_description": "synthetic geometry fixture; not measured",
        },
        "propagation": {"model": "plane_wave", "sound_speed_m_s": 1490,
                        "source_or_rationale": "synthetic fixture value only"},
        "synchronization": {"status": "assumed", "details": "unit test simulated choice"},
        "calibration": {"status": "uncalibrated", "handling": "none", "details": "fixture only"},
        "direction_plan": {"mode": "specified", "parameterization": "array_angle", "angle_unit": "deg",
                           "coordinate_frame": "test_frame", "zero_direction": "test broadside",
                           "positive_direction": "toward positive test array axis", "directions_deg": [[20]]},
        "processing": {"channels": ["a", "b", "c"], "band_hz": [20, 500],
                       "preprocessing": [], "precision": "float64"},
        "transform": {"domain": "stft", "window": "hann", "window_periodic": True,
                      "window_samples": 256, "hop_samples": 128, "nfft": 256,
                      "boundary": "zeros", "synthesis": "dual_window",
                      "normalization": "amplitude_preserving", "out_of_band": "zero",
                      "time_alignment": "reference_position"},
        "cbf": {"element_weights": [1, 1, 1], "normalization": "unit_response"},
        "mvdr": {"training": {"mode": "processing_range"}, "covariance_window_frames": 16,
                 "update_interval_frames": 8, "center_snapshots": False,
                 "diagonal_loading": {"mode": "trace_relative", "value": 0.01},
                 "min_snapshots": 8, "max_condition_number": 1e8, "failure_policy": "stop",
                 "normalization": "unit_response"},
        "output": {"directory": str(folder / "future-results"), "format": "npy",
                   "save_time_domain": True, "beam_selection": "all_requested",
                   "auxiliary_products": [], "weights": "save_all", "max_waveform_bytes": 100000000},
    }


def confirm_fixture(plan):
    """Mock decisions for unit tests only; never export them as real user consent."""
    d = preflight.fingerprints(plan)
    plan["parameter_records"] = [
        {"key": key, "kind": "fact" if key == "input" else "processing_choice",
         "status": "confirmed", "value_sha256": digest, "scope_sha256": d["scope_sha256"],
         "evidence": "synthetic unit-test fixture, not user evidence",
         "confirmation": {"method": "user", "reference": "MOCK CONFIRMATION FOR UNIT TEST ONLY"}}
        for key, digest in d["groups"].items()
    ]
    return plan


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beamforming-preflight-test-")
        self.folder = Path(self.temp.name)
        self.plan = fixture(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, resign=True):
        if resign:
            confirm_fixture(self.plan)
        return preflight.check_plan(self.plan, self.folder)

    def assertCode(self, code, report=None):
        report = self.check() if report is None else report
        self.assertIn(code, {i["code"] for i in report["issues"]}, report)
        self.assertFalse(report["can_execute"])
        self.assertNotEqual(report["preflight_status"], "passed")

    def handoff(self, role="beamformed"):
        inp = self.plan["input"]
        inp["data_role"] = role
        if role == "single_sensor":
            inp["shape"][1] = 1
            inp["channels"] = ["a"]
        self.plan = {"schema_version": "0.2", "input": inp,
                     "handoff": {"selected_channels": inp["channels"], "unknown_direction_policy": "allow_anonymous"}}

    def grid(self, start=-30, stop=30, step=10, include=True):
        d = self.plan["direction_plan"]
        del d["directions_deg"]
        d.update(mode="grid", grid_axes=[{"start_deg": start, "stop_deg": stop,
                                         "step_deg": step, "include_stop": include}],
                 grid_order="first_axis_slowest")

    def test_complete_plan_passes_but_cannot_execute(self):
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["parameter_status"], "complete")
        self.assertEqual(r["route"], "beamforming")
        self.assertFalse(r["can_execute"])
        self.assertEqual(r["execution_status"], "not_run")
        self.assertEqual(r["artifacts"], [])
        self.assertEqual(r["planned_beam_count"], 1)
        self.assertEqual(r["estimated_waveform_payload_bytes"], 256000)

    def test_executor_guard_rejects_even_forged_report(self):
        with self.assertRaises(RuntimeError):
            preflight.require_executable({"can_execute": True, "preflight_status": "passed"})

    def test_no_mutation_or_waveform_read(self):
        confirm_fixture(self.plan)
        original = copy.deepcopy(self.plan)
        source = Path(self.plan["input"]["source"]["path"])
        before = source.read_bytes()
        from unittest.mock import patch
        with patch.object(Path, "open", side_effect=AssertionError("must not read waveform")):
            r = self.check(False)
        self.assertEqual(r["preflight_status"], "passed")
        self.assertEqual(self.plan, original)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((self.folder / "future-results").exists())

    def test_missing_every_required_group_blocks(self):
        valid = copy.deepcopy(self.plan)
        for group in ("input", "algorithms", "geometry", "propagation", "synchronization",
                      "calibration", "direction_plan", "processing", "transform", "output", "cbf", "mvdr"):
            with self.subTest(group=group):
                self.plan = copy.deepcopy(valid)
                del self.plan[group]
                self.assertCode("MISSING_PARAMETER")

    def test_values_without_confirmation_are_not_authorized(self):
        self.assertCode("CONFIRMATION_REQUIRED", self.check(False))

    def test_unknown_role_does_not_route(self):
        self.plan["input"]["data_role"] = "unknown"
        r = self.check()
        self.assertCode("UNKNOWN_ROLE", r)
        self.assertEqual(r["route"], "unresolved")

    def test_unknown_mode_no_default_scan(self):
        del self.plan["direction_plan"]["mode"]
        r = self.check()
        self.assertCode("MISSING_PARAMETER", r)
        self.assertIsNone(r["planned_beam_count"])

    def test_grid_missing_step(self):
        self.grid()
        del self.plan["direction_plan"]["grid_axes"][0]["step_deg"]
        self.assertCode("MISSING_PARAMETER")

    def test_grid_decimal_endpoint_exact(self):
        self.grid(-0.3, 0.3, 0.1)
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["planned_beam_count"], 7)

    def test_grid_off_endpoint_not_rounded(self):
        self.grid(0, 1, 0.3)
        self.assertCode("GRID_ENDPOINT")

    def test_grid_excluded_endpoint(self):
        self.grid(0, 1, 0.3, False)
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["planned_beam_count"], 4)

    def test_two_dimensional_grid(self):
        self.grid()
        d = self.plan["direction_plan"]
        d["parameterization"] = "azimuth_elevation"
        d["grid_axes"].append({"start_deg": -10, "stop_deg": 10, "step_deg": 10, "include_stop": True})
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["planned_beam_count"], 21)

    def test_grid_huge_resource_count_does_not_allocate_beams(self):
        self.grid(0, 1000000000, 1)
        r = self.check()
        self.assertEqual(r["planned_beam_count"], 1000000001)
        self.assertCode("OUTPUT_BUDGET", r)

    def test_mode_conflict(self):
        self.plan["direction_plan"]["grid_order"] = "first_axis_slowest"
        self.assertCode("MODE_CONFLICT")

    def test_duplicate_directions(self):
        self.plan["direction_plan"]["directions_deg"] = [[20], [20]]
        self.assertCode("DUPLICATE_VALUE")

    def test_direction_dimension(self):
        self.plan["direction_plan"]["directions_deg"] = [[20, 10]]
        self.assertCode("DIRECTION_DIMENSION")

    def test_elevation_invalid(self):
        self.plan["direction_plan"].update(parameterization="azimuth_elevation", directions_deg=[[20, 100]])
        self.assertCode("ELEVATION_RANGE")

    def test_periodic_duplicate_azimuth(self):
        self.plan["direction_plan"].update(parameterization="azimuth_elevation", directions_deg=[[0, 0], [360, 0]])
        self.assertCode("DUPLICATE_DIRECTION")

    def test_depth_only_no_zero_fill(self):
        self.plan["geometry"]["coordinates_m"] = [[0], [1], [2]]
        self.assertCode("ARRAY_LENGTH")
        self.assertEqual(self.plan["geometry"]["coordinates_m"], [[0], [1], [2]])

    def test_geometry_order_mismatch(self):
        self.plan["geometry"]["channel_ids"] = ["c", "b", "a"]
        self.assertCode("GEOMETRY_MAPPING")

    def test_duplicate_geometry(self):
        self.plan["geometry"]["coordinates_m"][1] = [0, 0, 0]
        self.assertCode("DUPLICATE_VALUE")

    def test_nonfinite_values_rejected(self):
        self.plan["propagation"]["sound_speed_m_s"] = float("nan")
        self.assertCode("INVALID_JSON_VALUE", self.check(False))

    def test_bool_is_not_sample_rate(self):
        self.plan["input"]["sample_rate_hz"] = True
        self.assertCode("INVALID_VALUE")

    def test_sample_range_bounds(self):
        self.plan["input"]["sample_range"] = [100, 17000]
        self.assertCode("SAMPLE_RANGE")

    def test_unknown_channel(self):
        self.plan["processing"]["channels"] = ["a", "b", "missing"]
        self.assertCode("UNKNOWN_CHANNEL")

    def test_channel_order_not_silently_changed(self):
        self.plan["processing"]["channels"] = ["c", "b", "a"]
        self.assertCode("CHANNEL_REORDER")

    def test_frequency_above_nyquist(self):
        self.plan["processing"]["band_hz"] = [20, 2000]
        self.assertCode("ABOVE_NYQUIST")

    def test_frequency_policy_conflict(self):
        self.plan["transform"]["out_of_band"] = "full_band"
        self.assertCode("BAND_POLICY_CONFLICT")

    def test_transform_lengths(self):
        self.plan["transform"]["nfft"] = 128
        self.assertCode("TRANSFORM_LENGTH")

    def test_missing_mvdr_loading_does_not_fallback(self):
        del self.plan["mvdr"]["diagonal_loading"]
        r = self.check()
        self.assertCode("MISSING_PARAMETER", r)
        self.assertEqual(self.plan["algorithms"], ["cbf", "mvdr"])

    def test_explicit_no_loading(self):
        self.plan["mvdr"]["diagonal_loading"] = {"mode": "none", "value": 0}
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])

    def test_inconsistent_loading(self):
        self.plan["mvdr"]["diagonal_loading"] = {"mode": "none", "value": 0.01}
        self.assertCode("LOADING_CONFLICT")

    def test_training_range_missing(self):
        self.plan["mvdr"]["training"] = {"mode": "specified_range"}
        self.assertCode("MISSING_TRAINING_RANGE")

    def test_training_out_of_range(self):
        self.plan["mvdr"]["training"] = {"mode": "specified_range", "sample_range": [0, 20000]}
        self.assertCode("TRAINING_RANGE")

    def test_insufficient_training_frames(self):
        self.plan["mvdr"]["training"] = {"mode": "specified_range", "sample_range": [0, 256]}
        self.assertCode("INSUFFICIENT_TRAINING_FRAMES")

    def test_cbf_only_does_not_require_mvdr(self):
        self.plan["algorithms"] = ["cbf"]
        del self.plan["mvdr"]
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertNotIn("mvdr", r["required_confirmation_groups"])

    def test_unused_algorithm_not_ignored(self):
        self.plan["algorithms"] = ["cbf"]
        self.assertCode("UNUSED_ALGORITHM")

    def test_adaptive_rule_not_silently_executed(self):
        self.plan["mvdr"]["diagonal_loading"]["mode"] = "auto_tune"
        self.assertCode("UNSUPPORTED_VALUE")

    def test_stale_confirmation_after_change(self):
        confirm_fixture(self.plan)
        self.plan["direction_plan"]["directions_deg"] = [[30]]
        self.assertCode("STALE_CONFIRMATION", self.check(False))

    def test_conflicting_record(self):
        confirm_fixture(self.plan)
        self.plan["parameter_records"][0]["status"] = "conflict"
        self.assertCode("PARAMETER_CONFLICT", self.check(False))

    def test_proposal_does_not_count(self):
        confirm_fixture(self.plan)
        self.plan["parameter_records"][0]["status"] = "proposed"
        self.assertCode("NOT_CONFIRMED", self.check(False))

    def test_duplicate_confirmation(self):
        confirm_fixture(self.plan)
        self.plan["parameter_records"].append(copy.deepcopy(self.plan["parameter_records"][0]))
        self.assertCode("DUPLICATE_APPROVAL", self.check(False))

    def test_source_cannot_confirm_processing_choices(self):
        confirm_fixture(self.plan)
        rec = next(r for r in self.plan["parameter_records"] if r["key"] == "transform")
        rec["confirmation"]["method"] = "source"
        self.assertCode("USER_DECISION_REQUIRED", self.check(False))

    def test_source_change_detected(self):
        confirm_fixture(self.plan)
        Path(self.plan["input"]["source"]["path"]).write_bytes(b"changed fixture")
        self.assertCode("SOURCE_CHANGED", self.check(False))

    def test_missing_source(self):
        self.plan["input"]["source"]["path"] = str(self.folder / "missing.bin")
        self.assertCode("SOURCE_UNAVAILABLE")

    def test_output_exists_not_overwritten(self):
        out = Path(self.plan["output"]["directory"])
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("keep")
        self.assertCode("OUTPUT_EXISTS")
        self.assertEqual(sentinel.read_text(), "keep")

    def test_must_save_time_domain(self):
        self.plan["output"]["save_time_domain"] = False
        self.assertCode("TIME_DOMAIN_REQUIRED")

    def test_cannot_auto_select_strongest(self):
        self.plan["output"]["beam_selection"] = "strongest"
        self.assertCode("UNSUPPORTED_VALUE")

    def test_multi_beam_bypass_no_array_parameters(self):
        self.handoff()
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["route"], "beamformed_handoff")
        self.assertEqual(r["required_confirmation_groups"], ["input", "handoff"])
        self.assertFalse(r["can_execute"])

    def test_single_sensor_bypass_keeps_identity(self):
        self.handoff("single_sensor")
        r = self.check()
        self.assertEqual(r["preflight_status"], "passed", r["issues"])
        self.assertEqual(r["route"], "single_sensor_handoff")

    def test_bypass_with_array_config_is_conflict(self):
        old_geometry = self.plan["geometry"]
        self.handoff()
        self.plan["geometry"] = old_geometry
        self.assertCode("ROUTE_CONFLICT")

    def test_required_beam_directions_missing(self):
        self.handoff()
        self.plan["handoff"]["unknown_direction_policy"] = "require_known"
        self.assertCode("MISSING_BEAM_METADATA")

    def test_unknown_keys_rejected(self):
        self.plan["mvdr"]["loadingg"] = 0.1
        self.assertCode("UNKNOWN_KEY")

    def test_representation_not_coerced(self):
        self.plan["input"]["representation"] = "power_spectrum"
        self.assertCode("UNSUPPORTED_VALUE")

    def test_axes_not_guessed(self):
        self.plan["input"]["axes"] = ["channel", "sample"]
        self.assertCode("AXES_NOT_STANDARD")

    def test_uncertain_sync_not_proved(self):
        self.plan["synchronization"]["status"] = "unknown"
        self.assertCode("UNKNOWN_CONDITION")

    def test_duplicate_json_key_rejected(self):
        path = self.folder / "duplicate.json"
        path.write_text('{"schema_version":"0.2","schema_version":"0.1"}')
        with self.assertRaises(ValueError):
            preflight.load_plan(path)

    def test_nonstandard_json_constant_rejected(self):
        path = self.folder / "nan.json"
        path.write_text('{"sample_rate_hz":NaN}')
        with self.assertRaises(ValueError):
            preflight.load_plan(path)

    def test_root_list_rejected(self):
        self.assertCode("ROOT_TYPE", preflight.check_plan([], self.folder))

    def test_cli_creates_only_reports_and_refuses_overwrite(self):
        confirm_fixture(self.plan)
        path = self.folder / "config.json"
        path.write_text(json.dumps(self.plan))
        out = self.folder / "preflight-report"
        command = [sys.executable, str(Path(preflight.__file__)), "check", str(path), "--out", str(out)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual({p.name for p in out.iterdir()}, {"preflight.json", "report.md"})
        report = json.loads((out / "preflight.json").read_text())
        self.assertFalse(report["can_execute"])
        old = (out / "preflight.json").read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertEqual((out / "preflight.json").read_bytes(), old)
        self.assertFalse(Path(self.plan["output"]["directory"]).exists())

    def test_cli_needs_input_exit_two(self):
        path = self.folder / "unconfirmed.json"
        path.write_text(json.dumps(self.plan))
        result = subprocess.run([sys.executable, str(Path(preflight.__file__)), "check", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["preflight_status"], "needs_input")

    def test_digests_do_not_create_confirmations(self):
        before = copy.deepcopy(self.plan)
        value = preflight.fingerprints(self.plan)
        self.assertEqual(len(value["scope_sha256"]), 64)
        self.assertEqual(self.plan, before)
        self.assertNotIn("parameter_records", self.plan)


if __name__ == "__main__":
    unittest.main()
