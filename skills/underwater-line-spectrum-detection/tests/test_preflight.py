"""Preflight unit/CLI tests using tiny fabricated files, never sea-trial data."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import preflight as pf
from test_contract_schema import fixture


def npy_bytes(shape=(100, 1), dtype="<f8"):
    text = repr({"descr": dtype, "fortran_order": False, "shape": shape})
    header = (text + " " * ((64 - (10 + len(text) + 1) % 64) % 64) + "\n").encode("latin1")
    count = 1
    for n in shape:
        count *= n
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\0" * count * (8 if dtype == "<f8" else 1)


class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.request = fixture("DetectionRequest")
        self.input = fixture("SignalInput")
        self.descriptor = fixture("AlgorithmDescriptor")
        self.context = {"context_version": "0.1.0", "document_status": "specified",
                        "inputs": ["input.json"], "descriptors": ["descriptor.json"],
                        "source_files": [], "max_source_bytes": 100000}
        p = self.input["payload"]
        p["source_package"]["manifest"] = self.add_source("manifest.json", b'{"fixture":"not a real handoff"}')
        p["processing_history"]["source_configuration"] = self.add_source("config.json", b'{"fixture":"no computation"}')
        p["waveform"]["file_ref"] = self.add_source("signal.npy", npy_bytes())
        p["provenance"] = [copy.deepcopy(p["source_package"]["manifest"])]
        p["validity"].update(status="known", sample_intervals=[[0, 100]])
        p["frequency_coverage"].update(status="known", band_hz=[0, 500])
        d = self.descriptor["payload"]
        d["input_requirements"].update(required_metadata=["/sample_rate_hz", "/validity"],
                                       constraints=[], unknown_metadata_policy="reject_unknown")
        d["parameter_definitions"]["json_schema"] = {
            "type": "object", "properties": {"test_value": {"type": "number", "minimum": 0, "default": 9}},
            "required": ["test_value"], "additionalProperties": False,
        }
        d["processing_definition"] = [
            {"step_id": "fixture-step", "description": "No code or calculation.",
             "parameter_paths": ["/test_value"]},
        ]
        d["product_definitions"] = [
            {"product_id": "fixture-values", "description": "fixture", "dependencies": [],
             "requires_additional_calculation": True, "coordinate_semantics": "fixture"},
            {"product_id": "fixture-plot", "description": "fixture", "dependencies": ["fixture-values"],
             "requires_additional_calculation": False, "coordinate_semantics": "fixture"},
        ]
        task = self.request["payload"]["tasks"][0]
        task["input_ref"]["package_sha256"] = p["source_package"]["manifest"]["sha256"]
        task["resolved_parameters"] = {"test_value": 1}
        task["parameter_evidence"] = [
            {"field": "/resolved_parameters/test_value", "basis": "user_choice", "reference": "FAKE TEST EVIDENCE"},
        ]
        task["processing_steps"] = [{"step_id": "fixture-step", "parameters": {"/test_value": 1}}]
        self.save_docs()

    def add_source(self, name, raw):
        (self.source / name).write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        self.context["source_files"].append({"sha256": sha, "path": name})
        return {"location": {"kind": "package_relative", "path": name},
                "sha256": sha, "availability": "not_checked"}

    def save_docs(self):
        for name, value in (("input.json", self.input), ("descriptor.json", self.descriptor)):
            (self.source / name).write_text(json.dumps(value), encoding="utf-8")

    def run_review(self, confirmation=None):
        self.save_docs()
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            return pf.review(self.request, self.context, self.source, confirmation)

    def codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def assert_blocked(self, report, code=None):
        self.assertEqual(report["review_status"], "blocked", report)
        self.assertFalse(report["can_execute"])
        if code:
            self.assertIn(code, self.codes(report), report["issues"])

    def clean(self):
        report = self.run_review()
        self.assertEqual(report["review_status"], "review_complete_pending_confirmation", report["issues"])
        self.assertFalse(report["can_execute"])
        self.assertFalse(report["authority_verified"])
        return report

    def evidence(self, report):
        return {"evidence_version": "0.1.0", "actor": "user", "decision": "confirm_reviewed_plan",
                "request_id": report["request_id"], "plan_sha256": report["plan_sha256"],
                "statement": "FAKE UNIT TEST statement, NOT user approval.", "reference": "FAKE TEST message"}

    def receipt(self):
        report = self.clean()
        return pf.record_confirmation(report, self.evidence(report), self.base / "receipt.json", self.source)

    def test_valid_review_checks_files_without_execution(self):
        report = self.clean()
        self.assertEqual(len(report["verified_sources"]), 3)
        self.assertEqual(report["execution_status"], "not_run")
        self.assertEqual(report["plan_summary"]["tasks"][0]["resolved_parameters"], {"test_value": 1})

    def test_review_does_not_mutate_documents_or_make_products(self):
        original = copy.deepcopy((self.request, self.input, self.descriptor, self.context))
        self.save_docs()
        before = {str(x): x.read_bytes() for x in self.source.iterdir()}
        self.clean()
        self.assertEqual(original, (self.request, self.input, self.descriptor, self.context))
        self.assertEqual(before, {str(x): x.read_bytes() for x in self.source.iterdir()})

    def test_draft_request_questions_without_algorithm_selection(self):
        self.request = pf.contracts.read_json(ROOT / "assets/templates/DetectionRequest.draft.json")
        report = self.run_review()
        self.assert_blocked(report, "unresolved_request")
        self.assertEqual(report["verified_sources"], [])
        self.assertIsNone(report["plan_sha256"])

    def test_draft_context_not_defaulted(self):
        self.context = pf.contracts.read_json(ROOT / "assets/templates/PreflightContext.draft.json")
        self.assert_blocked(self.run_review(), "context_invalid")

    def test_missing_algorithm_is_question_not_fallback(self):
        self.context["descriptors"] = []
        self.assert_blocked(self.run_review(), "algorithm_not_supplied")

    def test_exact_algorithm_version_and_implementation(self):
        for key in ("detector_version", "implementation_sha256"):
            with self.subTest(key=key):
                doc = copy.deepcopy(self.request)
                self.request["payload"]["tasks"][0]["detector"][key] = "b" * 64
                self.assert_blocked(self.run_review(), "algorithm_not_supplied")
                self.request = doc

    def test_exact_package_and_signal_identity(self):
        for key in ("package_sha256", "signal_id"):
            with self.subTest(key=key):
                doc = copy.deepcopy(self.request)
                self.request["payload"]["tasks"][0]["input_ref"][key] = "b" * 64
                self.assert_blocked(self.run_review(), "input_not_supplied")
                self.request = doc

    def test_missing_required_parameter_does_not_use_default(self):
        self.request["payload"]["tasks"][0]["resolved_parameters"] = {}
        self.assert_blocked(self.run_review(), "parameter_invalid")
        self.assertEqual(self.request["payload"]["tasks"][0]["resolved_parameters"], {})

    def test_parameter_type_range_and_unknown_field(self):
        for value in ({"test_value": "1"}, {"test_value": -1}, {"test_value": 1, "typo": 1}):
            self.request["payload"]["tasks"][0]["resolved_parameters"] = value
            self.assert_blocked(self.run_review(), "parameter_invalid")

    def test_conditional_required_parameter(self):
        schema = self.descriptor["payload"]["parameter_definitions"]["json_schema"]
        schema["properties"]["mode"] = {"enum": ["a", "b"]}
        schema["properties"]["extra"] = {"type": "number"}
        schema["allOf"] = [{"if": {"properties": {"mode": {"const": "b"}}, "required": ["mode"]},
                            "then": {"required": ["extra"]}}]
        self.request["payload"]["tasks"][0]["resolved_parameters"]["mode"] = "b"
        self.assert_blocked(self.run_review(), "parameter_invalid")

    def test_unknown_schema_keyword_and_format_not_ignored(self):
        for key, value in (("required_if", {}), ("format", "unknown-format")):
            schema = self.descriptor["payload"]["parameter_definitions"]["json_schema"]
            schema[key] = value
            self.assert_blocked(self.run_review(), "parameter_schema_unsupported")
            del schema[key]

    def test_open_parameter_schema_is_not_silent_permission(self):
        del self.descriptor["payload"]["parameter_definitions"]["json_schema"]["additionalProperties"]
        self.assert_blocked(self.run_review(), "parameter_schema_unsupported")

    def test_external_schema_reference_never_fetched(self):
        self.descriptor["payload"]["parameter_definitions"]["json_schema"]["$ref"] = "https://example.invalid/evil"
        self.assert_blocked(self.run_review(), "document_invalid")

    def test_parameter_evidence_coverage(self):
        self.request["payload"]["tasks"][0]["parameter_evidence"] = []
        self.assert_blocked(self.run_review(), "parameter_evidence_missing")
        self.request["payload"]["tasks"][0]["parameter_evidence"] = [
            {"field": "/resolved_parameters/missing", "basis": "upstream", "reference": "fixture"}]
        self.assert_blocked(self.run_review(), "parameter_evidence_dangling")

    def test_missing_source_binding_and_missing_file(self):
        binding = self.context["source_files"].pop()
        self.assert_blocked(self.run_review(), "source_binding_missing")
        self.context["source_files"].append(binding)
        (self.source / "signal.npy").unlink()
        self.assert_blocked(self.run_review(), "source_check_failed")

    def test_hash_mismatch_not_repaired(self):
        raw = (self.source / "signal.npy").read_bytes() + b"x"
        (self.source / "signal.npy").write_bytes(raw)
        self.assert_blocked(self.run_review(), "source_check_failed")
        self.assertEqual((self.source / "signal.npy").read_bytes(), raw)

    def test_header_shape_dtype_and_truncation(self):
        for raw in (npy_bytes((50, 2)), npy_bytes((100, 1), "|b1"), npy_bytes()[:-1], b"not npy"):
            self.context["source_files"] = [x for x in self.context["source_files"] if x["path"] != "signal.npy"]
            self.input["payload"]["waveform"]["file_ref"] = self.add_source("signal.npy", raw)
            self.assert_blocked(self.run_review())

    def test_no_outside_or_symlink_sources(self):
        outside = self.base / "outside.npy"
        outside.write_bytes(npy_bytes())
        (self.source / "link.npy").symlink_to(outside)
        self.context["source_files"][-1]["path"] = "link.npy"
        self.assert_blocked(self.run_review(), "source_check_failed")
        self.context["source_files"][-1]["path"] = "../outside.npy"
        self.assert_blocked(self.run_review(), "context_invalid")

    def test_symlink_directory_rejected(self):
        (self.source / "escape").symlink_to(self.base, target_is_directory=True)
        self.context["source_files"][-1]["path"] = "escape/outside.npy"
        self.assert_blocked(self.run_review(), "source_check_failed")

    def test_duplicate_source_bindings_and_documents(self):
        self.context["source_files"].append(copy.deepcopy(self.context["source_files"][-1]))
        self.assert_blocked(self.run_review(), "context_invalid")
        self.context["source_files"].pop()
        (self.source / "input-copy.json").write_text(json.dumps(self.input))
        self.context["inputs"].append("input-copy.json")
        self.assert_blocked(self.run_review(), "duplicate_input")

    def test_source_read_budget_not_expanded(self):
        self.context["max_source_bytes"] = 1
        self.assert_blocked(self.run_review(), "source_check_failed")
        self.assertEqual(self.context["max_source_bytes"], 1)

    def test_source_change_during_review(self):
        original = pf.Review.unchanged
        def changed(review):
            (self.source / "signal.npy").write_bytes(b"changed")
            original(review)
        with patch.object(pf.Review, "unchanged", changed):
            self.assert_blocked(self.run_review(), "source_changed_during_review")

    def test_sample_frequency_and_time_scope(self):
        task = self.request["payload"]["tasks"][0]
        for key, value in (("sample_intervals", [[0, 101]]), ("search_band_hz", [10, 501]),
                           ("time_reference", "wrong-clock")):
            before = copy.deepcopy(task["scope"])
            task["scope"][key] = value
            self.assert_blocked(self.run_review())
            task["scope"] = before

    def test_no_valid_samples_not_zero_candidates(self):
        self.input["payload"]["validity"]["sample_intervals"] = []
        self.assert_blocked(self.run_review(), "no_valid_support")

    def test_unknown_validity_requires_compatible_task_decision(self):
        self.input["payload"]["validity"].update(status="unknown", sample_intervals=None)
        self.assert_blocked(self.run_review(), "unknown_metadata_unresolved")
        self.descriptor["payload"]["input_requirements"]["unknown_metadata_policy"] = "allow_with_explicit_decision"
        self.assert_blocked(self.run_review(), "unknown_metadata_unresolved")
        self.request["payload"]["unknown_decisions"] = [{
            "field": "/validity", "impact": "fixture", "decision": "accept only in this fixture",
            "evidence": "FAKE TEST", "limitations": ["fixture only"], "affected_tasks": ["fixture-task"],
            "affected_actions": ["detection"],
        }]
        self.clean()
        self.assertEqual(self.input["payload"]["validity"]["status"], "unknown")
        self.request["payload"]["unknown_decisions"][0]["affected_actions"] = ["handoff"]
        self.assert_blocked(self.run_review(), "unknown_metadata_unresolved")

    def test_irrelevant_unknown_units_not_fabricated_or_blocked(self):
        self.clean()
        self.assertEqual(self.input["payload"]["units"]["status"], "unknown")
        self.descriptor["payload"]["input_requirements"]["required_metadata"].append("/units")
        self.assert_blocked(self.run_review(), "unknown_metadata_unresolved")

    def test_free_text_conditions_are_not_guessed(self):
        self.descriptor["payload"]["input_requirements"]["constraints"] = ["scientific condition not encoded"]
        self.assert_blocked(self.run_review(), "free_text_constraint")

    def test_processing_steps_cannot_hide_parameters(self):
        task = self.request["payload"]["tasks"][0]
        task["processing_steps"][0]["parameters"]["/test_value"] = 2
        self.assert_blocked(self.run_review(), "step_parameters_mismatch")
        task["processing_steps"] = []
        self.assert_blocked(self.run_review(), "processing_steps_mismatch")

    def test_view_does_not_enable_implicit_computation(self):
        products = self.request["payload"]["tasks"][0]["products"]
        products["view"] = ["fixture-plot"]
        self.assert_blocked(self.run_review(), "product_dependency_missing")
        products["compute"] = ["fixture-values"]
        self.clean()
        products["view"] = ["fixture-values"]
        products["compute"] = []
        self.assert_blocked(self.run_review(), "product_calculation_unconfirmed")

    def test_unknown_product_and_save_conflict(self):
        products = self.request["payload"]["tasks"][0]["products"]
        products["view"] = ["undeclared"]
        self.assert_blocked(self.run_review(), "product_unsupported")
        products.update(view=[], compute=["fixture-values"], save=["fixture-values"])
        self.assert_blocked(self.run_review(), "save_plan_conflict")

    def test_confirmation_is_separate_and_non_executable(self):
        original = copy.deepcopy(self.request)
        receipt = self.receipt()
        report = self.run_review(receipt)
        self.assertEqual(report["confirmation_status"], "recorded_current")
        self.assertFalse(report["can_execute"])
        self.assertFalse(report["authority_verified"])
        self.assertEqual(original, self.request)

    def test_fake_confirmed_request_does_not_establish_confirmation(self):
        self.request["payload"]["approval"] = {
            "status": "confirmed", "bound_plan_sha256": "a" * 64, "evidence_refs": ["FAKE TEST"]}
        report = self.clean()
        self.assertEqual(report["confirmation_status"], "unverified_request_claim")

    def test_changed_parameters_invalidate_confirmation(self):
        receipt = self.receipt()
        task = self.request["payload"]["tasks"][0]
        task["resolved_parameters"]["test_value"] = 2
        task["processing_steps"][0]["parameters"]["/test_value"] = 2
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "stale")

    def test_changed_input_or_algorithm_document_invalidates_confirmation(self):
        receipt = self.receipt()
        self.input["payload"]["limitations"].append("new limitation")
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "stale")
        self.input["payload"]["limitations"].pop()
        self.descriptor["payload"]["detector_version"] = "test-2"
        self.request["payload"]["tasks"][0]["detector"]["detector_version"] = "test-2"
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "stale")

    def test_changed_source_invalidates_even_if_expected_hash_unchanged(self):
        receipt = self.receipt()
        (self.source / "signal.npy").write_bytes(b"changed")
        report = self.run_review(receipt)
        self.assert_blocked(report)
        self.assertIn(report["confirmation_status"], ("stale", "invalidated_by_review_blocker"))

    def test_confirmation_cannot_bind_another_request_or_hash(self):
        report = self.clean()
        for key in ("plan_sha256", "request_id"):
            evidence = self.evidence(report)
            evidence[key] = "b" * 64
            with self.assertRaises(ValueError):
                pf.record_confirmation(report, evidence, self.base / "wrong.json", self.source)
        self.assertFalse((self.base / "wrong.json").exists())

    def test_receipt_cannot_overwrite_or_write_into_source(self):
        report = self.clean()
        path = self.base / "keep.json"
        path.write_text("keep")
        with self.assertRaises(FileExistsError):
            pf.record_confirmation(report, self.evidence(report), path, self.source)
        self.assertEqual(path.read_text(), "keep")
        with self.assertRaises(ValueError):
            pf.record_confirmation(report, self.evidence(report), self.source / "receipt.json", self.source)

    def test_blocked_review_cannot_record_confirmation(self):
        self.context["descriptors"] = []
        report = self.run_review()
        with self.assertRaises(ValueError):
            pf.record_confirmation(report, self.evidence(report), self.base / "blocked.json", self.source)

    def test_batch_keeps_task_identity_and_questions(self):
        task = copy.deepcopy(self.request["payload"]["tasks"][0])
        task["task_id"] = "second-task"
        task["input_ref"]["signal_id"] = "missing"
        self.request["payload"]["tasks"].append(task)
        report = self.run_review()
        self.assert_blocked(report, "input_not_supplied")
        issue = next(x for x in report["issues"] if x["code"] == "input_not_supplied")
        self.assertEqual(issue["affected_tasks"], ["second-task"])

    def cli_files(self):
        request_path = self.base / "request.json"
        context_path = self.base / "context.json"
        request_path.write_text(json.dumps(self.request))
        context_path.write_text(json.dumps(self.context))
        return [str(ROOT / "scripts/preflight.py"), "review", str(request_path),
                "--context", str(context_path), "--source-root", str(self.source)]

    def test_cli_review_and_record_round_trip(self):
        args = self.cli_files()
        process = subprocess.run([sys.executable] + args, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        evidence_path = self.base / "evidence.json"
        evidence_path.write_text(json.dumps(self.evidence(report)))
        record_args = args[:]
        record_args[1] = "record-confirmation"
        receipt_path = self.base / "cli-receipt.json"
        process = subprocess.run([sys.executable] + record_args + [
            "--user-evidence", str(evidence_path), "--out", str(receipt_path)],
            capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        process = subprocess.run([sys.executable] + args + ["--confirmation", str(receipt_path)],
                                 capture_output=True, text=True)
        self.assertEqual(json.loads(process.stdout)["confirmation_status"], "recorded_current")
        self.assertFalse(json.loads(process.stdout)["can_execute"])

    def test_cli_blocked_and_parse_error_exit_codes(self):
        self.context["descriptors"] = []
        args = self.cli_files()
        process = subprocess.run([sys.executable] + args, capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stdout)
        Path(args[2]).write_text('{"x":1,"x":2}')
        process = subprocess.run([sys.executable] + args, capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertFalse(json.loads(process.stdout)["can_execute"])


    def test_all_missing_parameters_produce_questions(self):
        schema = self.descriptor["payload"]["parameter_definitions"]["json_schema"]
        schema["properties"]["another"] = {"type": "number"}
        schema["required"].append("another")
        self.request["payload"]["tasks"][0]["resolved_parameters"] = {}
        report = self.run_review()
        reasons = [x["reason"] for x in report["issues"] if x["code"] == "parameter_invalid"]
        self.assertTrue(any("test_value" in r for r in reasons))
        self.assertTrue(any("another" in r for r in reasons))

    def test_receipt_modified_statement_is_invalid(self):
        receipt = self.receipt()
        receipt["user_statement"] = "tampered"
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "invalid")

    def test_request_id_and_output_change_invalidate_confirmation(self):
        receipt = self.receipt()
        self.request["payload"]["request_id"] = "different-request"
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "stale")
        self.request["payload"]["request_id"] = "fixture-request"
        self.request["payload"]["resources"]["max_working_bytes"] *= 2
        self.assertEqual(self.run_review(receipt)["confirmation_status"], "stale")

    def test_unselected_source_is_not_read(self):
        (self.source / "unused.bin").write_bytes(b"unused content")
        self.context["source_files"].append({"sha256": "b" * 64, "path": "unused.bin"})
        report = self.clean()
        self.assertNotIn("unused.bin", [x["path"] for x in report["verified_sources"]])

    def test_optional_provenance_missing_is_reported_without_blocking(self):
        self.input["payload"]["provenance"].append({
            "location": {"kind": "external_reference", "path": "unbundled/original"},
            "sha256": "b" * 64, "availability": "unavailable",
        })
        report = self.clean()
        issue = next(x for x in report["issues"] if x["code"] == "source_binding_missing")
        self.assertFalse(issue["blocking"])

    def test_unknown_frequency_coverage_not_filled_with_nyquist(self):
        self.input["payload"]["frequency_coverage"].update(status="unknown", band_hz=None)
        self.assert_blocked(self.run_review(), "unknown_metadata_unresolved")
        self.assertIsNone(self.input["payload"]["frequency_coverage"]["band_hz"])

    def test_mask_header_checked_without_filling_unknown_mask(self):
        self.input["payload"]["validity"]["mask_ref"] = self.add_source("mask.npy", npy_bytes((99,), "|b1"))
        self.assert_blocked(self.run_review(), "array_header_mismatch")

    def test_local_parameter_schema_reference(self):
        schema = self.descriptor["payload"]["parameter_definitions"]["json_schema"]
        schema["$defs"] = {"nonnegative": {"type": "number", "minimum": 0}}
        schema["properties"]["test_value"] = {"$ref": "#/$defs/nonnegative"}
        self.clean()
        self.request["payload"]["tasks"][0]["resolved_parameters"]["test_value"] = -1
        self.assert_blocked(self.run_review(), "parameter_invalid")

    def test_cyclic_product_dependencies_are_blocked(self):
        self.descriptor["payload"]["product_definitions"][0]["dependencies"] = ["fixture-plot"]
        self.request["payload"]["tasks"][0]["products"]["compute"] = ["fixture-values", "fixture-plot"]
        self.assert_blocked(self.run_review(), "product_dependency_cycle")


if __name__ == "__main__":
    unittest.main()
