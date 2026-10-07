"""Contract and package-runtime tests using only synthetic arrays."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_module("beam_eval_contract", ROOT / "scripts" / "validate_contract.py")
runtime = load_module("beam_eval_runtime", ROOT / "scripts" / "evaluation_runtime.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_ref(path, object_id):
    return {"kind": "file", "path": str(path), "sha256": digest(path), "object_id": object_id}


def evidence(truth="absent", baseline="absent", comparability="not_applicable"):
    return {"truth_status": truth, "truth_scope": None if truth != "provided" else "All synthetic rows",
            "baseline_status": baseline, "comparability": comparability,
            "independence": "unknown", "notes": []}


def request(power, angles, destination, confirmed=True):
    return {
        "schema_version": "1.0.0", "record_type": "EvaluationRequest", "document_status": "specified",
        "payload": {
            "request_id": "synthetic-request", "mode": "descriptive",
            "question": "Describe a synthetic spatial spectrum without claiming target truth.",
            "jobs": [{
                "job_id": "spatial-cbf", "command": "spectrum", "subject": "Synthetic scan power",
                "algorithm": "cbf", "scenario": "unit-test",
                "inputs": {"power": file_ref(power, "power"), "angles": file_ref(angles, "angles")},
                "provenance_refs": [file_ref(power, "synthetic-provenance-placeholder")],
                "parameters": {"scale": "power", "reduce": "max", "mainlobe_exclusion_deg": 1.0,
                               "false_peak_threshold_db": 12.0, "top_k": 3},
                "evidence": evidence(), "limitations": ["Synthetic fixture only."]
            }],
            "output_plan": {"save_destination": str(destination), "save_job_results": True,
                            "save_metrics_csv": True, "save_report": True},
            "confirmation": {"status": "recorded" if confirmed else "pending",
                             "statement": "Execute this synthetic fixture." if confirmed else None},
            "accepted_limitations": ["No truth is available."]
        },
        "unresolved_items": []
    }


class ContractRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_ctx.name)
        self.power = self.tmp / "power.npy"
        self.angles = self.tmp / "angles.npy"
        np.save(self.power, np.array([1.0, 4.0, 1.0]))
        np.save(self.angles, np.array([-1.0, 0.0, 1.0]))
        self.output = self.tmp / "evaluation"

    def tearDown(self):
        self.tmp_ctx.cleanup()

    def test_draft_template_is_valid_but_not_executable(self):
        draft = contract.read_json(ROOT / "assets" / "templates" / "EvaluationRequest.draft.json")
        report = contract.validate_document(draft, "EvaluationRequest")
        self.assertTrue(report["valid"], report)
        self.assertFalse(report["can_execute"])

    def test_specified_request_is_valid_and_executable(self):
        report = contract.validate_document(request(self.power, self.angles, self.output), "EvaluationRequest")
        self.assertTrue(report["valid"], report)
        self.assertTrue(report["can_execute"])

    def test_pending_request_is_not_executable(self):
        report = contract.validate_document(request(self.power, self.angles, self.output, confirmed=False))
        self.assertTrue(report["valid"], report)
        self.assertFalse(report["can_execute"])

    def test_duplicate_job_id_rejected(self):
        document = request(self.power, self.angles, self.output)
        document["payload"]["jobs"].append(copy.deepcopy(document["payload"]["jobs"][0]))
        self.assertFalse(contract.validate_document(document)["valid"])

    def test_missing_required_input_rejected(self):
        document = request(self.power, self.angles, self.output)
        del document["payload"]["jobs"][0]["inputs"]["power"]
        self.assertFalse(contract.validate_document(document)["valid"])

    def test_truth_input_requires_truth_declaration(self):
        document = request(self.power, self.angles, self.output)
        document["payload"]["jobs"][0]["parameters"]["truth_deg"] = "0"
        self.assertFalse(contract.validate_document(document)["valid"])
        document["payload"]["jobs"][0]["evidence"].update(truth_status="provided", truth_scope="All rows")
        self.assertTrue(contract.validate_document(document)["valid"])

    def test_compare_requires_confirmed_comparability(self):
        metrics_csv = self.tmp / "metrics.csv"
        spec_csv = self.tmp / "spec.csv"
        metrics_csv.write_text("algorithm,rmse\nA,1\n")
        spec_csv.write_text("metric,direction,weight\nrmse,lower,1\n")
        document = request(self.power, self.angles, self.output)
        document["payload"]["mode"] = "paper"
        job = document["payload"]["jobs"][0]
        job.update(command="compare", inputs={"metrics": file_ref(metrics_csv, "metrics"),
                                               "spec": file_ref(spec_csv, "spec")}, parameters={})
        self.assertFalse(contract.validate_document(document)["valid"])
        job["evidence"]["comparability"] = "confirmed"
        self.assertTrue(contract.validate_document(document)["valid"])

    def test_relative_destination_rejected(self):
        document = request(self.power, self.angles, Path("relative-output"))
        self.assertFalse(contract.validate_document(document)["valid"])

    def test_schema_rejects_unknown_field(self):
        document = request(self.power, self.angles, self.output)
        document["payload"]["jobs"][0]["unexpected"] = True
        self.assertFalse(contract.validate_document(document)["valid"])

    def test_duplicate_json_key_and_nonfinite_are_rejected(self):
        duplicate = self.tmp / "duplicate.json"
        duplicate.write_text('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            contract.read_json(duplicate)
        nonfinite = self.tmp / "nonfinite.json"
        nonfinite.write_text('{"a":NaN}')
        with self.assertRaises(ValueError):
            contract.read_json(nonfinite)

    def _save_request(self, document):
        path = self.tmp / "request.json"
        path.write_text(json.dumps(document, indent=2))
        return path

    def test_preflight_detects_digest_mismatch(self):
        document = request(self.power, self.angles, self.output)
        document["payload"]["jobs"][0]["inputs"]["power"]["sha256"] = "0" * 64
        path = self._save_request(document)
        with self.assertRaises(runtime.EvaluationError):
            runtime.preflight(path)

    def test_preflight_is_read_only(self):
        path = self._save_request(request(self.power, self.angles, self.output))
        before = digest(self.power)
        checked = runtime.preflight(path)
        self.assertFalse(self.output.exists())
        self.assertEqual(before, digest(self.power))
        self.assertEqual(checked["resolved_jobs"][0]["inputs"]["power"]["sha256"], before)

    def test_output_override_must_match(self):
        path = self._save_request(request(self.power, self.angles, self.output))
        with self.assertRaises(runtime.EvaluationError):
            runtime.preflight(path, str(self.tmp / "other"))

    def test_execute_publishes_valid_package_without_mutating_source(self):
        path = self._save_request(request(self.power, self.angles, self.output))
        before = digest(self.power)
        destination = runtime.execute(runtime.preflight(path))
        self.assertEqual(destination, self.output.resolve())
        self.assertEqual(before, digest(self.power))
        expected = {"evaluation-result.json", "resolved-evaluation-config.json", "job-results.json",
                    "metrics.csv", "report.md", "package-manifest.json"}
        self.assertEqual({item.name for item in destination.iterdir()}, expected)
        result = contract.read_json(destination / "evaluation-result.json")
        validation = contract.validate_document(result, "EvaluationResult")
        self.assertTrue(validation["valid"], validation)
        job = result["payload"]["job_results"][0]
        self.assertEqual(job["metrics"]["peak_angle_deg"], 0.0)
        self.assertEqual(job["evidence_class"], "descriptive")
        self.assertEqual(result["payload"]["acceptance"]["status"], "not_requested")
        manifest = json.loads((destination / "package-manifest.json").read_text())
        for item in manifest["files"]:
            artifact = destination / item["path"]
            self.assertEqual(digest(artifact), item["sha256"])

    def test_existing_destination_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep")
        path = self._save_request(request(self.power, self.angles, self.output))
        with self.assertRaises(runtime.EvaluationError):
            runtime.preflight(path)
        self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
