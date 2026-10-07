"""Fixed local registry. Descriptors bind actual implementation bytes, not names alone."""
from pathlib import Path
import hashlib
import json
import importlib.metadata
import platform

VERSION = "1.0.0"
IMPLEMENTATION_FILES = ("cfar_core.py", "cfar_theory.py", "cfar_registry.py", "detection_runtime.py",
                        "cfar_calibration.py", "detection_products.py", "detection_associations.py",
                        "preflight.py", "input_adapter.py", "beamformed_input.py", "validate_contract.py")
PRODUCTS = {
    "candidates": ([], "Candidate table with support, group extent and threshold evidence."),
    "ledger": ([], "All complete frames, tested/excluded bins and rejected groups; includes empty rows."),
    "spectra": ([], "Linear PSD, background, threshold, cell-valid mask and exact native coordinates."),
    "spectrum_plot": (["spectra"], "Spectrum of each selected detection row with background/threshold/candidates."),
    "time_frequency_plot": (["spectra"], "Native framewise PSD with candidate markers, gaps not interpolated."),
    "report": ([], "HTML candidate/source/coverage summary; no target judgment or performance metric."),
}


def closed(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def nullable(schema):
    return {"anyOf": [{"type": "null"}, schema]}


def number(minimum=0, exclusive=False):
    return {"type": "number", "exclusiveMinimum" if exclusive else "minimum": minimum}


def integer(minimum):
    return {"type": "integer", "minimum": minimum}


def band():
    return {"type": "array", "items": number(), "minItems": 2, "maxItems": 2}


def text_schema():
    return {"type": "string", "minLength": 1}


def file_schema():
    return closed({"location": closed({"kind": {"enum": ["package_relative", "external_reference"]},
                                       "path": text_schema()}),
                   "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                   "availability": {"enum": ["not_checked", "available", "unavailable"]}})


def parameter_schema():
    policy = {"enum": ["skip_and_report", "stop"]}
    return closed({
        "spectrum": closed({"window_length": integer(2), "hop_length": integer(1), "nfft": integer(2),
            "window": {"enum": ["periodic_hann", "rectangular"]}, "demean": {"type": "boolean"},
            "frame_origin": {"enum": ["each_interval_start", "signal_sample_zero"]},
            "invalid_frame": policy, "unknown_validity": {"enum": ["reject", "analyze_unverified"]}}),
        "cfar": closed({"reference_per_side": integer(1), "guard_per_side": integer(0),
            "rank": nullable(integer(1)), "reference_band_hz": band(),
            "insufficient_reference": policy, "zero_background": policy}),
        "threshold": closed({"route": {"enum": ["theory", "calibration"]},
            "event_scope": {"enum": ["frame", "segment"]},
            "event_probability": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
            "family": {"const": "this_task_signal_detector_only_no_joint_guarantee"},
            "theory_assumption": nullable(closed({"model": {"const": "iid_exponential_cells"},
                "applicability": {"enum": ["model_asserted", "nominal_approximation"]},
                "rationale": text_schema()})), "calibration_ref": nullable(file_schema())}),
        "candidates": closed({"group_width_hz": nullable(band()),
            "minimum_peak_distance_hz": nullable(number(0, True))}),
        "display": nullable(closed({"db_reference_psd": number(0, True),
            "db_limits": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "spectrum_rows": {"type": "array", "items": integer(0), "uniqueItems": True},
            "title": text_schema()})),
    })


def implementation_digest():
    base = Path(__file__).resolve().parent
    h = hashlib.sha256()
    paths = [base / name for name in IMPLEMENTATION_FILES]
    paths += sorted((base.parent / "assets" / "schemas").glob("*.json"))
    for sibling in ("underwater-beamforming", "underwater-data-inspection"):
        folder = base.parent.parent / sibling / "scripts"
        paths += sorted(folder.glob("*.py")) if folder.is_dir() else []
    h.update(json.dumps({"python": platform.python_version(), **{name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "jsonschema", "referencing")}}, sort_keys=True).encode())
    for path in paths:
        h.update(str(path.relative_to(base.parent.parent)).encode()); h.update(b"\0")
        h.update(path.read_bytes()); h.update(b"\0")
    return h.hexdigest()


def envelope(kind, payload):
    return {"schema_version": "0.1.0", "record_type": kind, "document_status": "specified",
            "payload": payload, "unresolved_items": []}


def descriptor(method):
    if method not in ("ca_cfar", "os_cfar"):
        raise ValueError("Only explicitly registered ca_cfar/os_cfar are executable.")
    return envelope("AlgorithmDescriptor", {
        "detector_id": method, "detector_version": VERSION,
        "implementation_identity": {"registration_key": method + "@" + VERSION,
                                    "sha256": implementation_digest()},
        "input_requirements": {"data_roles": ["single_sensor", "beamformed"],
            "representation": "real_waveform", "dtypes": ["float64"],
            "required_metadata": ["/sample_rate_hz", "/time_mapping"], "constraints": [],
            "unknown_metadata_policy": "allow_with_explicit_decision"},
        "capabilities": [{"task_kind": kind, "description": desc} for kind, desc in (
            ("framewise", "Each complete valid frame is a detection spectrum."),
            ("average_spectrum", "Arithmetic mean of complete valid PSDs; matching calibration required."))],
        "parameter_definitions": {"json_schema": parameter_schema(), "annotations": []},
        "processing_definition": [{"step_id": k, "description": description, "parameter_paths": ["/" + k]}
            for k, description in (("spectrum", "Validate support and estimate one-sided density."),
                ("cfar", "Full two-sided CA mean or one-based OS statistic."),
                ("threshold", "Explicit event budget or matched calibration."),
                ("candidates", "Strict exceedance groups, ties and selected filters."),
                ("display", "Only explicitly requested views, no SPL label."))],
        "result_definition": {"frequency_semantics": "FFT bin center, no interpolation.",
            "time_support_semantics": "Original half-open sample support, not target duration.",
            "decision_semantics": "PSD > alpha*background, then declared group filters.",
            "measurement_definitions": [{"name": name, "definition_id": "cfar-v1/"+name, "definition_version": VERSION,
                "unit": unit, "scale": "linear", "interpretation": interpretation}
                for name, unit, interpretation in (
                    ("power", "input_unit^2/Hz", "One-sided PSD at retained bin; unit resolved from SignalInput."),
                    ("background", "input_unit^2/Hz", "CA mean or one-based OS statistic, not known physical noise."),
                    ("threshold", "input_unit^2/Hz", "alpha times background; strict exceedance."),
                    ("ratio", "dimensionless", "PSD/background; not physical SNR or probability."),
                    ("group_width_hz", "Hz", "Exceeding bin count times fs/nfft; not physical linewidth."))],
            "extension_schema": closed({"cfar_v1": closed({"row": integer(0),
                "group_bins": {"type": "array", "items": integer(0), "minItems": 2, "maxItems": 2},
                "tied_maximum_bins": {"type": "array", "items": integer(0), "minItems": 1},
                "plateau_extent_bins": {"type": "array", "items": integer(0), "minItems": 2, "maxItems": 2},
                "plateau_is_contiguous": {"type": "boolean"}})})},
        "product_definitions": [{"product_id": name, "description": desc, "dependencies": deps,
            "requires_additional_calculation": True,
            "coordinate_semantics": "Native FFT Hz and original sample/time coordinates."}
            for name, (deps, desc) in PRODUCTS.items()],
        "resource_model": {"description": "Bounded in-memory executor with conservative size admission and exclusive output.",
            "limitations": ["Allocation estimate is not an operating-system RSS hard limit."]},
        "limitations": ["Candidate is not a target or false alarm without truth.",
            "Adjacent spectral lines may form one threshold-exceeding group.",
            "No joint guarantee across tasks, beams or algorithms; no tracking.",
            "Model probabilities and empirical calibration are not unconditional field guarantees."],
        "validation_evidence": [],
    })


def identity(method):
    return {"detector_id": method, "detector_version": VERSION,
            "implementation_sha256": implementation_digest()}


def processing_steps(parameters):
    return [{"step_id": k, "parameters": {"/" + k: parameters[k]}}
            for k in ("spectrum", "cfar", "threshold", "candidates", "display")]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=["ca_cfar", "os_cfar"])
    parser.add_argument("--out", help="Explicit new absolute descriptor path; otherwise stdout only.")
    args = parser.parse_args()
    value = json.dumps(descriptor(args.method), ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    if args.out:
        from detection_runtime import safe_new_path
        with safe_new_path(args.out).open("x", encoding="utf-8") as handle:
            handle.write(value)
    else:
        print(value, end="")
