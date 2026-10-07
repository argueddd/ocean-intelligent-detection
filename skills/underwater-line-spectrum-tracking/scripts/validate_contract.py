#!/usr/bin/env python3
"""Read-only validator for tracking request, handoff, and result contracts."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import tracking_runtime as runtime


SCHEMAS = {
    "request": (runtime.REQUEST_SCHEMA, "TrackingRequest"),
    "handoff": (runtime.HANDOFF_SCHEMA, "DetectionTrackingHandoff"),
    "result": (runtime.RESULT_SCHEMA, "TrackingResult"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(SCHEMAS))
    parser.add_argument("path")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.is_absolute():
        raise ValueError("Contract path must be absolute.")
    raw = runtime._read_regular_absolute(path)
    document = runtime.parse_json(raw)
    if args.kind == "request":
        runtime._validate_schema(document, runtime.REQUEST_SCHEMA, "TrackingRequest")
        if document["document_status"] == "specified":
            runtime.require_request(document)
    elif args.kind == "handoff":
        runtime.require_handoff(document)
    else:
        runtime.require_result(document)
    print(runtime.json_bytes({"status": "valid", "kind": args.kind,
                              "path": str(path), "sha256": runtime.sha256_bytes(raw)}).decode(), end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(runtime.json_bytes({"status": "invalid", "error": str(exc)}).decode(), end="")
        sys.exit(2)
