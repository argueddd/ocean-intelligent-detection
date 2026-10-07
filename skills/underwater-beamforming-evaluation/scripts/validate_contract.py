#!/usr/bin/env python3
"""Read-only validation for beamforming-evaluation request/result contracts."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import sys


KINDS = ("EvaluationRequest", "EvaluationResult")
VERSION = "1.0.0"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "assets" / "schemas"

COMMAND_INPUTS = {
    "spectrum": ({"power"}, {"angles"}),
    "doa": ({"estimates"}, {"truth"}),
    "freq-bearing": ({"matrix"}, {"freqs", "angles"}),
    "btr": ({"matrix"}, {"times", "angles", "truth_track"}),
    "signal": ({"signal"}, {"baseline", "reference"}),
    "spectrum-output": ({"spectrum", "freqs"}, {"baseline"}),
    "time-frequency": ({"matrix", "freqs"}, {"times", "baseline"}),
    "compare": ({"metrics", "spec"}, set()),
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON token: {value}")


def _check_json_domain(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Non-finite number, including exponent overflow.")
        return
    if type(value) is list:
        for child in value:
            _check_json_domain(child)
        return
    if type(value) is dict:
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Object keys must be strings.")
            _check_json_domain(child)
        return
    raise ValueError("Only the JSON data model is supported.")


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"),
                       object_pairs_hook=_pairs, parse_constant=_constant)
    _check_json_domain(value)
    return value


@lru_cache(maxsize=1)
def _validators():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    common = read_json(SCHEMA_DIR / "common.schema.json")
    docs = {kind: read_json(SCHEMA_DIR / f"{kind}.schema.json") for kind in KINDS}
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common))
    for doc in docs.values():
        Draft202012Validator.check_schema(doc)
        registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))
    return {kind: Draft202012Validator(doc, registry=registry) for kind, doc in docs.items()}


def _pointer(parts):
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def _semantic_errors(kind: str, document: dict) -> list[dict]:
    errors: list[dict] = []

    def issue(path, message):
        errors.append({"path": path, "message": message})

    if kind != "EvaluationRequest" or document.get("document_status") != "specified":
        return errors
    payload = document["payload"]
    jobs = payload["jobs"]
    ids = [job["job_id"] for job in jobs]
    if len(ids) != len(set(ids)):
        issue("/payload/jobs", "job_id values must be unique.")

    confirmation = payload["confirmation"]
    if confirmation["status"] == "recorded" and not confirmation["statement"]:
        issue("/payload/confirmation", "Recorded confirmation needs a statement.")
    if confirmation["status"] == "pending" and confirmation["statement"] is not None:
        issue("/payload/confirmation", "Pending confirmation must not contain an invented statement.")

    destination = Path(payload["output_plan"]["save_destination"]).expanduser()
    if not destination.is_absolute():
        issue("/payload/output_plan/save_destination", "Save destination must be an absolute path.")

    for index, job in enumerate(jobs):
        base = f"/payload/jobs/{index}"
        command = job["command"]
        required, optional = COMMAND_INPUTS[command]
        names = set(job["inputs"])
        missing = required - names
        unknown = names - required - optional
        if missing:
            issue(base + "/inputs", f"Missing required input roles: {sorted(missing)}")
        if unknown:
            issue(base + "/inputs", f"Unknown input roles for {command}: {sorted(unknown)}")

        evidence = job["evidence"]
        has_truth = "truth" in names or "truth_track" in names or bool(job["parameters"].get("truth_deg"))
        if evidence["truth_status"] == "provided":
            if not has_truth:
                issue(base + "/evidence", "truth_status=provided needs a truth input or truth_deg.")
            if not evidence["truth_scope"]:
                issue(base + "/evidence/truth_scope", "Provided truth needs a declared scope.")
        elif has_truth:
            issue(base + "/evidence", "Truth input is present but truth_status is not provided.")

        has_baseline = "baseline" in names
        if evidence["baseline_status"] == "provided" and not has_baseline:
            issue(base + "/evidence", "baseline_status=provided needs a baseline input.")
        if has_baseline and evidence["baseline_status"] != "provided":
            issue(base + "/evidence", "Baseline input is present but baseline_status is not provided.")

        if command == "compare" and evidence["comparability"] != "confirmed":
            issue(base + "/evidence/comparability",
                  "Algorithm comparison requires comparability=confirmed; otherwise evaluate rows separately.")
        if command != "compare" and evidence["comparability"] == "not_confirmed":
            issue(base + "/evidence/comparability", "A non-comparison job cannot assert failed comparability.")

    return errors


def validate_document(document, expected_kind: str | None = None) -> dict:
    errors: list[dict] = []
    if not isinstance(document, dict):
        return {"valid": False, "record_type": None, "can_execute": False,
                "errors": [{"path": "/", "message": "Document must be a JSON object."}]}
    kind = document.get("record_type")
    if kind not in KINDS:
        return {"valid": False, "record_type": kind, "can_execute": False,
                "errors": [{"path": "/record_type", "message": f"Expected one of {KINDS}."}]}
    if expected_kind and kind != expected_kind:
        errors.append({"path": "/record_type", "message": f"Expected {expected_kind}, observed {kind}."})
    try:
        validator = _validators()[kind]
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
            errors.append({"path": _pointer(error.absolute_path), "message": error.message})
    except Exception as exc:
        errors.append({"path": "/", "message": f"Schema validation failed: {exc}"})
    if not errors:
        errors.extend(_semantic_errors(kind, document))
    can_execute = (
        not errors
        and kind == "EvaluationRequest"
        and document.get("document_status") == "specified"
        and document.get("payload", {}).get("confirmation", {}).get("status") == "recorded"
    )
    return {"valid": not errors, "record_type": kind, "can_execute": can_execute, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--expect", choices=KINDS)
    args = parser.parse_args()
    try:
        report = validate_document(read_json(args.document), args.expect)
    except Exception as exc:
        report = {"valid": False, "record_type": None, "can_execute": False,
                  "errors": [{"path": "/", "message": str(exc)}]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["valid"] else 2)


if __name__ == "__main__":
    main()
