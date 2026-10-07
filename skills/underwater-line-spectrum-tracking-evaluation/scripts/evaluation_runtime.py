#!/usr/bin/env python3
"""Evidence-gated evaluation runtime for existing line-spectrum tracks."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile

from validate_contract import ContractError, read_json, validate_document


VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
MAX_JSON_BYTES = 64 * 1024 * 1024
HASH_KEYS = ("candidate_table_sha256", "ledger_sha256")


class EvaluationError(RuntimeError):
    pass


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path):
    path = Path(path)
    if not path.is_file():
        raise EvaluationError(f"JSON file is unavailable: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise EvaluationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        return read_json(path)
    except ContractError as exc:
        raise EvaluationError(str(exc)) from exc


def write_json(path, value):
    Path(path).write_bytes(json_bytes(value))


def _safe_package_file(package_dir, relative):
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise EvaluationError(f"unsafe package-relative path: {relative}")
    result = (package_dir / relative_path).resolve()
    try:
        result.relative_to(package_dir.resolve())
    except ValueError as exc:
        raise EvaluationError(f"package entry escapes directory: {relative}") from exc
    if result.is_symlink() or not result.is_file():
        raise EvaluationError(f"package entry is unavailable or a symlink: {relative}")
    return result


def _validate_tracking_invariants(result):
    source = result["source"]
    coverage = result["coverage"]
    tracks = result["tracks"]
    associations = result["candidate_track_associations"]
    ledger = result["row_ledger"]
    track_ids = [track["track_id"] for track in tracks]
    if len(track_ids) != len(set(track_ids)):
        raise EvaluationError("tracking result has duplicate track_id values")
    rows = [row["row"] for row in ledger]
    times = [row["time_seconds"] for row in ledger]
    if rows != sorted(rows) or len(rows) != len(set(rows)):
        raise EvaluationError("row_ledger rows must be strictly increasing")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise EvaluationError("row_ledger times must be strictly increasing")
    if coverage["detection_row_count"] != len(ledger):
        raise EvaluationError("coverage.detection_row_count differs from row_ledger length")
    tested = sum(item["source_status"] == "tested" for item in ledger)
    skipped = len(ledger) - tested
    zero = sum(item["source_status"] == "tested" and item["candidate_count"] == 0 for item in ledger)
    candidates = sum(item["candidate_count"] for item in ledger)
    if (coverage["tested_row_count"], coverage["skipped_row_count"], coverage["zero_candidate_row_count"], coverage["candidate_count"]) != (tested, skipped, zero, candidates):
        raise EvaluationError("tracking coverage counters differ from row_ledger")
    if coverage["associated_candidate_count"] != len(associations):
        raise EvaluationError("associated_candidate_count differs from association table length")
    if coverage["candidate_count"] != len(associations):
        raise EvaluationError("every upstream candidate must have exactly one track association")
    candidate_ids = [item["candidate_id"] for item in associations]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise EvaluationError("candidate association table contains duplicate candidate_id values")
    by_candidate = {item["candidate_id"]: item for item in associations}
    point_count = 0
    for track in tracks:
        points = track["points"]
        point_count += len(points)
        if track["detection_count"] != len(points):
            raise EvaluationError(f"{track['track_id']} detection_count differs from points")
        point_indices = [item["point_index"] for item in points]
        if point_indices != list(range(len(points))):
            raise EvaluationError(f"{track['track_id']} point_index sequence is invalid")
        point_rows = [item["row"] for item in points]
        point_times = [item["time_seconds"] for item in points]
        if point_rows != sorted(point_rows) or len(point_rows) != len(set(point_rows)):
            raise EvaluationError(f"{track['track_id']} point rows must be strictly increasing")
        if any(b <= a for a, b in zip(point_times, point_times[1:])):
            raise EvaluationError(f"{track['track_id']} point times must be strictly increasing")
        if (track["start_row"], track["end_row"]) != (point_rows[0], point_rows[-1]):
            raise EvaluationError(f"{track['track_id']} start/end rows differ from points")
        if (track["start_time_seconds"], track["end_time_seconds"]) != (point_times[0], point_times[-1]):
            raise EvaluationError(f"{track['track_id']} start/end times differ from points")
        for point in points:
            assoc = by_candidate.get(point["candidate_id"])
            if assoc is None or assoc["track_id"] != track["track_id"] or assoc["row"] != point["row"]:
                raise EvaluationError(f"point/association mismatch for {point['candidate_id']}")
            if assoc["tracking_run_id"] != result["tracking_run_id"]:
                raise EvaluationError("association tracking_run_id mismatch")
            if assoc["detection_run_id"] != source["detection_run_id"] or assoc["detection_task_id"] != source["detection_task_id"]:
                raise EvaluationError("association detection source mismatch")
    if point_count != len(associations):
        raise EvaluationError("track point count differs from association table length")
    if ledger[0]["time_seconds"] != coverage["time_range_seconds"][0] or ledger[-1]["time_seconds"] != coverage["time_range_seconds"][1]:
        raise EvaluationError("coverage time range differs from row_ledger")


def load_tracking_package(ref):
    package_dir = Path(ref["directory"])
    if not package_dir.is_absolute():
        raise EvaluationError("tracking package directory must be absolute")
    package_dir = package_dir.resolve()
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise EvaluationError(f"tracking package directory is unavailable or a symlink: {package_dir}")
    manifest_path = package_dir / "package-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise EvaluationError("tracking package needs a regular package-manifest.json")
    observed_manifest_hash = sha256_file(manifest_path)
    if observed_manifest_hash != ref["manifest_sha256"]:
        raise EvaluationError("tracking package manifest SHA-256 mismatch")
    manifest = load_json(manifest_path)
    required = {"package_version", "record_type", "status", "tracking_run_id", "files", "semantic_boundary"}
    if set(manifest) != required or manifest["package_version"] != "1.0.0" or manifest["record_type"] != "TrackingResultPackage" or manifest["status"] != "completed":
        raise EvaluationError("unsupported or malformed TrackingResultPackage manifest")
    boundary = manifest["semantic_boundary"]
    expected_boundary = {
        "detection_recomputed": False, "tracking_performed": True,
        "harmonic_grouping_performed": False, "source_association_performed": False,
        "target_identification_performed": False, "evaluation_performed": False,
    }
    if boundary != expected_boundary:
        raise EvaluationError("tracking package semantic boundary is incompatible")
    seen = set()
    result_path = None
    for entry in manifest["files"]:
        if set(entry) != {"path", "size_bytes", "sha256"}:
            raise EvaluationError("malformed tracking manifest file entry")
        relative = entry["path"]
        if relative in seen:
            raise EvaluationError(f"duplicate package file entry: {relative}")
        seen.add(relative)
        path = _safe_package_file(package_dir, relative)
        if path.stat().st_size != entry["size_bytes"] or sha256_file(path) != entry["sha256"]:
            raise EvaluationError(f"tracking package file identity mismatch: {relative}")
        if relative == "tracking-result.json":
            result_path = path
    if result_path is None:
        raise EvaluationError("tracking package has no tracking-result.json")
    result = load_json(result_path)
    try:
        validate_document(result, "tracking")
    except ContractError as exc:
        raise EvaluationError(str(exc)) from exc
    if result["tracking_run_id"] != manifest["tracking_run_id"] or result["semantic_boundary"] != boundary:
        raise EvaluationError("tracking result identity differs from package manifest")
    _validate_tracking_invariants(result)
    return {
        "directory": str(package_dir), "manifest_path": str(manifest_path),
        "manifest_sha256": observed_manifest_hash, "manifest": manifest,
        "result_path": str(result_path), "result_sha256": sha256_file(result_path), "result": result,
    }


def _nearest_rank(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _stats(values):
    values = list(values)
    if not values:
        return {"count": 0, "minimum": None, "mean": None, "median": None, "p90": None, "maximum": None}
    return {
        "count": len(values), "minimum": min(values), "mean": statistics.fmean(values),
        "median": statistics.median(values), "p90": _nearest_rank(values, 0.90), "maximum": max(values),
    }


def descriptive_metrics(result, settings):
    tracks = result["tracks"]
    ledger = result["row_ledger"]
    coverage = result["coverage"]
    short_max = settings["short_track_max_detections"]
    all_rows = [item["row"] for item in ledger]
    tested_rows = [item["row"] for item in ledger if item["source_status"] == "tested"]
    basis_rows = tested_rows if settings["continuity_basis"] == "tested_rows" else all_rows
    occupancy = []
    row_spans = []
    frequency_steps = []
    for track in tracks:
        eligible = sum(track["start_row"] <= row <= track["end_row"] for row in basis_rows)
        if eligible <= 0:
            raise EvaluationError(f"no eligible occupancy rows for {track['track_id']}")
        occupancy.append(track["detection_count"] / eligible)
        row_spans.append(sum(track["start_row"] <= row <= track["end_row"] for row in all_rows))
        frequencies = [point["frequency_hz"] for point in track["points"]]
        frequency_steps.extend(abs(b - a) for a, b in zip(frequencies, frequencies[1:]))
    track_count = len(tracks)
    confirmed = sum(track["confirmation_status"] == "confirmed" for track in tracks)
    singleton = sum(track["detection_count"] == 1 for track in tracks)
    short = sum(track["detection_count"] <= short_max for track in tracks)
    gap_terminated = sum(track["termination_reason"] == "gap_exceeded" for track in tracks)
    end_of_input = sum(track["termination_reason"] == "end_of_input" for track in tracks)
    with_gaps = sum(track["maximum_consecutive_missed_rows"] > 0 for track in tracks)
    association_completeness = 1.0 if coverage["candidate_count"] == 0 else coverage["associated_candidate_count"] / coverage["candidate_count"]
    return {
        "association_completeness": association_completeness,
        "track_count": track_count,
        "confirmed_track_count": confirmed,
        "tentative_track_count": track_count - confirmed,
        "confirmed_track_fraction": confirmed / track_count if track_count else None,
        "singleton_track_count": singleton,
        "singleton_track_fraction": singleton / track_count if track_count else None,
        "short_track_count": short,
        "short_track_fraction": short / track_count if track_count else None,
        "gap_termination_count": gap_terminated,
        "gap_termination_fraction": gap_terminated / track_count if track_count else None,
        "end_of_input_termination_count": end_of_input,
        "tracks_with_gap_count": with_gaps,
        "tracks_with_gap_fraction": with_gaps / track_count if track_count else None,
        "maximum_active_track_count": max(item["active_track_count_after_row"] for item in ledger),
        "termination_row_count": sum(bool(item["terminated_track_ids"]) for item in ledger),
        "terminated_track_event_count": sum(len(item["terminated_track_ids"]) for item in ledger),
        "track_detection_count": _stats(track["detection_count"] for track in tracks),
        "track_duration_seconds": _stats(track["end_time_seconds"] - track["start_time_seconds"] for track in tracks),
        "track_row_span": _stats(row_spans),
        "track_occupancy": _stats(occupancy),
        "frequency_step_abs_hz": _stats(frequency_steps),
        "settings": {"short_track_max_detections": short_max, "continuity_basis": settings["continuity_basis"]},
    }


def _in_scope(row, frequency, scope):
    in_row = any(start <= row < stop for start, stop in scope["row_ranges"])
    fmin, fmax = scope["frequency_range_hz"]
    return in_row and fmin <= frequency <= fmax


def load_truth(ref, primary):
    path = Path(ref["path"])
    if not path.is_absolute():
        raise EvaluationError("truth path must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise EvaluationError(f"truth file is unavailable or a symlink: {path}")
    observed = sha256_file(path)
    if observed != ref["sha256"]:
        raise EvaluationError("truth label SHA-256 mismatch")
    truth = load_json(path)
    try:
        validate_document(truth, "truth")
    except ContractError as exc:
        raise EvaluationError(str(exc)) from exc
    source = primary["result"]["source"]
    for key in ("detection_run_id", "detection_task_id", "candidate_table_sha256", "ledger_sha256", "time_reference"):
        if truth["source"][key] != source[key]:
            raise EvaluationError(f"truth source differs from primary tracking source at {key}")
    ledger = {item["row"]: item for item in primary["result"]["row_ledger"]}
    for track in truth["truth_tracks"]:
        for point in track["points"]:
            source_row = ledger.get(point["row"])
            if source_row is None:
                raise EvaluationError(f"truth row is absent from tracking ledger: {point['row']}")
            if not math.isclose(point["time_seconds"], source_row["time_seconds"], rel_tol=0.0, abs_tol=1e-9):
                raise EvaluationError(f"truth time differs from row_ledger at row {point['row']}")
    return {"path": str(path), "sha256": observed, "document": truth}


def _best_assignment(estimates, truths, tolerance):
    """Return a non-crossing maximum-cardinality, minimum-error 1-D assignment."""
    est = sorted(estimates, key=lambda x: (x["frequency_hz"], x["track_id"], x["candidate_id"]))
    tru = sorted(truths, key=lambda x: (x["frequency_hz"], x["truth_track_id"]))
    memo = {}

    def better(a, b):
        if a[0] != b[0]:
            return a if a[0] > b[0] else b
        if not math.isclose(a[1], b[1], rel_tol=0.0, abs_tol=1e-12):
            return a if a[1] < b[1] else b
        a_key = tuple((est[i]["track_id"], tru[j]["truth_track_id"]) for i, j in a[2])
        b_key = tuple((est[i]["track_id"], tru[j]["truth_track_id"]) for i, j in b[2])
        return a if a_key <= b_key else b

    def solve(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(est) or j == len(tru):
            answer = (0, 0.0, ())
        else:
            answer = better(solve(i + 1, j), solve(i, j + 1))
            error = abs(est[i]["frequency_hz"] - tru[j]["frequency_hz"])
            if error <= tolerance:
                tail = solve(i + 1, j + 1)
                match = (tail[0] + 1, tail[1] + error, ((i, j),) + tail[2])
                answer = better(answer, match)
        memo[key] = answer
        return answer

    _, _, pairs = solve(0, 0)
    return [(est[i], tru[j]) for i, j in pairs]


def truth_metrics(result, truth, settings):
    scope = truth["label_scope"]
    estimated_points = []
    for track in result["tracks"]:
        for point in track["points"]:
            if _in_scope(point["row"], point["frequency_hz"], scope):
                estimated_points.append({
                    "track_id": track["track_id"], "candidate_id": point["candidate_id"],
                    "row": point["row"], "time_seconds": point["time_seconds"], "frequency_hz": point["frequency_hz"],
                })
    truth_points = []
    truth_point_counts = {}
    for track in truth["truth_tracks"]:
        truth_point_counts[track["truth_track_id"]] = len(track["points"])
        for point in track["points"]:
            truth_points.append({"truth_track_id": track["truth_track_id"], **point})
    rows = sorted({item["row"] for item in estimated_points} | {item["row"] for item in truth_points})
    matches = []
    tolerance = settings["frequency_tolerance_hz"]
    for row in rows:
        est_row = [item for item in estimated_points if item["row"] == row]
        truth_row = [item for item in truth_points if item["row"] == row]
        for estimate, label in _best_assignment(est_row, truth_row, tolerance):
            signed = estimate["frequency_hz"] - label["frequency_hz"]
            matches.append({
                "row": row, "time_seconds": estimate["time_seconds"],
                "estimated_track_id": estimate["track_id"], "candidate_id": estimate["candidate_id"],
                "truth_track_id": label["truth_track_id"],
                "estimated_frequency_hz": estimate["frequency_hz"], "truth_frequency_hz": label["frequency_hz"],
                "signed_error_hz": signed, "absolute_error_hz": abs(signed),
            })
    errors = [item["signed_error_hz"] for item in matches]
    match_counts_truth = {}
    match_counts_pair = {}
    match_est_by_truth = {}
    match_truth_by_est = {}
    for item in matches:
        truth_id = item["truth_track_id"]
        est_id = item["estimated_track_id"]
        match_counts_truth[truth_id] = match_counts_truth.get(truth_id, 0) + 1
        match_counts_pair[(est_id, truth_id)] = match_counts_pair.get((est_id, truth_id), 0) + 1
        match_est_by_truth.setdefault(truth_id, set()).add(est_id)
        match_truth_by_est.setdefault(est_id, []).append((item["row"], truth_id))
    detected_truth = 0
    qualifying_pairs = set()
    for truth_id, total in truth_point_counts.items():
        for est_id in match_est_by_truth.get(truth_id, set()):
            pair_count = match_counts_pair[(est_id, truth_id)]
            if pair_count >= settings["minimum_matched_points"] and pair_count / total >= settings["minimum_truth_track_recall"]:
                qualifying_pairs.add((est_id, truth_id))
        if any(pair[1] == truth_id for pair in qualifying_pairs):
            detected_truth += 1
    estimated_track_ids = {item["track_id"] for item in estimated_points}
    qualifying_estimated = {est_id for est_id, _ in qualifying_pairs}
    fragmentation = sum(max(0, len(ids) - 1) for ids in match_est_by_truth.values())
    switches = 0
    for sequence in match_truth_by_est.values():
        ordered = [truth_id for _, truth_id in sorted(sequence)]
        switches += sum(a != b for a, b in zip(ordered, ordered[1:]))
    complete_negatives = scope["negative_labels_complete"]
    matched = len(matches)
    return ({
        "labeled_truth_point_count": len(truth_points),
        "estimated_point_count_in_scope": len(estimated_points),
        "matched_point_count": matched,
        "point_recall": matched / len(truth_points) if truth_points else None,
        "point_precision": matched / len(estimated_points) if complete_negatives and estimated_points else (1.0 if complete_negatives and not estimated_points and not truth_points else None),
        "frequency_bias_hz": statistics.fmean(errors) if errors else None,
        "frequency_mae_hz": statistics.fmean(abs(value) for value in errors) if errors else None,
        "frequency_rmse_hz": math.sqrt(statistics.fmean(value * value for value in errors)) if errors else None,
        "frequency_max_abs_error_hz": max((abs(value) for value in errors), default=None),
        "truth_track_count": len(truth_point_counts),
        "detected_truth_track_count": detected_truth,
        "truth_track_recall": detected_truth / len(truth_point_counts) if truth_point_counts else None,
        "estimated_track_count_in_scope": len(estimated_track_ids),
        "qualified_estimated_track_count": len(qualifying_estimated) if complete_negatives else None,
        "estimated_track_precision": len(qualifying_estimated) / len(estimated_track_ids) if complete_negatives and estimated_track_ids else (1.0 if complete_negatives and not estimated_track_ids and not truth_point_counts else None),
        "observed_labeled_fragmentation_count": fragmentation,
        "fragmentation_count": fragmentation if scope["truth_tracks_complete"] else None,
        "observed_labeled_identity_switch_count": switches,
        "identity_switch_count": switches if scope["truth_tracks_complete"] else None,
        "negative_labels_complete": complete_negatives,
        "truth_tracks_complete": scope["truth_tracks_complete"],
        "matching": settings,
    }, matches)


def _comparability_differences(primary, baseline):
    a = primary["result"]
    b = baseline["result"]
    differences = []
    for key in ("detection_run_id", "detection_task_id", "candidate_table_sha256", "ledger_sha256", "time_reference", "input_ref", "detector", "beam_source", "analysis_grid", "power_measurement_definition"):
        if a["source"][key] != b["source"][key]:
            differences.append(f"source.{key}")
    for key in ("detection_row_count", "tested_row_count", "skipped_row_count", "candidate_count", "time_range_seconds"):
        if a["coverage"][key] != b["coverage"][key]:
            differences.append(f"coverage.{key}")
    left_rows = [(x["row"], x["time_seconds"], x["source_status"], x["candidate_count"]) for x in a["row_ledger"]]
    right_rows = [(x["row"], x["time_seconds"], x["source_status"], x["candidate_count"]) for x in b["row_ledger"]]
    if left_rows != right_rows:
        differences.append("row_ledger.source_coverage")
    return differences


def _flatten_numeric(node, prefix=""):
    output = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            output.update(_flatten_numeric(value, path))
    elif type(node) in (int, float) and not isinstance(node, bool):
        output[prefix] = float(node)
    return output


def comparison_metrics(primary_metrics, baseline_metrics):
    primary_flat = _flatten_numeric(primary_metrics)
    baseline_flat = _flatten_numeric(baseline_metrics)
    return {
        key: primary_flat[key] - baseline_flat[key]
        for key in sorted(primary_flat.keys() & baseline_flat.keys())
    }


def _metric_value(metrics, name):
    group, key = name.split(".", 1)
    node = metrics.get(group, {})
    if key == "mean_track_occupancy":
        return node.get("track_occupancy", {}).get("mean")
    if key == "median_track_occupancy":
        return node.get("track_occupancy", {}).get("median")
    if key == "frequency_step_abs_mean_hz":
        return node.get("frequency_step_abs_hz", {}).get("mean")
    if key == "frequency_step_abs_p90_hz":
        return node.get("frequency_step_abs_hz", {}).get("p90")
    return node.get(key)


def evaluate_acceptance(checks, metrics):
    if not checks:
        return {"aggregate_status": "not_requested", "checks": []}
    operators = {
        "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
        "==": lambda a, b: math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12),
    }
    output = []
    for check in checks:
        value = _metric_value(metrics, check["metric"])
        if value is None:
            status = "insufficient_evidence"
        else:
            status = "passed" if operators[check["operator"]](value, check["threshold"]) else "failed"
        output.append({**check, "observed_value": value, "status": status})
    statuses = {item["status"] for item in output}
    aggregate = "failed" if "failed" in statuses else ("insufficient_evidence" if "insufficient_evidence" in statuses else "passed")
    return {"aggregate_status": aggregate, "checks": output}


def _review_body(request_path, request, primary, baseline, truth):
    payload = request["payload"]
    return {
        "schema_version": VERSION,
        "record_type": "TrackingEvaluationReview",
        "status": "ready",
        "evaluation_id": payload["evaluation_id"],
        "mode": payload["mode"],
        "request": {"path": str(request_path.resolve()), "sha256": sha256_file(request_path)},
        "primary": {"tracking_run_id": primary["result"]["tracking_run_id"], "manifest_sha256": primary["manifest_sha256"], "tracking_result_sha256": primary["result_sha256"]},
        "baseline": None if baseline is None else {"tracking_run_id": baseline["result"]["tracking_run_id"], "manifest_sha256": baseline["manifest_sha256"], "tracking_result_sha256": baseline["result_sha256"]},
        "truth": None if truth is None else {"path": truth["path"], "sha256": truth["sha256"], "label_status": truth["document"]["label_status"], "label_scope": truth["document"]["label_scope"]},
        "resolved_settings": payload["settings"],
        "acceptance_check_count": len(payload["acceptance_checks"]),
        "output_directory": payload["output_directory"],
        "blocking_issues": [],
        "semantic_boundary": {"detection_recomputed": False, "tracking_recomputed": False, "parameters_tuned": False, "target_identification_performed": False},
    }


def prepare(request_path, *, execution=False):
    request_path = Path(request_path).resolve()
    request = load_json(request_path)
    try:
        validate_document(request, "request")
    except ContractError as exc:
        raise EvaluationError(str(exc)) from exc
    if execution and request["document_status"] != "specified":
        raise EvaluationError("execute requires document_status=specified")
    payload = request["payload"]
    primary = load_tracking_package(payload["primary"])
    baseline = load_tracking_package(payload["baseline"]) if payload["baseline"] is not None else None
    if baseline is not None:
        differences = _comparability_differences(primary, baseline)
        if differences:
            raise EvaluationError(f"primary and baseline are not directly comparable: {differences}")
    truth = load_truth(payload["truth"], primary) if payload["truth"] is not None else None
    if truth is not None and baseline is not None:
        for key in ("detection_run_id", "detection_task_id", "candidate_table_sha256", "ledger_sha256", "time_reference"):
            if truth["document"]["source"][key] != baseline["result"]["source"][key]:
                raise EvaluationError(f"truth source differs from baseline at {key}")
    body = _review_body(request_path, request, primary, baseline, truth)
    review_hash = sha256_bytes(json_bytes(body))
    review = {**body, "review_sha256": review_hash}
    return request, primary, baseline, truth, review


def _evidence_level(truth):
    if truth is None:
        return "descriptive_only"
    scope = truth["document"]["label_scope"]
    return "complete_truth" if truth["document"]["label_status"] == "complete" and scope["truth_tracks_complete"] and scope["negative_labels_complete"] else "partial_truth"


def _findings(metrics, evidence_level):
    descriptive = metrics["descriptive"]
    findings = [
        f"轨迹包内 {descriptive['track_count']} 条轨迹关联了全部候选，关联完整率为 {descriptive['association_completeness']:.6g}。"
    ]
    if descriptive["track_count"]:
        findings.append(f"确认轨迹 {descriptive['confirmed_track_count']} 条；短轨迹 {descriptive['short_track_count']} 条，短轨迹定义为检测点数不超过 {descriptive['settings']['short_track_max_detections']}。")
    if evidence_level == "descriptive_only":
        findings.append("未提供绑定真值；这些统计不能证明轨迹正确、误轨率或身份保持性能。")
    else:
        truth = metrics["truth"]
        findings.append(f"在已声明真值覆盖内匹配 {truth['matched_point_count']}/{truth['labeled_truth_point_count']} 个真值点，频率误差只对成功匹配点计算。")
        if not truth["negative_labels_complete"]:
            findings.append("负例标注不完整，因此点精确率和估计轨迹精确率不报告。")
    return findings


def _limitations(evidence_level, truth):
    output = [
        "本结果只评价给定轨迹产物；没有重新检测、重新跟踪或调整参数。",
        "频率轨迹不等同于谐波族、声源归属或目标身份。",
        "描述性统计只能表述产物结构，不能单独证明准确性。",
    ]
    if evidence_level == "partial_truth":
        output.append("真值覆盖不完整；未标注估计点不能自动计为误报，精确率类结论受限。")
    if truth is not None:
        output.extend(truth["document"]["limitations"])
    return list(dict.fromkeys(output))


def _write_metrics_csv(path, primary_metrics, baseline_metrics, deltas):
    rows = []
    for target, metrics in (("primary", primary_metrics), ("baseline", baseline_metrics)):
        if metrics is None:
            continue
        for key, value in sorted(_flatten_numeric(metrics).items()):
            rows.append((target, key, value))
    if deltas is not None:
        for key, value in sorted(deltas.items()):
            rows.append(("delta_primary_minus_baseline", key, value))
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["target", "metric", "value"])
        writer.writerows(rows)


def _format_value(value):
    return "—" if value is None else (f"{value:.8g}" if isinstance(value, float) else str(value))


def _write_report(path, result, primary_metrics, baseline_metrics):
    lines = [
        "# 线谱轨迹跟踪评价报告", "",
        f"- 评价编号：`{result['evaluation_id']}`",
        f"- 模式：`{result['mode']}`",
        f"- 证据等级：`{result['evidence_level']}`",
        f"- 验收状态：`{result['acceptance']['aggregate_status']}`", "",
        "## 主要结果", "",
    ]
    for finding in result["findings"]:
        lines.append(f"- {finding}")
    lines += ["", "## 主结果指标", "", "| 指标 | 数值 |", "|---|---:|"]
    selected = {
        "轨迹数": primary_metrics["descriptive"]["track_count"],
        "确认轨迹比例": primary_metrics["descriptive"]["confirmed_track_fraction"],
        "短轨迹比例": primary_metrics["descriptive"]["short_track_fraction"],
        "平均占用率": primary_metrics["descriptive"]["track_occupancy"]["mean"],
    }
    if "truth" in primary_metrics:
        selected.update({
            "点召回率": primary_metrics["truth"]["point_recall"],
            "点精确率": primary_metrics["truth"]["point_precision"],
            "频率 MAE (Hz)": primary_metrics["truth"]["frequency_mae_hz"],
            "真值轨迹召回率": primary_metrics["truth"]["truth_track_recall"],
            "碎片化计数": primary_metrics["truth"]["fragmentation_count"],
            "身份切换计数": primary_metrics["truth"]["identity_switch_count"],
        })
    for key, value in selected.items():
        lines.append(f"| {key} | {_format_value(value)} |")
    if baseline_metrics is not None:
        lines += ["", "## 对照", "", "差值定义为 `primary - baseline`；不自动宣布哪一种算法更优。"]
    lines += ["", "## 验收检查", ""]
    if not result["acceptance"]["checks"]:
        lines.append("未请求验收阈值。")
    else:
        lines += ["| 检查 | 指标 | 观测值 | 条件 | 状态 |", "|---|---|---:|---|---|"]
        for check in result["acceptance"]["checks"]:
            lines.append(f"| {check['check_id']} | `{check['metric']}` | {_format_value(check['observed_value'])} | {check['operator']} {check['threshold']} | {check['status']} |")
    lines += ["", "## 限制", ""] + [f"- {item}" for item in result["limitations"]]
    lines += ["", "## 模块边界", "", "本评价未重新进行检测或跟踪，也未进行调参、谐波归并、声源归属或目标身份判断。", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _save_plots(directory, primary_metrics, baseline_metrics, matches, dpi):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        raise EvaluationError(f"save_plots=true but matplotlib is unavailable: {exc}") from exc
    values = [primary_metrics["descriptive"]["track_detection_count"]]
    labels = ["primary"]
    if baseline_metrics is not None:
        values.append(baseline_metrics["descriptive"]["track_detection_count"])
        labels.append("baseline")
    means = [item["mean"] or 0.0 for item in values]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.bar(labels, means)
    ax.set_ylabel("Mean detections per track")
    ax.set_title("Track length summary")
    fig.tight_layout()
    fig.savefig(Path(directory) / "track-length-summary.png", dpi=dpi)
    plt.close(fig)
    if matches:
        fig, ax = plt.subplots(figsize=(6.4, 4.0))
        ax.hist([item["signed_error_hz"] for item in matches], bins="auto")
        ax.set_xlabel("Estimated - truth frequency (Hz)")
        ax.set_ylabel("Matched points")
        ax.set_title("Frequency error")
        fig.tight_layout()
        fig.savefig(Path(directory) / "frequency-error-histogram.png", dpi=dpi)
        plt.close(fig)


def execute(request_path, expected_review_hash):
    request, primary, baseline, truth, review = prepare(request_path, execution=True)
    if expected_review_hash != review["review_sha256"]:
        raise EvaluationError(f"review SHA-256 mismatch: expected {review['review_sha256']}")
    payload = request["payload"]
    output = Path(payload["output_directory"])
    if output.exists() or output.is_symlink():
        raise EvaluationError(f"output_directory already exists; refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        primary_metrics = {"descriptive": descriptive_metrics(primary["result"], payload["settings"])}
        baseline_metrics = None
        primary_matches = []
        if truth is not None:
            truth_values, primary_matches = truth_metrics(primary["result"], truth["document"], payload["settings"]["truth_matching"])
            primary_metrics["truth"] = truth_values
        if baseline is not None:
            baseline_metrics = {"descriptive": descriptive_metrics(baseline["result"], payload["settings"])}
            if truth is not None:
                truth_values, _ = truth_metrics(baseline["result"], truth["document"], payload["settings"]["truth_matching"])
                baseline_metrics["truth"] = truth_values
        deltas = comparison_metrics(primary_metrics, baseline_metrics) if baseline_metrics is not None else None
        evidence = _evidence_level(truth)
        acceptance = evaluate_acceptance(payload["acceptance_checks"], primary_metrics)
        source_identity = {
            "primary": {"tracking_run_id": primary["result"]["tracking_run_id"], "manifest_sha256": primary["manifest_sha256"], "tracking_result_sha256": primary["result_sha256"], "detection_run_id": primary["result"]["source"]["detection_run_id"], "detection_task_id": primary["result"]["source"]["detection_task_id"], "candidate_table_sha256": primary["result"]["source"]["candidate_table_sha256"], "ledger_sha256": primary["result"]["source"]["ledger_sha256"]},
            "baseline": None if baseline is None else {"tracking_run_id": baseline["result"]["tracking_run_id"], "manifest_sha256": baseline["manifest_sha256"], "tracking_result_sha256": baseline["result_sha256"]},
            "truth": None if truth is None else {"path": truth["path"], "sha256": truth["sha256"]},
        }
        result = {
            "schema_version": VERSION, "record_type": "TrackingEvaluationResult", "status": "completed",
            "evaluation_id": payload["evaluation_id"], "mode": payload["mode"], "evidence_level": evidence,
            "source_identity": source_identity, "settings": payload["settings"], "metrics": primary_metrics,
            "comparison": None if baseline_metrics is None else {"baseline_metrics": baseline_metrics, "delta_primary_minus_baseline": deltas},
            "acceptance": acceptance, "findings": _findings(primary_metrics, evidence),
            "limitations": _limitations(evidence, truth),
            "semantic_boundary": {"detection_recomputed": False, "tracking_recomputed": False, "tracking_evaluated": True, "parameters_tuned": False, "harmonic_grouping_performed": False, "source_association_performed": False, "target_identification_performed": False},
            "validation": {"request_sha256": sha256_file(request_path), "review_sha256": review["review_sha256"], "runtime_version": VERSION, "package_hashes_verified": True, "tracking_invariants_verified": True},
        }
        try:
            validate_document(result, "result")
        except ContractError as exc:
            raise EvaluationError(str(exc)) from exc
        write_json(temp / "evaluation-result.json", result)
        write_json(temp / "resolved-evaluation-config.json", request)
        write_json(temp / "review.json", review)
        if payload["products"]["save_matches"]:
            write_json(temp / "matches.json", {"schema_version": VERSION, "record_type": "TrackingTruthMatches", "matches": primary_matches})
        _write_metrics_csv(temp / "metrics.csv", primary_metrics, baseline_metrics, deltas)
        _write_report(temp / "report.md", result, primary_metrics, baseline_metrics)
        if payload["products"]["save_plots"]:
            _save_plots(temp, primary_metrics, baseline_metrics, primary_matches, payload["products"]["plot_dpi"])
        files = []
        for path in sorted(temp.iterdir(), key=lambda item: item.name):
            if path.is_file():
                files.append({"path": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        manifest = {
            "package_version": VERSION, "record_type": "TrackingEvaluationResultPackage", "status": "completed",
            "evaluation_id": payload["evaluation_id"], "files": files,
            "semantic_boundary": result["semantic_boundary"],
        }
        write_json(temp / "package-manifest.json", manifest)
        if output.exists():
            raise EvaluationError(f"output_directory appeared during execution; refusing overwrite: {output}")
        os.rename(temp, output)
        return output, result
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    review_parser = subparsers.add_parser("review", help="Validate inputs and emit a review hash")
    review_parser.add_argument("request", type=Path)
    execute_parser = subparsers.add_parser("execute", help="Execute an approved evaluation")
    execute_parser.add_argument("request", type=Path)
    execute_parser.add_argument("--review-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "review":
            _, _, _, _, review = prepare(args.request)
            print(json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            output, result = execute(args.request, args.review_sha256)
            print(json.dumps({"status": "completed", "output_directory": str(output), "evaluation_id": result["evaluation_id"], "evidence_level": result["evidence_level"], "acceptance": result["acceptance"]["aggregate_status"]}, ensure_ascii=False, indent=2))
    except (EvaluationError, ContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
