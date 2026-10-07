"""Explicit H0-trial calibration and held-out validation, never automatic noise selection."""
from __future__ import annotations
import argparse
import copy
import hashlib
import math
from pathlib import Path
import sys
import numpy as np
from scipy.stats import beta
import cfar_core as core
import cfar_registry as registry
import detection_products as products
import detection_runtime as runtime
import preflight as pf

VERSION = "1.0.0"


def event_signature(task, inp, prepared):
    """Exact numerical recipe, target processing identity, frame/gap geometry; no inferred equivalence."""
    p = task["resolved_parameters"]
    first = task["scope"]["sample_intervals"][0][0]
    geometry = ([[0, p["spectrum"]["window_length"]]] if p["threshold"]["event_scope"] == "frame" else
                [[a-first, b-first] for a, b in prepared["frames"]])
    beam = inp["beam_source"]
    return {"implementation": task["detector"], "task_kind": task["task_kind"],
        "spectrum": p["spectrum"], "cfar": p["cfar"], "event_scope": p["threshold"]["event_scope"],
        "event_probability": p["threshold"]["event_probability"], "search_band_hz": task["scope"]["search_band_hz"],
        "eligible_frequency_bins": prepared["cuts"].tolist(), "frame_geometry": geometry,
        "sample_rate_hz": inp["sample_rate_hz"], "data_role": inp["data_role"],
        "units": {k: inp["units"][k] for k in ("status", "value", "amplitude_convention")},
        "beam_algorithm": beam.get("beamformer_algorithm"), "beam_direction": beam.get("direction"),
        "source_configuration_sha256": inp["processing_history"]["source_configuration"]["sha256"]}


def order_coefficient(maxima, q):
    """Order ceil((n+1)*(1-q)); no extrapolation beyond observed tail resolution."""
    if not isinstance(maxima, (list, tuple)) or any(type(v) not in (int, float) for v in maxima):
        raise ValueError("Maxima must be explicit numeric values, not coerced strings or booleans.")
    values = np.asarray(maxima, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Calibration requires positive finite event maxima.")
    order = math.ceil((len(values) + 1) * (1 - q))
    if not 1 <= order <= len(values):
        raise ValueError("Insufficient calibration tail resolution for requested event probability; collect more H0 trials.")
    return float(np.partition(values, order - 1)[order - 1]), order


def validation_summary(maxima, alpha, q, confidence):
    values = np.asarray(maxima, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Independent validation requires positive finite event maxima.")
    n = len(values); k = int(np.count_nonzero(values > alpha))
    upper = 1.0 if k == n else float(beta.ppf(confidence, k + 1, n - k))
    return {"event_count": n, "exceedance_count": k, "observed_event_fraction": k/n,
        "confidence_level": confidence, "one_sided_clopper_pearson_upper": upper,
        "passes_declared_rule": bool(upper <= q),
        "interpretation": "H0 validation event rate only under asserted independent trials; not field detection performance."}


def check_record(record, task, inp, prepared):
    required = {"calibration_version", "status", "signature", "signature_sha256", "alpha", "order",
                "calibration_maxima", "validation_maxima", "validation", "minimum_calibration_events",
                "minimum_validation_events", "confidence_level", "trial_records", "plan_sha256",
                "execution_receipt", "h0_assertions", "limitations"}
    if set(record) != required or record["calibration_version"] != VERSION or record["status"] != "qualified_for_declared_scope":
        raise ValueError("Calibration is incomplete, failed independent validation, or unsupported.")
    signature = event_signature(task, inp, prepared)
    if record["signature"] != signature or record["signature_sha256"] != pf.digest(signature):
        raise ValueError("Calibration is not matched to detector/input processing/frame geometry/probability.")
    q = signature["event_probability"]
    alpha, order = order_coefficient(record["calibration_maxima"], q)
    conf = record["confidence_level"]
    if type(conf) not in (int, float) or not 0 < conf < 1:
        raise ValueError("Invalid calibration validation confidence.")
    checked = validation_summary(record["validation_maxima"], alpha, q, conf)
    if record["alpha"] != alpha or record["order"] != order or record["validation"] != checked or not checked["passes_declared_rule"]:
        raise ValueError("Calibration coefficient/validation audit mismatch.")
    for field, values in (("minimum_calibration_events", record["calibration_maxima"]),
                          ("minimum_validation_events", record["validation_maxima"])):
        if type(record[field]) is not int or not 1 <= record[field] <= len(values):
            raise ValueError("Calibration trial-count requirement not met.")
    if len(record["trial_records"]) != len(record["calibration_maxima"]) + len(record["validation_maxima"]):
        raise ValueError("Calibration trial provenance is incomplete.")
    for split, values in (("calibration", record["calibration_maxima"]), ("validation", record["validation_maxima"])):
        if [v["maximum_ratio"] for v in record["trial_records"] if v["split"] == split] != values:
            raise ValueError("Trial maxima and split audit do not agree.")
    assumptions = record["h0_assertions"]
    if set(assumptions) != {"independence_statement", "background_evidence_reference"} or not all(isinstance(v, str) and v.strip() for v in assumptions.values()):
        raise ValueError("Missing explicit H0/independence provenance.")
    trial_supports = [(inp["waveform"]["file_ref"]["sha256"], prepared["frames"])]
    for trial in record["trial_records"]:
        sha = trial["waveform_sha256"]; support = trial["frame_support"]
        for other_sha, intervals in trial_supports:
            if sha == other_sha and any(max(a, c) < min(b, d) for a, b in support for c, d in intervals):
                raise ValueError("Calibration/validation/target waveform supports overlap; not independent held-out use.")
        trial_supports.append((sha, support))
    evidence = record["execution_receipt"]
    if evidence.get("scope") != "calibration" or evidence.get("plan_sha256") != record["plan_sha256"]:
        raise ValueError("Calibration execution receipt mismatch.")
    return alpha


def make_review(config, root):
    keys = {"calibration_version", "target_request", "context", "trials", "independence_statement",
            "background_evidence_reference", "confidence_level", "minimum_calibration_events",
            "minimum_validation_events", "quantile_rule", "validation_rule"}
    if not isinstance(config, dict) or set(config) != keys or config["calibration_version"] != VERSION:
        raise ValueError("Incomplete or unsupported calibration configuration; no defaults supplied.")
    if config["quantile_rule"] != "conservative_order_statistic" or config["validation_rule"] != "one_sided_clopper_pearson_upper_le_q":
        raise ValueError("Unsupported explicitly selected calibration/validation rule.")
    if not all(isinstance(config[k], str) and config[k].strip() for k in ("independence_statement", "background_evidence_reference")):
        raise ValueError("H0 provenance and independent-trial rationale must be explicit.")
    conf = config["confidence_level"]
    if type(conf) not in (int, float) or not 0 < conf < 1:
        raise ValueError("Choose a validation confidence strictly between 0 and 1.")
    for key in ("minimum_calibration_events", "minimum_validation_events"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError("Explicit positive minimum trial counts are required.")
    request = copy.deepcopy(config["target_request"])
    runtime.require_contract(request, "DetectionRequest")
    if len(request["payload"]["tasks"]) != 1:
        raise ValueError("One target signal/detector/task per calibration, not pooled methods/beams.")
    target = request["payload"]["tasks"][0]
    th = target["resolved_parameters"]["threshold"]
    if th["route"] != "calibration" or th["calibration_ref"] is not None or th["theory_assumption"] is not None:
        raise ValueError("Calibration target requires route=calibration and both references/assumptions null until built.")
    if target["products"] != {"compute": [], "view": [], "save": []} or target["resolved_parameters"]["display"] is not None:
        raise ValueError("Calibration computes event maxima only; no hidden detection or plotting products.")
    if request["payload"]["unknown_decisions"]:
        raise ValueError("H0 calibration needs known validity/frequency support; no unknown metadata bypass.")
    trial_ids = set()
    for index, trial in enumerate(config["trials"]):
        expected = {"trial_id", "split", "input_ref", "scope", "background_statement", "processing_equivalence_statement"}
        if set(trial) != expected or trial["split"] not in ("calibration", "validation"):
            raise ValueError("Trial identity/split/scope and explicit H0/processing evidence are required.")
        if not all(isinstance(trial[k], str) and trial[k].strip() for k in ("trial_id", "background_statement", "processing_equivalence_statement")):
            raise ValueError("No inferred H0 labels or processing equivalence.")
        if trial["trial_id"] in trial_ids:
            raise ValueError("Duplicate calibration trial id.")
        trial_ids.add(trial["trial_id"])
        t = copy.deepcopy(target); t.update(task_id=f"calibration_trial_{index:08d}", input_ref=trial["input_ref"], scope=trial["scope"])
        request["payload"]["tasks"].append(t)
    state = runtime.RuntimeReview(request, config["context"], root, calibrating=True)
    report = state.run()
    if report["status"] == "blocked":
        return report, state
    try:
        original = state.states[0]
        target_signature = event_signature(target, original["input"]["payload"], original["prepared"])
        identities = [(original["input"]["payload"]["waveform"]["file_ref"]["sha256"], original["prepared"]["frames"])]
        for item, trial in zip(state.states[1:], config["trials"]):
            inp = item["input"]["payload"]; prepared = item["prepared"]
            if inp["validity"]["status"] != "known" or inp["frequency_coverage"]["status"] != "known":
                raise ValueError("Calibration trials require known validity and frequency coverage.")
            sig = event_signature(item["task"], inp, prepared)
            # Metadata equality is machine checked; differing source configs need the separately recorded
            # user's processing-equivalence evidence, never inferred from filenames or approximate grids.
            lhs = {k: v for k, v in sig.items() if k != "source_configuration_sha256"}
            rhs = {k: v for k, v in target_signature.items() if k != "source_configuration_sha256"}
            if lhs != rhs:
                raise ValueError("H0 trial does not match target metadata or event-frame geometry.")
            if th["event_scope"] == "frame" and len(prepared["frames"]) != 1:
                raise ValueError("Each frame-control H0 trial must supply exactly one complete valid frame; overlapping frames are not independent trials.")
            sha = inp["waveform"]["file_ref"]["sha256"]
            support = core.merge(prepared["frames"])
            for other_sha, other_support in identities:
                if sha == other_sha and any(max(a, c) < min(b, d) for a, b in support for c, d in other_support):
                    raise ValueError("H0 trials overlap in the same waveform; no train/validation reuse.")
            identities.append((sha, support))
        nc = sum(t["split"] == "calibration" for t in config["trials"])
        nv = sum(t["split"] == "validation" for t in config["trials"])
        if nc < config["minimum_calibration_events"] or nv < config["minimum_validation_events"]:
            raise ValueError("Not enough explicitly supplied calibration/independent validation trials.")
        if math.ceil((nc + 1) * (1 - th["event_probability"])) > nc:
            raise ValueError("Insufficient calibration tail resolution; no maximum-as-guarantee substitution.")
        report["target_signature"] = target_signature
        report["calibration_trial_count"] = nc; report["validation_trial_count"] = nv
        report["plan_sha256"] = pf.digest({"runtime_plan": report["plan_sha256"], "calibration_config": config,
                                          "target_signature": target_signature})
    except Exception as exc:
        report["issues"].append(str(exc)); report["status"] = "blocked"; report["plan_sha256"] = None
    return report, state


def review(config, root):
    return make_review(config, root)[0]


def run(config, root, receipt):
    report, state = make_review(config, root)
    runtime.require_receipt(report, receipt); state.recheck()
    maxima = {"calibration": [], "validation": []}; records = []
    for item, trial in zip(state.states[1:], config["trials"]):
        values = []
        for row, support, psd in core.spectra(item["waveform"], item["input"]["payload"]["sample_rate_hz"], item["task"], item["prepared"]):
            z, good = core.background(psd, item["task"], item["prepared"])
            if not np.all(good):
                raise ValueError("H0 calibration trial has zero/nonfinite background; do not silently remove trials/cells.")
            ratios = psd[item["prepared"]["cuts"]] / z
            if not np.all(np.isfinite(ratios)):
                raise ValueError("Nonfinite H0 ratios.")
            values.append(float(np.max(ratios)))
        maximum = max(values)
        maxima[trial["split"]].append(maximum)
        records.append({**trial, "maximum_ratio": maximum,
            "waveform_sha256": item["input"]["payload"]["waveform"]["file_ref"]["sha256"],
            "source_configuration": item["input"]["payload"]["processing_history"]["source_configuration"],
            "frame_support": item["prepared"]["frames"]})
    q = report["target_signature"]["event_probability"]
    alpha, order = order_coefficient(maxima["calibration"], q)
    validation = validation_summary(maxima["validation"], alpha, q, config["confidence_level"])
    record = {"calibration_version": VERSION,
        "status": "qualified_for_declared_scope" if validation["passes_declared_rule"] else "not_qualified",
        "signature": report["target_signature"], "signature_sha256": pf.digest(report["target_signature"]),
        "alpha": alpha, "order": order, "calibration_maxima": maxima["calibration"], "validation_maxima": maxima["validation"],
        "validation": validation, "minimum_calibration_events": config["minimum_calibration_events"],
        "minimum_validation_events": config["minimum_validation_events"], "confidence_level": config["confidence_level"],
        "trial_records": records, "plan_sha256": report["plan_sha256"], "execution_receipt": receipt,
        "h0_assertions": {k: config[k] for k in ("independence_statement", "background_evidence_reference")},
        "limitations": ["H0 truth, independence and processing equivalence include explicit user assertions, not machine proof.",
            "Finite-sample validation is conditional evidence, not a real-data or cross-beam guarantee.",
            "Validation samples do not select/re-tune the coefficient; a failed record cannot authorize detection."]}
    files = {"calibration-record.json": products.json_bytes(record), "calibration-request.json": products.json_bytes(config),
             "calibration-review.json": products.json_bytes(report)}
    rp = config["target_request"]["payload"]["resources"]
    if sum(map(len, files.values())) > rp["max_artifact_bytes"]:
        raise ValueError("Calibration artifacts exceed explicit budget.")
    state.recheck()
    if rp["persistence"] == "saved":
        marker = {"package_version": VERSION, "kind": "cfar_calibration", "status": record["status"],
            "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest(), "size_bytes": len(v)} for k, v in files.items()]}
        runtime.publish(rp["output_directory"], files, marker, rp["max_artifact_bytes"], state.root, state.recheck)
    return {"record": record, "output_directory": rp["output_directory"], "files": files if rp["persistence"] == "session" else {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["review", "confirm", "run"]); parser.add_argument("config")
    parser.add_argument("--source-root", required=True); parser.add_argument("--evidence")
    parser.add_argument("--receipt"); parser.add_argument("--receipt-output")
    args = parser.parse_args(); config = pf.explicit_json(args.config)
    if args.action == "review":
        answer = review(config, args.source_root)
    elif args.action == "confirm":
        if not args.evidence or not args.receipt_output:
            parser.error("confirm requires --evidence and --receipt-output")
        answer = runtime.confirm(review(config, args.source_root), pf.explicit_json(args.evidence))
        path = runtime.safe_new_path(args.receipt_output, args.source_root)
        with path.open("xb") as handle:
            handle.write(products.json_bytes(answer))
    else:
        if not args.receipt:
            parser.error("run requires --receipt")
        answer = run(config, args.source_root, pf.explicit_json(args.receipt)); answer.pop("files")
    print(products.json_bytes(answer).decode())
    if answer.get("status") == "blocked" or answer.get("record", {}).get("status") == "not_qualified":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(products.json_bytes({"status": "blocked_or_failed", "error": str(exc)}).decode()); sys.exit(2)
