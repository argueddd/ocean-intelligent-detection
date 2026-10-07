"""Detection-to-tracking handoff regression; no tracking algorithm is executed."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cfar_registry as registry
import detection_products as products
import detection_runtime as runtime
import input_adapter as adapter
import tracking_handoff as handoff
from test_detection_runtime import LIMITS, make_task, mock_receipt, sha


class TrackingHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_fixture = tempfile.TemporaryDirectory(prefix="line-tracking-handoff-fixture-")
        cls.addClassCleanup(cls.tmp_fixture.cleanup)
        cls.fixture_root = Path(cls.tmp_fixture.name).resolve()
        command = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tests/runtime_fixture_producer.py"), str(cls.fixture_root)],
            capture_output=True, text=True, timeout=60)
        if command.returncode:
            raise AssertionError(command.stdout + command.stderr)
        cls.paths = json.loads(command.stdout)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="line-tracking-handoff-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        shutil.copytree(Path(self.paths["noise"]).parent, self.root / "noise")
        source = self.root / "noise" / "handoff.json"
        document = adapter.adapt(source, sha(source), "bypass_handoff", "signal_000000", **LIMITS)["signal_input"]
        input_path = self.root / "input.json"
        input_path.write_bytes(products.json_bytes(document))
        self.context = {"context_version": "0.1.0", "document_status": "specified",
            "inputs": [input_path.name], "descriptors": [], "source_files": [],
            "max_source_bytes": 64 * 1024**2, "handoff_validation": LIMITS}
        seen = set()
        for path in (self.root / "noise").iterdir():
            if path.is_file() and sha(path) not in seen:
                self.context["source_files"].append({"sha256": sha(path),
                    "path": path.relative_to(self.root).as_posix()})
                seen.add(sha(path))
        self.task = make_task(document["payload"])
        self.task["products"] = {"compute": ["candidates", "ledger"], "view": [],
                                 "save": ["candidates", "ledger"]}
        self.request = registry.envelope("DetectionRequest", {"request_id": "tracking-handoff-test",
            "tasks": [self.task], "unknown_decisions": [],
            "resources": {"max_working_bytes": 1024**3, "max_artifact_bytes": 128 * 1024**2,
                "persistence": "saved", "output_directory": str(self.base / "output"),
                "temporary_storage_policy": "memory_only_until_publish"},
            "batch_failure_policy": "stop_batch",
            "approval": {"status": "pending", "bound_plan_sha256": None, "evidence_refs": []},
            "parent_request": None, "parent_result": None})
        self.sync()

    def sync(self):
        descriptor = self.root / "ca_cfar.json"
        descriptor.write_bytes(products.json_bytes(registry.descriptor("ca_cfar")))
        self.context["descriptors"] = [descriptor.name]
        self.task["processing_steps"] = registry.processing_steps(self.task["resolved_parameters"])

    def execute(self):
        self.sync()
        report = runtime.review(self.request, self.context, self.root)
        self.assertEqual(report["status"], "ready_pending_execution_confirmation", report)
        return runtime.run(self.request, self.context, self.root, mock_receipt(report))

    def build(self):
        package = self.base / "output"
        return handoff.build(package, sha(package / "package-manifest.json"), self.task["task_id"], 64 * 1024**2)

    def test_complete_candidate_and_ledger_handoff(self):
        self.execute()
        document = self.build()
        self.assertEqual(document["status"], "ready")
        self.assertTrue(document["completeness"]["candidate_table_complete"])
        self.assertTrue(document["completeness"]["frame_ledger_complete"])
        self.assertFalse(document["completeness"]["candidate_output_truncated"])
        self.assertFalse(document["semantic_boundary"]["tracking_performed"])
        self.assertFalse(document["semantic_boundary"]["target_identification_performed"])
        answer = handoff.check(document, 64 * 1024**2)
        self.assertEqual(answer["status"], "verified")
        self.assertEqual(answer["candidate_count"], document["completeness"]["candidate_count"])

    def test_missing_saved_ledger_blocks_without_recomputation(self):
        self.task["products"] = {"compute": ["candidates", "ledger"], "view": [], "save": ["candidates"]}
        self.execute()
        with self.assertRaisesRegex(ValueError, "ledger must be durably saved"):
            self.build()

    def test_handoff_rejects_tracking_or_target_semantics(self):
        self.execute()
        document = self.build()
        changed = copy.deepcopy(document)
        changed["semantic_boundary"]["tracking_performed"] = True
        with self.assertRaisesRegex(ValueError, "Invalid DetectionTrackingHandoff"):
            handoff.require_contract(changed)
        changed = copy.deepcopy(document)
        changed["signal"]["track_id"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "Invalid DetectionTrackingHandoff|forbidden"):
            handoff.require_contract(changed)

    def test_changed_candidate_evidence_invalidates_handoff(self):
        self.execute()
        document = self.build()
        candidate_path = self.base / "output" / document["evidence"]["candidate_table"]["path"]
        with candidate_path.open("ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(ValueError, "size|SHA256|differs"):
            handoff.check(document, 64 * 1024**2)

    def test_build_is_framewise_only(self):
        self.execute()
        document = self.build()
        changed = copy.deepcopy(document)
        changed["task"]["task_kind"] = "average_spectrum"
        with self.assertRaisesRegex(ValueError, "Invalid DetectionTrackingHandoff"):
            handoff.require_contract(changed)


if __name__ == "__main__":
    unittest.main()
