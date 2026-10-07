"""Offline contract between saved v0.4 beam products and evaluation v1.0.

The fixture and confirmation are synthetic.  They do not authorize real data
processing or represent an engineering acceptance result.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
BEAMFORMING = PROJECT / "skills" / "underwater-beamforming"
EVALUATION = PROJECT / "skills" / "underwater-beamforming-evaluation"
RUN_ROOT = PROJECT / ".run" / "beamforming-evaluation-integration"
RUN_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(RUN_ROOT / "matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

for folder in (BEAMFORMING / "scripts", BEAMFORMING / "tests"):
    sys.path.insert(0, str(folder))

import execute as beam_runner
from test_numerical import mock_confirm, numerical_fixture
from test_output_products import settings

sys.path.insert(0, str(EVALUATION / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    spec.loader.exec_module(module)
    return module


evaluation_contract = load_module("integrated_beam_evaluation_contract", EVALUATION / "scripts" / "validate_contract.py")
evaluation_runtime = load_module("integrated_beam_evaluation_runtime", EVALUATION / "scripts" / "evaluation_runtime.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_ref(path: Path, object_id: str) -> dict:
    return {"kind": "file", "path": str(path), "sha256": digest(path), "object_id": object_id}


class SavedBeamEvaluationContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=RUN_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def test_saved_spatial_spectrum_maps_directly_to_descriptive_evaluation(self):
        config = numerical_fixture(self.folder)
        config["analysis"] = settings(band=config["plan"]["processing"]["band_hz"])
        config["plan"]["output"]["auxiliary_products"] = ["spatial_spectrum"]
        mock_confirm(config)
        beam_result = beam_runner.execute(config)
        beam_dir = Path(config["plan"]["output"]["directory"])
        power = beam_dir / "cbf_scan_power.npy"
        angles = beam_dir / "directions_deg.npy"
        provenance = beam_dir / "result.json"
        self.assertIn("spatial_spectrum", beam_result["coverage"]["requested_auxiliary_products"])

        upstream_hashes = {path: digest(path) for path in (power, angles, provenance)}
        destination = self.folder / "evaluation"
        request = {
            "schema_version": "1.0.0",
            "record_type": "EvaluationRequest",
            "document_status": "specified",
            "payload": {
                "request_id": "synthetic-v04-spatial-spectrum",
                "mode": "descriptive",
                "question": "Describe the saved CBF spatial spectrum without claiming target truth.",
                "jobs": [{
                    "job_id": "cbf-spatial-spectrum",
                    "command": "spectrum",
                    "subject": "Saved CBF scan output power",
                    "algorithm": "cbf",
                    "scenario": "synthetic integration fixture",
                    "inputs": {
                        "power": file_ref(power, "cbf_scan_power"),
                        "angles": file_ref(angles, "beam_directions"),
                    },
                    "provenance_refs": [file_ref(provenance, "beamforming-result-v0.4")],
                    "parameters": {
                        "scale": "power",
                        "reduce": "max",
                        "mainlobe_exclusion_deg": 5.0,
                        "false_peak_threshold_db": 12.0,
                        "top_k": 2,
                    },
                    "evidence": {
                        "truth_status": "absent",
                        "truth_scope": None,
                        "baseline_status": "absent",
                        "comparability": "not_applicable",
                        "independence": "unknown",
                        "notes": ["Synthetic integration fixture only."],
                    },
                    "limitations": ["No target truth or independent acceptance threshold is provided."],
                }],
                "output_plan": {
                    "save_destination": str(destination),
                    "save_job_results": True,
                    "save_metrics_csv": True,
                    "save_report": True,
                },
                "confirmation": {
                    "status": "recorded",
                    "statement": "Execute this synthetic integration fixture only.",
                },
                "accepted_limitations": ["No target truth is available."],
            },
            "unresolved_items": [],
        }
        request_path = self.folder / "evaluation-request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        validation = evaluation_contract.validate_document(request, "EvaluationRequest")
        self.assertTrue(validation["valid"], validation)
        self.assertTrue(validation["can_execute"])
        checked = evaluation_runtime.preflight(request_path, str(destination))
        self.assertFalse(destination.exists(), "preflight must be read-only")
        published = evaluation_runtime.execute(checked)
        self.assertEqual(published, destination.resolve())

        result = evaluation_contract.read_json(destination / "evaluation-result.json")
        result_validation = evaluation_contract.validate_document(result, "EvaluationResult")
        self.assertTrue(result_validation["valid"], result_validation)
        job = result["payload"]["job_results"][0]
        self.assertEqual(job["status"], "computed")
        self.assertEqual(job["evidence_class"], "descriptive")
        self.assertIn(job["metrics"]["peak_angle_deg"], (0.0, 20.0))
        self.assertIsNone(job["metrics"]["mae_deg"])
        self.assertIsNone(job["metrics"]["rmse_deg"])
        self.assertEqual(result["payload"]["acceptance"]["status"], "not_requested")
        self.assertIn("只读取已保存结果，不重算波束形成", "".join(result["payload"]["limitations"]))
        for path, before in upstream_hashes.items():
            self.assertEqual(digest(path), before, f"evaluation modified upstream artifact {path.name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
