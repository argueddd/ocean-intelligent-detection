#!/usr/bin/env python3
"""Read-only evaluation contract validation; never executes evaluation or detection."""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import sys

KINDS = ("EvaluationRequest", "TruthCoverage", "EvaluationResult")
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "assets" / "schemas"
VERSION = "0.1.0"
FALSE_METRICS = {"false_count", "mean_false_per_frame", "false_per_hour",
                 "cell_false_fraction", "background_frame_false_fraction",
                 "background_segment_false_fraction"}
MATCH_METRICS = {"recall", "precision", "f1", "frequency_mae_hz",
                 "frequency_rmse_hz", "frequency_bias_hz"}
FRAME_METRICS = {"mean_candidates_per_frame", "candidate_frame_fraction",
                 "mean_false_per_frame", "background_frame_false_fraction"}
FRACTIONS = {"candidate_frame_fraction", "cell_false_fraction",
             "background_frame_false_fraction", "background_segment_false_fraction",
             "recall", "precision", "f1"}
RATIOS = FRACTIONS | {"mean_candidates_per_frame", "mean_false_per_frame", "false_per_hour"}
COUNTS = {"candidate_count", "false_count"}
SIGNED = {"frequency_bias_hz", "mean_threshold_margin_db", "mean_background_contrast_db"}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON token: {value}")


def _json_domain(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Non-finite number, including exponent overflow.")
        return
    if type(value) is list:
        for child in value:
            _json_domain(child)
        return
    if type(value) is dict:
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Object keys must be strings.")
            _json_domain(child)
        return
    raise ValueError("Only the JSON data model is supported.")


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"),
                       object_pairs_hook=_pairs, parse_constant=_constant)
    _json_domain(value)
    return value


@lru_cache(maxsize=1)
def _validators():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    docs = [read_json(SCHEMA_DIR / "common.schema.json")]
    docs += [read_json(SCHEMA_DIR / f"{kind}.schema.json") for kind in KINDS]
    registry = Registry()  # No network or arbitrary filesystem retrieval.
    for doc in docs:
        Draft202012Validator.check_schema(doc)
        registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))
    return {kind: Draft202012Validator(doc, registry=registry)
            for kind, doc in zip(KINDS, docs[1:])}


def pointer(parts):
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def _available(ref):
    return ref is not None and ref["kind"] in ("file", "session")


def _walk(node, path="/payload"):
    yield node, path
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, path + "/" + key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, path + "/" + str(i))


def _semantic_errors(kind, p):
    errors = []

    def issue(path, message):
        errors.append({"path": path, "message": message})

    def need(condition, path, message):
        if not condition:
            issue(path, message)

    def unique(items, key, path):
        values = [x[key] for x in items]
        need(len(values) == len(set(values)), path, f"Duplicate {key}.")

    def available(refs):
        return bool(refs) and all(_available(x) for x in refs)

    def scope_inside(inner, outer, path):
        a, b = inner["frequency_band_hz"]
        c, d = outer["frequency_band_hz"]
        need(c <= a < b <= d, path, "Frequency range outside target scope.")
        it, ot = inner["time"], outer["time"]
        need(it["status"] == ot["status"], path, "Time status differs from target.")
        if it["status"] == ot["status"] == "known":
            need(it["reference"] == ot["reference"], path, "Time reference differs from target.")
            for lo, hi in it["intervals_s"]:
                # Adjacent intervals may jointly cover an interval, without editing either.
                cursor = lo
                for start, stop in ot["intervals_s"]:
                    if start <= cursor < stop:
                        cursor = max(cursor, stop)
                need(cursor >= hi, path, "Time interval outside target scope.")

    # Common checks apply to nested declarations; referenced documents are not opened.
    for node, path in _walk(p):
        if not isinstance(node, dict):
            continue
        if set(node) == {"kind", "locator", "sha256", "object_id", "reason"}:
            if node["kind"] == "file":
                need(node["locator"] is not None and node["sha256"] is not None,
                     path, "File reference needs locator and declared SHA-256.")
            elif node["kind"] == "session":
                need(node["locator"] is not None, path, "Session reference needs a locator.")
            else:
                need(node["reason"] is not None, path, "Unavailable reference needs a reason.")
        if set(node) == {"status", "reference", "intervals_s", "reason"}:
            if node["status"] == "known":
                need(node["reference"] is not None and node["intervals_s"] is not None,
                     path, "Known time needs reference and intervals.")
                previous = None
                for start, stop in node["intervals_s"] or []:
                    need(start < stop, path, "Require time start < stop.")
                    need(previous is None or start >= previous, path,
                         "Time intervals must be ordered and non-overlapping.")
                    previous = stop
            else:
                need(node["intervals_s"] is None and node["reason"] is not None, path,
                     "Unknown/not-applicable time must not invent intervals; give reason.")
                if node["status"] == "not_applicable":
                    need(node["reference"] is None, path, "Not-applicable time has no reference.")
        if set(node) == {"time", "frequency_band_hz"}:
            need(node["frequency_band_hz"][0] < node["frequency_band_hz"][1],
                 path, "Require lower frequency < upper frequency.")
        if set(node) == {"status", "input_package_sha256", "signal_id", "beam", "reason"}:
            if node["status"] == "known":
                need(node["input_package_sha256"] is not None and node["signal_id"] is not None,
                     path, "Known signal needs package digest and signal_id.")
            else:
                need(node["reason"] is not None, path,
                     "Unknown signal identity needs reason; retain any known partial facts.")
        if set(node) == {"status", "result_sha256", "beamformer", "beam_id", "metadata_ref", "reason"}:
            names = ("result_sha256", "beamformer", "beam_id", "metadata_ref")
            if node["status"] == "known":
                need(all(node[x] is not None for x in names), path, "Known beam identity is incomplete.")
            else:
                need(node["reason"] is not None, path, "Unknown/not-applicable beam needs reason.")
                if node["status"] == "not_applicable":
                    need(all(node[x] is None for x in names), path,
                         "Not-applicable beam must not invent an identity.")

    if kind == "TruthCoverage":
        regions = p["regions"]
        unique(regions, "region_id", "/payload/regions")
        if p["availability"] == "available":
            need(bool(regions) and available(p["provenance_refs"]), "/payload",
                 "Available coverage needs regions and available provenance.")
            need(p["evidence_origin"] not in ("none", "unknown"), "/payload/evidence_origin",
                 "Available coverage needs declared evidence origin.")
        else:
            need(not regions, "/payload/regions", "Absent/unknown truth cannot declare labeled regions.")
            need(p["evidence_origin"] == p["availability"], "/payload/evidence_origin",
                 "Absent/unknown evidence origin must agree with availability.")
        if p["independence"]["status"] == "independent":
            need(available(p["independence"]["relative_to_refs"]), "/payload/independence",
                 "Independence must state what it is relative to.")
        for i, r in enumerate(regions):
            path = f"/payload/regions/{i}"
            scope_inside(r["scope"], p["target"]["scope"], path + "/scope")
            status = r["label_status"]
            if status in ("complete", "partial_positive"):
                need(_available(r["labels_ref"]) and available(r["evidence_refs"]), path,
                     "Annotated region needs labels and supporting references.")
                need(r["positive_definition"] is not None and r["label_grain"] not in ("none", "unknown"),
                     path, "Positive labels need a definition and known grain.")
            if status == "complete":
                need(r["negative_definition"] is not None and r["unmarked_policy"] == "negative",
                     path, "Complete labeling needs explicit negative semantics.")
            if status in ("partial_positive", "unlabeled", "disputed"):
                need(r["unmarked_policy"] == "unknown", path,
                     "Unmarked items in partial/unlabeled/disputed coverage remain unknown.")
            if status == "verified_background":
                need(r["h0_definition"] is not None and r["negative_definition"] is not None
                     and available(r["evidence_refs"]) and r["unmarked_policy"] == "negative"
                     and r["label_grain"] not in ("none", "unknown"), path,
                     "Background needs H0 definition, evidence and explicit negative semantics.")
            if status in ("unlabeled", "excluded"):
                need(r["labels_ref"] is None and r["reason"] is not None, path,
                     "Unlabeled/excluded region cannot supply truth labels; give reason.")
            if status == "excluded":
                need(r["unmarked_policy"] == "out_of_scope", path, "Excluded region is out of scope.")
            if p["evidence_origin"] == "expected_reference":
                need(status not in ("complete", "verified_background"), path,
                     "Expected frequencies cannot certify complete truth or pure background.")
            for earlier in regions[:i]:
                t1, t2 = earlier["scope"]["time"], r["scope"]["time"]
                f1, f2 = earlier["scope"]["frequency_band_hz"], r["scope"]["frequency_band_hz"]
                freq_overlap = max(f1[0], f2[0]) <= min(f1[1], f2[1])
                time_overlap = t1["status"] != "known" or t2["status"] != "known"
                if not time_overlap and t1["reference"] == t2["reference"]:
                    time_overlap = any(max(a,c) < min(b,d) for a,b in t1["intervals_s"]
                                       for c,d in t2["intervals_s"])
                need(not (freq_overlap and time_overlap), path,
                     "Regions overlap or cannot be distinguished; resolve coverage, do not guess.")
        return errors

    targets = p["targets"]
    unique(targets, "target_id", "/payload/targets")
    target_map = {x["target_id"]: x for x in targets}
    target_ids = set(target_map)
    if kind == "EvaluationRequest":
        bindings, metrics = p["truth_bindings"], p["metric_requests"]
        unique(bindings, "target_id", "/payload/truth_bindings")
        need({b["target_id"] for b in bindings} == target_ids, "/payload/truth_bindings",
             "Each target needs exactly one explicit truth binding.")
        for i, binding in enumerate(bindings):
            if binding["status"] == "provided":
                need(_available(binding["coverage_ref"]), f"/payload/truth_bindings/{i}",
                     "Provided coverage requires an available reference.")
            else:
                need(binding["coverage_ref"] is None and binding["reason"] is not None,
                     f"/payload/truth_bindings/{i}", "No/unknown truth needs null reference and reason.")
        unique(metrics, "metric_id", "/payload/metric_requests")
        unique(p["matching_rules"], "rule_id", "/payload/matching_rules")
        rules = {r["rule_id"] for r in p["matching_rules"]}
        for i, rule in enumerate(p["matching_rules"]):
            path = f"/payload/matching_rules/{i}"
            values = ("frequency_gate_hz","time_rule","assignment_method","tie_break","duplicate_policy")
            if rule["status"] == "specified":
                need(all(rule[x] is not None for x in values), path, "Specified matching rule incomplete.")
                need((rule["time_rule"] == "tolerance") == (rule["time_gate_s"] is not None),
                     path, "Time gate is supplied only for the tolerance rule.")
            else:
                need(all(rule[x] is None for x in values) and rule["time_gate_s"] is None
                     and rule["reason"] is not None, path, "Pending rule cannot imply chosen parameters.")
        for i, metric in enumerate(metrics):
            path = f"/payload/metric_requests/{i}"
            need(metric["target_id"] in target_ids, path, "Unknown target_id.")
            need(metric["matching_rule_id"] is None or metric["matching_rule_id"] in rules,
                 path, "Unknown matching_rule_id.")
            if metric["compute"] and metric["metric_kind"] in MATCH_METRICS:
                need(metric["matching_rule_id"] is not None, path,
                     "Matching-dependent computation must declare a specified or pending rule.")
            target = target_map.get(metric["target_id"])
            if target and metric["metric_kind"] in FRAME_METRICS:
                need(target["task_kind"] == "framewise", path,
                     "Averaged-spectrum task is not a collection of detection frames.")
        plan = p["output_plan"]
        metric_ids = {m["metric_id"] for m in metrics}
        need(set(plan["display_metric_ids"] + plan["save_metric_ids"]) <= metric_ids,
             "/payload/output_plan", "Output plan references unknown metric_id.")
        unique(plan["artifact_requests"], "artifact_id", "/payload/output_plan/artifact_requests")
        saves = bool(plan["save_metric_ids"]) or any(a["save"] for a in plan["artifact_requests"])
        need(saves == (plan["save_destination"] is not None), "/payload/output_plan",
             "Save destination is required exactly when saving is selected.")
        for artifact in plan["artifact_requests"]:
            need(set(artifact["target_ids"]) <= target_ids, "/payload/output_plan/artifact_requests",
                 "Unknown artifact target.")
        conf = p["confirmation"]
        if conf["status"] == "recorded":
            need(_available(conf["evidence_ref"]) and conf["statement"] is not None,
                 "/payload/confirmation", "Recorded confirmation needs statement and evidence.")
        else:
            need(conf["evidence_ref"] is None and conf["statement"] is None,
                 "/payload/confirmation", "Do not fabricate pending confirmation.")
        return errors

    metrics = p["metrics"]
    unique(metrics, "metric_id", "/payload/metrics")
    unique(p["artifacts"], "artifact_id", "/payload/artifacts")
    for i, metric in enumerate(metrics):
        path = f"/payload/metrics/{i}"
        k, status = metric["metric_kind"], metric["status"]
        basis, accounting = metric["basis"], metric["accounting"]
        target = target_map.get(metric["target_id"])
        need(target is not None, path, "Unknown target_id.")
        item_unit = "candidate" if metric["count_stage"] == "final_candidate" else "cfar_cell"
        expected_unit = ("1" if k in FRACTIONS else "Hz" if k.startswith("frequency_")
                         else "dB" if k.endswith("_db") else item_unit if k in COUNTS
                         else item_unit + "/hour" if k == "false_per_hour"
                         else item_unit + "/frame")
        need(metric["unit"] == expected_unit, path + "/unit", "Unit differs from metric definition.")
        if metric["actual_scope"] is not None and target:
            scope_inside(metric["actual_scope"], target["scope"], path + "/actual_scope")
        if status != "computed":
            need(metric["value"] is None and metric["reason"] is not None, path,
                 "Non-computed metric must have null value and explicit reason, never zero-fill.")
        else:
            need(metric["value"] is not None and metric["actual_scope"] is not None
                 and available(basis["evidence_refs"]), path,
                 "Computed metric needs value, actual coverage and evidence.")
            need(_available(p["configuration_ref"]) and _available(p["request_ref"]),
                 path, "Computed metric needs available request/configuration references.")
            need(target is not None and _available(target["result_ref"]), path,
                 "Computed metric needs an available source result.")
            need(basis["kind"] not in ("unknown","image_only","expected_reference","theoretical"),
                 path, "Scalar measured metrics cannot claim image/model/expected evidence as measurement.")
            value = metric["value"]
            if value is not None:
                if k not in SIGNED:
                    need(value >= 0, path, "This metric is nonnegative.")
                if k in COUNTS:
                    need(value == int(value), path, "Counts must be integral.")
                if k in FRACTIONS:
                    need(value <= 1, path, "Fraction must be in [0,1].")
            if k in RATIOS:
                numerator, denominator = metric["numerator"], metric["denominator"]
                need(numerator is not None and denominator is not None, path,
                     "Ratio/rate needs explicit numerator and denominator.")
                if numerator is not None:
                    need(numerator["value"] >= 0 and available(numerator["evidence_refs"]), path,
                         "Numerator must be nonnegative with available evidence.")
                if denominator is not None:
                    need(denominator["value"] > 0 and available(denominator["evidence_refs"]), path,
                         "Computed ratio requires positive denominator and available evidence.")
                if k in FRACTIONS and numerator is not None and denominator is not None:
                    need(numerator["value"] <= denominator["value"], path, "Fraction numerator exceeds denominator.")
            if k in FALSE_METRICS | MATCH_METRICS:
                need(basis["kind"] in ("label_matched","verified_background",
                                      "calibration_observation","validation_observation"),
                     path, "Performance metric needs labeled/background observation evidence.")
                need(_available(basis["coverage_ref"]) and bool(basis["region_ids"]), path,
                     "Performance metric needs explicit coverage reference and region IDs.")
                allowed = {"complete","verified_background"} if k in FALSE_METRICS else {"complete"}
                if k.startswith("frequency_"):
                    allowed = {"complete","partial"}
                need(basis["truth_status"] in allowed, path,
                     "Truth/background declaration is insufficient for this metric.")
                if k in MATCH_METRICS or (k in FALSE_METRICS and basis["truth_status"] == "complete"
                                          and metric["count_stage"] == "final_candidate"):
                    need(_available(metric["matching_rule_ref"]), path,
                         "Matched metric needs an explicit matching-rule reference.")
            if k in {"cell_false_fraction","background_frame_false_fraction","background_segment_false_fraction"}:
                need(basis["truth_status"] == "verified_background", path,
                     "This metric requires declared H0/background trials.")
            if k in FRAME_METRICS:
                need(target is not None and target["task_kind"] == "framewise", path,
                     "Frame metric cannot count averaging windows as detection frames.")
                need(accounting["trial_unit"] == "frame"
                     and accounting["zero_detection_units_included"] is True, path,
                     "Frame denominator must include zero-detection valid frames.")
            if k == "cell_false_fraction":
                need(metric["count_stage"] == "cell_threshold_crossing"
                     and accounting["trial_unit"] == "cfar_cell", path,
                     "Final peaks cannot stand in for CFAR-cell trials.")
            if k == "background_segment_false_fraction":
                need(accounting["trial_unit"] == "segment", path, "Require segment-level accounting.")
            if k == "false_per_hour":
                need(accounting["trial_unit"] == "hour" and metric["denominator"] is not None
                     and metric["denominator"]["unit"] == "hour", path,
                     "Hourly rate needs effective observation hours, not first/last detection times.")
            need(accounting["status"] == "complete" and available(accounting["evidence_refs"]), path,
                 "Computed scalar needs complete accounting for its explicitly selected actual scope.")
            if metric["count_stage"] == "final_candidate":
                need(accounting["candidates_complete"] is True, path,
                     "Truncated/unknown candidate list cannot masquerade as complete.")
        if k not in {"false_count","mean_false_per_frame","cell_false_fraction",
                     "background_frame_false_fraction","background_segment_false_fraction"}:
            need(metric["count_stage"] == "final_candidate", path, "Metric requires final-candidate semantics.")
        counts = [accounting[x] for x in ("requested_units","processed_units","excluded_units")]
        if all(x is not None for x in counts):
            need(counts[0] >= counts[1] + counts[2], path, "Processed/excluded counts exceed requested.")
            if accounting["status"] == "complete":
                need(counts[0] == counts[1] + counts[2], path, "Complete accounting must cover requested units.")
        if accounting["excluded_units"]:
            need(bool(accounting["exclusion_reasons"]), path, "Excluded units need reasons.")
        if status == "computed" and k in FRAME_METRICS:
            den = metric["denominator"]
            need(accounting["processed_units"] is not None, path, "Frame count is not inferred from candidates.")
            if den is not None:
                need(den["unit"] == "frame" and den["value"] == accounting["processed_units"],
                     path, "Frame denominator differs from processed valid-frame count.")

    computed = [m for m in metrics if m["status"] == "computed"]
    if p["execution_status"] in ("not_run","blocked"):
        need(not computed, "/payload/execution_status", "Unexecuted/blocked result cannot contain computed metrics.")
    if p["execution_status"] == "completed":
        need(not any(m["status"] in ("not_run","pending_confirmation","failed") for m in metrics),
             "/payload/execution_status", "Completed review cannot hide pending/failed metric work.")
    for item in p["findings"] + p["artifacts"]:
        need(set(item["target_ids"]) <= target_ids, "/payload", "Unknown finding/artifact target.")
    for i, artifact in enumerate(p["artifacts"]):
        path = f"/payload/artifacts/{i}"
        if artifact["status"] == "saved":
            need(artifact["reference"] is not None and artifact["reference"]["kind"] == "file",
                 path, "Saved artifact needs file locator and digest.")
        elif artifact["status"] == "temporary":
            need(_available(artifact["reference"]), path, "Temporary artifact needs usable reference.")
        elif artifact["status"] in ("not_requested","not_generated"):
            need(artifact["reference"] is None, path, "Ungenerated artifact cannot claim a reference.")
        else:
            need(artifact["reason"] is not None, path, "Unavailable/failed artifact needs reason.")
    acceptance = p["acceptance"]
    critical_ids = set(acceptance["metric_ids"])
    need(critical_ids <= {m["metric_id"] for m in metrics}, "/payload/acceptance",
         "Acceptance references an unknown metric.")
    if acceptance["status"] == "not_requested":
        need(not critical_ids and acceptance["criteria_ref"] is None
             and not acceptance["evidence_refs"], "/payload/acceptance",
             "Unrequested acceptance cannot imply an acceptance plan.")
    if acceptance["status"] in ("pass","fail","conditional_pass"):
        critical = [m for m in computed if m["metric_id"] in critical_ids]
        need(_available(acceptance["criteria_ref"]) and available(acceptance["evidence_refs"])
             and bool(critical_ids) and len(critical) == len(critical_ids)
             and any(m["metric_kind"] in FALSE_METRICS | MATCH_METRICS for m in critical),
             "/payload/acceptance",
             "Conclusive performance acceptance needs criteria and all selected critical metrics computed.")
    return errors


def validate_document(document, expected_kind=None):
    report = {"valid": False, "record_type": None, "document_status": None,
              "validation_scope": "document_structure_only", "can_execute": False,
              "not_checked": ["referenced_file_contents_or_hashes", "cross_document_consistency",
                              "truth_authenticity_and_label_completeness", "actual_trial_accounting",
                              "metric_calculation_or_formula_correctness", "real_user_authority",
                              "matching_and_statistical_assumptions", "engineering_acceptance"],
              "errors": []}
    try:
        _json_domain(document)
        if not isinstance(document, dict):
            raise ValueError("Root must be a JSON object.")
        kind = document.get("record_type")
        report.update(record_type=kind, document_status=document.get("document_status"))
        if kind not in KINDS:
            raise ValueError("Unknown record_type.")
        if expected_kind is not None and kind != expected_kind:
            raise ValueError("record_type differs from --kind.")
        report["errors"] = [{"path": pointer(e.absolute_path), "message": e.message}
                            for e in _validators()[kind].iter_errors(document)]
        if not report["errors"] and document["document_status"] == "specified":
            report["validation_scope"] = "document_structure_and_local_consistency"
            report["errors"] = _semantic_errors(kind, document["payload"])
        report["valid"] = not report["errors"]
        report["interpretation"] = (
            "Draft format valid; unresolved information remains. Not executable."
            if report["valid"] and document["document_status"] == "draft" else
            "Declarations locally consistent; evidence, authority and numerical correctness unverified. Not executable."
            if report["valid"] else "Invalid document; no repair or execution performed.")
    except Exception as exc:
        report["errors"].append({"path": "/", "message": f"{type(exc).__name__}: {exc}"})
        report["interpretation"] = "Validation failed; no repair or execution performed."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="One explicit JSON file; no referenced sources opened.")
    parser.add_argument("--kind", choices=KINDS)
    args = parser.parse_args()
    try:
        document = read_json(args.document)
    except Exception as exc:
        print(json.dumps({"valid": False, "can_execute": False, "validation_scope": "document_parse_only",
                          "errors": [{"path": "/", "message": f"{type(exc).__name__}: {exc}"}]},
                         ensure_ascii=False, indent=2))
        return 2
    report = validate_document(document, args.kind)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
