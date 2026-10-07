"""Offline contract from a compliant detection handoff through tracking evaluation.

All candidates, parameters and approvals are synthetic fixtures.  This test
does not authorize processing real recordings or claim target identity.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
TRACKING = PROJECT / "skills" / "underwater-line-spectrum-tracking"
EVALUATION = PROJECT / "skills" / "underwater-line-spectrum-tracking-evaluation"
RUN_ROOT = PROJECT / ".run" / "line-spectrum-tracking-integration"
RUN_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(RUN_ROOT / "matplotlib"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    spec.loader.exec_module(module)
    return module


tracking_fixtures = load_module(
    "integrated_tracking_fixtures", TRACKING / "tests" / "test_tracking_runtime.py"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class TrackingEvaluationIntegrationContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=RUN_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def cli(self, script: Path, *arguments: str) -> dict:
        process = subprocess.run(
            [sys.executable, "-B", "-W", "error::RuntimeWarning", str(script), *map(str, arguments)],
            cwd=PROJECT,
            env={**os.environ, "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(RUN_ROOT / "matplotlib")},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_detection_handoff_tracks_then_evaluates_without_mutating_sources(self):
        fixture = tracking_fixtures.RuntimeFixture(
            self.folder,
            [[(10.0, 1.0)], [(10.2, 1.1)], [], [(10.6, 1.05)], [(10.8, 1.0)]],
        )
        tracking_request = fixture.request(gate=1.0, max_missed=1, minimum=3)
        tracking_request["payload"]["tracking_run_id"] = "synthetic-tracking-integration"
        tracking_request_path = self.folder / "tracking-request.json"
        write_json(tracking_request_path, tracking_request)

        upstream_files = [fixture.handoff_path, *sorted(fixture.package.rglob("*"))]
        upstream_files = [path for path in upstream_files if path.is_file()]
        upstream_hashes = {path: digest(path) for path in upstream_files}

        tracking_script = TRACKING / "scripts" / "tracking_runtime.py"
        tracking_review = self.cli(tracking_script, "review", tracking_request_path)
        self.assertEqual(tracking_review["status"], "ready_pending_execution_confirmation")
        tracking_answer = self.cli(
            tracking_script,
            "execute",
            tracking_request_path,
            "--review-sha256",
            tracking_review["review_sha256"],
        )
        self.assertEqual(tracking_answer["status"], "completed")
        tracking_output = Path(tracking_answer["output_directory"])
        tracking_result = json.loads((tracking_output / "tracking-result.json").read_text(encoding="utf-8"))
        self.assertEqual(tracking_result["coverage"]["candidate_count"], 4)
        self.assertEqual(tracking_result["coverage"]["associated_candidate_count"], 4)
        self.assertFalse(tracking_result["semantic_boundary"]["detection_recomputed"])
        self.assertFalse(tracking_result["semantic_boundary"]["target_identification_performed"])

        tracking_hashes = {
            path: digest(path) for path in sorted(tracking_output.rglob("*")) if path.is_file()
        }
        evaluation_output = self.folder / "tracking-evaluation"
        evaluation_request = {
            "schema_version": "1.0.0",
            "record_type": "TrackingEvaluationRequest",
            "document_status": "specified",
            "payload": {
                "evaluation_id": "synthetic-tracking-evaluation",
                "mode": "descriptive",
                "primary": {
                    "directory": str(tracking_output.resolve()),
                    "manifest_sha256": digest(tracking_output / "package-manifest.json"),
                },
                "baseline": None,
                "truth": None,
                "settings": {
                    "short_track_max_detections": 2,
                    "continuity_basis": "all_rows",
                    "truth_matching": None,
                },
                "acceptance_checks": [],
                "products": {"save_matches": False, "save_plots": False, "plot_dpi": 120},
                "output_directory": str(evaluation_output.resolve()),
            },
            "unresolved_items": [],
        }
        evaluation_request_path = self.folder / "evaluation-request.json"
        write_json(evaluation_request_path, evaluation_request)

        evaluation_script = EVALUATION / "scripts" / "evaluation_runtime.py"
        evaluation_review = self.cli(evaluation_script, "review", evaluation_request_path)
        self.assertEqual(evaluation_review["status"], "ready")
        evaluation_answer = self.cli(
            evaluation_script,
            "execute",
            evaluation_request_path,
            "--review-sha256",
            evaluation_review["review_sha256"],
        )
        self.assertEqual(evaluation_answer["status"], "completed")
        self.assertEqual(evaluation_answer["evidence_level"], "descriptive_only")
        self.assertEqual(evaluation_answer["acceptance"], "not_requested")
        evaluation_result = json.loads(
            (evaluation_output / "evaluation-result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(evaluation_result["metrics"]["descriptive"]["association_completeness"], 1.0)
        self.assertNotIn("truth", evaluation_result["metrics"])

        for path, before in {**upstream_hashes, **tracking_hashes}.items():
            self.assertEqual(digest(path), before, f"downstream step modified {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
