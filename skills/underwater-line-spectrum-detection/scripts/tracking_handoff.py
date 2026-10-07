#!/usr/bin/env python3
"""Build or verify a read-only detection-to-tracking evidence handoff.

This module never links candidates across frames and never emits track, source,
or target identities.  It only proves that one completed framewise detection
task has a complete saved candidate table and frame/cell ledger.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys

import detection_associations as associations
import detection_products as products
import detection_runtime as runtime
import preflight as pf


VERSION = "1.0.0"
SCHEMA = Path(__file__).resolve().parents[1] / "assets" / "schemas" / "DetectionTrackingHandoff.schema.json"
FORBIDDEN_SEMANTIC_KEYS = {
    "track_id", "source_id", "target_id", "harmonic_family_id", "same_target"
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _single(values, message):
    _require(len(values) == 1, message)
    return values[0]


def _finite_json(value):
    if isinstance(value, float):
        _require(math.isfinite(value), "Handoff contains a non-finite number.")
    elif isinstance(value, dict):
        for child in value.values():
            _finite_json(child)
    elif isinstance(value, list):
        for child in value:
            _finite_json(child)


def _forbidden_keys(value, path=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_SEMANTIC_KEYS:
                found.append((path + "/" + key) or "/")
            found.extend(_forbidden_keys(child, path + "/" + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_keys(child, path + "/" + str(index)))
    return found


def require_contract(document):
    """Validate the handoff envelope and its no-tracking/no-target boundary."""
    from jsonschema import Draft202012Validator

    schema = pf.parse_json(SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(value) for value in first.path)
        raise ValueError(f"Invalid DetectionTrackingHandoff at {location}: {first.message}")
    _finite_json(document)
    forbidden = _forbidden_keys(document)
    _require(not forbidden, "Tracking/target semantic keys are forbidden in a detection handoff: " + ", ".join(forbidden))
    return document


def _entry_ref(entries, path):
    _require(path in entries, f"Package manifest does not contain {path!r}.")
    entry = entries[path]
    return {"path": path, "sha256": entry["sha256"], "size_bytes": entry["size_bytes"]}


def _read_product(reader, entries, artifact, expected_product, expected_file):
    _require(artifact["status"] == "saved", f"{expected_product} must be durably saved before tracking handoff.")
    location = artifact["file_ref"]["location"]
    _require(location["kind"] == "package_relative", f"{expected_product} must be inside the completed package.")
    manifest_path = location["path"]
    entry = entries.get(manifest_path)
    _require(entry is not None and entry["sha256"] == artifact["file_ref"]["sha256"],
             f"{expected_product} result reference differs from the package manifest.")
    manifest = pf.parse_json(reader.read(manifest_path, entry["sha256"], entry["size_bytes"]))
    _require(set(manifest) == {"product_id", "task_id", "files"}, f"Malformed {expected_product} product manifest.")
    _require(manifest["product_id"] == expected_product and manifest["task_id"] == artifact["task_id"],
             f"{expected_product} product identity mismatch.")
    file_entry = _single([value for value in manifest["files"] if value.get("name") == expected_file],
                         f"{expected_product} product must contain exactly one {expected_file}.")
    data_path = (PurePosixPath(manifest_path).parent / expected_file).as_posix()
    package_entry = entries.get(data_path)
    _require(package_entry == {"path": data_path, "sha256": file_entry["sha256"],
                               "size_bytes": file_entry["size_bytes"]},
             f"{expected_product} data identity differs from the package manifest.")
    raw = reader.read(data_path, file_entry["sha256"], file_entry["size_bytes"])
    return pf.parse_json(raw), _entry_ref(entries, manifest_path), _entry_ref(entries, data_path)


def _input_document(config, input_ref):
    matches = []
    for document in config.get("input_documents", []):
        runtime.require_contract(document, "SignalInput")
        payload = document["payload"]
        key = {"package_sha256": payload["source_package"]["manifest"]["sha256"],
               "signal_id": payload["signal_id"]}
        if key == input_ref:
            matches.append(payload)
    return _single(matches, "Task input does not resolve to exactly one validated SignalInput.")


def _row_index(candidate):
    extension = candidate.get("extensions", {}).get("cfar_v1")
    _require(isinstance(extension, dict) and type(extension.get("row")) is int,
             "Every current CA/OS candidate must retain its exact detection row.")
    return extension["row"]


def _validate_completeness(task_result, task_request, evidence, candidates, ledger):
    _require(candidates == task_result["candidates"],
             "Saved candidate table is not the complete public candidate list.")
    _require(isinstance(ledger, dict) and isinstance(ledger.get("rows"), list)
             and isinstance(ledger.get("frame_ledger"), list), "Saved ledger is missing rows or frame_ledger.")
    _require(ledger["frame_ledger"] == evidence.get("frame_ledger"),
             "Saved and resolved frame ledgers differ.")
    summary_rows = evidence.get("rows")
    _require(isinstance(summary_rows, list) and len(summary_rows) == len(ledger["rows"]),
             "Resolved evidence does not cover every saved detection row.")
    _require([row.get("row") for row in ledger["rows"]] == list(range(len(ledger["rows"]))),
             "Detection rows must use one complete contiguous zero-based index.")
    _require([row.get("row") for row in summary_rows] == list(range(len(summary_rows))),
             "Resolved row summaries must use the same complete row index.")

    counts = {row: 0 for row in range(len(ledger["rows"]))}
    for candidate in candidates:
        row = _row_index(candidate)
        _require(row in counts, "Candidate points to an absent detection row.")
        _require(candidate["analysis_support"]["sample_intervals"] == ledger["rows"][row]["sample_intervals"],
                 "Candidate support differs from its exact ledger row.")
        counts[row] += 1
    for row, (full, summary) in enumerate(zip(ledger["rows"], summary_rows)):
        _require(full["sample_intervals"] == summary["sample_intervals"]
                 and full["status"] == summary["status"], "Saved and resolved row identity/status differ.")
        _require(full["candidate_count"] == summary["candidate_count"] == counts[row],
                 "Candidate count is inconsistent across result, ledger, and row summary.")
    _require(all(row.get("status") in ("tested", "skipped") for row in ledger["rows"]),
             "Ledger contains an unsupported row status.")
    _require(task_request["task_kind"] == "framewise", "Frequency tracking handoff accepts framewise detection only.")
    _require(task_result["execution_status"] == "completed", "Only a completed detection task can be handed off.")
    return {
        "candidate_table_complete": True,
        "candidate_count": len(candidates),
        "frame_ledger_complete": True,
        "complete_frame_count": len(ledger["frame_ledger"]),
        "detection_row_count": len(ledger["rows"]),
        "zero_candidate_rows_included": True,
        "zero_candidate_row_count": sum(row["candidate_count"] == 0 for row in ledger["rows"]),
        "invalid_or_skipped_frames_preserved": True,
        "invalid_or_skipped_frame_count": sum(row.get("status") != "eligible" for row in ledger["frame_ledger"]),
        "candidate_output_truncated": False,
    }


def build(package_directory, manifest_sha256, task_id, max_read_bytes):
    """Build a deterministic handoff from one immutable saved detection task."""
    directory = Path(package_directory).resolve(strict=True)
    selection = {"directory": str(directory), "manifest_sha256": manifest_sha256}
    reader, entries, result, config, _association = associations.load_package(selection, max_read_bytes)
    task_result = _single([value for value in result["payload"]["task_results"] if value["task_id"] == task_id],
                          "Select exactly one existing detection task_id.")
    task_request = _single([value for value in config["request"]["payload"]["tasks"] if value["task_id"] == task_id],
                           "Resolved configuration does not contain the selected task exactly once.")
    _require(task_result["input_ref"] == task_request["input_ref"], "Request/result input identity mismatch.")
    signal = _input_document(config, task_result["input_ref"])
    evidence = config.get("detection_evidence", {}).get(task_id)
    _require(isinstance(evidence, dict), "Resolved configuration lacks detection evidence for the selected task.")

    artifacts = task_result["artifacts"]
    candidate_artifact = _single([value for value in artifacts if value["product_id"] == "candidates"],
                                 "Tracking handoff requires exactly one candidates artifact declaration.")
    ledger_artifact = _single([value for value in artifacts if value["product_id"] == "ledger"],
                              "Tracking handoff requires exactly one ledger artifact declaration.")
    candidates, candidate_manifest, candidate_data = _read_product(
        reader, entries, candidate_artifact, "candidates", "candidates.json")
    ledger, ledger_manifest, ledger_data = _read_product(
        reader, entries, ledger_artifact, "ledger", "ledger.json")
    _require(isinstance(candidates, list), "Candidate product must be a JSON array.")
    completeness = _validate_completeness(task_result, task_request, evidence, candidates, ledger)

    spectrum = task_request["resolved_parameters"]["spectrum"]
    sample_rate = signal["sample_rate_hz"]
    _require(type(sample_rate) in (int, float) and math.isfinite(sample_rate) and sample_rate > 0,
             "Validated input sample rate must be positive and finite.")
    document = {
        "handoff_version": VERSION,
        "record_type": "DetectionTrackingHandoff",
        "status": "ready",
        "source_package": {
            "directory": str(directory),
            "manifest_sha256": manifest_sha256,
            "manifest_size_bytes": (directory / "package-manifest.json").stat().st_size,
            "run_id": result["payload"]["run_id"],
            "package_status": pf.parse_json(reader.cache[("package-manifest.json", manifest_sha256)])["status"],
        },
        "task": {
            "task_id": task_id,
            "task_kind": task_request["task_kind"],
            "input_ref": copy.deepcopy(task_result["input_ref"]),
            "detector": copy.deepcopy(task_result["detector"]),
        },
        "signal": {
            "sample_rate_hz": sample_rate,
            "time_mapping": copy.deepcopy(signal["time_mapping"]),
            "beam_source": copy.deepcopy(signal["beam_source"]),
            "units": copy.deepcopy(signal["units"]),
            "validity": copy.deepcopy(signal["validity"]),
        },
        "analysis_grid": {
            "window_length_samples": spectrum["window_length"],
            "hop_length_samples": spectrum["hop_length"],
            "nfft": spectrum["nfft"],
            "window": spectrum["window"],
            "demean": spectrum["demean"],
            "frame_origin": spectrum["frame_origin"],
            "frequency_grid_definition": "One-sided real FFT bin centers k*sample_rate_hz/nfft; no interpolation.",
            "frequency_spacing_hz": sample_rate / spectrum["nfft"],
            "nyquist_hz": sample_rate / 2,
            "time_reference": task_request["scope"]["time_reference"],
        },
        "scope": copy.deepcopy(task_request["scope"]),
        "coverage": copy.deepcopy(task_result["coverage"]),
        "evidence": {
            "detection_result": _entry_ref(entries, "detection-result.json"),
            "resolved_configuration": _entry_ref(entries, "resolved-configuration.json"),
            "candidate_product_manifest": candidate_manifest,
            "candidate_table": candidate_data,
            "ledger_product_manifest": ledger_manifest,
            "ledger": ledger_data,
        },
        "completeness": completeness,
        "semantic_boundary": {
            "detection_completed": True,
            "tracking_performed": False,
            "harmonic_grouping_performed": False,
            "source_association_performed": False,
            "target_identification_performed": False,
            "evaluation_performed": False,
            "association_record_semantics": "provenance_only_not_physical_target_association",
        },
        "limitations": list(dict.fromkeys(task_result["limitations"] + [
            "This handoff contains detections and coverage only; it creates no frequency trajectory.",
            "Candidate proximity across time, frequency, or bearing is not a same-source or same-target relation.",
            "Downstream tracking must preserve run_id, task_id, candidate_id and immutable evidence hashes.",
        ])),
    }
    return require_contract(document)


def check(document, max_read_bytes):
    """Re-read all bound evidence and require a byte-for-byte semantic rebuild."""
    require_contract(document)
    source = document["source_package"]
    actual = build(source["directory"], source["manifest_sha256"], document["task"]["task_id"], max_read_bytes)
    _require(actual == document, "Handoff differs from a fresh rebuild of its bound detection evidence.")
    raw = products.json_bytes(document)
    return {"status": "verified", "handoff_sha256": hashlib.sha256(raw).hexdigest(),
            "run_id": source["run_id"], "task_id": document["task"]["task_id"],
            "candidate_count": document["completeness"]["candidate_count"],
            "detection_row_count": document["completeness"]["detection_row_count"],
            "tracking_performed": False, "target_identification_performed": False}


def _read_handoff(path):
    target = Path(path)
    _require(target.is_absolute(), "Handoff path must be absolute.")
    _require(target.is_file() and not target.is_symlink(), "Handoff must be a regular non-symlink file.")
    _require(target.stat().st_size <= 4 * 1024**2, "Handoff exceeds the 4 MiB parsing limit.")
    return pf.parse_json(target.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("build")
    create.add_argument("package_directory")
    create.add_argument("task_id")
    create.add_argument("--manifest-sha256", required=True)
    create.add_argument("--max-read-bytes", required=True, type=int)
    create.add_argument("--output", required=True)
    verify = sub.add_parser("check")
    verify.add_argument("handoff")
    verify.add_argument("--max-read-bytes", required=True, type=int)
    args = parser.parse_args()
    if args.action == "build":
        document = build(args.package_directory, args.manifest_sha256, args.task_id, args.max_read_bytes)
        output = Path(args.output)
        _require(output.is_absolute(), "Output path must be absolute.")
        source = Path(args.package_directory).resolve(strict=True)
        _require(not output.resolve().is_relative_to(source), "Handoff must not modify the immutable source package.")
        runtime.safe_new_path(output)
        raw = products.json_bytes(document)
        with output.open("xb") as handle:
            handle.write(raw)
        answer = {"status": "created", "output": str(output), "sha256": hashlib.sha256(raw).hexdigest(),
                  "task_id": args.task_id, "candidate_count": document["completeness"]["candidate_count"],
                  "tracking_performed": False, "target_identification_performed": False}
    else:
        answer = check(_read_handoff(args.handoff), args.max_read_bytes)
    print(products.json_bytes(answer).decode())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(products.json_bytes({"status": "blocked_or_failed", "error": str(exc)}).decode())
        sys.exit(2)
