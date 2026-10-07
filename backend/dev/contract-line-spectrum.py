"""Independent CLI contracts for the installed line-spectrum evaluation Skill.

Existing RuntimeFixture data represents explicitly SYNTHETIC persisted detector
evidence, not a new detector or permission to process real recordings. All mock
confirmation and truth records remain inside the isolated test workspace. No
model, detection algorithm, beam receiver, or external service is called.
"""
from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
SKILL = PROJECT / "skills" / "underwater-line-spectrum-evaluation"
CLI = SKILL / "scripts" / "evaluation_runtime.py"
RUN_ROOT = PROJECT / ".run" / "line-spectrum-integration"
RUN_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "tests"))

import test_runtime as provided
from evaluation_runtime import sha256_file
from validate_contract import validate_document

MOCK = "SYNTHETIC INTEGRATION FIXTURE / MOCK ONLY / NEVER REAL USER AUTHORIZATION"


class LineSpectrumEvaluationIntegrationContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=RUN_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.temp = str(self.folder)  # Existing package helper uses this explicit fixture root.
        self.fixture = provided.RuntimeFixture(self.folder)
        self.serial = 0

    def snapshot(self, root):
        return {str(path.relative_to(root)): sha256_file(path)
                for path in sorted(Path(root).rglob("*")) if path.is_file()}

    def cli(self, request, *, output=None, expected=0):
        command = [sys.executable, "-B", str(CLI), str(request)]
        command.extend(["--preflight-only"] if output is None else ["--output-dir", str(output)])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        self.assertTrue(completed.stdout.strip(), "public CLI must return its JSON result")
        return json.loads(completed.stdout)

    def matching_rule(self):
        return {"rule_id": "mock-match-rule", "status": "specified", "frequency_gate_hz": 5.0,
                "time_rule": "frame_identity", "time_gate_s": None,
                "assignment_method": "maximum_cardinality_minimum_frequency_error",
                "tie_break": "candidate_id_then_truth_id", "duplicate_policy": "count_as_false",
                "reason": None}

    def request(self, output, kinds, *, truth=None, rules=None, artifacts=None):
        requests = [provided.metric(f"metric-{index}", kind,
                                   rule="mock-match-rule" if kind in {
                                       "recall", "precision", "f1", "frequency_mae_hz"} else None)
                    for index, kind in enumerate(kinds)]
        request = self.fixture.request(output, requests, truth_binding=truth, rules=rules, artifacts=artifacts)
        request["payload"]["question"] = MOCK
        request["payload"]["confirmation"]["statement"] = MOCK
        request["payload"]["confirmation"]["evidence_ref"]["locator"] = "synthetic-project-contract-only"
        request["payload"]["accepted_limitations"] = [MOCK]
        return request

    def save_request(self, request):
        self.serial += 1
        path = self.folder/f"request-{self.serial}.json"
        provided.write_json(path, request)
        validation = validate_document(request, "EvaluationRequest")
        self.assertTrue(validation["valid"], validation)
        return path

    def artifact(self, kind):
        return {"artifact_id": f"mock-{kind}", "target_ids": [self.fixture.target_id],
                "kind": kind, "compute": True, "display": False, "save": True, "definition": MOCK}

    def rebind_product(self, kind, filename, value):
        """Update only synthetic evidence and its explicit chain of digests."""
        directory = self.fixture.package/"task-000000"/kind
        product_path = directory/filename
        provided.write_json(product_path, value)
        manifest_path = directory/"product.json"
        provided.write_json(manifest_path, {
            "product_id": kind, "task_id": self.fixture.task_id,
            "files": [{"name": filename, "sha256": sha256_file(product_path),
                       "size_bytes": product_path.stat().st_size}],
        })
        result = json.loads(self.fixture.result_path.read_text())
        artifact = next(item for item in result["payload"]["task_results"][0]["artifacts"]
                        if item["kind"] == kind)
        artifact["file_ref"]["sha256"] = sha256_file(manifest_path)
        provided.write_json(self.fixture.result_path, result)

    def with_zero_candidate_frame(self, request):
        """The synthetic third frame was tested successfully and found no candidates."""
        ledger = copy.deepcopy(self.fixture.ledger)
        ledger["rows"].append({"row": 2, "sample_intervals": [[200, 300]], "status": "tested",
                               "tested_bins": list(range(5, 31)), "zero_background_bins": [],
                               "candidate_count": 0, "rejected_groups": []})
        ledger["frame_ledger"].append({"start_sample": 200, "stop_sample": 300,
                                      "status": "eligible", "reason": None})
        ledger["tests_per_event"] = 78
        self.rebind_product("ledger", "ledger.json", ledger)
        result = json.loads(self.fixture.result_path.read_text())
        coverage = result["payload"]["task_results"][0]["coverage"]
        coverage["requested"]["sample_intervals"] = [[0, 300]]
        coverage["processed"] = [[0, 300]]
        provided.write_json(self.fixture.result_path, result)
        target = request["payload"]["targets"][0]
        target["result_ref"] = provided.file_ref(self.fixture.result_path, "DetectionResult")
        target["scope"]["time"]["intervals_s"] = [[0.0, .3]]

    def assert_output_package(self, output):
        result = json.loads((output/"evaluation-result.json").read_text())
        self.assertTrue(validate_document(result, "EvaluationResult")["valid"])
        self.assertEqual(result["payload"]["acceptance"]["status"], "not_requested")
        manifest = json.loads((output/"package-manifest.json").read_text())
        self.assertTrue(manifest["upstream_immutable"])
        for entry in manifest["files"]:
            path = output/entry["path"]
            self.assertEqual(path.stat().st_size, entry["size_bytes"])
            self.assertEqual(sha256_file(path), entry["sha256"])
        return result

    def assert_blocked(self, request, output, *, contains):
        before = self.snapshot(self.fixture.package)
        report = self.cli(request, expected=1)
        self.assertFalse(report["can_execute"])
        self.assertIn(contains, json.dumps(report, ensure_ascii=False))
        self.assertFalse(output.exists(), "read-only preflight must not publish an evaluation")
        failure = self.cli(request, output=output, expected=1)
        self.assertFalse(failure["ok"])
        self.assertFalse(output.exists(), "blocked execution must not publish an evaluation")
        self.assertEqual(self.snapshot(self.fixture.package), before)

    def test_cli_zero_candidate_frames_count_in_denominator_and_missing_truth_never_zero_fills(self):
        output = self.folder/"evaluation"
        kinds = ["candidate_count", "mean_candidates_per_frame", "candidate_frame_fraction",
                 "mean_threshold_margin_db", "mean_background_contrast_db", "recall"]
        request = self.request(output, kinds, rules=[self.matching_rule()], artifacts=[self.artifact("metric_table")])
        self.with_zero_candidate_frame(request)
        path = self.save_request(request)
        before = self.snapshot(self.fixture.package)
        report = self.cli(path)
        self.assertTrue(report["can_execute"], report)
        self.assertEqual(report["targets"][0]["valid_frame_count"], 3)
        self.assertFalse(output.exists(), "preflight is read-only")
        summary = self.cli(path, output=output)
        self.assertTrue(summary["ok"])
        result = self.assert_output_package(output)
        metrics = {item["metric_kind"]: item for item in result["payload"]["metrics"]}
        self.assertEqual(metrics["candidate_count"]["value"], 3)
        self.assertEqual(metrics["mean_candidates_per_frame"]["value"], 1.0)
        self.assertEqual(metrics["mean_candidates_per_frame"]["denominator"]["value"], 3)
        self.assertAlmostEqual(metrics["candidate_frame_fraction"]["value"], 2/3)
        self.assertEqual(metrics["candidate_frame_fraction"]["numerator"]["value"], 2)
        self.assertTrue(metrics["candidate_frame_fraction"]["accounting"]["zero_detection_units_included"])
        self.assertAlmostEqual(metrics["mean_threshold_margin_db"]["value"], 10*math.log10(2))
        self.assertAlmostEqual(metrics["mean_background_contrast_db"]["value"],
                               sum(10*math.log10(value) for value in (10, 8, 6))/3)
        self.assertEqual(metrics["recall"]["status"], "insufficient_evidence")
        self.assertIsNone(metrics["recall"]["value"])
        with (output/"metrics.csv").open(newline="", encoding="utf-8") as stream:
            table = {row["metric_kind"]: row for row in csv.DictReader(stream)}
        self.assertEqual(table["recall"]["status"], "insufficient_evidence")
        self.assertEqual(table["recall"]["value"], "")
        self.assertFalse((output/"report.md").exists(), "no report was requested")
        self.assertFalse((output/"matches.json").exists(), "no matching audit was requested")
        self.assertEqual(self.snapshot(self.fixture.package), before)

    def truth(self):
        coverage_path = provided.RuntimeTests.truth_documents(self)
        coverage = json.loads(coverage_path.read_text())
        coverage["payload"]["evidence_origin"] = "simulation"
        coverage["payload"]["limitations"] = [MOCK]
        provided.write_json(coverage_path, coverage)
        return {"target_id": self.fixture.target_id, "status": "provided",
                "coverage_ref": provided.file_ref(coverage_path, "coverage-001"), "reason": None}

    def test_cli_complete_synthetic_truth_matches_original_candidate_ids_and_preserves_sources(self):
        output = self.folder/"matched-evaluation"
        request = self.request(output, ["recall", "precision", "f1", "frequency_mae_hz"],
                               truth=self.truth(), rules=[self.matching_rule()],
                               artifacts=[self.artifact("matches"), self.artifact("metric_table")])
        path = self.save_request(request)
        before = self.snapshot(self.fixture.package)
        truth_before = {name: sha256_file(self.folder/name)
                        for name in ("truth-coverage.json", "truth-labels.json")}
        self.assertTrue(self.cli(path)["can_execute"])
        self.assertTrue(self.cli(path, output=output)["ok"])
        result = self.assert_output_package(output)
        values = {item["metric_kind"]: item["value"] for item in result["payload"]["metrics"]}
        self.assertEqual(values["recall"], 1.0)
        self.assertAlmostEqual(values["precision"], 2/3)
        self.assertEqual(values["f1"], .8)
        self.assertEqual(values["frequency_mae_hz"], 1.0)
        matches = json.loads((output/"matches.json").read_text())["results"][0]
        self.assertEqual(matches["unmatched_candidate_ids"], ["c2"])
        self.assertEqual(matches["unmatched_truth_ids"], [])
        self.assertEqual({item["candidate_id"] for item in matches["matches"]}, {"c1", "c3"})
        self.assertEqual({item["truth_id"] for item in matches["matches"]}, {"t1", "t2"})
        self.assertFalse((output/"report.md").exists())
        self.assertEqual(self.snapshot(self.fixture.package), before)
        self.assertEqual({name: sha256_file(self.folder/name) for name in truth_before}, truth_before)

    def test_unknown_or_missing_detection_result_version_blocks_even_with_current_digest(self):
        original = json.loads(self.fixture.result_path.read_text())
        for version in ("0.2.0", "1.0.0", None):
            with self.subTest(version=version):
                result = copy.deepcopy(original)
                if version is None:
                    result.pop("schema_version")
                else:
                    result["schema_version"] = version
                provided.write_json(self.fixture.result_path, result)
                output = self.folder/f"unsupported-{version}"
                path = self.save_request(self.request(output, ["candidate_count"]))
                self.assert_blocked(path, output, contains="Unsupported DetectionResult schema_version")

    def test_changed_candidate_product_digest_blocks_before_output_publication(self):
        output = self.folder/"stale-candidates"
        path = self.save_request(self.request(output, ["candidate_count"]))
        candidate_path = self.fixture.package/"task-000000"/"candidates"/"candidates.json"
        candidate_path.write_text("[]\n", encoding="utf-8")
        self.assert_blocked(path, output, contains="Product file identity mismatch")

    def test_pending_confirmation_does_not_execute_complete_persisted_evidence(self):
        output = self.folder/"unconfirmed"
        request = self.request(output, ["candidate_count"])
        request["payload"]["confirmation"] = {"status": "pending", "evidence_ref": None, "statement": None}
        path = self.save_request(request)
        self.assert_blocked(path, output, contains="confirmation_missing")

    def test_missing_declared_truth_labels_blocks_without_fabricating_or_rerunning_detection(self):
        output = self.folder/"missing-truth"
        request = self.request(output, ["recall"], truth=self.truth(), rules=[self.matching_rule()])
        path = self.save_request(request)
        (self.folder/"truth-labels.json").unlink()
        self.assert_blocked(path, output, contains="Referenced file is unavailable")
        self.assertFalse((self.folder/"truth-labels.json").exists())

    def test_completed_output_is_immutable_and_cannot_be_replaced_by_second_execution(self):
        output = self.folder/"existing-evaluation"
        path = self.save_request(self.request(output, ["candidate_count"]))
        self.assertTrue(self.cli(path)["can_execute"])
        self.assertTrue(self.cli(path, output=output)["ok"])
        self.assert_output_package(output)
        before = self.snapshot(output)
        failure = self.cli(path, output=output, expected=1)
        self.assertFalse(failure["ok"])
        self.assertIn("refusing to overwrite", failure["error"])
        self.assertEqual(self.snapshot(output), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
