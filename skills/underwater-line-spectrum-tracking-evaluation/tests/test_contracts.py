from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_contract import ContractError, read_json, validate_document  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_draft_templates_validate(self):
        validate_document(read_json(ROOT / "assets/templates/EvaluationRequest.draft.json"), "request")
        validate_document(read_json(ROOT / "assets/templates/TrackingTruthLabels.draft.json"), "truth")

    def test_partial_truth_cannot_claim_complete_negatives(self):
        document = read_json(ROOT / "assets/templates/TrackingTruthLabels.draft.json")
        document["label_scope"]["negative_labels_complete"] = True
        with self.assertRaisesRegex(ContractError, "partial_positive"):
            validate_document(document, "truth")

    def test_truth_forbids_identity_fields(self):
        document = read_json(ROOT / "assets/templates/TrackingTruthLabels.draft.json")
        document["truth_tracks"][0]["points"][0]["target_id"] = "not-allowed"
        with self.assertRaises(ContractError):
            validate_document(document, "truth")

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate"):
                read_json(path)

    def test_nonfinite_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "non-finite"):
                read_json(path)


if __name__ == "__main__":
    unittest.main()
