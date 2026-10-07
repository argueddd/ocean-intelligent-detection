"""Fail-closed edge cases for metadata and report handling."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_preflight import fixture, confirm_fixture
import preflight


class EdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beamforming-edge-test-")
        self.folder = Path(self.temp.name)
        self.plan = fixture(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def report(self):
        confirm_fixture(self.plan)
        return preflight.check_plan(self.plan, self.folder)

    def test_huge_number_fails_closed(self):
        self.plan["input"]["sample_rate_hz"] = 10 ** 400
        report = self.report()
        self.assertEqual(report["preflight_status"], "invalid")
        self.assertFalse(report["can_execute"])

    def test_overflow_weight_sum_fails_closed(self):
        self.plan["cbf"]["element_weights"] = [1e308, 1e308, 1e308]
        report = self.report()
        self.assertIn("ZERO_WEIGHT_SUM", {i["code"] for i in report["issues"]})

    def test_dangling_output_symlink_rejected(self):
        out = Path(self.plan["output"]["directory"])
        out.symlink_to(self.folder / "absent-target", target_is_directory=True)
        report = self.report()
        self.assertIn("OUTPUT_EXISTS", {i["code"] for i in report["issues"]})
        self.assertTrue(out.is_symlink())
        self.assertFalse((self.folder / "absent-target").exists())

    def test_report_cannot_occupy_future_output(self):
        confirm_fixture(self.plan)
        config = self.folder / "plan.json"
        config.write_text(json.dumps(self.plan))
        for target in (self.folder / "future-results", self.folder / "future-results" / "preflight"):
            result = subprocess.run([sys.executable, str(Path(preflight.__file__)), "check", str(config),
                                     "--out", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse((self.folder / "future-results").exists())

    def test_source_directory_rejected(self):
        self.plan["input"]["source"]["path"] = str(self.folder)
        self.assertIn("SOURCE_UNAVAILABLE", {i["code"] for i in self.report()["issues"]})

    def test_relative_source_resolves_against_config_directory(self):
        self.plan["input"]["source"]["path"] = "synthetic-manifest-source.bin"
        self.assertEqual(self.report()["preflight_status"], "passed")

    def test_nonfinite_exponent_json_never_passes(self):
        file = self.folder / "large.json"
        file.write_text('{"schema_version":"0.2","input":{"sample_rate_hz":1e9999}}')
        plan = preflight.load_plan(file)
        self.assertEqual(preflight.check_plan(plan, self.folder)["preflight_status"], "invalid")

    def test_oversized_configuration_rejected(self):
        file = self.folder / "too-large.json"
        file.write_bytes(b" " * (preflight.MAX_CONFIG_BYTES + 1))
        with self.assertRaises(ValueError):
            preflight.load_plan(file)

    def test_invalid_shapes_and_nested_types_do_not_crash(self):
        cases = [("input", "shape"), ("input", "source"), ("direction_plan", "directions_deg"),
                 ("geometry", "coordinates_m"), ("mvdr", "training"), ("mvdr", "diagonal_loading"),
                 ("processing", "channels"), ("output", "auxiliary_products")]
        for group, key in cases:
            for value in (None, True, 0, "not-a-value", {}, [None], [[None]]):
                with self.subTest(group=group, key=key, value=value):
                    plan = copy.deepcopy(self.plan)
                    plan[group][key] = value
                    confirm_fixture(plan)
                    result = preflight.check_plan(plan, self.folder)
                    self.assertNotEqual(result["preflight_status"], "passed")
                    self.assertFalse(result["can_execute"])

    def test_record_cannot_confirm_absent_group(self):
        confirm_fixture(self.plan)
        record = copy.deepcopy(self.plan["parameter_records"][0])
        record["key"] = "not_a_group"
        self.plan["parameter_records"].append(record)
        report = preflight.check_plan(self.plan, self.folder)
        self.assertIn("UNKNOWN_APPROVAL_KEY", {i["code"] for i in report["issues"]})

    def test_source_only_unknown_units_require_user(self):
        confirm_fixture(self.plan)
        self.plan["parameter_records"][0]["confirmation"]["method"] = "source"
        report = preflight.check_plan(self.plan, self.folder)
        self.assertIn("USER_DECISION_REQUIRED", {i["code"] for i in report["issues"]})

    def test_unconfirmed_input_does_not_get_confirmed_route(self):
        confirm_fixture(self.plan)
        self.plan["parameter_records"][0]["status"] = "proposed"
        report = preflight.check_plan(self.plan, self.folder)
        self.assertEqual(report["route"], "unresolved")

    def test_changed_source_size_cannot_be_hidden_by_old_confirmations(self):
        confirm_fixture(self.plan)
        self.plan["input"]["source"]["size_bytes"] += 1
        report = preflight.check_plan(self.plan, self.folder)
        codes = {i["code"] for i in report["issues"]}
        self.assertIn("SOURCE_CHANGED", codes)
        self.assertIn("STALE_CONFIRMATION", codes)

    def test_report_order_is_deterministic(self):
        del self.plan["geometry"]
        del self.plan["mvdr"]
        config = self.folder / "plan.json"
        config.write_text(json.dumps(self.plan))
        cmd = [sys.executable, str(Path(preflight.__file__)), "check", str(config)]
        results = [subprocess.run(cmd, capture_output=True, text=True).stdout for _ in range(3)]
        self.assertTrue(results[0])
        self.assertEqual(results, [results[0]] * 3)


if __name__ == "__main__":
    unittest.main()
