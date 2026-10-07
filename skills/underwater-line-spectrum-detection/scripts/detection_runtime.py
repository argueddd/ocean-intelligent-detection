"""CFAR v1: review -> explicit execution receipt -> run. Old preflight stays read-only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
import numpy as np
import preflight as pf
import validate_contract as contracts
import cfar_core as core
import cfar_registry as registry
import detection_products as products

VERSION = "1.0.0"


def require_contract(document, kind):
    checked = contracts.validate_document(document, kind)
    if not checked["valid"] or document["document_status"] != "specified":
        raise ValueError(kind + ": " + str(checked["errors"][:10]))


def safe_new_path(path, readonly_root=None):
    path = Path(path)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("Output must be an explicit new absolute path; never overwrite.")
    if not path.parent.is_dir() or path.parent.resolve() != path.parent:
        raise ValueError("Output parent must exist, be canonical and contain no symlinks.")
    if readonly_root is not None and path.is_relative_to(Path(readonly_root).resolve()):
        raise ValueError("Output must be outside the explicitly read-only source root.")
    return path


def confirm(report, evidence):
    """Create an in-memory receipt from a real supplied user statement; not identity authentication."""
    expected = {"actor", "decision", "plan_sha256", "statement", "reference"}
    if set(evidence) != expected or evidence["actor"] != "user" or evidence["decision"] != "authorize_execution":
        raise ValueError("Explicit user execution evidence required; old preflight receipts are not execution approval.")
    if report["status"] != "ready_pending_execution_confirmation" or evidence["plan_sha256"] != report["plan_sha256"]:
        raise ValueError("Cannot confirm blocked/stale plan.")
    if any(not isinstance(evidence[k], str) or not evidence[k].strip() for k in ("statement", "reference")):
        raise ValueError("Actual user statement and reference are required, never fabricate them.")
    return {"receipt_version": VERSION, "scope": report["operation"], "plan_sha256": report["plan_sha256"],
            "evidence": copy.deepcopy(evidence), "authority_verified": False}


def require_receipt(report, receipt):
    if not isinstance(receipt, dict) or set(receipt) != {"receipt_version", "scope", "plan_sha256", "evidence", "authority_verified"}:
        raise ValueError("A current execution receipt is required.")
    expected = confirm(report, receipt["evidence"])
    if receipt != expected:
        raise ValueError("Receipt scope, version or plan mismatch. Reconfirm the changed plan.")


class RuntimeReview:
    def __init__(self, request, context, root, *, calibrating=False):
        self.request = copy.deepcopy(request); self.context = copy.deepcopy(context)
        self.root = Path(root).resolve(); self.calibrating = calibrating
        self.base = pf.Review(self.root, self.context)
        self.states = []; self.array_cache = {}; self.loaded_bytes = 0
        self.report = None

    def load(self, ref):
        sha = ref["sha256"]
        if sha in self.array_cache:
            return self.array_cache[sha]
        item = self.base.sources[sha]
        maximum = self.request["payload"]["resources"]["max_working_bytes"]
        if self.loaded_bytes + item["size_bytes"] * 2 > maximum:
            raise ValueError("Input arrays exceed explicit working budget before allocation.")
        with pf.scoped_open(self.root, item["path"]) as handle:
            before = os.fstat(handle.fileno())
            if pf.signature(before) != self.base.snapshots[item["path"]]:
                raise ValueError("Input changed before load.")
            value = np.load(handle, allow_pickle=False, max_header_size=65536)
            if pf.signature(os.fstat(handle.fileno())) != pf.signature(before):
                raise ValueError("Input changed while loading.")
        self.loaded_bytes += value.nbytes; self.array_cache[sha] = value
        return value

    def source_document(self, ref):
        item = self.base.source(ref, "/runtime/calibration_ref")
        if item is None:
            raise ValueError("Calibration record is not explicitly bound and verified.")
        if item["size_bytes"] > self.request["payload"]["resources"]["max_working_bytes"]:
            raise ValueError("Calibration record exceeds working budget.")
        with pf.scoped_open(self.root, item["path"]) as handle:
            raw = handle.read(item["size_bytes"] + 1)
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("Calibration source changed.")
        return pf.parse_json(raw)

    def recheck(self):
        self.base.unchanged()
        if any(v["blocking"] for v in self.base.issues):
            raise ValueError("Source/document changed: " + str(self.base.issues[-3:]))
        for item in self.base.sources.values():
            h = hashlib.sha256()
            with pf.scoped_open(self.root, item["path"]) as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != item["sha256"]:
                raise ValueError("Source SHA256 changed before computation/publication.")
        if registry.implementation_digest() != self.report["implementation_sha256"]:
            raise ValueError("Implementation changed; execution confirmation is stale.")

    def run(self):
        base_report = self.base.run(self.request)
        report = {"runtime_version": VERSION, "operation": "calibration" if self.calibrating else "detection",
            "status": "blocked", "can_execute": False, "execution_status": "not_run", "authority_verified": False,
            "plan_sha256": None, "issues": [], "base_preflight": base_report,
            "implementation_sha256": registry.implementation_digest(), "tasks": []}
        self.report = report
        if base_report["review_status"] == "blocked":
            report["issues"].append("Base preflight blocked; resolve its questions first.")
            return report
        try:
            if "handoff_validation" not in self.context:
                raise ValueError("Full upstream handoff validation is mandatory for execution.")
            inputs = self.base.inputs(); descriptors = self.base.descriptors()
            rp = self.request["payload"]; resources = rp["resources"]
            if resources["persistence"] == "saved":
                safe_new_path(resources["output_directory"], self.root)
                if resources["temporary_storage_policy"] != "memory_only_until_publish":
                    raise ValueError("Saved runs require explicit memory_only_until_publish policy.")
            elif resources["output_directory"] is not None or resources["temporary_storage_policy"] != "memory_only":
                raise ValueError("Session requires output_directory=null and memory_only policy.")
            total_estimate = 0
            for task in rp["tasks"]:
                method = task["detector"]["detector_id"]
                actual = registry.descriptor(method)
                key = (method, task["detector"]["detector_version"], task["detector"]["implementation_sha256"])
                if task["detector"] != registry.identity(method) or descriptors[key][0] != actual:
                    raise ValueError("Descriptor/implementation differs from trusted fixed registry.")
                ikey = (task["input_ref"]["package_sha256"], task["input_ref"]["signal_id"])
                doc = inputs[ikey][0]; inp = doc["payload"]
                waveform = self.load(inp["waveform"]["file_ref"])
                mask = self.load(inp["validity"]["mask_ref"]) if inp["validity"]["mask_ref"] else None
                prepared = core.plan(task, inp, waveform, mask, resources["max_working_bytes"], calibrating=self.calibrating)
                selected = set(task["products"]["compute"])
                if not set(task["products"]["view"] + task["products"]["save"]) <= selected:
                    raise ValueError("View/save products require explicit compute selection.")
                display = task["resolved_parameters"]["display"]
                plots = selected & {"spectrum_plot", "time_frequency_plot"}
                if bool(plots) != (display is not None):
                    raise ValueError("Plots require explicit display parameters; unused display must be null.")
                if plots:
                    if not display["db_limits"][0] < display["db_limits"][1]:
                        raise ValueError("Display dB limits must increase.")
                    if "spectrum_plot" in plots and not display["spectrum_rows"]:
                        raise ValueError("Select exact spectrum rows, not an implicit first/all row.")
                    if any(row >= prepared["rows"] for row in display["spectrum_rows"]):
                        raise ValueError("Requested display row does not exist.")
                    if "spectrum_plot" not in plots and display["spectrum_rows"]:
                        raise ValueError("Spectrum rows selected without spectrum_plot computation.")
                    if "time_frequency_plot" in plots and task["task_kind"] != "framewise":
                        raise ValueError("Average spectrum has no framewise time-frequency detection product.")
                alpha, calibration = None, None
                if task["resolved_parameters"]["threshold"]["route"] == "calibration" and not self.calibrating:
                    import cfar_calibration
                    calibration = self.source_document(task["resolved_parameters"]["threshold"]["calibration_ref"])
                    alpha = cfar_calibration.check_record(calibration, task, inp, prepared)
                estimate = prepared["working_bytes_estimate"] + (67108864 + len(display["spectrum_rows"]) * 8388608 if plots else 0)
                total_estimate += estimate
                self.states.append({"task": task, "input": doc, "waveform": waveform, "mask": mask,
                                    "prepared": prepared, "alpha": alpha, "calibration": calibration})
                report["tasks"].append({"task_id": task["task_id"], "complete_frames": len(prepared["frame_ledger"]),
                    "valid_frames": len(prepared["frames"]), "detection_rows": prepared["rows"],
                    "eligible_frequency_bins": prepared["cuts"].tolist(), "tests_per_event": prepared["tests_per_event"],
                    "cell_probability": prepared["p_cell"] if task["resolved_parameters"]["threshold"]["route"] == "theory" else None,
                    "working_bytes_estimate": estimate, "validity_status": prepared["validity_status"]})
            if total_estimate > resources["max_working_bytes"]:
                raise ValueError(f"Batch retained-memory estimate {total_estimate} exceeds budget; reduce scope or explicitly change budget.")
            report["working_bytes_estimate"] = total_estimate
            # Serialized products are bounded again by actual bytes before any output directory exists.
            report["warnings"] = ["No identity authentication; user evidence must be genuine.",
                "CFAR probability applies only under declared model/calibration assumptions, separately per task.",
                "Actual product-byte budget is enforced before publication; OS RSS is not a hard limit."]
            self.base.unchanged()
            if any(v["blocking"] for v in self.base.issues):
                raise ValueError("Sources changed or calibration source check failed.")
            report["plan_sha256"] = pf.digest({"runtime": VERSION, "operation": report["operation"],
                "base_plan": base_report["plan_sha256"], "request": self.request, "context": self.context,
                "root": str(self.root), "implementation": report["implementation_sha256"],
                "sources": sorted(self.base.sources.values(), key=lambda v: v["sha256"]), "tasks": report["tasks"]})
            report["status"] = "ready_pending_execution_confirmation"
        except Exception as exc:
            report["issues"].append(str(exc))
        return report


def review(request, context, root):
    return RuntimeReview(request, context, root).run()


def publish(directory, files, marker, max_bytes, readonly_root, before_marker=None):
    """New directory only; marker written last. An interrupted directory is never a completed package."""
    marker_bytes = products.json_bytes(marker)
    if sum(map(len, files.values())) + len(marker_bytes) > max_bytes:
        raise ValueError("Actual artifact-byte budget exceeded; no output published.")
    target = safe_new_path(directory, readonly_root)
    target.mkdir(mode=0o700)
    for name, raw in files.items():
        relative = Path(name)
        if relative.is_absolute() or any(p in ("..", ".") for p in relative.parts):
            raise ValueError("Invalid generated output path.")
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    if before_marker is not None:
        before_marker()
    for name, raw in files.items():
        with pf.scoped_open(target, name) as handle:
            if hashlib.sha256(handle.read(len(raw)+1)).digest() != hashlib.sha256(raw).digest():
                raise ValueError("Output changed before completion marker publication.")
    with (target / "package-manifest.json").open("xb") as handle:
        handle.write(marker_bytes)


def external_source(ref, state):
    item = state.base.sources.get(ref["sha256"])
    if item is None:
        raise ValueError("Cannot publish an unverified upstream source as available.")
    return {"location": {"kind": "external_reference", "path": str(state.root/item["path"])},
            "sha256": ref["sha256"], "availability": "available"}


def run(request, context, root, receipt):
    state = RuntimeReview(request, context, root); report = state.run()
    require_receipt(report, receipt); state.recheck()
    run_id = str(uuid.uuid4()); files = {}; views = {}; results = []; details = {}
    rp = request["payload"]; saved = rp["resources"]["persistence"] == "saved"
    files["request.json"] = products.json_bytes(request)
    bound_inputs = [v["input"] for v in state.states]
    for index, item in enumerate(state.states):
        task = item["task"]; inp = item["input"]["payload"]; tid = task["task_id"]
        try:
            output = core.execute(task, inp, item["waveform"], item["prepared"], item["alpha"])
            public = products.public_task(task, inp, output)
            from jsonschema import Draft202012Validator
            extension_schema = registry.descriptor(task["detector"]["detector_id"])["payload"]["result_definition"]["extension_schema"]
            for candidate in public["candidates"]:
                Draft202012Validator(extension_schema).validate(candidate["extensions"])
            generated = products.build_products(task, inp, output, public)
            details[tid] = products.minimum_ledger(output)
            for name in task["products"]["compute"]:
                entries = generated[name]; prefix = f"task-{index:06d}/{name}/"
                index_bytes = products.json_bytes({"product_id": name, "task_id": tid,
                    "files": [{"name": k, "sha256": hashlib.sha256(v).hexdigest(), "size_bytes": len(v)} for k, v in entries.items()]})
                if name in task["products"]["save"]:
                    files.update({prefix+k: v for k, v in entries.items()}); files[prefix+"product.json"] = index_bytes
                    ref = products.reference(prefix+"product.json", index_bytes); status = "saved"
                elif name in task["products"]["view"]:
                    ref = products.reference(f"session:{run_id}/{prefix}product.json", index_bytes, saved=False)
                    status = "temporary_available"
                else:
                    ref = None; status = "not_retained"
                if name in task["products"]["view"]:
                    views[f"{index}:{name}"] = entries
                artifact = products.artifact(task, inp, name, ref, status)
                artifact["provenance_refs"] = [external_source(ref, state) for ref in artifact["provenance_refs"]]
                public["artifacts"].append(artifact)
            results.append(public)
        except Exception as exc:
            if rp["batch_failure_policy"] == "stop_batch":
                raise
            results.append({"task_id": tid, "input_ref": task["input_ref"], "detector": task["detector"],
                "execution_status": "failed", "reason": str(exc), "coverage": {"requested": task["scope"], "processed": [],
                    "excluded": [{"interval": v, "reason": "Task failed; no completed detection coverage."} for v in task["scope"]["sample_intervals"]]},
                "candidates": None, "limitations": ["Failure is not zero candidates."], "diagnostics": [],
                "artifacts": [], "quality": products.quality()})
    config = {"runtime_version": VERSION, "run_id": run_id, "request": request, "context": context,
        "source_root": str(state.root), "input_documents": bound_inputs, "execution_receipt": receipt,
        "runtime_review": report, "detection_evidence": details,
        "source_bindings": sorted(state.base.sources.values(), key=lambda v: v["sha256"])}
    files["resolved-configuration.json"] = products.json_bytes(config)
    import detection_associations
    association = detection_associations.build(run_id, results, bound_inputs, "saved" if saved else "session")
    association["payload"]["evidence_refs"] = [external_source(ref, state) for ref in association["payload"]["evidence_refs"]]
    for entity in association["payload"]["entities"]:
        if entity["evidence_ref"] is not None and entity["kind"] != "artifact":
            entity["evidence_ref"] = external_source(entity["evidence_ref"], state)
    require_contract(association, "AssociationRecord")
    files["association.json"] = products.json_bytes(association)
    result = registry.envelope("DetectionResult", {"run_id": run_id,
        "request_ref": products.reference("request.json", files["request.json"], saved=saved),
        "resolved_configuration": products.reference("resolved-configuration.json", files["resolved-configuration.json"], saved=saved),
        "task_results": results, "delivery_status": "completed" if all(t["execution_status"] == "completed" for t in results) else "partial",
        "association_ref": products.reference("association.json", files["association.json"], saved=saved),
        "validation": {"structure_summary": "Contract checked; numerical execution is separate from quality acceptance.",
                       "quality": products.quality()}})
    require_contract(result, "DetectionResult")
    files["detection-result.json"] = products.json_bytes(result)
    marker = {"package_version": VERSION, "kind": "line_spectrum_detection", "run_id": run_id,
        "status": result["payload"]["delivery_status"], "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest(),
            "size_bytes": len(v)} for k, v in files.items()]}
    total = sum(map(len, files.values())) + len(products.json_bytes(marker))
    total += sum(len(raw) for entries in views.values() for raw in entries.values())
    if total > rp["resources"]["max_artifact_bytes"]:
        raise ValueError("Generated saved/session artifacts exceed explicit byte budget; no publication.")
    state.recheck()
    if saved:
        publish(rp["resources"]["output_directory"], files, marker, rp["resources"]["max_artifact_bytes"], state.root, state.recheck)
    return {"result": result, "association": association, "files": files if not saved else {}, "views": views,
            "output_directory": rp["resources"]["output_directory"], "authority_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["review", "confirm", "run"])
    parser.add_argument("request"); parser.add_argument("context"); parser.add_argument("--source-root", required=True)
    parser.add_argument("--evidence"); parser.add_argument("--receipt"); parser.add_argument("--receipt-output")
    args = parser.parse_args()
    req = pf.explicit_json(args.request); ctx = pf.explicit_json(args.context)
    if args.action == "review":
        answer = review(req, ctx, args.source_root)
    elif args.action == "confirm":
        if not args.evidence or not args.receipt_output:
            parser.error("confirm requires --evidence and --receipt-output")
        answer = confirm(review(req, ctx, args.source_root), pf.explicit_json(args.evidence))
        target = safe_new_path(args.receipt_output, args.source_root)
        with target.open("xb") as handle:
            handle.write(products.json_bytes(answer))
    else:
        if not args.receipt:
            parser.error("run requires --receipt")
        answer = run(req, ctx, args.source_root, pf.explicit_json(args.receipt))
        answer = {k: v for k, v in answer.items() if k not in ("files", "views")}
        answer["session_products_lifecycle"] = "Not retained after this CLI process; use Python API for in-process viewing."
    print(json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False))
    if answer.get("status") == "blocked" or answer.get("result", {}).get("payload", {}).get("delivery_status") == "partial":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"execution_status": "blocked_or_failed", "error": str(exc), "success": False}, ensure_ascii=False))
        sys.exit(2)
