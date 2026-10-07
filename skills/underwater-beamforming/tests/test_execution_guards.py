"""Execution-edge regression tests. All inputs and confirmations are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from test_numerical import numerical_fixture, mock_confirm
import beamforming_core as core
import execute as runner
import preflight


class ExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beamforming-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = numerical_fixture(self.folder)
        self.plan = self.config["plan"]
        self.dest = Path(self.plan["output"]["directory"])

    def test_each_numeric_field_is_required_before_source_read(self):
        for key in runner.NUMERICS:
            with self.subTest(key=key):
                c = copy.deepcopy(self.config)
                del c["numerics"][key]
                mock_confirm(c)
                with patch.object(runner, "file_digest", side_effect=AssertionError("must not read")):
                    with self.assertRaises(runner.ExecutionBlocked):
                        runner.execute(c, self.folder)
        self.assertFalse(self.dest.exists())

    def test_existing_beams_not_treated_as_sensors(self):
        inp = self.plan["input"]
        inp["data_role"] = "beamformed"
        self.config["plan"] = {
            "schema_version": "0.2", "input": inp,
            "handoff": {"selected_channels": inp["channels"], "unknown_direction_policy": "allow_anonymous"}}
        mock_confirm(self.config)
        with patch.object(core, "analyze", side_effect=AssertionError("no beamforming allowed")):
            with self.assertRaises(runner.ExecutionBlocked) as caught:
                runner.execute(self.config, self.folder)
        self.assertIn("BYPASS_NOT_EXECUTED", {x["code"] for x in caught.exception.report["issues"]})

    def test_source_change_during_calculation_prevents_publish(self):
        original = core.cbf_weights
        source = Path(self.plan["input"]["source"]["path"])

        def altered(*args):
            result = original(*args)
            with source.open("ab") as handle:
                handle.write(b"SIMULATED CONCURRENT CHANGE")
            return result

        with patch.object(core, "cbf_weights", side_effect=altered):
            with self.assertRaisesRegex(core.NumericalError, "源数据发生变化"):
                runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())

    def test_irfft_imaginary_endpoint_not_silently_discarded(self):
        transform = self.plan["transform"]
        z, starts = core.analyze(np.ones((1000, 2)), transform)
        z[:, 0, :] += 1j
        with self.assertRaisesRegex(core.NumericalError, "虚部"):
            core.synthesize(z, starts, 1000, transform, 1e-12)

    def test_fullband_zero_edges_conflict_at_metadata_gate(self):
        self.plan["processing"]["band_hz"] = [0, 1000]
        self.plan["transform"]["out_of_band"] = "full_band"
        mock_confirm(self.config)
        with patch.object(runner, "file_digest", side_effect=AssertionError("must not read")):
            with self.assertRaises(runner.ExecutionBlocked):
                runner.execute(self.config, self.folder)

    def test_giant_grid_budget_gated_before_allocation(self):
        d = self.plan["direction_plan"]
        del d["directions_deg"]
        d.update(mode="grid", grid_axes=[{"start_deg": -90, "stop_deg": 90,
                                         "step_deg": 0.000001, "include_stop": True}],
                 grid_order="first_axis_slowest")
        mock_confirm(self.config)
        with patch.object(core, "expand_directions", side_effect=AssertionError("must not allocate")):
            with self.assertRaises(runner.ExecutionBlocked):
                runner.execute(self.config, self.folder)

    def test_numeric_failure_no_result_directory(self):
        self.plan["transform"]["hop_samples"] = 256
        self.plan["mvdr"]["covariance_window_frames"] = 8
        mock_confirm(self.config)
        with self.assertRaises(core.NumericalError):
            runner.execute(self.config, self.folder)
        self.assertFalse(self.dest.exists())

    def test_legacy_report_cannot_authorize_new_configuration(self):
        fake = {"execution_version": "0.3", "can_execute": True,
                "execution_status": "completed", "preflight_status": "passed"}
        with self.assertRaises(runner.ExecutionBlocked):
            runner.execute(fake, self.folder)

    def test_unused_algorithm_config_rejected(self):
        self.plan["algorithms"] = ["cbf"]
        self.config["numerics"]["covariance_schedule"] = "not_applicable"
        mock_confirm(self.config)
        self.assertFalse(runner.check(self.config, self.folder)["can_attempt_execution"])

    def test_success_manifest_is_atomic_last_publication(self):
        # Simulated publication failure must not leave a success result.json.
        self.plan["algorithms"] = ["cbf"]
        del self.plan["mvdr"]
        self.config["numerics"]["covariance_schedule"] = "not_applicable"
        mock_confirm(self.config)
        with patch.object(Path, "rename", side_effect=OSError("simulated publication failure")):
            with self.assertRaises(OSError):
                runner.execute(self.config, self.folder)
        self.assertFalse((self.dest / "result.json").exists())
        self.assertEqual(json.loads((self.dest / "failure.json").read_text())["execution_status"], "failed")


if __name__ == "__main__":
    unittest.main()
