#!/usr/bin/env python3
"""Read-only structural validation for a TruthLabels 1.0.0 document."""
import argparse
import json
from pathlib import Path
import sys

from evaluation_runtime import _load_json, _validate_truth_labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    try:
        document = _load_json(args.document)
        errors = _validate_truth_labels(document)
        report = {"valid": not errors, "record_type": document.get("record_type"),
                  "validation_scope": "truth_label_structure_only",
                  "can_execute": False,
                  "not_checked": ["truth_authenticity", "label_completeness",
                                  "cross_document_identity", "referenced_evidence"],
                  "errors": errors}
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["valid"] else 1
    except Exception as exc:
        print(json.dumps({"valid": False, "can_execute": False,
                          "validation_scope": "document_parse_only",
                          "errors": [{"path": "/", "message": f"{type(exc).__name__}: {exc}"}]},
                         ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
