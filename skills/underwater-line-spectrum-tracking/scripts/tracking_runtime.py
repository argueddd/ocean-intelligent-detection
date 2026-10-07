#!/usr/bin/env python3
"""Review and execute deterministic line-spectrum candidate tracking.

The runtime consumes one immutable DetectionTrackingHandoff 1.0.0.  It never
re-runs detection and never assigns harmonic, source, target, or identity
semantics.  Execution always creates a new output directory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


VERSION = "1.0.0"
TRACKER_ID = "global-frequency-assignment-v1"
ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA = ROOT / "assets" / "schemas" / "TrackingRequest.schema.json"
HANDOFF_SCHEMA = ROOT / "assets" / "schemas" / "DetectionTrackingHandoff.schema.json"
RESULT_SCHEMA = ROOT / "assets" / "schemas" / "TrackingResult.schema.json"
MAX_JSON_BYTES = 64 * 1024**2
FORBIDDEN_ID_KEYS = {"source_id", "target_id", "harmonic_family_id", "same_target"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def parse_json(raw):
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        value = json.loads(text, object_pairs_hook=_pairs,
                           parse_constant=lambda token: (_ for _ in ()).throw(
                               ValueError(f"Non-finite JSON number: {token}.")))
    except UnicodeDecodeError as exc:
        raise ValueError("JSON must be UTF-8.") from exc
    _finite(value)
    return value


def _finite(value):
    if isinstance(value, float):
        _require(math.isfinite(value), "JSON contains a non-finite number.")
    elif isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def json_bytes(value, *, canonical=False):
    options = {"ensure_ascii": False, "allow_nan": False}
    if canonical:
        options.update(sort_keys=True, separators=(",", ":"))
    else:
        options.update(indent=2)
    return (json.dumps(value, **options) + ("" if canonical else "\n")).encode("utf-8")


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_regular_absolute(path, max_bytes=MAX_JSON_BYTES):
    target = Path(path)
    _require(target.is_absolute(), f"Path must be absolute: {path!r}.")
    _require(target.exists() and target.is_file() and not target.is_symlink(),
             f"Path must be a regular non-symlink file: {path!r}.")
    _require(target.stat().st_size <= max_bytes, f"File exceeds read limit: {path!r}.")
    return target.read_bytes()


def _schema(path):
    return parse_json(path.read_bytes())


def _validate_schema(document, path, label):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("jsonschema is required for contract validation.") from exc
    schema = _schema(path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(value) for value in first.path)
        raise ValueError(f"Invalid {label} at {location}: {first.message}")


def require_request(document):
    _validate_schema(document, REQUEST_SCHEMA, "TrackingRequest")
    _require(document["document_status"] == "specified", "TrackingRequest is not specified.")
    payload = document["payload"]
    handoff_path = Path(payload["handoff"]["path"])
    output = Path(payload["output_directory"])
    _require(handoff_path.is_absolute(), "Handoff path must be absolute.")
    _require(output.is_absolute(), "Output directory must be absolute.")
    _require(not output.exists(), "Output directory already exists; results are never overwritten.")
    _require(output.parent.exists() and output.parent.is_dir() and not output.parent.is_symlink(),
             "Output parent must be an existing regular directory.")
    algorithm = payload["algorithm"]
    _require(algorithm["frequency_cost_weight"] > 0,
             "frequency_cost_weight must be positive for a frequency tracker.")
    if algorithm["power_change_gate_db"] is None:
        _require(algorithm["power_cost_weight"] == 0,
                 "power_cost_weight must be zero when power_change_gate_db is disabled.")
    return document


def _walk_forbidden(value, path=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_ID_KEYS:
                found.append(path + "/" + key)
            found.extend(_walk_forbidden(child, path + "/" + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_forbidden(child, path + "/" + str(index)))
    return found


def require_handoff(document):
    _validate_schema(document, HANDOFF_SCHEMA, "DetectionTrackingHandoff")
    forbidden = _walk_forbidden(document)
    _require(not forbidden, "Detection handoff contains forbidden target/source identity fields: " + ", ".join(forbidden))
    return document


def _secure_source_file(root, ref, max_bytes=MAX_JSON_BYTES):
    relative = PurePosixPath(ref["path"])
    _require(not relative.is_absolute() and ".." not in relative.parts,
             f"Evidence path must remain inside the source package: {relative}.")
    target = root.joinpath(*relative.parts)
    _require(target.exists() and target.is_file() and not target.is_symlink(),
             f"Evidence is not a regular non-symlink file: {relative}.")
    resolved = target.resolve(strict=True)
    _require(resolved.is_relative_to(root), f"Evidence escapes the source package: {relative}.")
    size = target.stat().st_size
    _require(size == ref["size_bytes"], f"Evidence size changed: {relative}.")
    _require(size <= max_bytes, f"Evidence exceeds read limit: {relative}.")
    raw = target.read_bytes()
    _require(sha256_bytes(raw) == ref["sha256"], f"Evidence SHA-256 changed: {relative}.")
    return raw


def _measurement(candidate, name):
    matches = [value for value in candidate.get("measurements", []) if value.get("name") == name]
    _require(len(matches) <= 1, f"Candidate {candidate.get('candidate_id')} repeats measurement {name!r}.")
    if not matches:
        return None
    record = matches[0]
    value = record.get("value")
    _require(type(value) in (int, float) and math.isfinite(value),
             f"Candidate {candidate.get('candidate_id')} has invalid {name!r}.")
    return {
        "value": float(value),
        "definition_id": record.get("definition_id"),
        "definition_version": record.get("definition_version"),
        "unit": record.get("unit"),
        "scale": record.get("scale"),
    }


def _one_interval(row, label):
    intervals = row.get("sample_intervals")
    _require(isinstance(intervals, list) and len(intervals) == 1,
             f"{label} must contain exactly one sample interval in tracker v1.")
    interval = intervals[0]
    _require(isinstance(interval, list) and len(interval) == 2
             and all(type(value) is int for value in interval)
             and 0 <= interval[0] < interval[1], f"{label} has an invalid half-open sample interval.")
    return interval


def _row_time(row, sample_rate, offset):
    start, stop = _one_interval(row, f"Row {row.get('row')}")
    return offset + (start + stop - 1) / (2.0 * sample_rate)


def _load_evidence(handoff):
    package = Path(handoff["source_package"]["directory"])
    _require(package.is_absolute() and package.exists() and package.is_dir() and not package.is_symlink(),
             "Source package directory must be an existing absolute non-symlink directory.")
    root = package.resolve(strict=True)
    manifest_path = root / "package-manifest.json"
    _require(manifest_path.is_file() and not manifest_path.is_symlink(), "Source package manifest is unavailable.")
    manifest_raw = manifest_path.read_bytes()
    source = handoff["source_package"]
    _require(len(manifest_raw) <= MAX_JSON_BYTES, "Source package manifest exceeds the read limit.")
    _require(len(manifest_raw) == source["manifest_size_bytes"], "Source package manifest size changed.")
    _require(sha256_bytes(manifest_raw) == source["manifest_sha256"], "Source package manifest SHA-256 changed.")

    evidence_raw = {}
    for name, ref in handoff["evidence"].items():
        evidence_raw[name] = _secure_source_file(root, ref)
    candidates = parse_json(evidence_raw["candidate_table"])
    ledger = parse_json(evidence_raw["ledger"])
    _require(isinstance(candidates, list), "Candidate table must be a JSON array.")
    _require(isinstance(ledger, dict) and isinstance(ledger.get("rows"), list),
             "Ledger must contain the complete rows array.")
    _require(len(candidates) == handoff["completeness"]["candidate_count"],
             "Candidate count differs from the handoff.")
    _require(len(ledger["rows"]) == handoff["completeness"]["detection_row_count"],
             "Ledger row count differs from the handoff.")
    return root, candidates, ledger


def _normalize_observations(handoff, candidates, ledger, require_power):
    rows = ledger["rows"]
    _require([row.get("row") for row in rows] == list(range(len(rows))),
             "Detection rows must be a complete contiguous zero-based sequence.")
    sample_rate = float(handoff["signal"]["sample_rate_hz"])
    time_mapping = handoff["signal"]["time_mapping"]
    offset = time_mapping.get("sample_zero_offset_seconds")
    _require(type(offset) in (int, float) and math.isfinite(offset),
             "Handoff time mapping lacks a finite sample_zero_offset_seconds.")
    row_times = []
    for row in rows:
        _require(row.get("status") in ("tested", "skipped"), "Ledger row status must be tested or skipped.")
        row_times.append(_row_time(row, sample_rate, float(offset)))
    _require(all(row_times[index] > row_times[index - 1] for index in range(1, len(row_times))),
             "Detection row center times must be strictly increasing.")

    task_id = handoff["task"]["task_id"]
    nyquist = float(handoff["analysis_grid"]["nyquist_hz"])
    by_row = {index: [] for index in range(len(rows))}
    seen = set()
    power_signatures = set()
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        _require(isinstance(candidate_id, str) and candidate_id and candidate_id not in seen,
                 "Candidate IDs must be nonempty and unique.")
        seen.add(candidate_id)
        _require(candidate.get("task_id") == task_id, f"Candidate {candidate_id} has the wrong task_id.")
        extension = candidate.get("extensions", {}).get("cfar_v1", {})
        row_index = extension.get("row")
        _require(type(row_index) is int and row_index in by_row,
                 f"Candidate {candidate_id} has an invalid detection row.")
        _require(rows[row_index]["status"] == "tested", f"Candidate {candidate_id} belongs to a skipped row.")
        support = candidate.get("analysis_support", {})
        _require(support.get("sample_intervals") == rows[row_index].get("sample_intervals"),
                 f"Candidate {candidate_id} support differs from its ledger row.")
        frequency = candidate.get("frequency", {}).get("value_hz")
        _require(type(frequency) in (int, float) and math.isfinite(frequency) and 0 <= frequency <= nyquist,
                 f"Candidate {candidate_id} has an invalid frequency.")
        power_record = _measurement(candidate, "power")
        power = None if power_record is None else power_record["value"]
        if power_record is not None:
            signature = tuple(power_record[key] for key in
                              ("definition_id", "definition_version", "unit", "scale"))
            power_signatures.add(signature)
        if require_power:
            _require(power_record is not None and power > 0,
                     f"Candidate {candidate_id} needs a positive power measurement for configured power tracking.")
            _require(all(isinstance(power_record[key], str) and power_record[key]
                         for key in ("definition_id", "definition_version", "unit"))
                     and power_record["scale"] == "linear",
                     f"Candidate {candidate_id} needs a common identified linear power measurement.")
        elif power is not None:
            _require(power > 0, f"Candidate {candidate_id} has a nonpositive power measurement.")
        interval = _one_interval(support, f"Candidate {candidate_id}")
        observation = {
            "candidate_id": candidate_id,
            "row": row_index,
            "time_seconds": row_times[row_index],
            "frequency_hz": float(frequency),
            "power": power,
            "sample_interval": interval,
        }
        by_row[row_index].append(observation)

    for index, row in enumerate(rows):
        by_row[index].sort(key=lambda item: (item["frequency_hz"], item["candidate_id"]))
        expected = row.get("candidate_count")
        _require(type(expected) is int and expected == len(by_row[index]),
                 f"Candidate count differs at detection row {index}.")
    _require(len(power_signatures) <= 1,
             "Candidate power measurements do not share one definition, version, unit, and scale.")
    power_definition = None
    if power_signatures:
        definition_id, definition_version, unit, scale = next(iter(power_signatures))
        power_definition = {"definition_id": definition_id, "definition_version": definition_version,
                            "unit": unit, "scale": scale}
    return rows, row_times, by_row, power_definition


def _prepare(request_document, request_raw):
    require_request(request_document)
    payload = request_document["payload"]
    handoff_raw = _read_regular_absolute(payload["handoff"]["path"])
    _require(sha256_bytes(handoff_raw) == payload["handoff"]["sha256"],
             "Handoff SHA-256 differs from TrackingRequest.")
    handoff = require_handoff(parse_json(handoff_raw))
    _root, candidates, ledger = _load_evidence(handoff)
    algorithm = payload["algorithm"]
    require_power = algorithm["power_change_gate_db"] is not None or algorithm["power_cost_weight"] > 0
    rows, row_times, by_row, power_definition = _normalize_observations(
        handoff, candidates, ledger, require_power)
    review_core = {
        "review_version": VERSION,
        "record_type": "TrackingReview",
        "status": "ready_pending_execution_confirmation",
        "request_sha256": sha256_bytes(request_raw),
        "handoff_sha256": sha256_bytes(handoff_raw),
        "tracking_run_id": payload["tracking_run_id"],
        "source": {
            "detection_run_id": handoff["source_package"]["run_id"],
            "detection_task_id": handoff["task"]["task_id"],
            "candidate_table_sha256": handoff["evidence"]["candidate_table"]["sha256"],
            "ledger_sha256": handoff["evidence"]["ledger"]["sha256"],
        },
        "resolved_algorithm": copy.deepcopy(algorithm),
        "coverage": {
            "detection_row_count": len(rows),
            "tested_row_count": sum(row["status"] == "tested" for row in rows),
            "skipped_row_count": sum(row["status"] == "skipped" for row in rows),
            "zero_candidate_row_count": sum(len(by_row[index]) == 0 for index in range(len(rows))),
            "candidate_count": len(candidates),
            "time_range_seconds": [row_times[0], row_times[-1]],
        },
        "output_directory": payload["output_directory"],
        "execution_performed": False,
        "semantic_boundary": {
            "detection_recomputed": False,
            "tracking_performed": False,
            "source_association_performed": False,
            "target_identification_performed": False,
            "evaluation_performed": False,
        },
    }
    review_sha = sha256_bytes(json_bytes(review_core, canonical=True))
    review = {**review_core, "review_sha256": review_sha}
    state = {"handoff": handoff, "candidates": candidates, "ledger": ledger,
             "rows": rows, "row_times": row_times, "by_row": by_row,
             "power_definition": power_definition}
    return review, state


def review(request_document, request_raw):
    return _prepare(request_document, request_raw)[0]


def _predict(track, time_seconds, mode):
    points = track["points"]
    last = points[-1]
    if mode == "constant_velocity" and len(points) >= 2:
        previous = points[-2]
        delta = last["time_seconds"] - previous["time_seconds"]
        if delta > 0:
            slope = (last["frequency_hz"] - previous["frequency_hz"]) / delta
            return last["frequency_hz"] + slope * (time_seconds - last["time_seconds"])
    return last["frequency_hz"]


def _edge(track, observation, algorithm):
    last = track["points"][-1]
    dt = observation["time_seconds"] - last["time_seconds"]
    _require(dt > 0, "Candidate time must be later than the active track's last observation.")
    predicted = _predict(track, observation["time_seconds"], algorithm["prediction_mode"])
    residual = abs(observation["frequency_hz"] - predicted)
    if residual > algorithm["frequency_gate_hz"]:
        return None
    rate = abs(observation["frequency_hz"] - last["frequency_hz"]) / dt
    rate_gate = algorithm["frequency_rate_gate_hz_per_s"]
    if rate_gate is not None and rate > rate_gate:
        return None
    power_change = None
    power_gate = algorithm["power_change_gate_db"]
    if power_gate is not None:
        _require(last["power"] is not None and observation["power"] is not None,
                 "Power-gated association encountered a missing power measurement.")
        power_change = abs(10.0 * math.log10(observation["power"] / last["power"]))
        if power_change > power_gate:
            return None
    cost = algorithm["frequency_cost_weight"] * residual / algorithm["frequency_gate_hz"]
    if algorithm["power_cost_weight"]:
        cost += algorithm["power_cost_weight"] * power_change / power_gate
    return {"cost": float(cost), "predicted_frequency_hz": float(predicted),
            "frequency_residual_hz": float(residual), "power_change_db": power_change}


def _add_flow_edge(graph, start, end, capacity, cost):
    forward = [end, len(graph[end]), capacity, float(cost)]
    reverse = [start, len(graph[start]), 0, -float(cost)]
    graph[start].append(forward)
    graph[end].append(reverse)
    return forward


def _global_assignment(tracks, observations, algorithm):
    """Maximum-cardinality, minimum-cost bipartite assignment."""
    track_ids = sorted(tracks)
    candidate_ids = [item["candidate_id"] for item in observations]
    candidate_map = {item["candidate_id"]: item for item in observations}
    source = 0
    track_offset = 1
    candidate_offset = track_offset + len(track_ids)
    sink = candidate_offset + len(candidate_ids)
    graph = [[] for _ in range(sink + 1)]
    edge_refs = {}
    details = {}
    for index, track_id in enumerate(track_ids):
        _add_flow_edge(graph, source, track_offset + index, 1, 0.0)
    for index, candidate_id in enumerate(candidate_ids):
        _add_flow_edge(graph, candidate_offset + index, sink, 1, 0.0)
    for ti, track_id in enumerate(track_ids):
        for ci, candidate_id in enumerate(candidate_ids):
            detail = _edge(tracks[track_id], candidate_map[candidate_id], algorithm)
            if detail is None:
                continue
            tie = 1e-12 * (ti * (len(candidate_ids) + 1) + ci)
            edge_refs[(track_id, candidate_id)] = _add_flow_edge(
                graph, track_offset + ti, candidate_offset + ci, 1, detail["cost"] + tie)
            details[(track_id, candidate_id)] = detail

    potentials = [0.0] * len(graph)
    while True:
        distance = [math.inf] * len(graph)
        previous = [None] * len(graph)
        distance[source] = 0.0
        queue = [(0.0, source)]
        while queue:
            current, node = heapq.heappop(queue)
            if current > distance[node] + 1e-15:
                continue
            for edge_index, edge in enumerate(graph[node]):
                target, _reverse, capacity, cost = edge
                if capacity <= 0:
                    continue
                reduced = cost + potentials[node] - potentials[target]
                if reduced < 0 and reduced > -1e-12:
                    reduced = 0.0
                proposed = current + reduced
                if proposed + 1e-15 < distance[target]:
                    distance[target] = proposed
                    previous[target] = (node, edge_index)
                    heapq.heappush(queue, (proposed, target))
        if not math.isfinite(distance[sink]):
            break
        for node, value in enumerate(distance):
            if math.isfinite(value):
                potentials[node] += value
        node = sink
        while node != source:
            parent, edge_index = previous[node]
            edge = graph[parent][edge_index]
            edge[2] -= 1
            graph[node][edge[1]][2] += 1
            node = parent

    matches = []
    for key, edge in edge_refs.items():
        if edge[2] == 0:
            matches.append((key[0], key[1], details[key]))
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches


def _new_point(observation, kind, detail=None):
    return {
        "point_index": 0,
        "candidate_id": observation["candidate_id"],
        "row": observation["row"],
        "time_seconds": observation["time_seconds"],
        "frequency_hz": observation["frequency_hz"],
        "power": observation["power"],
        "association_kind": kind,
        "predicted_frequency_hz": None if detail is None else detail["predicted_frequency_hz"],
        "frequency_residual_hz": None if detail is None else detail["frequency_residual_hz"],
        "power_change_db": None if detail is None else detail["power_change_db"],
        "association_cost": None if detail is None else detail["cost"],
    }


def _ols_slope(points):
    if len(points) < 2:
        return None
    times = [point["time_seconds"] for point in points]
    values = [point["frequency_hz"] for point in points]
    mean_t = sum(times) / len(times)
    mean_f = sum(values) / len(values)
    denominator = sum((value - mean_t) ** 2 for value in times)
    if denominator == 0:
        return None
    return sum((t - mean_t) * (f - mean_f) for t, f in zip(times, values)) / denominator


def _track(state, request, review_document):
    payload = request["payload"]
    algorithm = payload["algorithm"]
    rows, row_times, by_row = state["rows"], state["row_times"], state["by_row"]
    tracks = {}
    active = set()
    associations = []
    row_ledger = []
    next_track = 1
    detection_run = state["handoff"]["source_package"]["run_id"]
    detection_task = state["handoff"]["task"]["task_id"]

    for row_index, source_row in enumerate(rows):
        observations = by_row[row_index]
        active_map = {track_id: tracks[track_id] for track_id in sorted(active)}
        matches = _global_assignment(active_map, observations, algorithm) if observations and active_map else []
        matched_tracks = set()
        matched_candidates = set()
        for track_id, candidate_id, detail in matches:
            observation = next(item for item in observations if item["candidate_id"] == candidate_id)
            point = _new_point(observation, "matched", detail)
            point["point_index"] = len(tracks[track_id]["points"])
            tracks[track_id]["points"].append(point)
            tracks[track_id]["missed_rows"] = 0
            matched_tracks.add(track_id)
            matched_candidates.add(candidate_id)
            associations.append({
                "detection_run_id": detection_run,
                "detection_task_id": detection_task,
                "candidate_id": candidate_id,
                "tracking_run_id": payload["tracking_run_id"],
                "track_id": track_id,
                "row": row_index,
                "association_kind": "matched",
            })

        unmatched_before_termination = sorted(active - matched_tracks)
        terminated = []
        count_gap = algorithm["gap_count_basis"] == "all_rows" or source_row["status"] == "tested"
        for track_id in unmatched_before_termination:
            if count_gap:
                tracks[track_id]["missed_rows"] += 1
                tracks[track_id]["maximum_consecutive_missed_rows"] = max(
                    tracks[track_id]["maximum_consecutive_missed_rows"], tracks[track_id]["missed_rows"])
            if tracks[track_id]["missed_rows"] > algorithm["max_missed_rows"]:
                tracks[track_id]["termination_reason"] = "gap_exceeded"
                active.remove(track_id)
                terminated.append(track_id)

        new_count = 0
        for observation in observations:
            if observation["candidate_id"] in matched_candidates:
                continue
            track_id = f"track_{next_track:06d}"
            next_track += 1
            point = _new_point(observation, "new_track")
            tracks[track_id] = {
                "track_id": track_id,
                "points": [point],
                "missed_rows": 0,
                "maximum_consecutive_missed_rows": 0,
                "termination_reason": None,
            }
            active.add(track_id)
            new_count += 1
            associations.append({
                "detection_run_id": detection_run,
                "detection_task_id": detection_task,
                "candidate_id": observation["candidate_id"],
                "tracking_run_id": payload["tracking_run_id"],
                "track_id": track_id,
                "row": row_index,
                "association_kind": "new_track",
            })
        row_ledger.append({
            "row": row_index,
            "time_seconds": row_times[row_index],
            "source_status": source_row["status"],
            "candidate_count": len(observations),
            "matched_count": len(matches),
            "new_track_count": new_count,
            "unmatched_active_track_count": len(unmatched_before_termination),
            "terminated_track_ids": terminated,
            "active_track_count_after_row": len(active),
        })

    for track_id in active:
        tracks[track_id]["termination_reason"] = "end_of_input"

    public_tracks = []
    for track_id in sorted(tracks):
        track = tracks[track_id]
        points = track["points"]
        frequencies = [point["frequency_hz"] for point in points]
        confirmed = len(points) >= algorithm["min_confirmed_detections"]
        flags = ["association_not_source_or_target_identity", "crossing_identity_not_resolved"]
        if not confirmed:
            flags.append("tentative_minimum_not_met")
        if track["maximum_consecutive_missed_rows"]:
            flags.append("contains_association_gap")
        public_tracks.append({
            "track_id": track_id,
            "confirmation_status": "confirmed" if confirmed else "tentative",
            "termination_reason": track["termination_reason"],
            "start_row": points[0]["row"],
            "end_row": points[-1]["row"],
            "start_time_seconds": points[0]["time_seconds"],
            "end_time_seconds": points[-1]["time_seconds"],
            "detection_count": len(points),
            "maximum_consecutive_missed_rows": track["maximum_consecutive_missed_rows"],
            "frequency_summary": {
                "minimum_hz": min(frequencies),
                "maximum_hz": max(frequencies),
                "mean_hz": sum(frequencies) / len(frequencies),
                "ols_slope_hz_per_s": _ols_slope(points),
            },
            "points": points,
            "quality_flags": flags,
        })

    associations.sort(key=lambda item: (item["row"], item["candidate_id"]))
    handoff = state["handoff"]
    limitations = [
        "Tracks are deterministic candidate associations, not verified physical sources or targets.",
        "Confirmed means only that the configured minimum detection count was reached; it is not a probability or accuracy judgment.",
        "Frequency-only prediction can exchange identities at crossings; no future smoothing or track stitching is performed.",
        "No harmonic grouping, source association, target identification, or performance evaluation was performed.",
        f"Gap counting used {algorithm['gap_count_basis']}; upstream skipped-row semantics are preserved.",
    ]
    if algorithm["power_change_gate_db"] is None:
        limitations.append("Power gating and power cost were explicitly disabled; association used frequency evidence only.")
    result = {
        "schema_version": VERSION,
        "record_type": "TrackingResult",
        "status": "completed",
        "tracking_run_id": payload["tracking_run_id"],
        "source": {
            "handoff_path": payload["handoff"]["path"],
            "handoff_sha256": payload["handoff"]["sha256"],
            "detection_run_id": detection_run,
            "detection_task_id": detection_task,
            "candidate_table_sha256": handoff["evidence"]["candidate_table"]["sha256"],
            "ledger_sha256": handoff["evidence"]["ledger"]["sha256"],
            "time_reference": handoff["analysis_grid"]["time_reference"],
            "input_ref": copy.deepcopy(handoff["task"]["input_ref"]),
            "detector": copy.deepcopy(handoff["task"]["detector"]),
            "beam_source": copy.deepcopy(handoff["signal"]["beam_source"]),
            "analysis_grid": copy.deepcopy(handoff["analysis_grid"]),
            "power_measurement_definition": copy.deepcopy(state["power_definition"]),
        },
        "resolved_algorithm": copy.deepcopy(algorithm),
        "coverage": {
            "detection_row_count": len(rows),
            "tested_row_count": sum(row["status"] == "tested" for row in rows),
            "skipped_row_count": sum(row["status"] == "skipped" for row in rows),
            "zero_candidate_row_count": sum(not by_row[index] for index in range(len(rows))),
            "candidate_count": len(state["candidates"]),
            "associated_candidate_count": len(associations),
            "time_range_seconds": [row_times[0], row_times[-1]],
        },
        "tracks": public_tracks,
        "candidate_track_associations": associations,
        "row_ledger": row_ledger,
        "semantic_boundary": {
            "detection_recomputed": False,
            "tracking_performed": True,
            "harmonic_grouping_performed": False,
            "source_association_performed": False,
            "target_identification_performed": False,
            "evaluation_performed": False,
        },
        "limitations": limitations,
        "validation": {
            "request_sha256": review_document["request_sha256"],
            "review_sha256": review_document["review_sha256"],
            "input_candidate_ids_unique": True,
            "every_candidate_assigned_once": True,
            "one_candidate_per_track_per_row": True,
            "result_schema_valid": True,
            "algorithm_performance_evaluated": False,
        },
    }
    return require_result(result)


def require_result(document):
    _validate_schema(document, RESULT_SCHEMA, "TrackingResult")
    forbidden = _walk_forbidden(document)
    _require(not forbidden, "Tracking result contains forbidden source/target identity fields: " + ", ".join(forbidden))
    track_ids = [track["track_id"] for track in document["tracks"]]
    _require(len(track_ids) == len(set(track_ids)), "Track IDs must be unique.")
    candidate_ids = [item["candidate_id"] for item in document["candidate_track_associations"]]
    _require(len(candidate_ids) == len(set(candidate_ids)), "Every candidate must have exactly one track association.")
    _require(len(candidate_ids) == document["coverage"]["candidate_count"]
             == document["coverage"]["associated_candidate_count"], "Candidate association coverage is incomplete.")
    points = []
    for track in document["tracks"]:
        _require(track["detection_count"] == len(track["points"]), "Track detection_count differs from its points.")
        _require([point["point_index"] for point in track["points"]] == list(range(len(track["points"]))),
                 "Track point indices must be contiguous.")
        rows = [point["row"] for point in track["points"]]
        times = [point["time_seconds"] for point in track["points"]]
        _require(all(rows[index] > rows[index - 1] for index in range(1, len(rows))),
                 "A track contains repeated or decreasing detection rows.")
        _require(all(times[index] > times[index - 1] for index in range(1, len(times))),
                 "A track contains repeated or decreasing times.")
        points.extend((point["candidate_id"], track["track_id"], point["association_kind"]) for point in track["points"])
    mapping = sorted((item["candidate_id"], item["track_id"], item["association_kind"])
                     for item in document["candidate_track_associations"])
    _require(sorted(points) == mapping, "Track points and candidate associations differ.")
    return document


def _plot_bytes(result, dpi):
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ImportError as exc:
        raise RuntimeError("matplotlib is required when save_plot=true.") from exc
    figure = Figure(figsize=(10, 6), dpi=dpi, layout="constrained")
    axis = figure.subplots()
    for track in result["tracks"]:
        times = [point["time_seconds"] for point in track["points"]]
        frequencies = [point["frequency_hz"] for point in track["points"]]
        axis.plot(times, frequencies, marker="o", markersize=3, linewidth=1,
                  label=track["track_id"] if len(result["tracks"]) <= 20 else None)
    axis.set_xlabel("Time (s; source reference)")
    axis.set_ylabel("Frequency (Hz)")
    axis.set_title("Line-spectrum candidate tracks (associations, not target identities)")
    axis.grid(alpha=0.2)
    if result["tracks"] and len(result["tracks"]) <= 20:
        axis.legend(fontsize=7, ncol=2)
    buffer = io.BytesIO()
    FigureCanvasAgg(figure).print_png(buffer)
    figure.clear()
    return buffer.getvalue()


def _write_new(path, raw):
    with path.open("xb") as handle:
        handle.write(raw)


def execute(request_document, request_raw, expected_review_sha256):
    review_document, state = _prepare(request_document, request_raw)
    _require(review_document["review_sha256"] == expected_review_sha256,
             "Review SHA-256 mismatch; re-review the current request and immutable evidence.")
    result = _track(state, request_document, review_document)
    output = Path(request_document["payload"]["output_directory"])
    parent = output.parent
    temporary = Path(tempfile.mkdtemp(prefix=".tracking-build-", dir=parent))
    try:
        files = {
            "tracking-result.json": json_bytes(result),
            "resolved-request.json": json_bytes(request_document),
            "review.json": json_bytes(review_document),
        }
        products = request_document["payload"]["products"]
        if products["save_plot"]:
            files["frequency-tracks.png"] = _plot_bytes(result, products["plot_dpi"])
        for name, raw in files.items():
            _write_new(temporary / name, raw)
        manifest = {
            "package_version": VERSION,
            "record_type": "TrackingResultPackage",
            "status": "completed",
            "tracking_run_id": request_document["payload"]["tracking_run_id"],
            "files": [
                {"path": name, "size_bytes": len(raw), "sha256": sha256_bytes(raw)}
                for name, raw in sorted(files.items())
            ],
            "semantic_boundary": copy.deepcopy(result["semantic_boundary"]),
        }
        manifest_raw = json_bytes(manifest)
        _write_new(temporary / "package-manifest.json", manifest_raw)
        _require(not output.exists(), "Output directory appeared during execution; refusing to overwrite.")
        os.replace(temporary, output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {
        "status": "completed",
        "output_directory": str(output),
        "tracking_run_id": result["tracking_run_id"],
        "track_count": len(result["tracks"]),
        "confirmed_track_count": sum(track["confirmation_status"] == "confirmed" for track in result["tracks"]),
        "tentative_track_count": sum(track["confirmation_status"] == "tentative" for track in result["tracks"]),
        "candidate_count": result["coverage"]["candidate_count"],
        "package_manifest_sha256": sha256_bytes(manifest_raw),
        "target_identification_performed": False,
        "evaluation_performed": False,
    }


def _request(path):
    raw = _read_regular_absolute(path)
    return parse_json(raw), raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("review")
    check.add_argument("request")
    run = sub.add_parser("execute")
    run.add_argument("request")
    run.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    document, raw = _request(args.request)
    if args.action == "review":
        answer = review(document, raw)
    else:
        answer = execute(document, raw, args.review_sha256)
    print(json_bytes(answer).decode("utf-8"), end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json_bytes({"status": "blocked_or_failed", "error": str(exc)}).decode("utf-8"), end="")
        sys.exit(2)
