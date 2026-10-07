#!/usr/bin/env python3
"""Validate contracts for the line-spectrum tracking evaluation skill."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "assets" / "schemas"
SCHEMAS = {
    "request": SCHEMA_DIR / "EvaluationRequest.schema.json",
    "truth": SCHEMA_DIR / "TrackingTruthLabels.schema.json",
    "tracking": SCHEMA_DIR / "TrackingResult.schema.json",
    "result": SCHEMA_DIR / "EvaluationResult.schema.json",
}

SUPPORTED_METRICS = {
    "descriptive.association_completeness",
    "descriptive.confirmed_track_fraction",
    "descriptive.short_track_fraction",
    "descriptive.singleton_track_fraction",
    "descriptive.mean_track_occupancy",
    "descriptive.median_track_occupancy",
    "descriptive.gap_termination_fraction",
    "descriptive.frequency_step_abs_mean_hz",
    "descriptive.frequency_step_abs_p90_hz",
    "truth.point_recall",
    "truth.point_precision",
    "truth.frequency_bias_hz",
    "truth.frequency_mae_hz",
    "truth.frequency_rmse_hz",
    "truth.frequency_max_abs_error_hz",
    "truth.truth_track_recall",
    "truth.estimated_track_precision",
    "truth.fragmentation_count",
    "truth.identity_switch_count",
}

FORBIDDEN_IDENTITY_KEYS = {
    "source_id", "target_id", "identity", "identity_id", "target_class",
    "harmonic_family_id", "harmonic_group_id",
}


class ContractError(RuntimeError):
    pass


def _object_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ContractError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _bad_constant(value):
    raise ContractError(f"non-finite JSON number is forbidden: {value}")


def read_json(path):
    path = Path(path)
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_bad_constant,
        )
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read strict JSON {path}: {exc}") from exc


def _schema(name):
    return read_json(SCHEMAS[name])


def _format_path(parts):
    return "/" + "/".join(str(x) for x in parts)


def _validate_schema(document, name):
    errors = sorted(Draft202012Validator(_schema(name)).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        lines = [f"{_format_path(error.path)}: {error.message}" for error in errors[:20]]
        suffix = "" if len(errors) <= 20 else f"\n... {len(errors) - 20} more"
        raise ContractError(f"{name} schema validation failed:\n" + "\n".join(lines) + suffix)


def _walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield path + (key,), key, value
            yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (index,))


def _finite(document):
    for path, _, value in _walk(document):
        if type(value) is float and not math.isfinite(value):
            raise ContractError(f"non-finite value at {_format_path(path)}")


def _validate_request(document):
    payload = document["payload"]
    mode = payload["mode"]
    baseline = payload["baseline"]
    truth = payload["truth"]
    matching = payload["settings"]["truth_matching"]
    has_baseline = mode in {"comparison", "truth_comparison"}
    has_truth = mode in {"truth", "truth_comparison"}
    if (baseline is not None) != has_baseline:
        raise ContractError(f"mode={mode} requires baseline={has_baseline}")
    if (truth is not None) != has_truth:
        raise ContractError(f"mode={mode} requires truth={has_truth}")
    if (matching is not None) != has_truth:
        raise ContractError(f"mode={mode} requires truth_matching={has_truth}")
    if payload["products"]["save_matches"] and not has_truth:
        raise ContractError("save_matches=true requires truth or truth_comparison mode")
    check_ids = [item["check_id"] for item in payload["acceptance_checks"]]
    if len(check_ids) != len(set(check_ids)):
        raise ContractError("acceptance check_id values must be unique")
    unsupported = sorted({item["metric"] for item in payload["acceptance_checks"]} - SUPPORTED_METRICS)
    if unsupported:
        raise ContractError(f"unsupported acceptance metrics: {unsupported}")
    truth_only = [item["metric"] for item in payload["acceptance_checks"] if item["metric"].startswith("truth.")]
    if truth_only and not has_truth:
        raise ContractError("truth.* acceptance metrics require truth evidence")
    if document["document_status"] == "specified":
        if document["unresolved_items"]:
            raise ContractError("specified request must have no unresolved_items")
        for label, ref in (("primary", payload["primary"]), ("baseline", baseline)):
            if ref is not None and not Path(ref["directory"]).is_absolute():
                raise ContractError(f"specified {label}.directory must be absolute")
        if truth is not None and not Path(truth["path"]).is_absolute():
            raise ContractError("specified truth.path must be absolute")
        if not Path(payload["output_directory"]).is_absolute():
            raise ContractError("specified output_directory must be absolute")


def _in_ranges(row, ranges):
    return any(start <= row < stop for start, stop in ranges)


def _validate_truth(document):
    for path, key, _ in _walk(document):
        if key in FORBIDDEN_IDENTITY_KEYS:
            raise ContractError(f"identity/harmonic key is outside this skill boundary: {_format_path(path)}")
    scope = document["label_scope"]
    ranges = scope["row_ranges"]
    previous_stop = -1
    for start, stop in ranges:
        if start >= stop:
            raise ContractError("truth row_ranges use non-empty half-open [start, stop) intervals")
        if start < previous_stop:
            raise ContractError("truth row_ranges must be sorted and non-overlapping")
        previous_stop = stop
    fmin, fmax = scope["frequency_range_hz"]
    if fmin >= fmax:
        raise ContractError("frequency_range_hz must satisfy minimum < maximum")
    if document["label_status"] == "partial_positive":
        if scope["truth_tracks_complete"] or scope["negative_labels_complete"]:
            raise ContractError("partial_positive labels cannot claim complete truth or negatives")
    elif not scope["truth_tracks_complete"]:
        raise ContractError("label_status=complete requires truth_tracks_complete=true")
    ids = [track["truth_track_id"] for track in document["truth_tracks"]]
    if len(ids) != len(set(ids)):
        raise ContractError("truth_track_id values must be unique")
    for track in document["truth_tracks"]:
        rows = [point["row"] for point in track["points"]]
        times = [point["time_seconds"] for point in track["points"]]
        if rows != sorted(rows) or len(rows) != len(set(rows)):
            raise ContractError(f"truth track {track['truth_track_id']} rows must be strictly increasing")
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ContractError(f"truth track {track['truth_track_id']} times must be strictly increasing")
        for point in track["points"]:
            if not _in_ranges(point["row"], ranges):
                raise ContractError(f"truth point row {point['row']} is outside label_scope")
            if not fmin <= point["frequency_hz"] <= fmax:
                raise ContractError("truth point frequency is outside label_scope")


def validate_document(document, kind):
    if kind not in SCHEMAS:
        raise ContractError(f"unknown contract kind: {kind}")
    _finite(document)
    _validate_schema(document, kind)
    if kind == "request":
        _validate_request(document)
    elif kind == "truth":
        _validate_truth(document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(SCHEMAS))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        document = read_json(args.path)
        validate_document(document, args.kind)
    except (ContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"VALID {args.kind}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
