#!/usr/bin/env python3
"""Read-only contract checks. Never authorizes or runs signal processing."""
import argparse
from functools import lru_cache
import json
import math
import sys
from pathlib import Path

KINDS = ("SignalInput", "AlgorithmDescriptor", "DetectionRequest",
         "DetectionResult", "AssociationRecord")
DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "assets" / "schemas"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON token: {value}")


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite number (including exponent overflow)")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"),
                       object_pairs_hook=_pairs, parse_constant=_constant)
    _finite(value)
    return value


@lru_cache(maxsize=1)
def _validators():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    documents = [read_json(SCHEMA_DIR / "common.schema.json")]
    documents += [read_json(SCHEMA_DIR / f"{kind}.schema.json") for kind in KINDS]
    registry = Registry()  # No network/filesystem retrieval callback.
    for document in documents:
        Draft202012Validator.check_schema(document)
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return {kind: Draft202012Validator(document, registry=registry)
            for kind, document in zip(KINDS, documents[1:])}


def _pointer(parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _semantic_errors(kind, p):
    errors = []

    def issue(path, message):
        errors.append({"path": "/payload" + path, "message": message})

    def unique(items, key, path):
        seen = set()
        for i, item in enumerate(items):
            value = item[key]
            if value in seen:
                issue(f"{path}/{i}/{key}", f"Duplicate {key}: {value}")
            seen.add(value)

    def intervals(values, path, maximum=None):
        previous = None
        for i, (start, stop) in enumerate(values):
            if start >= stop:
                issue(f"{path}/{i}", "Require start < stop for [start, stop).")
            if maximum is not None and stop > maximum:
                issue(f"{path}/{i}", "Interval exceeds sample_count.")
            if previous is not None and start < previous:
                issue(f"{path}/{i}", "Intervals must be ordered and non-overlapping.")
            previous = stop

    def inside(values, outer, path):
        for i, (start, stop) in enumerate(values):
            if not any(left <= start < stop <= right for left, right in merged(outer)):
                issue(f"{path}/{i}", "Interval is outside declared support/coverage.")

    def band(value, path):
        if value[0] >= value[1]:
            issue(path, "Require lower frequency < upper frequency.")

    def scope(value, path):
        intervals(value["sample_intervals"], path + "/sample_intervals")
        band(value["search_band_hz"], path + "/search_band_hz")

    if kind == "SignalInput":
        waveform = p["waveform"]
        if waveform["shape"][0] != waveform["sample_count"]:
            issue("/waveform", "shape[0] differs from sample_count.")
        validity = p["validity"]
        if validity["sample_intervals"] is not None:
            intervals(validity["sample_intervals"], "/validity/sample_intervals",
                      waveform["sample_count"])
        coverage = p["frequency_coverage"]
        if coverage["status"] == "known":
            band(coverage["band_hz"], "/frequency_coverage/band_hz")
            if coverage["band_hz"][1] > p["sample_rate_hz"] / 2:
                issue("/frequency_coverage/band_hz", "Coverage exceeds real-signal Nyquist.")
    elif kind == "AlgorithmDescriptor":
        unique(p["capabilities"], "task_kind", "/capabilities")
        unique(p["processing_definition"], "step_id", "/processing_definition")
        unique(p["product_definitions"], "product_id", "/product_definitions")
        from jsonschema import Draft202012Validator
        for path, schema in (
            ("/parameter_definitions/json_schema", p["parameter_definitions"]["json_schema"]),
            ("/result_definition/extension_schema", p["result_definition"]["extension_schema"]),
        ):
            try:
                if schema.get("$schema", DIALECT) != DIALECT:
                    raise ValueError("Embedded schemas must use Draft 2020-12.")
                Draft202012Validator.check_schema(schema)
                # Check actual schema locations, not arbitrary strings in defaults/examples.
                check_embedded_refs(schema)
            except Exception as exc:
                issue(path, f"Invalid/unsupported embedded schema: {exc}")
    elif kind == "DetectionRequest":
        unique(p["tasks"], "task_id", "/tasks")
        task_ids = {item["task_id"] for item in p["tasks"]}
        for i, task in enumerate(p["tasks"]):
            scope(task["scope"], f"/tasks/{i}/scope")
            unique(task["processing_steps"], "step_id", f"/tasks/{i}/processing_steps")
        for i, decision in enumerate(p["unknown_decisions"]):
            if not set(decision["affected_tasks"]) <= task_ids:
                issue(f"/unknown_decisions/{i}/affected_tasks", "Unknown task_id.")
    elif kind == "DetectionResult":
        unique(p["task_results"], "task_id", "/task_results")
        candidate_ids = set()
        for i, task in enumerate(p["task_results"]):
            base = f"/task_results/{i}"
            cov = task["coverage"]
            scope(cov["requested"], base + "/coverage/requested")
            intervals(cov["processed"], base + "/coverage/processed")
            excluded = [x["interval"] for x in cov["excluded"]]
            intervals(excluded, base + "/coverage/excluded")
            requested = cov["requested"]["sample_intervals"]
            inside(cov["processed"], requested, base + "/coverage/processed")
            inside(excluded, requested, base + "/coverage/excluded")
            for a, b in cov["processed"]:
                if any(max(a, c) < min(b, d) for c, d in excluded):
                    issue(base + "/coverage", "Processed and excluded intervals overlap.")
            if task["execution_status"] == "completed":
                if merged(cov["processed"] + excluded) != merged(requested):
                    issue(base + "/coverage", "Completed task must account for requested coverage.")
            for j, candidate in enumerate(task["candidates"] or []):
                cb = base + f"/candidates/{j}"
                cid = candidate["candidate_id"]
                if cid in candidate_ids:
                    issue(cb + "/candidate_id", "Candidate IDs must be unique within run.")
                candidate_ids.add(cid)
                if candidate["task_id"] != task["task_id"] or candidate["input_ref"] != task["input_ref"]:
                    issue(cb, "Candidate task/input identity differs from parent task.")
                support = candidate["analysis_support"]
                intervals(support["sample_intervals"], cb + "/analysis_support/sample_intervals")
                inside(support["sample_intervals"], cov["processed"],
                       cb + "/analysis_support/sample_intervals")
                if support["time_reference"] != cov["requested"]["time_reference"]:
                    issue(cb + "/analysis_support", "Time reference differs from task coverage.")
                frequency = candidate["frequency"]
                values = ([frequency["value_hz"]] if frequency["kind"] == "point"
                          else frequency["range_hz"])
                if frequency["kind"] == "interval":
                    band(values, cb + "/frequency/range_hz")
                lo, hi = cov["requested"]["search_band_hz"]
                if any(f < lo or f > hi for f in values):
                    issue(cb + "/frequency", "Frequency is outside requested search band.")
                event = candidate["event_extent"]
                if event["status"] == "estimated":
                    start, stop = event["interval_seconds"]
                    if start >= stop:
                        issue(cb + "/event_extent", "Require event start < stop.")
            unique(task["artifacts"], "product_id", base + "/artifacts")
            for j, artifact in enumerate(task["artifacts"]):
                if artifact["task_id"] != task["task_id"]:
                    issue(base + f"/artifacts/{j}/task_id", "Artifact task identity differs.")
    elif kind == "AssociationRecord":
        unique(p["entities"], "entity_id", "/entities")
        unique(p["comparisons"], "comparison_id", "/comparisons")
        unique(p["followups"], "followup_id", "/followups")
        entity_ids = {entity["entity_id"] for entity in p["entities"]}
        for i, relation in enumerate(p["relations"]):
            if {relation["from_entity"], relation["to_entity"]} - entity_ids:
                issue(f"/relations/{i}", "Relation references an undeclared entity.")
        for field in ("comparisons", "scope_mapping"):
            for i, item in enumerate(p[field]):
                if set(item["entity_ids"]) - entity_ids:
                    issue(f"/{field}/{i}/entity_ids", "Unknown entity_id.")
                if len(set(item["entity_ids"])) != len(item["entity_ids"]):
                    issue(f"/{field}/{i}/entity_ids", "Duplicate entity_id.")
    return errors


def merged(values):
    """Canonical union for comparison only; never changes the supplied document."""
    result = []
    for start, stop in sorted(values):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], stop)
        else:
            result.append([start, stop])
    return result


def check_embedded_refs(schema):
    """Only local JSON Pointers, with no retrieval or custom vocabulary execution."""
    root = schema

    def visit(node):
        if isinstance(node, bool):
            return
        for keyword in ("$dynamicRef", "$dynamicAnchor", "$anchor", "$vocabulary", "$id"):
            if keyword in node:
                raise ValueError(f"{keyword} is outside the embedded-schema profile.")
        if "$ref" in node:
            pointer = node["$ref"]
            if pointer != "#" and not pointer.startswith("#/"):
                raise ValueError("Only local JSON Pointer $ref is supported.")
            target = root
            for part in pointer[2:].split("/") if pointer != "#" else []:
                part = part.replace("~1", "/").replace("~0", "~")
                target = target[int(part)] if isinstance(target, list) else target[part]
            if not isinstance(target, (dict, bool)):
                raise ValueError("$ref must resolve to a schema.")
        for key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)
        for key in ("items", "contains", "additionalProperties", "unevaluatedProperties",
                    "unevaluatedItems", "propertyNames", "not", "if", "then", "else",
                    "contentSchema"):
            if key in node:
                visit(node[key])
    visit(schema)


def validate_document(document, expected_kind=None):
    """Validate serialized declarations, not external truth or permission."""
    report = {
        "valid": False, "record_type": None, "document_status": None,
        "validation_scope": "document_structure_only",
        "can_execute": False,
        "not_checked": [
            "source_file_contents_and_hashes", "upstream_adapter_correctness",
            "algorithm_registration_and_parameter_compatibility",
            "real_user_approval_and_plan_binding", "cross_document_consistency",
            "resource_feasibility", "numerical_results_and_detection_quality",
        ],
        "errors": [],
    }
    try:
        _finite(document)
        if not isinstance(document, dict):
            raise ValueError("Root must be a JSON object.")
        kind = document.get("record_type")
        report["record_type"] = kind
        report["document_status"] = document.get("document_status")
        if kind not in KINDS:
            raise ValueError("Unknown record_type.")
        if expected_kind is not None and kind != expected_kind:
            raise ValueError("record_type differs from --kind.")
        validator = _validators()[kind]
        report["errors"] = [
            {"path": _pointer(error.absolute_path), "message": error.message}
            for error in validator.iter_errors(document)
        ]
        if not report["errors"] and document["document_status"] == "specified":
            report["validation_scope"] = "document_structure_and_local_consistency"
            report["errors"] = _semantic_errors(kind, document["payload"])
        report["valid"] = not report["errors"]
        report["interpretation"] = (
            "Draft format valid; unresolved fields remain. Not executable."
            if report["valid"] and document["document_status"] == "draft" else
            "Specified format/local consistency valid; truth and authority unverified. Not executable."
            if report["valid"] else "Invalid document; no repair or execution performed."
        )
    except Exception as exc:
        report["errors"].append({"path": "/", "message": f"{type(exc).__name__}: {exc}"})
        report["interpretation"] = "Validation failed; no repair or execution performed."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="Explicit JSON document; referenced files are not opened.")
    parser.add_argument("--kind", choices=KINDS, help="Optional expected record type.")
    args = parser.parse_args()
    try:
        document = read_json(args.document)
    except Exception as exc:
        print(json.dumps({"valid": False, "can_execute": False,
                          "validation_scope": "document_parse_only",
                          "errors": [{"path": "/", "message": f"{type(exc).__name__}: {exc}"}]},
                         ensure_ascii=False, indent=2))
        return 2
    report = validate_document(document, args.kind)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
