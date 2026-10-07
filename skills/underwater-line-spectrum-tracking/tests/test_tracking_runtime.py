import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tracking_runtime", ROOT / "scripts" / "tracking_runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def raw(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def candidate(candidate_id, task_id, row, frequency, interval, power=1.0):
    measurements = [] if power is None else [{
        "name": "power", "value": power, "definition_id": "cfar-v1/power",
        "definition_version": "1.0.0", "unit": "fixture^2/Hz", "scale": "linear"
    }]
    return {
        "candidate_id": candidate_id,
        "task_id": task_id,
        "frequency": {"value_hz": frequency},
        "analysis_support": {"sample_intervals": [interval]},
        "measurements": measurements,
        "extensions": {"cfar_v1": {"row": row}},
    }


class RuntimeFixture:
    def __init__(self, base, row_candidates, statuses=None):
        self.base = Path(base)
        self.package = self.base / "detection-package"
        self.package.mkdir()
        self.task_id = "task-framewise"
        statuses = statuses or ["tested"] * len(row_candidates)
        self.rows = []
        self.candidates = []
        for row_index, values in enumerate(row_candidates):
            interval = [row_index * 100, row_index * 100 + 100]
            self.rows.append({"row": row_index, "status": statuses[row_index],
                              "sample_intervals": [interval], "candidate_count": len(values)})
            for item_index, item in enumerate(values):
                if len(item) == 2:
                    frequency, power = item
                else:
                    frequency, power = item[0], 1.0
                self.candidates.append(candidate(f"c{row_index}_{item_index}", self.task_id,
                                                 row_index, frequency, interval, power))
        self.ledger = {"rows": self.rows, "frame_ledger": []}
        contents = {
            "detection-result.json": {"status": "completed"},
            "resolved-configuration.json": {"status": "resolved"},
            "products/candidates/manifest.json": {"product_id": "candidates"},
            "products/candidates/candidates.json": self.candidates,
            "products/ledger/manifest.json": {"product_id": "ledger"},
            "products/ledger/ledger.json": self.ledger,
        }
        self.refs = {}
        for name, value in contents.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = raw(value)
            path.write_bytes(data)
            self.refs[name] = {"path": name, "sha256": digest(data), "size_bytes": len(data)}
        manifest = raw({"status": "completed", "files": list(self.refs.values())})
        (self.package / "package-manifest.json").write_bytes(manifest)
        self.handoff = {
            "handoff_version": "1.0.0",
            "record_type": "DetectionTrackingHandoff",
            "status": "ready",
            "source_package": {
                "directory": str(self.package), "manifest_sha256": digest(manifest),
                "manifest_size_bytes": len(manifest), "run_id": "detection-run", "package_status": "completed"
            },
            "task": {"task_id": self.task_id, "task_kind": "framewise", "input_ref": {}, "detector": {}},
            "signal": {
                "sample_rate_hz": 100.0,
                "time_mapping": {"sample_zero_offset_seconds": 0.0},
                "beam_source": {}, "units": {}, "validity": {}
            },
            "analysis_grid": {
                "window_length_samples": 100, "hop_length_samples": 100, "nfft": 200,
                "window": "periodic_hann", "demean": True, "frame_origin": "signal_sample_zero",
                "frequency_grid_definition": "fixture", "frequency_spacing_hz": 0.5,
                "nyquist_hz": 50.0, "time_reference": "fixture-relative"
            },
            "scope": {}, "coverage": {},
            "evidence": {
                "detection_result": self.refs["detection-result.json"],
                "resolved_configuration": self.refs["resolved-configuration.json"],
                "candidate_product_manifest": self.refs["products/candidates/manifest.json"],
                "candidate_table": self.refs["products/candidates/candidates.json"],
                "ledger_product_manifest": self.refs["products/ledger/manifest.json"],
                "ledger": self.refs["products/ledger/ledger.json"],
            },
            "completeness": {
                "candidate_table_complete": True, "candidate_count": len(self.candidates),
                "frame_ledger_complete": True, "complete_frame_count": len(self.rows),
                "detection_row_count": len(self.rows), "zero_candidate_rows_included": True,
                "zero_candidate_row_count": sum(not values for values in row_candidates),
                "invalid_or_skipped_frames_preserved": True,
                "invalid_or_skipped_frame_count": sum(value == "skipped" for value in statuses),
                "candidate_output_truncated": False
            },
            "semantic_boundary": {
                "detection_completed": True, "tracking_performed": False,
                "harmonic_grouping_performed": False, "source_association_performed": False,
                "target_identification_performed": False, "evaluation_performed": False,
                "association_record_semantics": "provenance_only_not_physical_target_association"
            },
            "limitations": ["fixture detection candidates are not targets"]
        }
        self.handoff_path = self.base / "handoff.json"
        self.handoff_raw = raw(self.handoff)
        self.handoff_path.write_bytes(self.handoff_raw)

    def request(self, *, output="tracking-output", gate=4.0, rate=None, power_gate=None,
                power_weight=0.0, max_missed=1, basis="all_rows", minimum=2,
                prediction="last_frequency"):
        return {
            "schema_version": "1.0.0", "record_type": "TrackingRequest", "document_status": "specified",
            "payload": {
                "tracking_run_id": "tracking-run",
                "handoff": {"path": str(self.handoff_path), "sha256": digest(self.handoff_raw)},
                "output_directory": str(self.base / output),
                "algorithm": {
                    "tracker_id": "global-frequency-assignment-v1", "tracker_version": "1.0.0",
                    "prediction_mode": prediction, "frequency_gate_hz": gate,
                    "frequency_rate_gate_hz_per_s": rate, "power_change_gate_db": power_gate,
                    "frequency_cost_weight": 1.0, "power_cost_weight": power_weight,
                    "max_missed_rows": max_missed, "gap_count_basis": basis,
                    "min_confirmed_detections": minimum
                },
                "products": {"save_plot": False, "plot_dpi": 120}
            },
            "unresolved_items": []
        }


class TrackingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_request(self, fixture, request):
        request_raw = raw(request)
        review, state = runtime._prepare(request, request_raw)
        result = runtime._track(state, request, review)
        return review, result

    def test_schemas_and_draft_template_are_valid(self):
        from jsonschema import Draft202012Validator
        for schema_path in (runtime.REQUEST_SCHEMA, runtime.HANDOFF_SCHEMA, runtime.RESULT_SCHEMA):
            Draft202012Validator.check_schema(json.loads(schema_path.read_text()))
        request_schema = json.loads(runtime.REQUEST_SCHEMA.read_text())
        draft = json.loads((ROOT / "assets/templates/TrackingRequest.draft.json").read_text())
        self.assertEqual(list(Draft202012Validator(request_schema).iter_errors(draft)), [])

    def test_review_and_execute_preserve_all_candidates(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [(11.0, 1.2)], [], [(13.0, 1.1)]])
        request = fixture.request(gate=3.0, max_missed=1, minimum=3)
        request_raw = raw(request)
        review = runtime.review(request, request_raw)
        answer = runtime.execute(request, request_raw, review["review_sha256"])
        self.assertEqual(answer["track_count"], 1)
        self.assertEqual(answer["confirmed_track_count"], 1)
        result = json.loads((Path(answer["output_directory"]) / "tracking-result.json").read_text())
        self.assertEqual(result["coverage"]["candidate_count"], 3)
        self.assertEqual(len(result["candidate_track_associations"]), 3)
        self.assertFalse(result["semantic_boundary"]["target_identification_performed"])
        self.assertTrue((Path(answer["output_directory"]) / "package-manifest.json").is_file())

    def test_gap_exceeded_splits_track(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [], [(10.5, 1.0)]])
        _review, result = self.run_request(fixture, fixture.request(max_missed=0))
        self.assertEqual(len(result["tracks"]), 2)
        self.assertEqual(result["tracks"][0]["termination_reason"], "gap_exceeded")

    def test_global_assignment_maximizes_cardinality(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0), (14.0, 1.0)], [(13.0, 1.0), (17.0, 1.0)]])
        _review, result = self.run_request(fixture, fixture.request(gate=4.0))
        tracks = {track["track_id"]: [point["frequency_hz"] for point in track["points"]]
                  for track in result["tracks"]}
        self.assertEqual(len(tracks), 2)
        self.assertIn([10.0, 13.0], tracks.values())
        self.assertIn([14.0, 17.0], tracks.values())

    def test_power_gate_blocks_frequency_match(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [(10.1, 100.0)]])
        request = fixture.request(power_gate=5.0, power_weight=1.0)
        _review, result = self.run_request(fixture, request)
        self.assertEqual(len(result["tracks"]), 2)

    def test_skipped_row_policy_is_explicit(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [], [(10.2, 1.0)]],
                                 statuses=["tested", "skipped", "tested"])
        _review, tested_only = self.run_request(
            fixture, fixture.request(output="one", max_missed=0, basis="tested_rows_only"))
        _review, all_rows = self.run_request(
            fixture, fixture.request(output="two", max_missed=0, basis="all_rows"))
        self.assertEqual(len(tested_only["tracks"]), 1)
        self.assertEqual(len(all_rows["tracks"]), 2)

    def test_evidence_change_invalidates_review(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [(10.2, 1.0)]])
        request = fixture.request()
        runtime.review(request, raw(request))
        with (fixture.package / "products/candidates/candidates.json").open("ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(ValueError, "size changed|SHA-256 changed"):
            runtime.review(request, raw(request))

    def test_wrong_review_digest_blocks_execute(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)]])
        request = fixture.request()
        with self.assertRaisesRegex(ValueError, "Review SHA-256 mismatch"):
            runtime.execute(request, raw(request), "0" * 64)
        self.assertFalse(Path(request["payload"]["output_directory"]).exists())

    def test_duplicate_json_key_and_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            runtime.parse_json('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            runtime.parse_json('{"a":NaN}')

    def test_power_weight_requires_power_gate(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)]])
        request = fixture.request(power_gate=None, power_weight=1.0)
        with self.assertRaisesRegex(ValueError, "power_cost_weight"):
            runtime.review(request, raw(request))

    def test_zero_candidate_input_is_completed_not_failure(self):
        fixture = RuntimeFixture(self.base, [[], [], []])
        _review, result = self.run_request(fixture, fixture.request())
        self.assertEqual(result["tracks"], [])
        self.assertEqual(result["candidate_track_associations"], [])
        self.assertEqual(result["coverage"]["zero_candidate_row_count"], 3)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib is optional")
    def test_optional_plot_is_packaged(self):
        fixture = RuntimeFixture(self.base, [[(10.0, 1.0)], [(10.2, 1.0)]])
        request = fixture.request()
        request["payload"]["products"]["save_plot"] = True
        request_raw = raw(request)
        review = runtime.review(request, request_raw)
        answer = runtime.execute(request, request_raw, review["review_sha256"])
        self.assertTrue((Path(answer["output_directory"]) / "frequency-tracks.png").is_file())


if __name__ == "__main__":
    unittest.main()
