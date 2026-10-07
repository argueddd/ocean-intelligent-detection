"""Bounded bidirectional provenance, existing-evidence views, and confirmed one-shot follow-ups."""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import cfar_registry as registry
import detection_products as products
import preflight as pf


def build(run_id, task_results, input_documents, persistence):
    entities = {}; relations = []; mapping = []; evidence = {}
    def entity(kind, identity, ref=None):
        eid = kind + ":" + pf.digest(identity)
        entities[eid] = {"entity_id": eid, "kind": kind, "namespace": "line-spectrum-v1",
                         "identity": identity, "evidence_ref": ref}
        return eid
    def link(a, b, kind, basis):
        value = {"from_entity": a, "to_entity": b, "kind": kind, "basis": basis}
        if value not in relations:
            relations.append(value)
    run = entity("run", {"run_id": run_id})
    inputs = {(d["payload"]["source_package"]["manifest"]["sha256"], d["payload"]["signal_id"]): d["payload"] for d in input_documents}
    for task in task_results:
        p = inputs[(task["input_ref"]["package_sha256"], task["input_ref"]["signal_id"])]
        source = p["source_package"]["manifest"]; evidence[source["sha256"]] = source
        signal = entity("signal", task["input_ref"], source)
        t = entity("task", {"run_id": run_id, "task_id": task["task_id"]})
        link(t, run, "derived_from", "Task belongs to this new detection run.")
        link(t, signal, "sourced_from", "Exact handoff hash and explicit signal_id.")
        beam = p["beam_source"]
        if beam["status"] == "applicable" and beam.get("source_result") is not None:
            ref = beam["source_result"]; evidence[ref["sha256"]] = ref
            r = entity("source_result", {"result_sha256": ref["sha256"]}, ref)
            if beam["beam_id"]["status"] == "known" and beam["beamformer_algorithm"]["status"] == "known":
                b = entity("beam", {"result_sha256": ref["sha256"], "beamformer_algorithm": beam["beamformer_algorithm"]["value"],
                    "beam_id": beam["beam_id"]["value"]}, ref)
                link(signal, b, "sourced_from", "Validated upstream beam identity, not angle/name matching.")
                link(b, r, "sourced_from", "Exact upstream result SHA256.")
        mapping.append({"entity_ids": [signal, t], "status": "known",
            "definition": json.dumps({"scope": task["coverage"]["requested"], "processed": task["coverage"]["processed"],
                "time_mapping": p["time_mapping"], "sample_rate_hz": p["sample_rate_hz"], "beam_source": beam}, ensure_ascii=False),
            "evidence": "Validated SignalInput plus executed task coverage; unknown beam fields remain unknown."})
        for candidate in task["candidates"] or []:
            c = entity("candidate", {"run_id": run_id, "task_id": task["task_id"], "candidate_id": candidate["candidate_id"]})
            link(c, t, "derived_from", "Actual candidate of this detection task; not a same-target relation.")
        for artifact in task["artifacts"]:
            a = entity("artifact", {"run_id": run_id, "task_id": task["task_id"], "product_id": artifact["product_id"]}, artifact["file_ref"])
            link(a, t, "derived_from", "Product availability/lifecycle is declared by the detection result.")
    return registry.envelope("AssociationRecord", {"record_id": "association:"+run_id,
        "entities": list(entities.values()), "relations": relations, "scope_mapping": mapping,
        "evidence_refs": list(evidence.values()), "persistence": persistence, "comparisons": [], "followups": []})


def query(records, kind, identity, direction):
    """Search only supplied records; follow source/derived edges in the requested direction."""
    import detection_runtime as runtime
    if direction not in ("ancestors", "descendants"):
        raise ValueError("Choose ancestors or descendants explicitly.")
    entities, edges = {}, []
    for doc in records:
        runtime.require_contract(doc, "AssociationRecord")
        for entity in doc["payload"]["entities"]:
            eid = entity["entity_id"]
            if eid in entities and (entities[eid]["kind"], entities[eid]["identity"]) != (entity["kind"], entity["identity"]):
                raise ValueError("Conflicting identities in the explicitly supplied index scope.")
            entities[eid] = entity
        edges += [v for v in doc["payload"]["relations"] if v["kind"] in ("sourced_from", "derived_from", "followup_of")]
    roots = {k for k, v in entities.items() if v["kind"] == kind and v["identity"] == identity}
    reached = set(roots); frontier = list(roots)
    while frontier:
        node = frontier.pop()
        for edge in edges:
            start, end = edge["from_entity"], edge["to_entity"]
            if direction == "descendants":
                start, end = end, start
            if start == node and end not in reached:
                reached.add(end); frontier.append(end)
    return {"scope": "explicitly_supplied_records_only", "matched_roots": sorted(roots),
            "entities": [entities[k] for k in sorted(reached)],
            "relations": [v for v in edges if v["from_entity"] in reached and v["to_entity"] in reached]}


class Reader:
    def __init__(self, root, maximum):
        if type(maximum) is not int or maximum < 1:
            raise ValueError("Explicit positive read-byte budget required.")
        self.root = Path(root).resolve(strict=True); self.remaining = maximum; self.cache = {}

    def read(self, path, sha, size=None):
        key = (path, sha)
        if key in self.cache:
            return self.cache[key]
        with pf.scoped_open(self.root, path) as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > self.remaining or (size is not None and before.st_size != size):
                raise ValueError("Existing artifact exceeds byte budget or declared size.")
            raw = handle.read(before.st_size + 1)
            if pf.signature(before) != pf.signature(os.fstat(handle.fileno())):
                raise ValueError("Source changed during read.")
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Existing artifact SHA256 mismatch.")
        self.remaining -= len(raw); self.cache[key] = raw
        return raw


def load_package(selection, maximum):
    import detection_runtime as runtime
    reader = Reader(selection["directory"], maximum)
    marker = pf.parse_json(reader.read("package-manifest.json", selection["manifest_sha256"]))
    if marker.get("kind") != "line_spectrum_detection" or marker.get("status") not in ("completed", "partial"):
        raise ValueError("Only completed/explicitly partial detection packages, not interrupted folders.")
    entries = {v["path"]: v for v in marker["files"]}
    if len(entries) != len(marker["files"]):
        raise ValueError("Duplicate artifact identities in package manifest.")
    def document(name, kind=None):
        ref = entries[name]; obj = pf.parse_json(reader.read(name, ref["sha256"], ref["size_bytes"]))
        if kind:
            runtime.require_contract(obj, kind)
        return obj
    result = document("detection-result.json", "DetectionResult")
    config = document("resolved-configuration.json")
    request = document("request.json", "DetectionRequest")
    if config["request"] != request:
        raise ValueError("Resolved configuration differs from the original request.")
    association = document("association.json", "AssociationRecord")
    for key, name in (("resolved_configuration", "resolved-configuration.json"), ("association_ref", "association.json"),
                      ("request_ref", "request.json")):
        if result["payload"][key]["sha256"] != entries[name]["sha256"]:
            raise ValueError("Detection result and package manifest refer to different evidence.")
    if result["payload"]["run_id"] != config["run_id"] or marker["run_id"] != config["run_id"]:
        raise ValueError("Detection run identity mismatch.")
    return reader, entries, result, config, association


def beam_evidence(selection, maximum):
    """Read explicitly selected native beam products. Do not generate missing spectra or select a beam."""
    expected = {"result_path", "result_sha256", "algorithm", "beam_ids", "products", "plot_products",
                "frequency_range_hz", "time_range_seconds", "display"}
    if set(selection) != expected or not set(selection["plot_products"]) <= set(selection["products"]):
        raise ValueError("Explicit beam products, plot selection, native ranges (null=full) and display choice required.")
    if bool(selection["plot_products"]) != (selection["display"] is not None):
        raise ValueError("Display is required exactly when existing beam plots are selected.")
    path = Path(selection["result_path"])
    reader = Reader(path.parent, maximum)
    meta = pf.parse_json(reader.read(path.name, selection["result_sha256"]))
    if meta.get("execution_version") != "0.4" or meta.get("execution_status") != "completed":
        raise ValueError("Unsupported/incomplete upstream beam result.")
    spectral = meta.get("spectral_products")
    if spectral is None:
        raise ValueError("No existing spectral products; propose a confirmed follow-up instead of computing silently.")
    entries = {v["path"]: v for v in meta["artifacts"]}
    if len(entries) != len(meta["artifacts"]):
        raise ValueError("Duplicate upstream artifact paths.")
    beams = meta.get("spectral_beams", meta["scan_beams"])
    field = "spectral_column" if "spectral_beams" in meta else "scan_column"
    ids = selection["beam_ids"]
    if not ids or len(ids) != len(set(ids)) or not selection["products"]:
        raise ValueError("Select exact nonempty beam IDs and existing product types.")
    chosen = []
    for bid in ids:
        matches = [b for b in beams if b["beam_id"] == bid]
        if len(matches) != 1:
            raise ValueError("Requested beam has no unique existing spectral column.")
        chosen.append(matches[0])
    def array(name):
        ref = entries[name]; raw = reader.read(name, ref["sha256"], ref["size_bytes"])
        buffer = io.BytesIO(raw)
        version = np.lib.format.read_magic(buffer)
        if version not in ((1, 0), (2, 0)):
            raise ValueError("Only bounded NPY 1.0/2.0 native arrays are supported.")
        header = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        shape, fortran, dtype = header(buffer, max_header_size=65536)
        if len(shape) not in (1, 2, 3) or dtype.hasobject or dtype.kind not in "fiu" or any(v < 1 for v in shape):
            raise ValueError("Unsupported native array shape/type.")
        if math.prod(shape)*dtype.itemsize != len(raw)-buffer.tell():
            raise ValueError("Native NPY header/data size mismatch; no oversized allocation.")
        value = np.load(io.BytesIO(raw), allow_pickle=False, max_header_size=65536)
        if value.dtype.kind not in "fiu" or not np.all(np.isfinite(value)):
            raise ValueError("Invalid existing numeric product.")
        return value
    columns = [b[field] for b in chosen]
    values = {}
    for product in selection["products"]:
        if product not in ("psd", "time_frequency", "frequency_angle", "btr", "scan_power"):
            raise ValueError("Unsupported existing beam product selection.")
        entry = spectral["per_algorithm"][selection["algorithm"]].get(product)
        if entry is None:
            raise ValueError("Requested beam product absent; no automatic recomputation.")
        data = array(entry["path"])
        if len(entry["axes"]) != data.ndim or entry["axes"][-1] not in ("scan_beam", "spectral_beam") or data.shape[-1] != len(beams):
            raise ValueError("Beam product axes/columns mismatch; do not confuse saved/scan/spectral columns.")
        values[product] = data[..., columns]
    frequencies = array("analysis_frequency_hz.npy")
    times = array("analysis_time_seconds.npy")
    starts = array("analysis_frame_start_sample.npy")
    if frequencies.ndim != 1 or times.ndim != 1 or starts.shape != times.shape or np.any(np.diff(frequencies) <= 0):
        raise ValueError("Invalid native spectral coordinates.")
    for product, value in values.items():
        expected = {"psd": (len(frequencies), len(columns)), "frequency_angle": (len(frequencies), len(columns)),
            "time_frequency": (len(times), len(frequencies), len(columns)), "btr": (len(times), len(columns)),
            "scan_power": (len(columns),)}[product]
        if value.shape != expected:
            raise ValueError("Native coordinate length differs from product axes.")
    def selection_mask(coordinates, bounds, name):
        if bounds is None:
            return np.ones(len(coordinates), dtype=bool)
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(type(v) in (int, float) and np.isfinite(v) for v in bounds):
            raise ValueError("Explicit finite native range required: "+name)
        if not coordinates[0] <= bounds[0] < bounds[1] <= coordinates[-1]:
            raise ValueError("Requested native range is outside saved coverage; no silent intersection.")
        mask = (coordinates >= bounds[0]) & (coordinates <= bounds[1])
        if not np.any(mask):
            raise ValueError("No native coordinates in selected range.")
        return mask
    fm = selection_mask(frequencies, selection["frequency_range_hz"], "frequency")
    tm = selection_mask(times, selection["time_range_seconds"], "time")
    for product, value in values.items():
        if product in ("psd", "frequency_angle"):
            values[product] = value[fm]
        elif product == "time_frequency":
            values[product] = value[tm][:, fm]
        elif product == "btr":
            values[product] = value[tm]
    if selection["time_range_seconds"] is not None and any(p in values for p in ("psd", "frequency_angle", "scan_power")):
        raise ValueError("Saved time-averaged products cannot be narrowed to a new time interval without recomputation.")
    if selection["frequency_range_hz"] is not None and any(p in values for p in ("btr", "scan_power")):
        raise ValueError("Saved band-integrated products cannot be narrowed to a new band without recomputation.")
    return {"metadata": meta, "selected_beams": chosen, "values": values,
            "frequency_hz": frequencies[fm], "time_seconds": times[tm], "frame_start_sample": starts[tm],
            "selection": selection, "read_bytes": maximum-reader.remaining}


def joint_view(config):
    """Existing-evidence joint view, numeric lookup only at exact existing frequency bins."""
    import detection_runtime as runtime
    keys = {"view_version", "detections", "beams", "alignment_rule", "max_read_bytes", "max_artifact_bytes", "output_directory"}
    if set(config) != keys or config["view_version"] != "1.0.0" or config["alignment_rule"] != "native_coordinates_exact_bin_lookup_no_interpolation":
        raise ValueError("Explicit native-coordinate joint-view configuration required.")
    if not config["detections"]:
        raise ValueError("Select detection packages/tasks explicitly.")
    selections = []; rendered = []; associations = []; consumed = 0
    for selection in config["detections"]:
        reader, entries, result, actual, assoc = load_package(selection, config["max_read_bytes"]-consumed)
        associations.append(assoc)
        wanted = selection["task_ids"]
        if not wanted or len(set(wanted)) != len(wanted):
            raise ValueError("Explicit unique task IDs required, not all/first by default.")
        for tid in wanted:
            tasks = [v for v in result["payload"]["task_results"] if v["task_id"] == tid]
            if len(tasks) != 1 or tasks[0]["execution_status"] != "completed":
                raise ValueError("Selected task is absent or not completed.")
            task = tasks[0]
            params = next(t for t in actual["request"]["payload"]["tasks"] if t["task_id"] == tid)
            docs = [d["payload"] for d in actual["input_documents"] if d["payload"]["signal_id"] == task["input_ref"]["signal_id"]
                    and d["payload"]["source_package"]["manifest"]["sha256"] == task["input_ref"]["package_sha256"]]
            inp = docs[0]
            chosen_products = selection["product_ids"]
            for pid in chosen_products:
                artifacts = [a for a in task["artifacts"] if a["product_id"] == pid and a["status"] == "saved"]
                if len(artifacts) != 1:
                    raise ValueError("Requested detection view product was not saved; no automatic recomputation.")
                ref = artifacts[0]["file_ref"]; path = ref["location"]["path"]
                product_index = pf.parse_json(reader.read(path, ref["sha256"]))
                for entry in product_index["files"]:
                    name = (Path(path).parent / entry["name"]).as_posix()
                    if name not in entries or entries[name]["sha256"] != entry["sha256"]:
                        raise ValueError("Product index differs from package manifest.")
                    raw = reader.read(name, entry["sha256"], entry["size_bytes"])
                    if name.endswith(".png"):
                        rendered.append((f"{result['payload']['run_id']} / {tid} / {name}", raw))
            selections.append({"run_id": result["payload"]["run_id"], "task": task, "input": inp, "request_task": params})
        consumed += sum(map(len, reader.cache.values()))
    beam_data = []
    for selection in config["beams"]:
        data = beam_evidence(selection, config["max_read_bytes"]-consumed)
        # Reserve actual arrays and metadata under the same supplied limit conservatively.
        consumed += data["read_bytes"]
        beam_data.append(data)
        for name, raw in products.render_beam_context(data).items():
            rendered.append((selection["algorithm"]+" / existing beam evidence / "+name, raw))
    comparisons = []
    for i, a in enumerate(selections):
        for b in selections[i+1:]:
            fields = {"input_identity": (a["task"]["input_ref"], b["task"]["input_ref"]),
                "scope": (a["task"]["coverage"]["requested"], b["task"]["coverage"]["requested"]),
                "processed_coverage": (a["task"]["coverage"]["processed"], b["task"]["coverage"]["processed"]),
                "units": (a["input"]["units"], b["input"]["units"]),
                "sample_rate": (a["input"]["sample_rate_hz"], b["input"]["sample_rate_hz"]),
                "parameters": (a["request_task"]["resolved_parameters"], b["request_task"]["resolved_parameters"])}
            differences = [k for k, (left, right) in fields.items() if left != right]
            comparisons.append({"left": [a["run_id"], a["task"]["task_id"]], "right": [b["run_id"], b["task"]["task_id"]],
                "different_conditions": differences, "numeric_alignment": "native only, no aggregate performance comparison",
                "independence": "Not established; shared data/CBF/MVDR are not independent truth."})
    lookups = []
    for selected in selections:
        source = selected["input"]["beam_source"]
        if source["status"] != "applicable" or source.get("source_result") is None:
            continue
        for beam in beam_data:
            meta = beam["metadata"]
            original_sha = meta.get("source_result", {}).get("sha256", beam["selection"]["result_sha256"])
            if original_sha != source["source_result"]["sha256"]:
                continue
            if source["beamformer_algorithm"]["value"] != beam["selection"]["algorithm"]:
                continue
            ids = [b["beam_id"] for b in beam["selected_beams"]]
            if source["beam_id"]["value"] not in ids:
                continue
            col = ids.index(source["beam_id"]["value"])
            for candidate in selected["task"]["candidates"]:
                indices = np.flatnonzero(beam["frequency_hz"] == candidate["frequency"]["value_hz"])
                row = {"run_id": selected["run_id"], "candidate_id": candidate["candidate_id"],
                    "beam_id": source["beam_id"]["value"], "frequency_hz": candidate["frequency"]["value_hz"],
                    "frequency_alignment": "exact_bin" if len(indices) == 1 else "no_exact_bin_no_lookup",
                    "mean_psd_context": None,
                    "limitation": "Mean PSD is time-averaged context, not instantaneous line evidence; BTR is band-integrated."}
                name = "psd" if "psd" in beam["values"] else "frequency_angle"
                if len(indices) == 1 and name in beam["values"]:
                    row["mean_psd_context"] = float(beam["values"][name][int(indices[0]), col])
                lookups.append(row)
    summary = {"view_version": "1.0.0", "source_selections": config, "detections": selections,
        "comparisons": comparisons, "beam_context": [{"selection": b["selection"], "selected_beams": b["selected_beams"],
            "frequency_hz": b["frequency_hz"].tolist(), "time_seconds": b["time_seconds"].tolist(),
            "products": {k: v.tolist() for k, v in b["values"].items()}, "definition": b["metadata"]["spectral_products"]["definition"]} for b in beam_data],
        "exact_source_lookups": lookups, "read_bytes": consumed, "limitations": ["Existing data only: no beamforming, PSD estimation, CFAR or target decisions executed.",
            "Different native grids are not interpolated; unknown units/directions remain unknown."]}
    import base64
    text = "<!doctype html><meta charset='utf-8'><title>Linked evidence</title><h1>Detection and beam evidence</h1>"
    text += "<p>Existing evidence only. Same-source agreement is not independent truth. Native grids retained.</p>"
    for title, raw in rendered:
        text += "<h2>"+html.escape(title)+"</h2><img style='max-width:100%' src='data:image/png;base64,"+base64.b64encode(raw).decode()+"'>"
    text += "<pre>"+html.escape(json.dumps(summary, ensure_ascii=False, indent=2))+"</pre>"
    files = {"joint-view.json": products.json_bytes(summary), "joint-view.html": text.encode()}
    if sum(map(len, files.values())) > config["max_artifact_bytes"]:
        raise ValueError("Joint-view artifact budget exceeded; nothing saved.")
    if config["output_directory"] is not None:
        marker = {"kind": "line_spectrum_joint_view", "status": "completed", "files": [
            {"path": k, "sha256": hashlib.sha256(v).hexdigest(), "size_bytes": len(v)} for k, v in files.items()]}
        runtime.publish(config["output_directory"], files, marker, config["max_artifact_bytes"], None)
    return {"summary": summary, "files": files, "output_directory": config["output_directory"]}


def read_bound(ref):
    path = Path(ref["path"])
    if not path.is_absolute():
        raise ValueError("Follow-up document paths must be explicit absolute paths.")
    reader = Reader(path.parent, 1048576)
    return pf.parse_json(reader.read(path.name, ref["sha256"]))


def beam_call(action, config, base, timeout, execute=False):
    if action not in ("beam_execute", "beam_products") or type(timeout) is not int or timeout < 1:
        raise ValueError("Unknown beam operation or missing explicit process timeout.")
    beam = Path(__file__).resolve().parents[2] / "underwater-beamforming" / "scripts"
    module = "execute" if action == "beam_execute" else "analyze_results"
    if not (beam / (module + ".py")).is_file():
        raise ValueError("Required sibling beamforming executor is missing; no auto install/fallback.")
    bridge = ("import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
              f"import {module} as m; p=json.load(sys.stdin); "
              f"r=m.{'execute' if execute else 'check'}(p['config'],Path(p['base'])); "
              "print(json.dumps(r,ensure_ascii=False,allow_nan=False))")
    result = subprocess.run([sys.executable, "-B", "-c", bridge, str(beam)],
        input=json.dumps({"config": config, "base": str(base)}, allow_nan=False),
        text=True, capture_output=True, timeout=timeout, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode:
        raise ValueError("Responsible beam module blocked/failed: " + result.stderr[-4000:] + result.stdout[-4000:])
    return pf.parse_json(result.stdout.encode())



def parent_scope(association, followup):
    """Only supplied, hash-verified completed result identities may parent a follow-up."""
    import detection_runtime as runtime
    ids = []; directories = []
    for ref in followup["parent_refs"]:
        location = ref["location"]
        if location["kind"] != "external_reference" or not Path(location["path"]).is_absolute():
            raise ValueError("Follow-up parent results require explicit absolute external references.")
        parent = read_bound({"path": location["path"], "sha256": ref["sha256"]})
        if parent.get("record_type") == "DetectionResult":
            runtime.require_contract(parent, "DetectionResult")
            if parent["payload"]["delivery_status"] not in ("completed", "partial"):
                raise ValueError("Parent detection result is not published.")
            kind = "run"; identity = {"run_id": parent["payload"]["run_id"]}
        elif parent.get("execution_version") == "0.4" and parent.get("execution_status") == "completed":
            kind = "source_result"; identity = {"result_sha256": ref["sha256"]}
        else:
            raise ValueError("Parent must be a completed detection/beam result; identify specific candidates in question/reason.")
        matches = [e for e in association["payload"]["entities"] if e["kind"] == kind and e["identity"] == identity]
        if len(matches) != 1:
            raise ValueError("Parent result is not uniquely registered in this association.")
        ids.append(matches[0]["entity_id"]); directories.append(Path(location["path"]).resolve().parent)
    return sorted(set(ids)), directories


def review_followup(config):
    import detection_runtime as runtime
    keys = {"followup_version", "association_ref", "followup_id", "action", "config_ref", "context_ref",
            "source_root", "child_receipt_ref", "max_process_seconds", "result_record_path"}
    if set(config) != keys or config["followup_version"] != "1.0.0":
        raise ValueError("Complete explicit one-shot follow-up configuration required.")
    assoc = read_bound(config["association_ref"]); runtime.require_contract(assoc, "AssociationRecord")
    matches = [v for v in assoc["payload"]["followups"] if v["followup_id"] == config["followup_id"]]
    if len(matches) != 1:
        raise ValueError("Follow-up not uniquely present in explicit parent association.")
    followup = matches[0]
    if followup["status"] not in ("proposed", "pending", "confirmed") or followup["unresolved_items"] or any(
            v["status"] != "available" for v in followup["dependencies"]):
        raise ValueError("Follow-up remains blocked/unresolved or has already run; no automatic retry.")
    expected_parameters = {"action": config["action"], "config_sha256": config["config_ref"]["sha256"],
        "context_sha256": config["context_ref"]["sha256"] if config["context_ref"] else None,
        "source_root": config["source_root"]}
    if followup["parameters"] != expected_parameters or followup["scope"] != {"configuration_sha256": config["config_ref"]["sha256"]}:
        raise ValueError("Follow-up plan does not bind the exact child configuration/scope.")
    parent_ids, parent_directories = parent_scope(assoc, followup)
    child = read_bound(config["config_ref"])
    if followup["resource_and_output_plan"] != child_delivery_plan(config["action"], child):
        raise ValueError("Follow-up resource/output summary differs from its exact child configuration.")
    if config["action"] == "detection":
        if config["max_process_seconds"] is not None:
            raise ValueError("Detection follow-up is in-process; max_process_seconds must be null, not an ignored timeout.")
        if followup["responsible_module"] != "line_spectrum" or config["context_ref"] is None or config["child_receipt_ref"] is None:
            raise ValueError("Detection follow-up requires matching module, context and child execution receipt.")
        if child["payload"]["resources"]["persistence"] != "saved":
            raise ValueError("Cross-process follow-up requires explicit saved child output before execution.")
        ctx = read_bound(config["context_ref"])
        report = runtime.review(child, ctx, config["source_root"])
        runtime.require_receipt(report, read_bound(config["child_receipt_ref"]))
        ready = report["status"] == "ready_pending_execution_confirmation"
    elif config["action"] in ("beam_execute", "beam_products"):
        if config["source_root"] is not None:
            raise ValueError("Beam follow-up uses its own bound configuration paths; source_root must be null.")
        if followup["responsible_module"] != "beamforming" or config["context_ref"] is not None or config["child_receipt_ref"] is not None:
            raise ValueError("Beam follow-up must use beamforming's own confirmed config; no unused context/receipt.")
        report = beam_call(config["action"], child, Path(config["config_ref"]["path"]).parent, config["max_process_seconds"])
        ready = report.get("can_attempt_execution", False)
    else:
        raise ValueError("Only detection, beam_execute or beam_products follow-up actions are registered.")
    folder = child_delivery_plan(config["action"], child)["resources"]["output_directory"]
    folder = Path(folder)
    if not folder.is_absolute():
        folder = Path(config["config_ref"]["path"]).parent/folder
    protected = parent_directories + ([Path(config["source_root"]).resolve()] if config["source_root"] else [])
    for output in [folder, Path(config["result_record_path"])]:
        if any(output.resolve().is_relative_to(parent) for parent in protected):
            raise ValueError("Follow-up outputs must not be placed inside read-only input or parent-result packages.")
    for suffix in ("", ".receipt.json", ".association.json"):
        runtime.safe_new_path(config["result_record_path"]+suffix)
    return {"operation": "followup", "status": "ready_pending_execution_confirmation" if ready else "blocked",
        "plan_sha256": pf.digest({"config": config, "child_review": report, "implementation": registry.implementation_digest()}),
        "child_review": report, "parent_entity_ids": parent_ids, "authority_verified": False, "can_execute": False}


def child_delivery_plan(action, child):
    if action == "detection":
        resources = child["payload"]["resources"]
        products_ = {key: sorted(set(v for t in child["payload"]["tasks"] for v in t["products"][key]))
                     for key in ("compute", "view", "save")}
    elif action in ("beam_execute", "beam_products"):
        caps = child["numerics"] if action == "beam_execute" else child
        folder = child["plan"]["output"]["directory"] if action == "beam_execute" else child["output_directory"]
        resources = {"max_working_bytes": caps["max_working_bytes"], "max_artifact_bytes": caps["max_artifact_bytes"],
            "persistence": "saved", "output_directory": folder, "temporary_storage_policy": "responsible_module_managed"}
        output = child["plan"]["output"] if action == "beam_execute" else child
        auxiliary = list(output["auxiliary_products"])
        time = output["save_time_domain"] if action == "beam_execute" else bool(child["time_domain_beam_ids"])
        names = auxiliary+(["time_domain"] if time else [])
        products_ = {"compute": names, "view": auxiliary, "save": names}
    else:
        raise ValueError("Unregistered follow-up action.")
    return {"resources": copy.deepcopy(resources), "products": products_}


def propose_followup(association, *, followup_id, parent_refs, question, reason, action,
                     config_ref, context_ref, source_root, dependencies):
    import detection_runtime as runtime
    runtime.require_contract(association, "AssociationRecord")
    child = read_bound(config_ref)
    if any(v["followup_id"] == followup_id for v in association["payload"]["followups"]):
        raise ValueError("Follow-up ID already exists; do not overwrite an old proposal.")
    result = copy.deepcopy(association)
    result["payload"]["record_id"] += ":proposal:"+followup_id
    result["payload"]["followups"].append({
        "followup_id": followup_id, "parent_refs": parent_refs, "question": question, "reason": reason,
        "responsible_module": "line_spectrum" if action == "detection" else "beamforming",
        "requested_action": action, "scope": {"configuration_sha256": config_ref["sha256"]},
        "dependencies": dependencies, "parameters": {"action": action, "config_sha256": config_ref["sha256"],
            "context_sha256": context_ref["sha256"] if context_ref else None, "source_root": source_root},
        "unresolved_items": [], "resource_and_output_plan": child_delivery_plan(action, child),
        "approval": {"status": "pending", "bound_plan_sha256": None, "evidence_refs": []},
        "status": "pending", "result_refs": []})
    runtime.require_contract(result, "AssociationRecord")
    return result


def run_followup(config, receipt):
    import detection_runtime as runtime
    report = review_followup(config); runtime.require_receipt(report, receipt)
    child = read_bound(config["config_ref"])
    target = runtime.safe_new_path(config["result_record_path"])
    association = read_bound(config["association_ref"])
    receipt_path = runtime.safe_new_path(str(target)+".receipt.json")
    association_path = runtime.safe_new_path(str(target)+".association.json")
    receipt_raw = products.json_bytes(receipt)
    receipt_ref = {"location": {"kind": "external_reference", "path": str(receipt_path)},
                   "sha256": hashlib.sha256(receipt_raw).hexdigest(), "availability": "available"}
    # Reserve a new execution log; a killed process leaves an incomplete log, never a completed result.
    with target.open("xb") as handle:
        with receipt_path.open("xb") as receipt_file:
            receipt_file.write(receipt_raw)
        record = {"followup_version": "1.0.0", "config": config, "execution_receipt": receipt,
                  "status": "running", "result_refs": [], "error": None, "association_ref": None}
        child_document = None
        try:
            if config["action"] == "detection":
                answer = runtime.run(child, read_bound(config["context_ref"]), config["source_root"], read_bound(config["child_receipt_ref"]))
                path = Path(answer["output_directory"]) / "detection-result.json"
            else:
                beam_call(config["action"], child, Path(config["config_ref"]["path"]).parent, config["max_process_seconds"], execute=True)
                folder = child["plan"]["output"]["directory"] if config["action"] == "beam_execute" else child["output_directory"]
                path = Path(folder)
                if not path.is_absolute():
                    path = Path(config["config_ref"]["path"]).parent / path
                path = path / "result.json"
            raw = path.read_bytes(); child_document = pf.parse_json(raw)
            record["result_refs"] = [{"location": {"kind": "external_reference", "path": str(path)},
                                      "sha256": hashlib.sha256(raw).hexdigest(), "availability": "available"}]
            if config["action"] == "detection" and child_document["payload"]["delivery_status"] != "completed":
                raise ValueError("Child detection completed only partially; inspect its own task failures.")
            record["status"] = "completed"
        except Exception as exc:
            record["status"] = "failed"; record["error"] = str(exc)
        association["payload"]["record_id"] += ":executed:"+config["followup_id"]
        entry = next(v for v in association["payload"]["followups"] if v["followup_id"] == config["followup_id"])
        entry.update(status=record["status"], result_refs=record["result_refs"],
            approval={"status": "confirmed", "bound_plan_sha256": report["plan_sha256"], "evidence_refs": [str(receipt_path)+"#sha256="+receipt_ref["sha256"]]})
        association["payload"]["evidence_refs"].append(receipt_ref)
        if child_document is not None and record["result_refs"]:
            if config["action"] == "detection":
                kind = "run"; identity = {"run_id": child_document["payload"]["run_id"]}
            else:
                kind = "source_result"; identity = {"result_sha256": record["result_refs"][0]["sha256"]}
            eid = kind+":"+pf.digest(identity)
            old_runs = report["parent_entity_ids"]
            association["payload"]["entities"].append({"entity_id": eid, "kind": kind, "namespace": "line-spectrum-v1",
                "identity": identity, "evidence_ref": record["result_refs"][0]})
            for parent in old_runs:
                association["payload"]["relations"].append({"from_entity": eid, "to_entity": parent, "kind": "followup_of",
                    "basis": "Explicit confirmed one-shot follow-up; no same-target or independent-truth assertion."})
        runtime.require_contract(association, "AssociationRecord")
        assoc_raw = products.json_bytes(association)
        with association_path.open("xb") as assoc_file:
            assoc_file.write(assoc_raw)
        record["association_ref"] = {"location": {"kind": "external_reference", "path": str(association_path)},
            "sha256": hashlib.sha256(assoc_raw).hexdigest(), "availability": "available"}
        handle.write(products.json_bytes(record))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["query", "joint-view", "propose-followup", "review-followup", "confirm-followup", "run-followup"])
    parser.add_argument("config"); parser.add_argument("--receipt"); parser.add_argument("--evidence"); parser.add_argument("--receipt-output")
    args = parser.parse_args(); config = pf.explicit_json(args.config)
    if args.action == "query":
        answer = query([read_bound(ref) for ref in config["associations"]], config["kind"], config["identity"], config["direction"])
    elif args.action == "joint-view":
        answer = joint_view(config); answer.pop("files")
    elif args.action == "propose-followup":
        import detection_runtime as runtime
        answer = propose_followup(read_bound(config["association_ref"]), **config["proposal"])
        with runtime.safe_new_path(config["output_path"]).open("xb") as handle:
            handle.write(products.json_bytes(answer))
    elif args.action == "review-followup":
        answer = review_followup(config)
    elif args.action == "confirm-followup":
        import detection_runtime as runtime
        if not args.evidence or not args.receipt_output:
            parser.error("confirm-followup requires --evidence and --receipt-output")
        answer = runtime.confirm(review_followup(config), pf.explicit_json(args.evidence))
        with runtime.safe_new_path(args.receipt_output).open("xb") as handle:
            handle.write(products.json_bytes(answer))
    else:
        if not args.receipt:
            parser.error("run-followup requires --receipt")
        answer = run_followup(config, pf.explicit_json(args.receipt))
    print(products.json_bytes(answer).decode())
    if answer.get("status") in ("blocked", "failed"):
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(products.json_bytes({"status": "blocked_or_failed", "error": str(exc)}).decode()); sys.exit(2)
