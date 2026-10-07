"""Synthetic contract fixtures only. No detector, waveform, or real approval."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_contract as vc

HASH = "a" * 64
REF = {"location": {"kind": "external_reference", "path": "fixture-only/not-a-real-file"},
       "sha256": HASH, "availability": "not_checked"}
INPUT = {"package_sha256": HASH, "signal_id": "fixture-signal"}
DETECTOR = {"detector_id": "fixture-no-implementation", "detector_version": "test-1",
            "implementation_sha256": HASH}
SCOPE = {"sample_intervals": [[0, 100]], "search_band_hz": [10, 100],
         "time_reference": "fixture-relative"}
APPROVAL = {"status": "pending", "bound_plan_sha256": None, "evidence_refs": []}
PRODUCTS = {"compute": [], "view": [], "save": []}
RESOURCES = {"max_working_bytes": 1024, "max_artifact_bytes": 0,
             "persistence": "session", "output_directory": None,
             "temporary_storage_policy": "fixture: no files"}
QUALITY = {"status": "not_evaluated", "summary": "Synthetic structure fixture only.",
           "evidence_refs": []}
CANDIDATE = {
    "candidate_id": "fixture-candidate", "task_id": "fixture-task", "input_ref": INPUT,
    "frequency": {"kind": "point", "value_hz": 50, "estimation_definition": "fixture-only",
                  "grid_index": None},
    "analysis_support": {"sample_intervals": [[0, 100]], "time_reference": "fixture-relative"},
    "event_extent": {"status": "not_estimated", "interval_seconds": None, "definition": None},
    "decision": {"summary": "No computation: synthetic structure example.", "evidence_refs": []},
    "measurements": [], "quality_flags": ["synthetic_fixture"], "extensions": {},
}


def fixture(kind):
    payloads = {
        "SignalInput": {
            "source_package": {"manifest": REF, "package_kind": "bypass_handoff",
                               "contract_version": "fixture-1"},
            "signal_id": "fixture-signal", "data_role": "single_sensor",
            "waveform": {"file_ref": REF, "dtype": "float64", "shape": [100, 1],
                         "axes": ["sample", "signal"], "sample_count": 100},
            "sample_rate_hz": 1000,
            "time_mapping": {"sample_zero_offset_seconds": 0, "time_reference": "fixture-relative",
                             "source_sample_zero": None, "evidence": "fixture"},
            "validity": {"status": "unknown", "sample_intervals": None, "mask_ref": None,
                         "meaning": "Not checked.", "evidence": "fixture"},
            "units": {"status": "unknown", "value": None, "amplitude_convention": None,
                      "evidence": "fixture"},
            "frequency_coverage": {"status": "unknown", "band_hz": None,
                                   "active_frequency_ref": None, "definition": "fixture",
                                   "evidence": "fixture"},
            "processing_history": {"steps": [], "source_configuration": REF},
            "beam_source": {"status": "not_applicable"}, "limitations": ["fixture"],
            "provenance": [REF],
        },
        "AlgorithmDescriptor": {
            "detector_id": "fixture-no-implementation", "detector_version": "test-1",
            "implementation_identity": {"registration_key": "fixture-only", "sha256": HASH},
            "input_requirements": {"data_roles": ["single_sensor"], "representation": "real_waveform",
                                   "dtypes": ["float64"], "required_metadata": [],
                                   "constraints": [], "unknown_metadata_policy": "fixture-only"},
            "capabilities": [{"task_kind": "fixture", "description": "No implementation."}],
            "parameter_definitions": {"json_schema": {"type": "object", "properties": {},
                                                     "additionalProperties": False}, "annotations": []},
            "processing_definition": [],
            "result_definition": {"frequency_semantics": "fixture", "time_support_semantics": "fixture",
                                  "decision_semantics": "fixture", "measurement_definitions": [],
                                  "extension_schema": {"type": "object", "additionalProperties": False}},
            "product_definitions": [], "resource_model": {"description": "fixture", "limitations": []},
            "limitations": ["No actual detector."], "validation_evidence": [],
        },
        "DetectionRequest": {
            "request_id": "fixture-request",
            "tasks": [{"task_id": "fixture-task", "input_ref": INPUT, "detector": DETECTOR,
                       "task_kind": "fixture", "scope": SCOPE, "resolved_parameters": {},
                       "processing_steps": [], "parameter_evidence": [], "products": PRODUCTS}],
            "unknown_decisions": [], "resources": RESOURCES, "batch_failure_policy": "stop_batch",
            "approval": APPROVAL, "parent_request": None, "parent_result": None,
        },
        "DetectionResult": {
            "run_id": "fixture-run", "request_ref": REF, "resolved_configuration": REF,
            "task_results": [{"task_id": "fixture-task", "input_ref": INPUT, "detector": DETECTOR,
                              "execution_status": "completed", "reason": None,
                              "coverage": {"requested": SCOPE, "processed": [[0, 100]], "excluded": []},
                              "candidates": [CANDIDATE], "limitations": ["fixture"], "diagnostics": [],
                              "artifacts": [], "quality": QUALITY}],
            "delivery_status": "not_requested", "association_ref": None,
            "validation": {"structure_summary": "fixture", "quality": QUALITY},
        },
        "AssociationRecord": {
            "record_id": "fixture-association",
            "entities": [{"entity_id": "fixture-node", "kind": "signal", "namespace": "fixture",
                          "identity": INPUT, "evidence_ref": None}],
            "relations": [], "scope_mapping": [], "evidence_refs": [], "persistence": "session",
            "comparisons": [], "followups": [],
        },
    }
    return json.loads(json.dumps({"schema_version": "0.1.0", "record_type": kind,
                          "document_status": "specified", "payload": payloads[kind],
                          "unresolved_items": []}))


def change(document, keys, value):
    cursor = document
    for key in keys[:-1]:
        cursor = cursor[key]
    cursor[keys[-1]] = value
    return document


class Contracts(unittest.TestCase):
    def assert_valid(self, document):
        report = vc.validate_document(document)
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(report["can_execute"])
        return report

    def assert_invalid(self, document):
        report = vc.validate_document(document)
        self.assertFalse(report["valid"], document)
        self.assertFalse(report["can_execute"])
        self.assertTrue(report["errors"])
        return report

    def test_five_specified_contracts_without_external_access(self):
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            for kind in vc.KINDS:
                with self.subTest(kind=kind):
                    self.assert_valid(fixture(kind))

    def test_five_drafts_preserve_nulls_and_do_not_authorize(self):
        for kind in vc.KINDS:
            with self.subTest(kind=kind):
                doc = vc.read_json(ROOT / "assets" / "templates" / f"{kind}.draft.json")
                before = copy.deepcopy(doc)
                self.assert_valid(doc)
                self.assertEqual(doc, before)
                self.assertTrue(all(v is None for v in doc["payload"].values()))

    def test_draft_to_specified_without_filling_is_invalid(self):
        for kind in vc.KINDS:
            with self.subTest(kind=kind):
                doc = vc.read_json(ROOT / "assets" / "templates" / f"{kind}.draft.json")
                doc.update(document_status="specified", unresolved_items=[])
                self.assert_invalid(doc)

    def test_draft_requires_issue(self):
        doc = vc.read_json(ROOT / "assets" / "templates" / "DetectionRequest.draft.json")
        doc["unresolved_items"] = []
        self.assert_invalid(doc)

    def test_draft_filled_groups_are_type_checked(self):
        doc = vc.read_json(ROOT / "assets" / "templates" / "SignalInput.draft.json")
        doc["payload"]["sample_rate_hz"] = "1000"
        self.assert_invalid(doc)

    def test_envelope_and_core_reject_unknown_keys(self):
        for kind in vc.KINDS:
            for container in ("envelope", "payload"):
                with self.subTest(kind=kind, container=container):
                    doc = fixture(kind)
                    (doc if container == "envelope" else doc["payload"])["unrecognized"] = True
                    self.assert_invalid(doc)

    def test_required_keys_cannot_disappear(self):
        for kind in vc.KINDS:
            doc = fixture(kind)
            del doc["payload"][next(iter(doc["payload"]))]
            self.assert_invalid(doc)

    def test_wrong_version_and_expected_kind(self):
        doc = fixture("SignalInput")
        self.assert_invalid(dict(doc, schema_version="99"))
        self.assertFalse(vc.validate_document(doc, "DetectionRequest")["valid"])

    def test_input_sample_rate_and_shape(self):
        for path, value in [
            (["sample_rate_hz"], 0), (["sample_rate_hz"], True),
            (["sample_rate_hz"], float("inf")), (["waveform", "sample_count"], 101),
            (["waveform", "shape"], [1, 100]), (["waveform", "dtype"], "float32"),
        ]:
            self.assert_invalid(change(fixture("SignalInput"), ["payload"] + path, value))

    def test_unknown_validity_not_filled(self):
        doc = fixture("SignalInput")
        doc["payload"]["validity"]["sample_intervals"] = [[0, 100]]
        self.assert_invalid(doc)

    def test_known_validity_intervals_and_mask(self):
        doc = fixture("SignalInput")
        validity = doc["payload"]["validity"]
        validity.update(status="known", sample_intervals=[])
        self.assert_valid(doc)  # Known no valid samples, not permission to calculate.
        validity.update(sample_intervals=None, mask_ref=copy.deepcopy(REF))
        self.assert_valid(doc)
        validity.update(mask_ref=None)
        self.assert_invalid(doc)

    def test_invalid_or_overlapping_input_intervals(self):
        for values in ([[10, 10]], [[0, 101]], [[40, 60], [20, 30]], [[0, 30], [20, 40]]):
            doc = fixture("SignalInput")
            doc["payload"]["validity"].update(status="known", sample_intervals=values)
            self.assert_invalid(doc)

    def test_beam_and_sensor_roles_not_swapped(self):
        doc = fixture("SignalInput")
        doc["payload"]["data_role"] = "beamformed"
        self.assert_invalid(doc)
        unknown = {"status": "unknown", "value": None, "evidence": "fixture"}
        doc["payload"]["beam_source"] = {
            "status": "applicable", "beamformer_algorithm": unknown, "beam_id": unknown,
            "direction": unknown, "source_result": None, "source_column": None, "scan_column": None,
        }
        self.assert_valid(doc)  # Unknown external beam facts are not fabricated.

    def test_units_unknown_cannot_be_given_pa(self):
        doc = fixture("SignalInput")
        doc["payload"]["units"]["value"] = "Pa"
        self.assert_invalid(doc)

    def test_frequency_coverage_constraints(self):
        doc = fixture("SignalInput")
        cov = doc["payload"]["frequency_coverage"]
        cov.update(status="known", band_hz=[0, 500])
        self.assert_valid(doc)
        for band in ([0, 501], [100, 50]):
            cov["band_hz"] = band
            self.assert_invalid(doc)

    def test_package_relative_paths_do_not_escape(self):
        for value in ("../x", "a/../../x", "/x", "C:/x", "a\\x"):
            doc = fixture("SignalInput")
            doc["payload"]["waveform"]["file_ref"]["location"] = {
                "kind": "package_relative", "path": value}
            self.assert_invalid(doc)

    def test_pending_and_confirmed_are_not_execution(self):
        doc = fixture("DetectionRequest")
        self.assert_valid(doc)
        approval = doc["payload"]["approval"]
        approval["status"] = "confirmed"
        self.assert_invalid(doc)
        approval.update(bound_plan_sha256=HASH, evidence_refs=["FAKE TEST EVIDENCE"])
        report = self.assert_valid(doc)
        self.assertIn("real_user_approval_and_plan_binding", report["not_checked"])

    def test_resources_saved_require_destination(self):
        doc = fixture("DetectionRequest")
        doc["payload"]["resources"]["persistence"] = "saved"
        self.assert_invalid(doc)

    def test_explicit_empty_products_allowed_missing_not_allowed(self):
        doc = fixture("DetectionRequest")
        self.assert_valid(doc)
        del doc["payload"]["tasks"][0]["products"]["save"]
        self.assert_invalid(doc)

    def test_unique_tasks_and_named_unknown_decisions(self):
        doc = fixture("DetectionRequest")
        doc["payload"]["tasks"].append(copy.deepcopy(doc["payload"]["tasks"][0]))
        self.assert_invalid(doc)
        doc = fixture("DetectionRequest")
        doc["payload"]["unknown_decisions"] = [{
            "field": "fixture", "impact": "fixture", "decision": "fixture", "evidence": "fixture",
            "limitations": [], "affected_tasks": ["absent"], "affected_actions": ["fixture"],
        }]
        self.assert_invalid(doc)

    def test_request_bad_scope(self):
        for field, value in (("sample_intervals", [[2, 1]]), ("search_band_hz", [100, 10])):
            doc = fixture("DetectionRequest")
            doc["payload"]["tasks"][0]["scope"][field] = value
            self.assert_invalid(doc)

    def test_descriptor_no_estimator_or_score_required(self):
        self.assert_valid(fixture("AlgorithmDescriptor"))

    def test_embedded_schema_meta_and_offline_profile(self):
        for schema in (
            {"type": "invalid-type"}, {"$ref": "https://example.invalid/schema"},
            {"$ref": "file:///private/secret"}, {"$ref": "#/$defs/absent"},
            {"$dynamicRef": "#x"}, {"$schema": "https://example.invalid/dialect"},
        ):
            doc = fixture("AlgorithmDescriptor")
            doc["payload"]["parameter_definitions"]["json_schema"] = schema
            with patch("socket.create_connection", side_effect=AssertionError("No network")):
                self.assert_invalid(doc)
        doc["payload"]["parameter_definitions"]["json_schema"] = {
            "$defs": {"value": {"type": "number"}}, "type": "object",
            "properties": {"value": {"$ref": "#/$defs/value"}}}
        self.assert_valid(doc)

    def test_duplicate_product_or_step_declarations(self):
        doc = fixture("AlgorithmDescriptor")
        doc["payload"]["capabilities"] *= 2
        self.assert_invalid(doc)

    def test_zero_candidates_only_when_completed(self):
        for status in ("not_run", "blocked", "running", "failed"):
            doc = fixture("DetectionResult")
            task = doc["payload"]["task_results"][0]
            task.update(execution_status=status, reason="fixture", candidates=[])
            task["coverage"]["processed"] = []
            self.assert_invalid(doc)
            task["candidates"] = None
            self.assert_valid(doc)
        doc = fixture("DetectionResult")
        doc["payload"]["task_results"][0]["candidates"] = []
        self.assert_valid(doc)

    def test_completed_requires_nonempty_accounted_coverage(self):
        for processed in ([], [[0, 50]], [[0, 101]]):
            doc = fixture("DetectionResult")
            task = doc["payload"]["task_results"][0]
            task["candidates"] = []
            task["coverage"]["processed"] = processed
            self.assert_invalid(doc)
        task["coverage"].update(processed=[[0, 50]], excluded=[{"interval": [50, 100], "reason": "fixture"}])
        self.assert_valid(doc)
        task["coverage"]["excluded"][0]["interval"] = [40, 100]
        self.assert_invalid(doc)

    def test_failed_requires_reason(self):
        doc = fixture("DetectionResult")
        doc["payload"]["task_results"][0].update(execution_status="failed", candidates=None)
        self.assert_invalid(doc)

    def test_candidate_identity_support_and_frequency(self):
        for path, value in (
            (["task_id"], "wrong"), (["input_ref", "signal_id"], "wrong"),
            (["frequency", "value_hz"], 101),
            (["analysis_support", "sample_intervals"], [[0, 101]]),
            (["analysis_support", "time_reference"], "wrong"),
            (["event_extent", "interval_seconds"], [0, 1]),
        ):
            doc = fixture("DetectionResult")
            change(doc["payload"]["task_results"][0]["candidates"][0], path, value)
            self.assert_invalid(doc)

    def test_candidate_ids_unique_in_run(self):
        doc = fixture("DetectionResult")
        task = doc["payload"]["task_results"][0]
        task["candidates"].append(copy.deepcopy(task["candidates"][0]))
        self.assert_invalid(doc)

    def test_probability_requires_calibration_no_generic_confidence(self):
        doc = fixture("DetectionResult")
        measure = {"name": "fixture score", "definition_id": "fixture", "definition_version": "1",
                   "value": 7, "unit": "dimensionless", "scale": "fixture", "interpretation": "fixture",
                   "probability_meaning": "not_probability", "calibration_evidence": None}
        doc["payload"]["task_results"][0]["candidates"][0]["measurements"] = [measure]
        self.assert_valid(doc)
        measure["probability_meaning"] = "calibrated_probability"
        self.assert_invalid(doc)
        measure.update(value=0.5, calibration_evidence=copy.deepcopy(REF))
        self.assert_valid(doc)  # Only declaration, not actual calibration verified.

    def test_quality_evaluated_requires_evidence(self):
        doc = fixture("DetectionResult")
        doc["payload"]["validation"]["quality"]["status"] = "evaluated"
        self.assert_invalid(doc)

    def test_association_entity_identity_and_dangling_relation(self):
        doc = fixture("AssociationRecord")
        doc["payload"]["entities"][0]["identity"] = {"signal_id": "fixture"}
        self.assert_invalid(doc)
        doc = fixture("AssociationRecord")
        doc["payload"]["relations"] = [{"from_entity": "fixture-node", "to_entity": "absent",
                                       "kind": "sourced_from", "basis": "fixture"}]
        self.assert_invalid(doc)
        doc["payload"]["relations"][0].update(to_entity="fixture-node", kind="same_target")
        self.assert_invalid(doc)

    def test_followup_proposal_does_not_authorize(self):
        doc = fixture("AssociationRecord")
        followup = {"followup_id": "fixture-followup", "parent_refs": [copy.deepcopy(REF)],
                    "question": "fixture", "reason": "fixture", "responsible_module": "beamforming",
                    "requested_action": "fixture", "scope": None, "dependencies": [], "parameters": None,
                    "unresolved_items": [{"field": "/scope", "reason": "unknown",
                                          "affected_actions": ["fixture"], "question": "scope?"}],
                    "resource_and_output_plan": None, "approval": copy.deepcopy(APPROVAL),
                    "status": "proposed", "result_refs": []}
        doc["payload"]["followups"] = [followup]
        self.assert_valid(doc)
        followup["status"] = "confirmed"
        self.assert_invalid(doc)

    def test_strict_json_rejects_duplicates_nan_and_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e400}'):
                path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    vc.read_json(path)

    def test_cli_draft_no_input_change_or_side_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            original = (ROOT / "assets" / "templates" / "DetectionRequest.draft.json").read_bytes()
            path.write_bytes(original)
            process = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_contract.py"),
                                      str(path)], capture_output=True, text=True, cwd=tmp)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertFalse(json.loads(process.stdout)["can_execute"])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual([x.name for x in Path(tmp).iterdir()], ["input.json"])

    def test_cli_invalid_json_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text('{"x": NaN}', encoding="utf-8")
            process = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_contract.py"),
                                      str(path)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertFalse(json.loads(process.stdout)["can_execute"])


    def test_saved_artifact_requires_file_and_provenance(self):
        doc = fixture("DetectionResult")
        artifact = {
            "product_id": "fixture-product", "task_id": "fixture-task", "kind": "fixture",
            "status": "saved", "file_ref": None, "definition": "fixture", "axes": [],
            "coordinates": {"definition": "fixture", "evidence_ref": None},
            "validity_definition": "fixture", "units": fixture("SignalInput")["payload"]["units"],
            "provenance_refs": [], "lifecycle": "fixture",
        }
        doc["payload"]["task_results"][0]["artifacts"] = [artifact]
        self.assert_invalid(doc)
        artifact.update(file_ref=copy.deepcopy(REF), provenance_refs=[copy.deepcopy(REF)])
        self.assert_valid(doc)
        artifact["task_id"] = "wrong-task"
        self.assert_invalid(doc)

    def test_direction_requires_coordinate_convention(self):
        doc = fixture("SignalInput")
        unknown = {"status": "unknown", "value": None, "evidence": "fixture"}
        direction = {"parameterization": "array_angle", "angles_deg": [0], "angle_unit": "deg",
                     "coordinate_frame": "fixture", "zero_direction": "fixture",
                     "positive_direction": "fixture", "fixed_direction": True}
        doc["payload"].update(data_role="beamformed", beam_source={
            "status": "applicable", "beamformer_algorithm": unknown, "beam_id": unknown,
            "direction": {"status": "known", "value": direction, "evidence": "fixture"},
            "source_result": None, "source_column": None, "scan_column": None,
        })
        self.assert_valid(doc)
        del direction["zero_direction"]
        self.assert_invalid(doc)

    def test_root_and_record_type_not_dynamic_paths(self):
        for doc in ([], None, {"record_type": "../../outside"}, {"record_type": []}):
            self.assert_invalid(doc)

    def test_cli_structurally_invalid_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text(json.dumps({"record_type": "SignalInput"}), encoding="utf-8")
            process = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_contract.py"),
                                      str(path)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 1)
            self.assertFalse(json.loads(process.stdout)["can_execute"])


if __name__ == "__main__":
    unittest.main()
