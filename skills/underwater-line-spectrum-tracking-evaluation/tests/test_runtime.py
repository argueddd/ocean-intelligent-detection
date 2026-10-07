from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation_runtime import EvaluationError, execute, prepare, sha256_file  # noqa: E402


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def make_result(run_id="tracking-primary", frequencies=(10.0, 10.1, 10.2, 10.3), source_hash=HASH_B):
    rows = []
    for row in range(4):
        rows.append({
            "row": row, "time_seconds": float(row), "source_status": "tested", "candidate_count": 1,
            "matched_count": 1 if row in (1, 3) else 0, "new_track_count": 1 if row in (0, 2) else 0,
            "unmatched_active_track_count": 0, "terminated_track_ids": [],
            "active_track_count_after_row": 1 if row != 2 else 2,
        })
    track_specs = [
        ("track_000001", [0, 1, 3], "confirmed", "end_of_input", 1),
        ("track_000002", [2], "tentative", "gap_exceeded", 1),
    ]
    tracks = []
    associations = []
    for track_id, track_rows, status, termination, missed in track_specs:
        points = []
        for point_index, row in enumerate(track_rows):
            candidate_id = f"candidate_{row:04d}"
            kind = "new_track" if point_index == 0 else "matched"
            points.append({
                "point_index": point_index, "candidate_id": candidate_id, "row": row,
                "time_seconds": float(row), "frequency_hz": frequencies[row], "power": 1.0,
                "association_kind": kind, "predicted_frequency_hz": None if point_index == 0 else frequencies[track_rows[point_index - 1]],
                "frequency_residual_hz": None if point_index == 0 else abs(frequencies[row] - frequencies[track_rows[point_index - 1]]),
                "power_change_db": None, "association_cost": None if point_index == 0 else 0.1,
            })
            associations.append({
                "detection_run_id": "detect-run", "detection_task_id": "detect-task",
                "candidate_id": candidate_id, "tracking_run_id": run_id, "track_id": track_id,
                "row": row, "association_kind": kind,
            })
        selected = [frequencies[row] for row in track_rows]
        tracks.append({
            "track_id": track_id, "confirmation_status": status, "termination_reason": termination,
            "start_row": track_rows[0], "end_row": track_rows[-1],
            "start_time_seconds": float(track_rows[0]), "end_time_seconds": float(track_rows[-1]),
            "detection_count": len(points), "maximum_consecutive_missed_rows": missed,
            "frequency_summary": {"minimum_hz": min(selected), "maximum_hz": max(selected), "mean_hz": sum(selected) / len(selected), "ols_slope_hz_per_s": None if len(selected) == 1 else 0.1},
            "points": points, "quality_flags": ["association_not_source_or_target_identity"],
        })
    boundary = {
        "detection_recomputed": False, "tracking_performed": True, "harmonic_grouping_performed": False,
        "source_association_performed": False, "target_identification_performed": False, "evaluation_performed": False,
    }
    return {
        "schema_version": "1.0.0", "record_type": "TrackingResult", "status": "completed", "tracking_run_id": run_id,
        "source": {
            "handoff_path": "/evidence/handoff.json", "handoff_sha256": HASH_A,
            "detection_run_id": "detect-run", "detection_task_id": "detect-task",
            "candidate_table_sha256": source_hash, "ledger_sha256": HASH_C,
            "time_reference": "relative seconds", "input_ref": {"signal_id": "signal"},
            "detector": {"detector_id": "test"}, "beam_source": {"status": "not_applicable"},
            "analysis_grid": {"frequency_spacing_hz": 0.1}, "power_measurement_definition": None,
        },
        "resolved_algorithm": {"tracker_id": "test"},
        "coverage": {"detection_row_count": 4, "tested_row_count": 4, "skipped_row_count": 0, "zero_candidate_row_count": 0, "candidate_count": 4, "associated_candidate_count": 4, "time_range_seconds": [0.0, 3.0]},
        "tracks": tracks, "candidate_track_associations": associations, "row_ledger": rows,
        "semantic_boundary": boundary, "limitations": ["synthetic fixture"], "validation": {},
    }


def make_package(directory, result):
    directory = Path(directory)
    directory.mkdir()
    result_path = directory / "tracking-result.json"
    write_json(result_path, result)
    boundary = result["semantic_boundary"]
    manifest = {
        "package_version": "1.0.0", "record_type": "TrackingResultPackage", "status": "completed",
        "tracking_run_id": result["tracking_run_id"],
        "files": [{"path": "tracking-result.json", "size_bytes": result_path.stat().st_size, "sha256": sha256_file(result_path)}],
        "semantic_boundary": boundary,
    }
    manifest_path = directory / "package-manifest.json"
    write_json(manifest_path, manifest)
    return {"directory": str(directory.resolve()), "manifest_sha256": sha256_file(manifest_path)}


def make_truth(path, complete=False):
    truth = {
        "schema_version": "1.0.0", "record_type": "TrackingTruthLabels",
        "label_status": "complete" if complete else "partial_positive",
        "source": {"detection_run_id": "detect-run", "detection_task_id": "detect-task", "candidate_table_sha256": HASH_B, "ledger_sha256": HASH_C, "time_reference": "relative seconds"},
        "label_scope": {"row_ranges": [[0, 4]], "frequency_range_hz": [9.0, 11.0], "truth_tracks_complete": complete, "negative_labels_complete": complete},
        "truth_tracks": [{"truth_track_id": "truth_001", "points": [{"row": row, "time_seconds": float(row), "frequency_hz": 10.0 + 0.1 * row} for row in range(4)]}],
        "provenance": {"description": "synthetic", "version": "1", "created_by": "unit-test"},
        "limitations": ["synthetic fixture"],
    }
    write_json(path, truth)
    return {"path": str(Path(path).resolve()), "sha256": sha256_file(path)}


def make_request(path, primary, output, *, mode="descriptive", truth=None, baseline=None, checks=None):
    request = {
        "schema_version": "1.0.0", "record_type": "TrackingEvaluationRequest", "document_status": "specified",
        "payload": {
            "evaluation_id": "eval-test", "mode": mode, "primary": primary, "baseline": baseline, "truth": truth,
            "settings": {
                "short_track_max_detections": 1, "continuity_basis": "all_rows",
                "truth_matching": None if truth is None else {"assignment_method": "per_row_maximum_cardinality_minimum_frequency_error", "tie_break": "estimated_track_id_then_truth_track_id", "frequency_tolerance_hz": 0.05, "minimum_matched_points": 1, "minimum_truth_track_recall": 0.5},
            },
            "acceptance_checks": checks or [],
            "products": {"save_matches": truth is not None, "save_plots": False, "plot_dpi": 100},
            "output_directory": str(Path(output).resolve()),
        },
        "unresolved_items": [],
    }
    write_json(path, request)
    return request


class RuntimeTests(unittest.TestCase):
    def test_descriptive_review_and_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            request_path = root / "request.json"
            output = root / "output"
            make_request(request_path, primary, output, checks=[{"check_id": "complete", "metric": "descriptive.association_completeness", "operator": "==", "threshold": 1.0, "source": "contract"}])
            _, _, _, _, review = prepare(request_path)
            _, result = execute(request_path, review["review_sha256"])
            self.assertEqual(result["evidence_level"], "descriptive_only")
            self.assertEqual(result["acceptance"]["aggregate_status"], "passed")
            self.assertEqual(result["metrics"]["descriptive"]["track_count"], 2)
            self.assertAlmostEqual(result["metrics"]["descriptive"]["short_track_fraction"], 0.5)
            self.assertTrue((output / "package-manifest.json").is_file())

    def test_partial_truth_withholds_precision_and_counts_fragmentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            truth = make_truth(root / "truth.json", complete=False)
            request_path = root / "request.json"
            output = root / "output"
            make_request(request_path, primary, output, mode="truth", truth=truth)
            _, _, _, _, review = prepare(request_path)
            _, result = execute(request_path, review["review_sha256"])
            metrics = result["metrics"]["truth"]
            self.assertEqual(result["evidence_level"], "partial_truth")
            self.assertEqual(metrics["point_recall"], 1.0)
            self.assertIsNone(metrics["point_precision"])
            self.assertIsNone(metrics["fragmentation_count"])
            self.assertEqual(metrics["observed_labeled_fragmentation_count"], 1)
            self.assertTrue((output / "matches.json").is_file())

    def test_complete_truth_reports_precision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            truth = make_truth(root / "truth.json", complete=True)
            request_path = root / "request.json"
            make_request(request_path, primary, root / "output", mode="truth", truth=truth)
            _, _, _, _, review = prepare(request_path)
            _, result = execute(request_path, review["review_sha256"])
            self.assertEqual(result["evidence_level"], "complete_truth")
            self.assertEqual(result["metrics"]["truth"]["point_precision"], 1.0)
            self.assertEqual(result["metrics"]["truth"]["fragmentation_count"], 1)

    def test_comparison_requires_same_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            baseline = make_package(root / "baseline", make_result("tracking-baseline", source_hash="d" * 64))
            request_path = root / "request.json"
            make_request(request_path, primary, root / "output", mode="comparison", baseline=baseline)
            with self.assertRaisesRegex(EvaluationError, "not directly comparable"):
                prepare(request_path)

    def test_comparison_produces_raw_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            baseline_result = make_result("tracking-baseline", frequencies=(10.0, 10.2, 10.2, 10.4))
            baseline = make_package(root / "baseline", baseline_result)
            request_path = root / "request.json"
            make_request(request_path, primary, root / "output", mode="comparison", baseline=baseline)
            _, _, _, _, review = prepare(request_path)
            _, result = execute(request_path, review["review_sha256"])
            self.assertIsNotNone(result["comparison"])
            self.assertIn("descriptive.frequency_step_abs_hz.mean", result["comparison"]["delta_primary_minus_baseline"])

    def test_tampered_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            with (root / "primary/tracking-result.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            request_path = root / "request.json"
            make_request(request_path, primary, root / "output")
            with self.assertRaisesRegex(EvaluationError, "identity mismatch"):
                prepare(request_path)

    def test_wrong_review_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = make_package(root / "primary", make_result())
            request_path = root / "request.json"
            output = root / "output"
            make_request(request_path, primary, output)
            with self.assertRaisesRegex(EvaluationError, "review SHA-256 mismatch"):
                execute(request_path, "0" * 64)
            output.mkdir()
            _, _, _, _, review = prepare(request_path)
            with self.assertRaisesRegex(EvaluationError, "refusing overwrite"):
                execute(request_path, review["review_sha256"])


if __name__ == "__main__":
    unittest.main()
