#!/usr/bin/env python3
"""Evidence-gated line-spectrum evaluation runtime.

The runtime reads an EvaluationRequest and immutable products from an existing
DetectionResult package.  It never estimates a spectrum, reruns CFAR, changes a
threshold, or writes into an upstream package.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from validate_contract import read_json, validate_document


VERSION = "1.0.0"
SKILL_ROOT = Path(__file__).resolve().parents[1]
TRUTH_LABEL_SCHEMA = SKILL_ROOT / "assets" / "schemas" / "TruthLabels.schema.json"
MAX_JSON_BYTES = 64 * 1024 * 1024

DESCRIPTIVE = {
    "candidate_count",
    "mean_candidates_per_frame",
    "candidate_frame_fraction",
    "mean_threshold_margin_db",
    "mean_background_contrast_db",
}
MATCH_METRICS = {
    "recall", "precision", "f1", "frequency_mae_hz",
    "frequency_rmse_hz", "frequency_bias_hz",
}
FALSE_METRICS = {
    "false_count", "mean_false_per_frame", "false_per_hour",
    "cell_false_fraction", "background_frame_false_fraction",
    "background_segment_false_fraction",
}
SUPPORTED = DESCRIPTIVE | MATCH_METRICS | FALSE_METRICS

DEFINITIONS = {
    "candidate_count": "所选实际覆盖内完整最终候选表的候选数量。",
    "mean_candidates_per_frame": "最终候选数除以成功测试的有效帧数；包含零候选有效帧。",
    "candidate_frame_fraction": "至少有一个最终候选的有效帧数除以全部成功测试有效帧数。",
    "false_count": "在完整标注或可信背景覆盖内，按已声明计数层级得到的误报数量。",
    "mean_false_per_frame": "误报数量除以同一证据覆盖内的有效测试帧数。",
    "false_per_hour": "最终候选误报数除以去重后的有效标注覆盖时长（小时）。",
    "cell_false_fraction": "可信背景内越过门限的合格 CFAR 单元数除以全部合格 H0 单元数。",
    "background_frame_false_fraction": "至少有一次误报的可信背景有效帧数除以全部可信背景有效帧数。",
    "background_segment_false_fraction": "至少有一次误报的可信背景区域数除以全部可信背景区域数。",
    "recall": "完整标注覆盖内 TP/(TP+FN)，采用已声明的一对一匹配。",
    "precision": "完整标注覆盖内 TP/(TP+FP)，采用已声明的重复候选处理规则。",
    "f1": "完整标注覆盖内 2TP/(2TP+FP+FN)。",
    "frequency_mae_hz": "已匹配候选与真值的绝对频率误差均值。",
    "frequency_rmse_hz": "已匹配候选与真值的频率误差均方根。",
    "frequency_bias_hz": "已匹配候选频率减真值频率的有符号误差均值。",
    "mean_threshold_margin_db": "候选峰值功率与原检测门限之比的 10log10 平均值；不是物理 SNR。",
    "mean_background_contrast_db": "候选峰值功率与原局部背景统计量之比的 10log10 平均值；不是物理 SNR。",
}


class EvaluationError(RuntimeError):
    """A controlled evidence, contract, or execution error."""


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path, max_bytes=MAX_JSON_BYTES):
    path = Path(path)
    size = path.stat().st_size
    if size > max_bytes:
        raise EvaluationError(f"JSON file exceeds {max_bytes} bytes: {path}")
    return read_json(path)


def _file_ref(path, object_id=None):
    path = Path(path).resolve()
    return {"kind": "file", "locator": str(path), "sha256": sha256_file(path),
            "object_id": object_id, "reason": None}


def _resolve_eval_ref(ref, base_dir, *, expected_object=None):
    if not isinstance(ref, dict) or ref.get("kind") != "file":
        raise EvaluationError("Executable input reference must be kind=file.")
    locator = ref.get("locator")
    declared = ref.get("sha256")
    if not locator or not declared:
        raise EvaluationError("Executable file reference needs locator and SHA-256.")
    path = Path(locator)
    if not path.is_absolute():
        path = Path(base_dir) / path
    path = path.resolve()
    if not path.is_file():
        raise EvaluationError(f"Referenced file is unavailable: {path}")
    actual = sha256_file(path)
    if actual != declared:
        raise EvaluationError(f"SHA-256 mismatch for {path}: declared {declared}, actual {actual}")
    if expected_object is not None and ref.get("object_id") not in (None, expected_object):
        raise EvaluationError(f"Reference object_id differs from {expected_object}.")
    return path


def _resolve_detection_ref(ref, package_dir):
    if not isinstance(ref, dict) or ref.get("availability") != "available":
        raise EvaluationError("Detection artifact reference is not available.")
    location = ref.get("location") or {}
    kind, value = location.get("kind"), location.get("path")
    if kind not in ("package_relative", "external_reference") or not value:
        raise EvaluationError("Unsupported detection artifact locator.")
    path = Path(value) if kind == "external_reference" else Path(package_dir) / value
    path = path.resolve()
    if kind == "package_relative":
        try:
            path.relative_to(Path(package_dir).resolve())
        except ValueError as exc:
            raise EvaluationError("Package-relative reference escapes the detection package.") from exc
    if not path.is_file():
        raise EvaluationError(f"Detection artifact is unavailable: {path}")
    actual = sha256_file(path)
    if actual != ref.get("sha256"):
        raise EvaluationError(f"Detection artifact digest mismatch: {path}")
    return path


def _load_product(task, package_dir, kind, filename):
    artifacts = [x for x in task.get("artifacts", []) if x.get("kind") == kind and x.get("status") == "saved"]
    if len(artifacts) != 1:
        raise EvaluationError(f"Expected exactly one saved {kind} artifact for task {task.get('task_id')}.")
    manifest_path = _resolve_detection_ref(artifacts[0].get("file_ref"), package_dir)
    manifest = _load_json(manifest_path)
    if manifest.get("task_id") != task.get("task_id") or manifest.get("product_id") != kind:
        raise EvaluationError(f"{kind} product manifest identity mismatch.")
    entries = [x for x in manifest.get("files", []) if x.get("name") == filename]
    if len(entries) != 1:
        raise EvaluationError(f"{kind} product must declare exactly one {filename}.")
    entry = entries[0]
    product_path = (manifest_path.parent / filename).resolve()
    try:
        product_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise EvaluationError("Product file escapes its manifest directory.") from exc
    if not product_path.is_file():
        raise EvaluationError(f"Product file is unavailable: {product_path}")
    if product_path.stat().st_size != entry.get("size_bytes") or sha256_file(product_path) != entry.get("sha256"):
        raise EvaluationError(f"Product file identity mismatch: {product_path}")
    return _load_json(product_path), product_path, manifest_path


def _iter_key(node, key):
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            yield from _iter_key(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_key(value, key)


def _single_numeric(node, key):
    values = [float(x) for x in _iter_key(node, key)
              if type(x) in (int, float) and math.isfinite(x)]
    unique = sorted(set(values))
    if len(unique) != 1 or unique[0] <= 0:
        raise EvaluationError(f"Could not resolve one positive {key}; observed {unique}.")
    return unique[0]


def _find_task_config(config, task_id):
    request = config.get("request", config)
    payload = request.get("payload", request.get("request", {}).get("payload", {}))
    tasks = payload.get("tasks", [])
    matches = [x for x in tasks if x.get("task_id") == task_id]
    if len(matches) != 1:
        raise EvaluationError(f"Resolved configuration has no unique task {task_id}.")
    return matches[0]


def _find_input_payload(config, input_ref):
    matches = []
    for document in config.get("input_documents", []):
        payload = document.get("payload", {})
        manifest = payload.get("source_package", {}).get("manifest", {})
        if (manifest.get("sha256") == input_ref.get("package_sha256") and
                payload.get("signal_id") == input_ref.get("signal_id")):
            matches.append(payload)
    if len(matches) != 1:
        raise EvaluationError("Resolved configuration has no unique SignalInput for the selected task.")
    return matches[0]


def _verify_beam_identity(target_source, input_payload, request_dir):
    declared = target_source["beam"]
    observed = input_payload.get("beam_source")
    if not isinstance(observed, dict):
        raise EvaluationError("Selected SignalInput does not retain beam_source provenance.")
    if declared["status"] == "not_applicable":
        if observed.get("status") != "not_applicable":
            raise EvaluationError("Evaluation declares single-sensor input but SignalInput has beam provenance.")
        return
    if declared["status"] == "unknown":
        return
    if observed.get("status") != "applicable":
        raise EvaluationError("Evaluation declares a known beam but SignalInput does not have applicable beam provenance.")
    algorithm = observed.get("beamformer_algorithm", {})
    beam_id = observed.get("beam_id", {})
    source_result = observed.get("source_result") or {}
    if (algorithm.get("status") != "known" or algorithm.get("value") != declared["beamformer"] or
            beam_id.get("status") != "known" or beam_id.get("value") != declared["beam_id"] or
            source_result.get("sha256") != declared["result_sha256"]):
        raise EvaluationError("Known beam identity differs from the selected SignalInput provenance.")
    metadata_path = _resolve_eval_ref(declared["metadata_ref"], request_dir)
    if sha256_file(metadata_path) != declared["result_sha256"]:
        raise EvaluationError("Beam metadata reference digest differs from declared result_sha256.")


def _validate_truth_labels(document):
    from jsonschema import Draft202012Validator
    schema = _load_json(TRUTH_LABEL_SCHEMA)
    errors = [{"path": "/" + "/".join(map(str, e.absolute_path)), "message": e.message}
              for e in Draft202012Validator(schema).iter_errors(document)]
    labels = document.get("labels", []) if isinstance(document, dict) else []
    ids = [x.get("truth_id") for x in labels if isinstance(x, dict)]
    if len(ids) != len(set(ids)):
        errors.append({"path": "/labels", "message": "Duplicate truth_id."})
    for i, label in enumerate(labels):
        intervals = label.get("sample_intervals")
        if intervals is not None:
            previous = None
            for start, stop in intervals:
                if start >= stop:
                    errors.append({"path": f"/labels/{i}/sample_intervals", "message": "Require start < stop."})
                if previous is not None and start < previous:
                    errors.append({"path": f"/labels/{i}/sample_intervals", "message": "Intervals overlap or are unordered."})
                previous = stop
    return errors


def _merge_intervals(intervals):
    result = []
    for start, stop in sorted((float(a), float(b)) for a, b in intervals):
        if start >= stop:
            raise EvaluationError("Invalid interval with start >= stop.")
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], stop)
        else:
            result.append([start, stop])
    return result


def _support_inside_seconds(sample_intervals, time_intervals, fs):
    for start, stop in sample_intervals:
        lo, hi = start / fs, stop / fs
        if not any(a <= lo and hi <= b for a, b in time_intervals):
            return False
    return True


def _scope_contains_candidate(scope, candidate, fs):
    frequency = candidate["frequency"]["value_hz"]
    low, high = scope["frequency_band_hz"]
    if not low <= frequency <= high:
        return False
    time = scope["time"]
    if time["status"] == "not_applicable":
        return True
    if time["status"] != "known":
        return False
    return _support_inside_seconds(candidate["analysis_support"]["sample_intervals"], time["intervals_s"], fs)


def _scope_contains_row(scope, row, fs):
    time = scope["time"]
    if time["status"] == "not_applicable":
        return True
    if time["status"] != "known":
        return False
    return _support_inside_seconds(row["sample_intervals"], time["intervals_s"], fs)


def _actual_scope(target_scope, rows, fs):
    if target_scope["time"]["status"] == "not_applicable":
        time = copy.deepcopy(target_scope["time"])
    else:
        merged = _merge_intervals([[a / fs, b / fs] for row in rows for a, b in row["sample_intervals"]])
        time = {"status": "known", "reference": target_scope["time"]["reference"],
                "intervals_s": merged, "reason": None}
    return {"time": time, "frequency_band_hz": list(target_scope["frequency_band_hz"])}


def _scope_for_regions(regions):
    if not regions:
        raise EvaluationError("No evidence regions are available for the requested metric.")
    bands = {tuple(x["scope"]["frequency_band_hz"]) for x in regions}
    if len(bands) != 1:
        raise EvaluationError("Runtime V1 cannot encode one aggregate scalar over evidence regions with different frequency bands; request separate targets/metrics.")
    times = [x["scope"]["time"] for x in regions]
    statuses = {x["status"] for x in times}
    references = {x["reference"] for x in times}
    if len(statuses) != 1 or len(references) != 1:
        raise EvaluationError("Evidence regions for one scalar metric must share one time status and reference.")
    status = times[0]["status"]
    if status == "known":
        time = {"status": "known", "reference": times[0]["reference"],
                "intervals_s": _merge_intervals([v for item in times for v in item["intervals_s"]]),
                "reason": None}
    else:
        time = copy.deepcopy(times[0])
    return {"time": time, "frequency_band_hz": list(next(iter(bands)))}


def _measurement(candidate, name):
    values = [x for x in candidate.get("measurements", []) if x.get("name") == name]
    if len(values) != 1:
        raise EvaluationError(f"Candidate {candidate.get('candidate_id')} lacks one {name} measurement.")
    value = values[0]
    if value.get("scale") != "linear" or type(value.get("value")) not in (int, float):
        raise EvaluationError(f"Candidate {candidate.get('candidate_id')} has incompatible {name} measurement.")
    number = float(value["value"])
    if not math.isfinite(number) or number <= 0:
        raise EvaluationError(f"Candidate {candidate.get('candidate_id')} has nonpositive/nonfinite {name}.")
    return number


def _artifact_evidence(path, object_id=None):
    return _file_ref(path, object_id)


def _issue(report, severity, code, path, message):
    report["issues"].append({"severity": severity, "code": code, "path": path, "message": message})


def preflight(request_path):
    request_path = Path(request_path).resolve()
    report = {"valid": False, "can_execute": False, "runtime_version": VERSION,
              "request": str(request_path), "issues": [], "targets": []}
    contexts = {}
    try:
        request = _load_json(request_path)
        validation = validate_document(request, "EvaluationRequest")
        if not validation["valid"]:
            for error in validation["errors"]:
                _issue(report, "error", "request_contract_invalid", error["path"], error["message"])
            return report, None, contexts
        if request.get("document_status") != "specified":
            _issue(report, "error", "request_not_specified", "/document_status",
                   "Only a specified EvaluationRequest can execute.")
            return report, request, contexts
        payload = request["payload"]
        if any(x["compute"] for x in payload["metric_requests"]) and payload["confirmation"]["status"] != "recorded":
            _issue(report, "error", "confirmation_missing", "/payload/confirmation",
                   "Requested computation requires recorded confirmation; the runtime never fabricates it.")
        target_ids = {x["target_id"] for x in payload["targets"]}
        for metric in payload["metric_requests"]:
            if metric["compute"] and metric["metric_kind"] not in SUPPORTED:
                _issue(report, "error", "metric_not_implemented", "/payload/metric_requests",
                       f"Metric {metric['metric_kind']} is not implemented by runtime {VERSION}.")
            if metric["compute"] and metric["metric_kind"] in MATCH_METRICS:
                rules = {x["rule_id"]: x for x in payload["matching_rules"]}
                rule = rules.get(metric["matching_rule_id"])
                if not rule or rule["status"] != "specified":
                    _issue(report, "error", "matching_rule_pending", "/payload/matching_rules",
                           f"Metric {metric['metric_id']} requires a specified matching rule.")
                elif rule["assignment_method"] != "maximum_cardinality_minimum_frequency_error":
                    _issue(report, "error", "unsupported_assignment", "/payload/matching_rules",
                           "Runtime V1 supports assignment_method=maximum_cardinality_minimum_frequency_error.")
                elif rule["tie_break"] != "candidate_id_then_truth_id":
                    _issue(report, "error", "unsupported_tie_break", "/payload/matching_rules",
                           "Runtime V1 supports tie_break=candidate_id_then_truth_id.")
        bindings = {x["target_id"]: x for x in payload["truth_bindings"]}
        artifact_kinds = [x["kind"] for x in payload["output_plan"]["artifact_requests"]]
        if len(artifact_kinds) != len(set(artifact_kinds)):
            _issue(report, "error", "duplicate_artifact_kind", "/payload/output_plan/artifact_requests",
                   "Runtime V1 accepts at most one request per artifact kind.")
        for artifact in payload["output_plan"]["artifact_requests"]:
            if artifact["display"] and not artifact["compute"]:
                _issue(report, "error", "artifact_display_without_compute", "/payload/output_plan/artifact_requests",
                       f"Artifact {artifact['artifact_id']} cannot display without compute=true.")
            if artifact["save"] and not artifact["compute"]:
                _issue(report, "error", "artifact_save_without_compute", "/payload/output_plan/artifact_requests",
                       f"Artifact {artifact['artifact_id']} cannot save without compute=true.")
            if artifact["compute"] and artifact["kind"] not in {"report", "metric_table", "matches"}:
                _issue(report, "error", "artifact_not_implemented", "/payload/output_plan/artifact_requests",
                       f"Artifact kind {artifact['kind']} is not implemented by runtime {VERSION}.")
            if artifact["compute"] and not artifact["save"]:
                _issue(report, "error", "temporary_artifact_not_supported", "/payload/output_plan/artifact_requests",
                       "The V1 CLI only creates explicitly saved artifacts; set save=true or compute=false.")
        for target in payload["targets"]:
            target_id = target["target_id"]
            entry = {"target_id": target_id, "status": "blocked", "checks": []}
            report["targets"].append(entry)
            try:
                result_path = _resolve_eval_ref(target["result_ref"], request_path.parent)
                result = _load_json(result_path)
                if result.get("record_type") != "DetectionResult" or result.get("document_status") != "specified":
                    raise EvaluationError("Target result is not a specified DetectionResult.")
                if result.get("schema_version") != "0.1.0":
                    raise EvaluationError("Unsupported DetectionResult schema_version; runtime requires 0.1.0.")
                if result.get("payload", {}).get("run_id") != target["run_id"]:
                    raise EvaluationError("Evaluation target run_id differs from DetectionResult.")
                tasks = [x for x in result["payload"].get("task_results", [])
                         if x.get("task_id") == target["task_id"]]
                if len(tasks) != 1:
                    raise EvaluationError("DetectionResult has no unique selected task.")
                task = tasks[0]
                if task.get("execution_status") != "completed":
                    raise EvaluationError("Selected detection task did not complete successfully.")
                expected_kind = "average_spectrum" if target["task_kind"] == "averaged_spectrum" else target["task_kind"]
                config_path = _resolve_eval_ref(target["configuration_ref"], request_path.parent)
                config = _load_json(config_path)
                declared_config = result.get("payload", {}).get("resolved_configuration")
                resolved_config_path = _resolve_detection_ref(declared_config, result_path.parent)
                if config_path != resolved_config_path:
                    raise EvaluationError("Evaluation configuration_ref is not the configuration bound by DetectionResult.")
                task_config = _find_task_config(config, target["task_id"])
                if task_config.get("task_kind") != expected_kind:
                    raise EvaluationError("Evaluation task_kind differs from resolved detection configuration.")
                source = target["source"]
                if source["status"] == "known":
                    observed = task.get("input_ref", {})
                    if (observed.get("package_sha256") != source["input_package_sha256"] or
                            observed.get("signal_id") != source["signal_id"]):
                        raise EvaluationError("Evaluation source identity differs from detection task input_ref.")
                    input_payload = _find_input_payload(config, observed)
                    _verify_beam_identity(source, input_payload, request_path.parent)
                requested = task.get("coverage", {}).get("requested", {})
                if target["scope"]["frequency_band_hz"][0] < requested.get("search_band_hz", [math.inf])[0] or target["scope"]["frequency_band_hz"][1] > requested.get("search_band_hz", [-math.inf, -math.inf])[1]:
                    raise EvaluationError("Evaluation frequency scope exceeds detection search band.")
                if target["scope"]["time"]["status"] == "known" and target["scope"]["time"]["reference"] != requested.get("time_reference"):
                    raise EvaluationError("Evaluation time reference differs from detection task.")
                fs = _single_numeric(config, "sample_rate_hz")
                nfft = int(_single_numeric(task_config.get("resolved_parameters", {}), "nfft"))
                candidates, candidates_path, candidate_manifest = _load_product(
                    task, result_path.parent, "candidates", "candidates.json")
                ledger, ledger_path, ledger_manifest = _load_product(
                    task, result_path.parent, "ledger", "ledger.json")
                if candidates != task.get("candidates"):
                    raise EvaluationError("Saved candidate table differs from DetectionResult candidates.")
                ids = [x.get("candidate_id") for x in candidates]
                if len(ids) != len(set(ids)):
                    raise EvaluationError("Candidate IDs are not unique.")
                rows = ledger.get("rows", [])
                row_ids = [x.get("row") for x in rows]
                if len(row_ids) != len(set(row_ids)):
                    raise EvaluationError("Ledger row IDs are not unique.")
                row_map = {x["row"]: x for x in rows}
                for candidate in candidates:
                    if candidate.get("task_id") != target["task_id"]:
                        raise EvaluationError("Candidate task_id mismatch.")
                    row = candidate.get("extensions", {}).get("cfar_v1", {}).get("row")
                    if row not in row_map or candidate.get("analysis_support", {}).get("sample_intervals") != row_map[row].get("sample_intervals"):
                        raise EvaluationError("Candidate row/support does not match ledger.")
                    grid = candidate["frequency"].get("grid_index")
                    value = candidate["frequency"].get("value_hz")
                    if grid is None or not math.isclose(value, grid * fs / nfft, rel_tol=0, abs_tol=1e-9):
                        raise EvaluationError("Candidate frequency/grid mapping differs from resolved fs/nfft.")
                expected_count = sum(x.get("candidate_count", -1) for x in rows)
                if expected_count != len(candidates):
                    raise EvaluationError("Ledger candidate accounting differs from complete candidate table.")
                selected_rows = [x for x in rows if x.get("status") == "tested" and _scope_contains_row(target["scope"], x, fs)]
                selected_row_ids = {x["row"] for x in selected_rows}
                selected_candidates = [x for x in candidates
                                       if x.get("extensions", {}).get("cfar_v1", {}).get("row") in selected_row_ids
                                       and _scope_contains_candidate(target["scope"], x, fs)]
                if not selected_rows:
                    raise EvaluationError("No fully covered tested detection rows fall inside the requested scope.")
                frame_ledger = ledger.get("frame_ledger", [])
                requested_frames = [x for x in frame_ledger
                                    if "start_sample" in x and "stop_sample" in x and
                                    _scope_contains_row(target["scope"], {"sample_intervals": [[x["start_sample"], x["stop_sample"]]]}, fs)]
                excluded_frames = [x for x in requested_frames if x.get("status") != "eligible"]
                binding = bindings[target_id]
                coverage = None
                coverage_path = None
                label_documents = {}
                label_paths = {}
                if binding["status"] == "provided":
                    coverage_path = _resolve_eval_ref(binding["coverage_ref"], request_path.parent)
                    coverage = _load_json(coverage_path)
                    check = validate_document(coverage, "TruthCoverage")
                    if not check["valid"] or coverage.get("document_status") != "specified":
                        raise EvaluationError("TruthCoverage is not a valid specified document.")
                    cp = coverage["payload"]
                    if cp["target"] != target:
                        raise EvaluationError("TruthCoverage target declaration differs from EvaluationRequest target.")
                    region_map = {x["region_id"]: x for x in cp["regions"]}
                    region_ids = set(region_map)
                    for region in cp["regions"]:
                        labels_ref = region.get("labels_ref")
                        if labels_ref is None:
                            continue
                        labels_path = _resolve_eval_ref(labels_ref, coverage_path.parent)
                        labels = _load_json(labels_path)
                        errors = _validate_truth_labels(labels)
                        if errors:
                            raise EvaluationError("TruthLabels invalid: " + "; ".join(x["message"] for x in errors))
                        if labels["target_id"] != target_id or labels["run_id"] != target["run_id"] or labels["task_id"] != target["task_id"]:
                            raise EvaluationError("TruthLabels target identity differs from EvaluationRequest.")
                        if labels["time_reference"] not in (None, requested.get("time_reference")):
                            raise EvaluationError("TruthLabels time reference differs from detection task.")
                        if labels["sample_rate_hz"] is not None and not math.isclose(labels["sample_rate_hz"], fs):
                            raise EvaluationError("TruthLabels sample rate differs from resolved detection input.")
                        if any(x["region_id"] not in region_ids for x in labels["labels"]):
                            raise EvaluationError("TruthLabels references an unknown coverage region.")
                        for label in labels["labels"]:
                            region = region_map[label["region_id"]]
                            low, high = region["scope"]["frequency_band_hz"]
                            if not low <= label["frequency_hz"] <= high:
                                raise EvaluationError("Truth label frequency lies outside its declared coverage region.")
                            if label["sample_intervals"] is not None:
                                time = region["scope"]["time"]
                                if time["status"] != "known" or not _support_inside_seconds(
                                        label["sample_intervals"], time["intervals_s"], fs):
                                    raise EvaluationError("Truth label sample support lies outside its declared coverage region.")
                            if label["time_s"] is not None:
                                time = region["scope"]["time"]
                                if time["status"] != "known" or not any(
                                        a <= label["time_s"] < b for a, b in time["intervals_s"]):
                                    raise EvaluationError("Truth label time lies outside its declared coverage region.")
                        label_documents[str(labels_path)] = labels
                        label_paths[str(labels_path)] = labels_path
                    relevant_metrics = [x for x in payload["metric_requests"]
                                        if x["target_id"] == target_id and x["compute"] and x["matching_rule_id"]]
                    rules = {x["rule_id"]: x for x in payload["matching_rules"]}
                    all_labels = [label for document in label_documents.values() for label in document["labels"]]
                    for metric in relevant_metrics:
                        rule = rules[metric["matching_rule_id"]]
                        if target["task_kind"] == "framewise" and rule["time_rule"] == "not_applicable":
                            raise EvaluationError("Framewise truth matching cannot declare time_rule=not_applicable.")
                        if rule["time_rule"] == "frame_identity" and any(
                                label["sample_intervals"] is None for label in all_labels):
                            raise EvaluationError("frame_identity matching requires sample_intervals on every supplied truth label.")
                        if rule["time_rule"] == "tolerance" and any(
                                label["time_s"] is None for label in all_labels):
                            raise EvaluationError("tolerance matching requires time_s on every supplied truth label.")
                context = {"target": target, "result": result, "result_path": result_path,
                           "task": task, "config": config, "config_path": config_path,
                           "task_config": task_config, "fs": fs, "nfft": nfft,
                           "candidates": candidates, "candidates_path": candidates_path,
                           "candidate_manifest": candidate_manifest, "ledger": ledger,
                           "ledger_path": ledger_path, "ledger_manifest": ledger_manifest,
                           "selected_rows": selected_rows, "selected_row_ids": selected_row_ids,
                           "selected_candidates": selected_candidates,
                           "requested_frames": requested_frames, "excluded_frames": excluded_frames,
                           "binding": binding, "coverage": coverage, "coverage_path": coverage_path,
                           "label_documents": label_documents, "label_paths": label_paths}
                contexts[target_id] = context
                entry.update(status="ready", candidate_count=len(selected_candidates),
                             valid_frame_count=len(selected_rows), sample_rate_hz=fs,
                             truth_status=binding["status"])
                entry["checks"] = ["result_identity", "source_identity", "artifact_hashes",
                                   "candidate_ledger_consistency", "scope_mapping"]
                if binding["status"] == "provided":
                    entry["checks"].append("truth_coverage_and_labels")
            except Exception as exc:
                _issue(report, "error", "target_preflight_failed", f"/payload/targets/{target_id}", str(exc))
        if set(contexts) != target_ids:
            _issue(report, "error", "target_context_incomplete", "/payload/targets",
                   "Not all requested targets passed cross-document preflight.")
        report["valid"] = not any(x["severity"] == "error" for x in report["issues"])
        report["can_execute"] = report["valid"]
        return report, request, contexts
    except Exception as exc:
        _issue(report, "error", "preflight_exception", "/", f"{type(exc).__name__}: {exc}")
        return report, None, contexts


def _region_candidates(context, region):
    return [x for x in context["selected_candidates"]
            if _scope_contains_candidate(region["scope"], x, context["fs"])]


def _region_rows(context, region):
    return [x for x in context["selected_rows"]
            if _scope_contains_row(region["scope"], x, context["fs"])]


def _labels_for_region(context, region_id):
    labels = []
    for document in context["label_documents"].values():
        labels.extend(x for x in document["labels"] if x["region_id"] == region_id)
    ids = [x["truth_id"] for x in labels]
    if len(ids) != len(set(ids)):
        raise EvaluationError(f"Duplicate truth_id across label files for region {region_id}.")
    return labels


def _time_eligible(candidate, truth, rule, fs):
    if rule["time_rule"] == "not_applicable":
        return True
    support = candidate["analysis_support"]["sample_intervals"]
    if rule["time_rule"] == "frame_identity":
        return truth["sample_intervals"] is not None and support == truth["sample_intervals"]
    if rule["time_rule"] == "tolerance":
        if truth["time_s"] is None or not support:
            return False
        candidate_time = sum(a + b for a, b in support) / (2 * len(support) * fs)
        return abs(candidate_time - truth["time_s"]) <= rule["time_gate_s"]
    raise EvaluationError(f"Unsupported time rule: {rule['time_rule']}")


def _min_cost_match(candidates, truths, rule, fs):
    candidates = sorted(candidates, key=lambda x: x["candidate_id"])
    truths = sorted(truths, key=lambda x: x["truth_id"])
    nc, nt = len(candidates), len(truths)
    source, truth0, candidate0, sink = 0, 1, 1 + nt, 1 + nt + nc
    graph = [[] for _ in range(sink + 1)]

    def edge(a, b, capacity, cost):
        graph[a].append([b, capacity, cost, len(graph[b])])
        graph[b].append([a, 0, -cost, len(graph[a]) - 1])

    for ti in range(nt):
        edge(source, truth0 + ti, 1, 0)
    for ci in range(nc):
        edge(candidate0 + ci, sink, 1, 0)
    stride = max(1, nc * max(1, nt) + 1)
    for ti, truth in enumerate(truths):
        for ci, candidate in enumerate(candidates):
            error = abs(candidate["frequency"]["value_hz"] - truth["frequency_hz"])
            if error <= rule["frequency_gate_hz"] and _time_eligible(candidate, truth, rule, fs):
                primary = int(round(error * 1_000_000_000))
                edge(truth0 + ti, candidate0 + ci, 1,
                     primary * stride + ci * max(1, nt) + ti)

    while True:
        distance = [math.inf] * len(graph)
        parent = [None] * len(graph)
        distance[source] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for u in range(len(graph)):
                if distance[u] == math.inf:
                    continue
                for ei, item in enumerate(graph[u]):
                    v, capacity, cost, _ = item
                    value = distance[u] + cost
                    if capacity and (value < distance[v] or
                                     (value == distance[v] and (parent[v] is None or (u, ei) < parent[v]))):
                        distance[v], parent[v], changed = value, (u, ei), True
            if not changed:
                break
        if parent[sink] is None:
            break
        node = sink
        while node != source:
            u, ei = parent[node]
            item = graph[u][ei]
            item[1] -= 1
            graph[node][item[3]][1] += 1
            node = u

    matches = []
    matched_candidates = set()
    matched_truths = set()
    for ti, truth in enumerate(truths):
        node = truth0 + ti
        for item in graph[node]:
            v, capacity, _, _ = item
            if candidate0 <= v < candidate0 + nc and capacity == 0:
                candidate = candidates[v - candidate0]
                error = candidate["frequency"]["value_hz"] - truth["frequency_hz"]
                matches.append({"truth_id": truth["truth_id"], "candidate_id": candidate["candidate_id"],
                                "truth_frequency_hz": truth["frequency_hz"],
                                "candidate_frequency_hz": candidate["frequency"]["value_hz"],
                                "frequency_error_hz": error})
                matched_candidates.add(candidate["candidate_id"])
                matched_truths.add(truth["truth_id"])
                break
    eligible_duplicates = set()
    for candidate in candidates:
        if candidate["candidate_id"] in matched_candidates:
            continue
        for truth in truths:
            if truth["truth_id"] in matched_truths:
                error = abs(candidate["frequency"]["value_hz"] - truth["frequency_hz"])
                if error <= rule["frequency_gate_hz"] and _time_eligible(candidate, truth, rule, fs):
                    eligible_duplicates.add(candidate["candidate_id"])
                    break
    return {"matches": sorted(matches, key=lambda x: (x["truth_id"], x["candidate_id"])),
            "matched_candidate_ids": matched_candidates, "matched_truth_ids": matched_truths,
            "duplicate_candidate_ids": eligible_duplicates,
            "candidate_ids": {x["candidate_id"] for x in candidates},
            "truth_ids": {x["truth_id"] for x in truths}}


def _matching_summary(context, rule, include_statuses=("complete", "partial_positive")):
    coverage = context["coverage"]["payload"]
    regions = [x for x in coverage["regions"] if x["label_status"] in include_statuses]
    combined = {"matches": [], "matched_candidate_ids": set(), "matched_truth_ids": set(),
                "duplicate_candidate_ids": set(), "candidate_ids": set(), "truth_ids": set(),
                "complete_region_ids": [], "partial_region_ids": []}
    for region in regions:
        candidates = _region_candidates(context, region)
        truths = _labels_for_region(context, region["region_id"])
        result = _min_cost_match(candidates, truths, rule, context["fs"])
        for match in result["matches"]:
            match["region_id"] = region["region_id"]
        combined["matches"].extend(result["matches"])
        for key in ("matched_candidate_ids", "matched_truth_ids", "duplicate_candidate_ids",
                    "candidate_ids", "truth_ids"):
            combined[key].update(result[key])
        combined["complete_region_ids" if region["label_status"] == "complete" else "partial_region_ids"].append(region["region_id"])
    unmatched = combined["candidate_ids"] - combined["matched_candidate_ids"]
    if rule["duplicate_policy"] == "report_separately":
        false_ids = unmatched - combined["duplicate_candidate_ids"]
    else:
        false_ids = unmatched
    combined["false_candidate_ids"] = false_ids
    combined["fn_truth_ids"] = combined["truth_ids"] - combined["matched_truth_ids"]
    combined["matches"].sort(key=lambda x: (x["region_id"], x["truth_id"], x["candidate_id"]))
    return combined


def _regions(context, statuses):
    if context["coverage"] is None:
        return []
    return [x for x in context["coverage"]["payload"]["regions"] if x["label_status"] in statuses]


def _coverage_ref(context):
    return _file_ref(context["coverage_path"], context["coverage"]["payload"]["coverage_id"])


def _evidence(context, include_truth=False):
    refs = [_artifact_evidence(context["candidates_path"], "candidates"),
            _artifact_evidence(context["ledger_path"], "ledger")]
    if include_truth and context["coverage_path"]:
        refs.append(_coverage_ref(context))
        refs.extend(_file_ref(path, "TruthLabels") for path in context["label_paths"].values())
    unique = {}
    for ref in refs:
        unique[(ref["kind"], ref["locator"], ref["object_id"])] = ref
    return list(unique.values())


def _basis(context, kind, truth_status, regions, limitations=None):
    include_truth = context["coverage"] is not None and truth_status not in ("none", "unknown")
    return {"kind": kind, "truth_status": truth_status,
            "coverage_ref": _coverage_ref(context) if include_truth else None,
            "region_ids": [x["region_id"] for x in regions],
            "evidence_refs": _evidence(context, include_truth),
            "limitations": list(limitations or [])}


def _accounting(context, trial_unit, *, rows=None, candidates_complete=True,
                requested=None, processed=None, excluded=None, reasons=None, include_truth=False):
    rows = context["selected_rows"] if rows is None else rows
    if trial_unit == "frame" and requested is None:
        requested = len(rows)
        processed = len(rows)
        excluded = 0
    return {"status": "complete", "trial_unit": trial_unit,
            "zero_detection_units_included": True if trial_unit in ("frame", "cfar_cell", "segment") else None,
            "candidates_complete": candidates_complete,
            "requested_units": requested, "processed_units": processed, "excluded_units": excluded,
            "exclusion_reasons": list(reasons or []),
            "evidence_refs": _evidence(context, include_truth)}


def _quantity(value, unit, definition, evidence):
    return {"value": value, "unit": unit, "definition": definition, "evidence_refs": evidence}


def _metric_unit(kind, stage):
    item = "candidate" if stage == "final_candidate" else "cfar_cell"
    if kind in {"candidate_frame_fraction", "cell_false_fraction", "background_frame_false_fraction",
                "background_segment_false_fraction", "recall", "precision", "f1"}:
        return "1"
    if kind.startswith("frequency_"):
        return "Hz"
    if kind.endswith("_db"):
        return "dB"
    if kind in {"candidate_count", "false_count"}:
        return item
    if kind == "false_per_hour":
        return item + "/hour"
    return item + "/frame"


def _empty_metric(metric, status, reason, context, *, truth_status="unknown"):
    return {"metric_id": metric["metric_id"], "target_id": metric["target_id"],
            "metric_kind": metric["metric_kind"], "definition_version": "0.1.0",
            "definition": DEFINITIONS[metric["metric_kind"]], "status": status, "value": None,
            "unit": _metric_unit(metric["metric_kind"], metric["count_stage"]),
            "numerator": None, "denominator": None, "actual_scope": None,
            "matching_rule_ref": None, "count_stage": metric["count_stage"],
            "basis": _basis(context, "unknown", truth_status, [], [reason]),
            "accounting": {"status": "unknown", "trial_unit": "not_applicable",
                           "zero_detection_units_included": None, "candidates_complete": None,
                           "requested_units": None, "processed_units": None, "excluded_units": None,
                           "exclusion_reasons": [], "evidence_refs": []},
            "reason": reason}


def _frame_counts(context, candidates, rows):
    by_row = {row["row"]: 0 for row in rows}
    for candidate in candidates:
        row = candidate["extensions"]["cfar_v1"]["row"]
        if row in by_row:
            by_row[row] += 1
    return by_row


def _union_duration_hours(regions):
    intervals = []
    for region in regions:
        time = region["scope"]["time"]
        if time["status"] != "known":
            return None
        intervals.extend(time["intervals_s"])
    return sum(stop - start for start, stop in _merge_intervals(intervals)) / 3600


def _cell_counts(context, regions):
    denominator = 0
    numerator = 0
    frame_with_false = set()
    rows_seen = set()
    candidates_by_row = {}
    for candidate in context["selected_candidates"]:
        row = candidate["extensions"]["cfar_v1"]["row"]
        candidates_by_row.setdefault(row, []).append(candidate)
    for region in regions:
        low, high = region["scope"]["frequency_band_hz"]
        for row in _region_rows(context, region):
            rows_seen.add((region["region_id"], row["row"]))
            tested = {b for b in row.get("tested_bins", []) if low <= b * context["fs"] / context["nfft"] <= high}
            denominator += len(tested)
            crossings = set()
            for candidate in candidates_by_row.get(row["row"], []):
                lo, hi = candidate["extensions"]["cfar_v1"]["group_bins"]
                crossings.update(range(lo, hi + 1))
            for rejected in row.get("rejected_groups", []):
                lo, hi = rejected["group_bins"]
                crossings.update(range(lo, hi + 1))
            count = len(tested & crossings)
            numerator += count
            if count:
                frame_with_false.add((region["region_id"], row["row"]))
    return numerator, denominator, frame_with_false, rows_seen


def compute_metrics(request, contexts, request_path):
    payload = request["payload"]
    rules = {x["rule_id"]: x for x in payload["matching_rules"]}
    match_cache = {}
    results = []
    for metric in payload["metric_requests"]:
        context = contexts[metric["target_id"]]
        kind = metric["metric_kind"]
        binding = context["binding"]
        if not metric["compute"]:
            results.append(_empty_metric(metric, "not_requested", "本次未请求计算。", context,
                                         truth_status="none" if binding["status"] == "none" else "unknown"))
            continue
        rows = context["selected_rows"]
        candidates = context["selected_candidates"]
        actual_scope = _actual_scope(context["target"]["scope"], rows, context["fs"])
        evidence = _evidence(context)
        value = numerator = denominator = None
        matching_ref = None
        reason = None
        basis = _basis(context, "empirical_descriptive",
                       "none" if binding["status"] == "none" else "unknown", [],
                       ["无真值指标仅描述已有检测输出，不表示误报率或目标正确性。"])
        accounting = _accounting(context, "candidate", requested=len(candidates),
                                 processed=len(candidates), excluded=0)
        if kind == "candidate_count":
            value = len(candidates)
        elif kind == "mean_candidates_per_frame":
            if not rows:
                reason = "有效完成帧数为 0，指标未定义。"
            else:
                value = len(candidates) / len(rows)
                numerator = _quantity(len(candidates), "candidate", "所选范围内最终候选数。", evidence)
                denominator = _quantity(len(rows), "frame", "包含零候选帧的有效测试帧数。", evidence)
                accounting = _accounting(context, "frame")
        elif kind == "candidate_frame_fraction":
            if not rows:
                reason = "有效完成帧数为 0，指标未定义。"
            else:
                counts = _frame_counts(context, candidates, rows)
                positive = sum(v > 0 for v in counts.values())
                value = positive / len(rows)
                numerator = _quantity(positive, "frame", "至少有一个候选的有效帧数。", evidence)
                denominator = _quantity(len(rows), "frame", "包含零候选帧的有效测试帧数。", evidence)
                accounting = _accounting(context, "frame")
        elif kind in ("mean_threshold_margin_db", "mean_background_contrast_db"):
            if not candidates:
                reason = "所选范围内没有候选，均值未定义。"
            else:
                reference_name = "threshold" if kind == "mean_threshold_margin_db" else "background"
                values = [10 * math.log10(_measurement(x, "power") / _measurement(x, reference_name))
                          for x in candidates]
                value = sum(values) / len(values)
        elif kind in MATCH_METRICS:
            if binding["status"] != "provided":
                results.append(_empty_metric(metric, "insufficient_evidence",
                    "未提供独立真值覆盖，不能计算匹配性能。", context,
                    truth_status="none" if binding["status"] == "none" else "unknown"))
                continue
            rule = rules[metric["matching_rule_id"]]
            statuses = ("complete",) if kind in {"recall", "precision", "f1"} else ("complete", "partial_positive")
            key = (metric["target_id"], rule["rule_id"], statuses)
            if key not in match_cache:
                match_cache[key] = _matching_summary(context, rule, statuses)
            match = match_cache[key]
            complete = _regions(context, {"complete"})
            partial = _regions(context, {"partial_positive"})
            if kind in {"recall", "precision", "f1"} and not complete:
                results.append(_empty_metric(metric, "insufficient_evidence",
                    "没有完整正负标签覆盖；部分正标注不能支持总体分类性能。", context,
                    truth_status="partial" if partial else "unknown"))
                continue
            if kind.startswith("frequency_") and not match["matches"]:
                results.append(_empty_metric(metric, "undefined",
                    "没有一对一匹配项，频率误差指标未定义。", context,
                    truth_status="complete" if complete else "partial"))
                continue
            tp = len(match["matched_truth_ids"])
            fn = len(match["fn_truth_ids"])
            fp = len(match["false_candidate_ids"])
            truth_status = "complete" if complete else "partial"
            used_regions = complete if kind in {"recall", "precision", "f1"} else complete + partial
            if kind.startswith("frequency_") and partial:
                truth_status = "partial"
            basis = _basis(context, "label_matched", truth_status, used_regions,
                           [f"重复候选策略：{rule['duplicate_policy']}。"])
            actual_scope = _scope_for_regions(used_regions)
            accounting = _accounting(context, "matched_candidate", requested=len(match["candidate_ids"]),
                                     processed=len(match["candidate_ids"]), excluded=0, include_truth=True)
            matching_ref = _file_ref(request_path, f"matching_rule:{rule['rule_id']}")
            metric_evidence = _evidence(context, True)
            if kind == "recall":
                den = tp + fn
                if den == 0:
                    reason = "完整标注覆盖内没有正真值，recall 未定义。"
                else:
                    value = tp / den
                    numerator = _quantity(tp, "candidate", "一对一匹配真值数（TP）。", metric_evidence)
                    denominator = _quantity(den, "candidate", "完整覆盖内真值总数（TP+FN）。", metric_evidence)
            elif kind == "precision":
                den = tp + fp
                if den == 0:
                    reason = "完整标注覆盖内没有计入精确率分母的预测阳性，precision 未定义。"
                else:
                    value = tp / den
                    numerator = _quantity(tp, "candidate", "一对一匹配候选数（TP）。", metric_evidence)
                    denominator = _quantity(den, "candidate", "按重复规则计入的预测阳性（TP+FP）。", metric_evidence)
            elif kind == "f1":
                den = 2 * tp + fp + fn
                if den == 0:
                    reason = "F1 分母为 0，指标未定义。"
                else:
                    value = 2 * tp / den
                    numerator = _quantity(2 * tp, "candidate", "F1 分子 2TP。", metric_evidence)
                    denominator = _quantity(den, "candidate", "F1 分母 2TP+FP+FN。", metric_evidence)
            else:
                errors = [x["frequency_error_hz"] for x in match["matches"]]
                if kind == "frequency_mae_hz":
                    value = sum(abs(x) for x in errors) / len(errors)
                elif kind == "frequency_rmse_hz":
                    value = math.sqrt(sum(x * x for x in errors) / len(errors))
                else:
                    value = sum(errors) / len(errors)
        elif kind in FALSE_METRICS:
            if binding["status"] != "provided":
                results.append(_empty_metric(metric, "insufficient_evidence",
                    "未提供完整标签或可信背景，不能把候选解释为误报。", context,
                    truth_status="none" if binding["status"] == "none" else "unknown"))
                continue
            complete = _regions(context, {"complete"})
            background = _regions(context, {"verified_background"})
            if metric["count_stage"] == "cell_threshold_crossing" or kind in {
                    "cell_false_fraction", "background_frame_false_fraction",
                    "background_segment_false_fraction"}:
                if not background:
                    results.append(_empty_metric(metric, "insufficient_evidence",
                        "该单元/背景事件指标要求可信背景覆盖。", context, truth_status="unknown"))
                    continue
                cell_fp, cell_total, false_frames, all_frames = _cell_counts(context, background)
                basis = _basis(context, "verified_background", "verified_background", background,
                               ["统计来自已有 ledger 的合格单元与越门限组，不重新运行 CFAR。"])
                actual_scope = _scope_for_regions(background)
                evidence_truth = _evidence(context, True)
                matching_ref = None
                if kind == "cell_false_fraction":
                    if cell_total == 0:
                        reason = "可信背景覆盖内没有合格 H0 单元。"
                    else:
                        value = cell_fp / cell_total
                        numerator = _quantity(cell_fp, "cfar_cell", "可信背景内越门限的合格单元数。", evidence_truth)
                        denominator = _quantity(cell_total, "cfar_cell", "可信背景内全部合格 H0 单元数。", evidence_truth)
                        accounting = _accounting(context, "cfar_cell", requested=cell_total,
                                                 processed=cell_total, excluded=0, include_truth=True)
                elif kind == "background_frame_false_fraction":
                    if metric["count_stage"] == "final_candidate":
                        background_rows = {(region["region_id"], row["row"])
                                           for region in background for row in _region_rows(context, region)}
                        candidate_rows = {(region["region_id"], candidate["extensions"]["cfar_v1"]["row"])
                                          for region in background for candidate in _region_candidates(context, region)}
                        event_frames, event_all_frames = candidate_rows, background_rows
                    else:
                        event_frames, event_all_frames = false_frames, all_frames
                    if not event_all_frames:
                        reason = "可信背景覆盖内没有可评价有效帧。"
                    else:
                        value = len(event_frames) / len(event_all_frames)
                        event = "最终候选" if metric["count_stage"] == "final_candidate" else "单元越门限"
                        numerator = _quantity(len(event_frames), "frame", f"至少一次{event}的可信背景帧数。", evidence_truth)
                        denominator = _quantity(len(event_all_frames), "frame", "全部可信背景有效帧数。", evidence_truth)
                        accounting = _accounting(context, "frame", rows=[{"row": x} for x in event_all_frames],
                                                 requested=len(event_all_frames), processed=len(event_all_frames), excluded=0,
                                                 include_truth=True)
                elif kind == "background_segment_false_fraction":
                    segments = len(background)
                    if metric["count_stage"] == "final_candidate":
                        positive = sum(bool(_region_candidates(context, region)) for region in background)
                    else:
                        positive = sum(bool(_cell_counts(context, [region])[0]) for region in background)
                    if segments == 0:
                        reason = "可信背景区域数为 0。"
                    else:
                        value = positive / segments
                        numerator = _quantity(positive, "segment", "至少一次单元越门限的可信背景区域数。", evidence_truth)
                        denominator = _quantity(segments, "segment", "可信背景区域总数。", evidence_truth)
                        accounting = _accounting(context, "segment", requested=segments, processed=segments,
                                                 excluded=0, include_truth=True)
                elif kind in {"false_count", "mean_false_per_frame"}:
                    value = cell_fp if kind == "false_count" else (
                        cell_fp / len(all_frames) if all_frames else None)
                    if kind == "mean_false_per_frame" and not all_frames:
                        reason = "可信背景覆盖内没有可评价有效帧。"
                    elif kind == "mean_false_per_frame":
                        numerator = _quantity(cell_fp, "cfar_cell", "可信背景内越门限的合格单元数。", evidence_truth)
                        denominator = _quantity(len(all_frames), "frame", "可信背景有效帧数。", evidence_truth)
                        accounting = _accounting(context, "frame", requested=len(all_frames),
                                                 processed=len(all_frames), excluded=0, include_truth=True)
                    else:
                        accounting = _accounting(context, "cfar_cell", requested=cell_total,
                                                 processed=cell_total, excluded=0, include_truth=True)
                else:
                    results.append(_empty_metric(metric, "not_applicable",
                        "该指标不支持 CFAR 单元计数层级。", context, truth_status="verified_background"))
                    continue
            else:
                rule = rules.get(metric["matching_rule_id"])
                if complete and rule:
                    statuses = ("complete",)
                    key = (metric["target_id"], rule["rule_id"], statuses)
                    if key not in match_cache:
                        match_cache[key] = _matching_summary(context, rule, statuses)
                    match = match_cache[key]
                    false_ids = match["false_candidate_ids"]
                    fp = len(false_ids)
                    used_regions = complete
                    basis = _basis(context, "label_matched", "complete", complete,
                                   [f"重复候选策略：{rule['duplicate_policy']}。"])
                    matching_ref = _file_ref(request_path, f"matching_rule:{rule['rule_id']}")
                elif background:
                    background_candidates = {x["candidate_id"] for region in background
                                             for x in _region_candidates(context, region)}
                    fp = len(background_candidates)
                    used_regions = background
                    basis = _basis(context, "verified_background", "verified_background", background)
                else:
                    results.append(_empty_metric(metric, "insufficient_evidence",
                        "没有完整标注或可信背景覆盖。", context, truth_status="unknown"))
                    continue
                evidence_truth = _evidence(context, True)
                covered_rows = {row["row"]: row for region in used_regions for row in _region_rows(context, region)}
                actual_scope = _scope_for_regions(used_regions)
                if kind == "false_count":
                    value = fp
                    accounting = _accounting(context, "candidate", requested=fp, processed=fp,
                                             excluded=0, include_truth=True)
                elif kind == "mean_false_per_frame":
                    if not covered_rows:
                        reason = "证据覆盖内没有可评价有效帧。"
                    else:
                        value = fp / len(covered_rows)
                        numerator = _quantity(fp, "candidate", "证据覆盖内最终候选误报数。", evidence_truth)
                        denominator = _quantity(len(covered_rows), "frame", "证据覆盖内有效测试帧数。", evidence_truth)
                        accounting = _accounting(context, "frame", rows=list(covered_rows.values()),
                                                 requested=len(covered_rows), processed=len(covered_rows),
                                                 excluded=0, include_truth=True)
                elif kind == "false_per_hour":
                    hours = _union_duration_hours(used_regions)
                    if hours is None or hours <= 0:
                        reason = "证据覆盖没有可用的正有效时长。"
                    else:
                        value = fp / hours
                        numerator = _quantity(fp, "candidate", "证据覆盖内最终候选误报数。", evidence_truth)
                        denominator = _quantity(hours, "hour", "去重后的有效证据覆盖时长。", evidence_truth)
                        accounting = _accounting(context, "hour", requested=None, processed=None,
                                                 excluded=None, include_truth=True)
                else:
                    results.append(_empty_metric(metric, "not_applicable",
                        "该指标要求可信背景事件或单元语义。", context,
                        truth_status=basis["truth_status"]))
                    continue
        if reason is not None:
            results.append(_empty_metric(metric, "undefined", reason, context,
                                         truth_status=basis["truth_status"]))
            continue
        results.append({"metric_id": metric["metric_id"], "target_id": metric["target_id"],
                        "metric_kind": kind, "definition_version": "0.1.0",
                        "definition": DEFINITIONS[kind], "status": "computed", "value": value,
                        "unit": _metric_unit(kind, metric["count_stage"]),
                        "numerator": numerator, "denominator": denominator,
                        "actual_scope": actual_scope, "matching_rule_ref": matching_ref,
                        "count_stage": metric["count_stage"], "basis": basis,
                        "accounting": accounting, "reason": None})
    return results, match_cache


def _write_json(path, value):
    Path(path).write_bytes(_json_bytes(value))


def _render_report(request, metrics, contexts):
    lines = ["# 水声线谱评价结果", "", f"评价请求：`{request['payload']['request_id']}`", "",
             "本报告只评价已有检测结果；未重新检测、调门限、跟踪或判断目标身份。", "", "## 指标", "",
             "| 指标 | 目标 | 状态 | 数值 | 单位 |", "|---|---|---|---:|---|"]
    for metric in metrics:
        value = "—" if metric["value"] is None else f"{metric['value']:.12g}"
        lines.append(f"| {metric['metric_kind']} | {metric['target_id']} | {metric['status']} | {value} | {metric['unit']} |")
    lines += ["", "## 证据边界", ""]
    for target_id, context in contexts.items():
        binding = context["binding"]["status"]
        lines.append(f"- `{target_id}`：{len(context['selected_candidates'])} 个候选，{len(context['selected_rows'])} 个有效测试行；真值状态 `{binding}`。")
    lines += ["", "候选数量不是误报数量；只有带完整标签或可信背景依据的指标才解释为性能指标。", ""]
    return "\n".join(lines)


def execute(request_path, output_dir):
    request_path = Path(request_path).resolve()
    output_dir = Path(output_dir).resolve()
    report, request, contexts = preflight(request_path)
    if not report["can_execute"]:
        raise EvaluationError(json.dumps(report, ensure_ascii=False))
    planned = request["payload"]["output_plan"]["save_destination"]
    if planned is None or Path(planned).resolve() != output_dir:
        raise EvaluationError("--output-dir must exactly match output_plan.save_destination.")
    if output_dir.exists():
        raise EvaluationError(f"Output directory already exists; refusing to overwrite: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=output_dir.name + ".tmp-", dir=output_dir.parent))
    try:
        config = {"runtime_version": VERSION, "request_path": str(request_path),
                  "request_sha256": sha256_file(request_path), "preflight": report,
                  "targets": [{"target_id": target_id,
                               "result_path": str(context["result_path"]),
                               "result_sha256": sha256_file(context["result_path"]),
                               "configuration_path": str(context["config_path"]),
                               "configuration_sha256": sha256_file(context["config_path"]),
                               "candidate_path": str(context["candidates_path"]),
                               "candidate_sha256": sha256_file(context["candidates_path"]),
                               "ledger_path": str(context["ledger_path"]),
                               "ledger_sha256": sha256_file(context["ledger_path"]),
                               "truth_coverage_path": str(context["coverage_path"]) if context["coverage_path"] else None,
                               "truth_coverage_sha256": sha256_file(context["coverage_path"]) if context["coverage_path"] else None}
                              for target_id, context in contexts.items()]}
        config_path = temp_dir / "resolved-evaluation-config.json"
        _write_json(config_path, config)
        metrics, match_cache = compute_metrics(request, contexts, request_path)
        final_config_path = output_dir / config_path.name
        artifacts = []
        artifact_requests = request["payload"]["output_plan"]["artifact_requests"]
        requested_artifacts = {x["kind"]: x for x in artifact_requests}
        produced = {}
        if requested_artifacts.get("matches", {}).get("compute") and match_cache:
            serial = []
            for (target_id, rule_id, statuses), item in sorted(match_cache.items()):
                serial.append({"target_id": target_id, "rule_id": rule_id,
                               "coverage_statuses": list(statuses),
                               "matches": item["matches"],
                               "unmatched_candidate_ids": sorted(item["false_candidate_ids"]),
                               "unmatched_truth_ids": sorted(item["fn_truth_ids"]),
                               "duplicate_candidate_ids": sorted(item["duplicate_candidate_ids"])})
            match_path = temp_dir / "matches.json"
            _write_json(match_path, {"runtime_version": VERSION, "results": serial})
            produced["matches"] = match_path
        else:
            match_path = None
        if requested_artifacts.get("report", {}).get("compute"):
            report_path = temp_dir / "report.md"
            report_path.write_text(_render_report(request, metrics, contexts), encoding="utf-8")
            produced["report"] = report_path
        if requested_artifacts.get("metric_table", {}).get("compute"):
            table_path = temp_dir / "metrics.csv"
            with table_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["metric_id", "target_id", "metric_kind", "status", "value", "unit", "reason"])
                for metric in metrics:
                    writer.writerow([metric["metric_id"], metric["target_id"], metric["metric_kind"],
                                     metric["status"], "" if metric["value"] is None else metric["value"],
                                     metric["unit"], metric["reason"] or ""])
            produced["metric_table"] = table_path
        all_target_ids = sorted(contexts)
        for plan in artifact_requests:
            kind = plan["kind"]
            path = produced.get(kind)
            if not plan["compute"]:
                artifacts.append({"artifact_id": plan["artifact_id"], "kind": kind,
                                  "target_ids": plan["target_ids"], "status": "not_requested",
                                  "reference": None, "reason": None})
            elif path is None:
                artifacts.append({"artifact_id": plan["artifact_id"], "kind": kind,
                                  "target_ids": plan["target_ids"], "status": "not_generated",
                                  "reference": None,
                                  "reason": "No matching operation produced rows for this requested artifact."})
            else:
                final_path = output_dir / path.name
                artifacts.append({"artifact_id": plan["artifact_id"], "kind": kind,
                                  "target_ids": plan["target_ids"], "status": "saved",
                                  "reference": {"kind": "file", "locator": str(final_path),
                                                "sha256": sha256_file(path), "object_id": kind, "reason": None},
                                  "reason": None})
        result = {"schema_version": "0.1.0", "record_type": "EvaluationResult",
                  "document_status": "specified",
                  "payload": {"evaluation_id": str(uuid.uuid4()),
                              "request_ref": _file_ref(request_path, request["payload"]["request_id"]),
                              "configuration_ref": {"kind": "file", "locator": str(final_config_path),
                                                    "sha256": sha256_file(config_path),
                                                    "object_id": "resolved-evaluation-config", "reason": None},
                              "targets": copy.deepcopy(request["payload"]["targets"]),
                              "execution_status": "completed",
                              "metrics": metrics,
                              "findings": [{"kind": "observation",
                                            "text": "评价只使用已保存候选、ledger 与明确提供的真值证据；未重新检测。",
                                            "target_ids": all_target_ids,
                                            "evidence_refs": [_file_ref(request_path, request["payload"]["request_id"])]}],
                              "artifacts": artifacts,
                              "acceptance": {"status": "not_requested", "criteria_ref": None,
                                             "evidence_refs": [], "reason": "本次未请求工程验收判定。",
                                             "metric_ids": []},
                              "limitations": list(request["payload"]["accepted_limitations"]) + [
                                  "评价结果只覆盖实际记录的时频范围与证据条件，不外推至其他海况或数据。"]},
                  "unresolved_items": []}
        validation = validate_document(result, "EvaluationResult")
        if not validation["valid"]:
            raise EvaluationError("Generated EvaluationResult failed validation: " +
                                  json.dumps(validation["errors"], ensure_ascii=False))
        result_path = temp_dir / "evaluation-result.json"
        _write_json(result_path, result)
        files = []
        for path in sorted(temp_dir.iterdir()):
            if path.name == "package-manifest.json":
                continue
            files.append({"path": path.name, "sha256": sha256_file(path),
                          "size_bytes": path.stat().st_size})
        manifest = {"package_version": VERSION, "record_type": "LineSpectrumEvaluationPackage",
                    "evaluation_id": result["payload"]["evaluation_id"], "files": files,
                    "upstream_immutable": True}
        _write_json(temp_dir / "package-manifest.json", manifest)
        os.replace(temp_dir, output_dir)
        return result, output_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="Specified EvaluationRequest JSON.")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Verify cross-document evidence and print a read-only report.")
    parser.add_argument("--output-dir", type=Path,
                        help="New output directory; must match output_plan.save_destination.")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            report, _, _ = preflight(args.request)
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
            return 0 if report["can_execute"] else 1
        if args.output_dir is None:
            raise EvaluationError("--output-dir is required unless --preflight-only is used.")
        result, output = execute(args.request, args.output_dir)
        print(json.dumps({"ok": True, "evaluation_id": result["payload"]["evaluation_id"],
                          "output_dir": str(output), "metric_count": len(result["payload"]["metrics"])},
                         ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
