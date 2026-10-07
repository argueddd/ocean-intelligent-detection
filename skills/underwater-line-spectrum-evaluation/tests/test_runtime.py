import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation_runtime import execute, preflight, sha256_file  # noqa: E402
from validate_contract import validate_document  # noqa: E402


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def file_ref(path, object_id=None):
    return {"kind": "file", "locator": str(Path(path).resolve()),
            "sha256": sha256_file(path), "object_id": object_id, "reason": None}


def beam_none():
    return {"status": "not_applicable", "result_sha256": None, "beamformer": None,
            "beam_id": None, "metadata_ref": None, "reason": "Synthetic single-sensor input."}


def scope(start=0.0, stop=0.2, low=50.0, high=300.0):
    return {"time": {"status": "known", "reference": "sample_zero_seconds",
                     "intervals_s": [[start, stop]], "reason": None},
            "frequency_band_hz": [low, high]}


class RuntimeFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.package = self.root / "detection"
        self.package.mkdir()
        self.run_id = "run-001"
        self.task_id = "task-001"
        self.target_id = "target-001"
        self.package_sha = "a" * 64
        self.signal_id = "signal-001"
        self.time_reference = "sample_zero_seconds"
        self.config_path = self.package / "resolved-configuration.json"
        config = {"request": {"payload": {"tasks": [{"task_id": self.task_id,
                   "task_kind": "framewise",
                   "resolved_parameters": {"spectrum": {"nfft": 100}}}]}},
                  "input_documents": [{"payload": {
                      "source_package": {"manifest": {"sha256": self.package_sha}},
                      "signal_id": self.signal_id, "sample_rate_hz": 1000.0,
                      "beam_source": {"status": "not_applicable"}}}]}
        config_sha = write_json(self.config_path, config)
        self.candidates = [
            self.candidate("c1", 0, 10, 100.0, [0, 100], 10.0, 5.0, 1.0),
            self.candidate("c2", 0, 12, 120.0, [0, 100], 8.0, 4.0, 1.0),
            self.candidate("c3", 1, 20, 200.0, [100, 200], 12.0, 6.0, 2.0),
        ]
        candidate_path = self.package / "task-000000" / "candidates" / "candidates.json"
        candidate_sha = write_json(candidate_path, self.candidates)
        candidate_manifest = candidate_path.parent / "product.json"
        candidate_manifest_sha = write_json(candidate_manifest, {
            "product_id": "candidates", "task_id": self.task_id,
            "files": [{"name": "candidates.json", "sha256": candidate_sha,
                       "size_bytes": candidate_path.stat().st_size}]})
        self.ledger = {"rows": [
                {"row": 0, "sample_intervals": [[0, 100]], "status": "tested",
                 "tested_bins": list(range(5, 31)), "zero_background_bins": [],
                 "candidate_count": 2, "rejected_groups": []},
                {"row": 1, "sample_intervals": [[100, 200]], "status": "tested",
                 "tested_bins": list(range(5, 31)), "zero_background_bins": [],
                 "candidate_count": 1, "rejected_groups": []}],
            "frame_ledger": [
                {"start_sample": 0, "stop_sample": 100, "status": "eligible", "reason": None},
                {"start_sample": 100, "stop_sample": 200, "status": "eligible", "reason": None}],
            "alpha": 5.0, "coefficient": None, "tests_per_event": 52,
            "p_cell": None, "excluded_frequency_bins": []}
        ledger_path = self.package / "task-000000" / "ledger" / "ledger.json"
        ledger_sha = write_json(ledger_path, self.ledger)
        ledger_manifest = ledger_path.parent / "product.json"
        ledger_manifest_sha = write_json(ledger_manifest, {
            "product_id": "ledger", "task_id": self.task_id,
            "files": [{"name": "ledger.json", "sha256": ledger_sha,
                       "size_bytes": ledger_path.stat().st_size}]})
        task = {"task_id": self.task_id,
                "input_ref": {"package_sha256": self.package_sha, "signal_id": self.signal_id},
                "execution_status": "completed", "reason": None,
                "coverage": {"requested": {"sample_intervals": [[0, 200]],
                                             "search_band_hz": [50.0, 300.0],
                                             "time_reference": self.time_reference},
                             "processed": [[0, 200]], "excluded": []},
                "candidates": self.candidates,
                "artifacts": [
                    self.detection_artifact("candidates", candidate_manifest, candidate_manifest_sha),
                    self.detection_artifact("ledger", ledger_manifest, ledger_manifest_sha)],
                "limitations": [], "diagnostics": [], "quality": {"status": "not_evaluated"}}
        self.result_path = self.package / "detection-result.json"
        result = {"schema_version": "0.1.0", "record_type": "DetectionResult",
                  "document_status": "specified", "payload": {"run_id": self.run_id,
                  "resolved_configuration": {"location": {"kind": "package_relative",
                                                           "path": self.config_path.name},
                                             "sha256": config_sha, "availability": "available"},
                  "task_results": [task]}, "unresolved_items": []}
        write_json(self.result_path, result)

    def candidate(self, cid, row, grid, frequency, support, power, threshold, background):
        def measurement(name, value):
            return {"name": name, "value": value, "scale": "linear"}
        return {"candidate_id": cid, "task_id": self.task_id,
                "input_ref": {"package_sha256": self.package_sha, "signal_id": self.signal_id},
                "frequency": {"kind": "point", "value_hz": frequency, "grid_index": grid},
                "analysis_support": {"sample_intervals": [support],
                                     "time_reference": self.time_reference},
                "measurements": [measurement("power", power), measurement("threshold", threshold),
                                 measurement("background", background)],
                "extensions": {"cfar_v1": {"row": row, "group_bins": [grid, grid]}}}

    def detection_artifact(self, kind, manifest, digest):
        return {"kind": kind, "status": "saved",
                "file_ref": {"location": {"kind": "package_relative",
                                           "path": str(manifest.relative_to(self.package))},
                             "sha256": digest, "availability": "available"}}

    def target(self):
        return {"target_id": self.target_id,
                "result_ref": file_ref(self.result_path, "DetectionResult"),
                "run_id": self.run_id, "task_id": self.task_id, "task_kind": "framewise",
                "source": {"status": "known", "input_package_sha256": self.package_sha,
                           "signal_id": self.signal_id, "beam": beam_none(), "reason": None},
                "configuration_ref": file_ref(self.config_path, "resolved-configuration"),
                "scope": scope(), "limitations": []}

    def request(self, output, metrics, truth_binding=None, rules=None, artifacts=None):
        truth_binding = truth_binding or {"target_id": self.target_id, "status": "none",
                                          "coverage_ref": None, "reason": "No truth supplied."}
        metric_ids = [x["metric_id"] for x in metrics]
        return {"schema_version": "0.1.0", "record_type": "EvaluationRequest",
                "document_status": "specified", "payload": {
                    "request_id": "evaluation-request-001", "question": "Synthetic runtime test.",
                    "targets": [self.target()], "truth_bindings": [truth_binding],
                    "metric_requests": metrics, "matching_rules": rules or [],
                    "output_plan": {"display_metric_ids": metric_ids,
                                    "save_metric_ids": metric_ids,
                                    "save_destination": str(Path(output).resolve()),
                                    "artifact_requests": artifacts or []},
                    "confirmation": {"status": "recorded",
                                     "evidence_ref": {"kind": "session", "locator": "unit-test",
                                                      "sha256": None, "object_id": None, "reason": None},
                                     "statement": "Execute the explicit synthetic test plan."},
                    "accepted_limitations": ["Synthetic fixture only."]},
                "unresolved_items": []}


def metric(mid, kind, *, rule=None, stage="final_candidate"):
    return {"metric_id": mid, "target_id": "target-001", "metric_kind": kind,
            "compute": True, "definition_version": "0.1.0", "matching_rule_id": rule,
            "count_stage": stage, "denominator_rule": "Runtime V1 metric definition.",
            "aggregation_rule": "All eligible evidence in selected scope.",
            "coverage_rule": "Only fully covered rows and declared evidence regions."}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.fixture = RuntimeFixture(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def save_request(self, request):
        path = Path(self.temp) / "request.json"
        write_json(path, request)
        self.assertTrue(validate_document(request, "EvaluationRequest")["valid"])
        return path

    def test_no_truth_descriptive_runtime(self):
        output = Path(self.temp) / "evaluation"
        kinds = ["candidate_count", "mean_candidates_per_frame", "candidate_frame_fraction",
                 "mean_threshold_margin_db", "mean_background_contrast_db"]
        request = self.fixture.request(output, [metric(f"m{i}", kind) for i, kind in enumerate(kinds)])
        path = self.save_request(request)
        report, _, _ = preflight(path)
        self.assertTrue(report["can_execute"], report)
        result, actual = execute(path, output)
        self.assertEqual(actual, output.resolve())
        values = {x["metric_kind"]: x["value"] for x in result["payload"]["metrics"]}
        self.assertEqual(values["candidate_count"], 3)
        self.assertEqual(values["mean_candidates_per_frame"], 1.5)
        self.assertEqual(values["candidate_frame_fraction"], 1.0)
        self.assertAlmostEqual(values["mean_threshold_margin_db"], 10 * __import__("math").log10(2))
        self.assertTrue((output / "evaluation-result.json").is_file())
        self.assertTrue((output / "package-manifest.json").is_file())
        self.assertTrue(validate_document(result, "EvaluationResult")["valid"])

    def truth_documents(self):
        labels_path = Path(self.temp) / "truth-labels.json"
        labels = {"schema_version": "1.0.0", "record_type": "TruthLabels",
                  "target_id": self.fixture.target_id, "run_id": self.fixture.run_id,
                  "task_id": self.fixture.task_id, "time_reference": self.fixture.time_reference,
                  "sample_rate_hz": 1000.0,
                  "labels": [
                      {"truth_id": "t1", "region_id": "complete-1", "frequency_hz": 100.0,
                       "sample_intervals": [[0, 100]], "time_s": 0.05, "note": None},
                      {"truth_id": "t2", "region_id": "complete-1", "frequency_hz": 202.0,
                       "sample_intervals": [[100, 200]], "time_s": 0.15, "note": None}],
                  "limitations": ["Synthetic truth."]}
        write_json(labels_path, labels)
        evidence = file_ref(labels_path, "TruthLabels")
        coverage_path = Path(self.temp) / "truth-coverage.json"
        coverage = {"schema_version": "0.1.0", "record_type": "TruthCoverage",
                    "document_status": "specified", "payload": {
                        "coverage_id": "coverage-001", "target": self.fixture.target(),
                        "availability": "available", "evidence_origin": "measurement_annotation",
                        "provenance_refs": [evidence],
                        "label_semantics": "Two complete synthetic candidate-peak labels.",
                        "regions": [{"region_id": "complete-1", "scope": scope(),
                                     "label_status": "complete", "label_grain": "candidate_peak",
                                     "positive_definition": "Listed line peak.",
                                     "negative_definition": "All unmarked peaks in this complete region.",
                                     "h0_definition": None, "unmarked_policy": "negative",
                                     "labels_ref": evidence, "evidence_refs": [evidence], "reason": None}],
                        "outside_regions_policy": "unknown",
                        "independence": {"status": "unknown", "relative_to_refs": [],
                                         "basis": "Synthetic unit-test declaration only."},
                        "limitations": ["Synthetic fixture."]}, "unresolved_items": []}
        write_json(coverage_path, coverage)
        self.assertTrue(validate_document(coverage, "TruthCoverage")["valid"])
        return coverage_path

    def background_coverage(self):
        evidence_path = Path(self.temp) / "background-evidence.json"
        write_json(evidence_path, {"statement": "Synthetic H0 region for runtime testing."})
        evidence = file_ref(evidence_path, "background-evidence")
        coverage_path = Path(self.temp) / "background-coverage.json"
        coverage = {"schema_version": "0.1.0", "record_type": "TruthCoverage",
                    "document_status": "specified", "payload": {
                        "coverage_id": "background-001", "target": self.fixture.target(),
                        "availability": "available", "evidence_origin": "measurement_annotation",
                        "provenance_refs": [evidence],
                        "label_semantics": "The complete synthetic scope is declared H0.",
                        "regions": [{"region_id": "background-1", "scope": scope(),
                                     "label_status": "verified_background", "label_grain": "cfar_cell",
                                     "positive_definition": None,
                                     "negative_definition": "All eligible cells are H0.",
                                     "h0_definition": "Synthetic noise-only background.",
                                     "unmarked_policy": "negative", "labels_ref": None,
                                     "evidence_refs": [evidence], "reason": None}],
                        "outside_regions_policy": "unknown",
                        "independence": {"status": "unknown", "relative_to_refs": [],
                                         "basis": "Synthetic unit-test declaration only."},
                        "limitations": ["Synthetic fixture."]}, "unresolved_items": []}
        write_json(coverage_path, coverage)
        self.assertTrue(validate_document(coverage, "TruthCoverage")["valid"])
        return coverage_path

    def test_complete_truth_metrics(self):
        coverage_path = self.truth_documents()
        output = Path(self.temp) / "truth-evaluation"
        rule = {"rule_id": "rule-1", "status": "specified", "frequency_gate_hz": 5.0,
                "time_rule": "frame_identity", "time_gate_s": None,
                "assignment_method": "maximum_cardinality_minimum_frequency_error",
                "tie_break": "candidate_id_then_truth_id", "duplicate_policy": "count_as_false",
                "reason": None}
        kinds = ["recall", "precision", "f1", "frequency_mae_hz",
                 "frequency_rmse_hz", "frequency_bias_hz", "false_count",
                 "mean_false_per_frame", "false_per_hour"]
        metrics = [metric(f"m{i}", kind, rule="rule-1") for i, kind in enumerate(kinds)]
        binding = {"target_id": self.fixture.target_id, "status": "provided",
                   "coverage_ref": file_ref(coverage_path, "coverage-001"), "reason": None}
        artifacts = [{"artifact_id": "matches", "target_ids": [self.fixture.target_id],
                      "kind": "matches", "compute": True, "display": False, "save": True,
                      "definition": "One-to-one match audit table."}]
        request = self.fixture.request(output, metrics, binding, [rule], artifacts)
        path = self.save_request(request)
        result, _ = execute(path, output)
        values = {x["metric_kind"]: x["value"] for x in result["payload"]["metrics"]}
        self.assertEqual(values["recall"], 1.0)
        self.assertAlmostEqual(values["precision"], 2 / 3)
        self.assertAlmostEqual(values["f1"], 0.8)
        self.assertAlmostEqual(values["frequency_mae_hz"], 1.0)
        self.assertAlmostEqual(values["frequency_rmse_hz"], 2 ** 0.5)
        self.assertAlmostEqual(values["frequency_bias_hz"], -1.0)
        self.assertEqual(values["false_count"], 1)
        self.assertEqual(values["mean_false_per_frame"], 0.5)
        self.assertAlmostEqual(values["false_per_hour"], 18000.0)
        self.assertTrue((output / "matches.json").is_file())
        self.assertTrue(validate_document(result, "EvaluationResult")["valid"])

    def test_hash_mismatch_blocks_preflight(self):
        output = Path(self.temp) / "evaluation"
        request = self.fixture.request(output, [metric("m0", "candidate_count")])
        request["payload"]["targets"][0]["result_ref"]["sha256"] = "0" * 64
        path = self.save_request(request)
        report, _, _ = preflight(path)
        self.assertFalse(report["can_execute"])
        self.assertTrue(any(x["code"] == "target_preflight_failed" for x in report["issues"]))

    def test_verified_background_candidate_and_cell_metrics(self):
        coverage_path = self.background_coverage()
        output = Path(self.temp) / "background-evaluation"
        specs = [
            ("false-candidates", "false_count", "final_candidate"),
            ("mean-false", "mean_false_per_frame", "final_candidate"),
            ("false-hour", "false_per_hour", "final_candidate"),
            ("cell-fraction", "cell_false_fraction", "cell_threshold_crossing"),
            ("frame-candidate", "background_frame_false_fraction", "final_candidate"),
            ("frame-cell", "background_frame_false_fraction", "cell_threshold_crossing"),
            ("segment-candidate", "background_segment_false_fraction", "final_candidate")]
        metrics = [metric(mid, kind, stage=stage) for mid, kind, stage in specs]
        binding = {"target_id": self.fixture.target_id, "status": "provided",
                   "coverage_ref": file_ref(coverage_path, "background-001"), "reason": None}
        path = self.save_request(self.fixture.request(output, metrics, binding))
        result, _ = execute(path, output)
        values = {x["metric_id"]: x["value"] for x in result["payload"]["metrics"]}
        self.assertEqual(values["false-candidates"], 3)
        self.assertEqual(values["mean-false"], 1.5)
        self.assertEqual(values["false-hour"], 54000.0)
        self.assertAlmostEqual(values["cell-fraction"], 3 / 52)
        self.assertEqual(values["frame-candidate"], 1.0)
        self.assertEqual(values["frame-cell"], 1.0)
        self.assertEqual(values["segment-candidate"], 1.0)

    def test_existing_output_is_never_overwritten(self):
        output = Path(self.temp) / "evaluation"
        request = self.fixture.request(output, [metric("m0", "candidate_count")])
        path = self.save_request(request)
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "refusing to overwrite"):
            execute(path, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_tampered_candidate_product_blocks_preflight(self):
        output = Path(self.temp) / "evaluation"
        request = self.fixture.request(output, [metric("m0", "candidate_count")])
        path = self.save_request(request)
        candidate_path = self.fixture.package / "task-000000" / "candidates" / "candidates.json"
        candidate_path.write_text("[]\n", encoding="utf-8")
        report, _, _ = preflight(path)
        self.assertFalse(report["can_execute"])
        self.assertIn("Product file identity mismatch", json.dumps(report, ensure_ascii=False))

    def test_beam_identity_mismatch_blocks_preflight(self):
        output = Path(self.temp) / "evaluation"
        request = self.fixture.request(output, [metric("m0", "candidate_count")])
        beam_result = Path(self.temp) / "beam-result.json"
        write_json(beam_result, {"kind": "synthetic-beam-result"})
        digest = sha256_file(beam_result)
        request["payload"]["targets"][0]["source"]["beam"] = {
            "status": "known", "result_sha256": digest, "beamformer": "CBF",
            "beam_id": "beam-001", "metadata_ref": file_ref(beam_result, "beam-result"),
            "reason": None}
        path = self.save_request(request)
        report, _, _ = preflight(path)
        self.assertFalse(report["can_execute"])
        self.assertIn("declares a known beam", json.dumps(report, ensure_ascii=False))

    def test_no_truth_performance_is_insufficient_not_zero(self):
        output = Path(self.temp) / "evaluation"
        rule = {"rule_id": "rule-1", "status": "specified", "frequency_gate_hz": 5.0,
                "time_rule": "frame_identity", "time_gate_s": None,
                "assignment_method": "maximum_cardinality_minimum_frequency_error",
                "tie_break": "candidate_id_then_truth_id", "duplicate_policy": "count_as_false",
                "reason": None}
        request = self.fixture.request(output, [metric("recall", "recall", rule="rule-1")],
                                       rules=[rule])
        path = self.save_request(request)
        result, _ = execute(path, output)
        item = result["payload"]["metrics"][0]
        self.assertEqual(item["status"], "insufficient_evidence")
        self.assertIsNone(item["value"])


if __name__ == "__main__":
    unittest.main()
