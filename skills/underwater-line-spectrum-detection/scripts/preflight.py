#!/usr/bin/env python3
"""Review declared inputs/parameters and record a user statement; never run detection."""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

from jsonschema import Draft202012Validator
from referencing import Registry
import validate_contract as contracts

VERSION = "0.1.0"  # Receipt/context schema version; preserve existing envelopes.
REVIEW_VERSION = "0.1.1"  # Review semantics are included in the confirmation scope.
MAX_JSON_BYTES = 1024 * 1024
MAX_NPY_HEADER = 65536
SCHEMAS = Path(__file__).resolve().parents[1] / "assets" / "schemas"


def digest(value):
    """Versioned local canonical JSON profile, NOT a claim of RFC 8785 compliance."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def parse_json(raw):
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=contracts._pairs,
                       parse_constant=contracts._constant)
    contracts._finite(value)
    return value


def explicit_json(path):
    """Read an explicitly provided CLI document, bounded and without following final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON_BYTES:
            raise ValueError("JSON must be a regular file no larger than 1 MiB.")
        raw = handle.read(MAX_JSON_BYTES + 1)
        if signature(before) != signature(os.fstat(handle.fileno())):
            raise ValueError("Document changed while reading.")
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("JSON exceeds 1 MiB.")
        return parse_json(raw)


def signature(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def scoped_open(root, relative):
    """dir_fd traversal refuses symlinks in every path component, including final file."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("A nonempty POSIX relative path is required.")
    parts = relative.split("/")
    if any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
        raise ValueError("Empty, absolute, dot, parent, or drive-qualified paths are forbidden.")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Only regular files may be read.")
        return os.fdopen(fd, "rb")
    finally:
        os.close(directory)


def helper_check(value, kind):
    schema = contracts.read_json(SCHEMAS / (kind + ".schema.json"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, registry=Registry()).iter_errors(value))
    if errors:
        raise ValueError("; ".join(contracts._pointer(e.path) + ": " + e.message for e in errors[:10]))


def pointer(value, path):
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/") or re.search(r"~(?![01])", path):
        raise ValueError("Expected a JSON Pointer.")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("Invalid array index.")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def param_schema_profile(schema):
    """Reject unsupported/unknown schema semantics rather than silently ignoring them."""
    contracts.check_embedded_refs(schema)
    annotations = {"$schema", "$comment", "$defs", "title", "description", "default", "examples",
                   "deprecated", "readOnly", "writeOnly", "then", "else"}
    allowed = set(Draft202012Validator.VALIDATORS) | annotations

    def visit(node, root=False):
        if isinstance(node, bool):
            return
        unknown = set(node) - allowed
        if unknown:
            raise ValueError(f"Unrecognized parameter-schema keywords: {sorted(unknown)}")
        if "$schema" in node and node["$schema"] != contracts.DIALECT:
            raise ValueError("Nested schemas must also use Draft 2020-12.")
        if "format" in node or any(x in node for x in ("contentEncoding", "contentMediaType", "contentSchema")):
            raise ValueError("format/content assertions are not implemented in this preflight profile.")
        if root or node.get("type") == "object" or (
                isinstance(node.get("type"), list) and "object" in node["type"]):
            closed = node.get("additionalProperties") is False or node.get("unevaluatedProperties") is False
            typed_map = isinstance(node.get("additionalProperties"), dict)
            if not closed and not typed_map:
                raise ValueError("Object parameters must explicitly reject or type additional keys.")
        for key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)
        for key in ("items", "contains", "additionalProperties", "unevaluatedProperties",
                    "unevaluatedItems", "propertyNames", "not", "if", "then", "else"):
            if key in node:
                visit(node[key])
    visit(schema, True)


def npy_header(prefix, size):
    """Inspect header/length only; no pickle, array load, FFT or value repair."""
    if not prefix.startswith(b"\x93NUMPY"):
        return None
    version = tuple(prefix[6:8])
    length_bytes = 2 if version == (1, 0) else 4 if version in ((2, 0), (3, 0)) else 0
    if not length_bytes:
        raise ValueError("Unsupported NPY header version.")
    offset = 8 + length_bytes
    length = int.from_bytes(prefix[8:offset], "little")
    if length > MAX_NPY_HEADER or len(prefix) < offset + length:
        raise ValueError("Truncated or oversized NPY header.")
    header = ast.literal_eval(prefix[offset:offset + length].decode("utf-8" if version == (3, 0) else "latin1"))
    if not isinstance(header, dict) or set(header) != {"descr", "fortran_order", "shape"}:
        raise ValueError("Invalid NPY header fields.")
    shape = header["shape"]
    if not isinstance(shape, tuple) or not shape or any(type(n) is not int or n < 0 for n in shape):
        raise ValueError("Invalid NPY shape.")
    if type(header["fortran_order"]) is not bool:
        raise ValueError("Invalid NPY order.")
    item_size = {"<f8": 8, ">f8": 8, "=f8": 8, "|b1": 1}.get(header["descr"])
    if item_size is None:
        raise ValueError("Only float64 waveform or bool mask NPY is supported; no object arrays.")
    if size != offset + length + math.prod(shape) * item_size:
        raise ValueError("NPY file length disagrees with its header.")
    return {"dtype": "bool" if item_size == 1 else "float64", "shape": list(shape),
            "fortran_order": header["fortran_order"]}


class Review:
    def __init__(self, root, context):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Source root must be a directory.")
        self.context = context
        self.issues = []
        self.snapshots = {}
        self.sources = {}
        self.source_paths = {}
        self.document_digests = {}
        self.read_bytes = 0
        self.remaining = 0
        self.adapter_checks = {}

    def issue(self, code, field, reason, question, task=None, blocking=True):
        issue = {"code": code, "field": field, "reason": reason, "question": question,
                 "affected_tasks": [task] if task else [],
                 "affected_actions": ["review_confirmation"], "blocking": blocking}
        issue["issue_id"] = digest([code, field, task, reason])[:16]
        if not any(x["issue_id"] == issue["issue_id"] for x in self.issues):
            self.issues.append(issue)

    def read_document(self, relative, kind):
        try:
            with scoped_open(self.root, relative) as handle:
                before = os.fstat(handle.fileno())
                if before.st_size > MAX_JSON_BYTES:
                    raise ValueError("Contract document exceeds 1 MiB.")
                raw = handle.read(MAX_JSON_BYTES + 1)
                if len(raw) > MAX_JSON_BYTES or signature(before) != signature(os.fstat(handle.fileno())):
                    raise ValueError("Document oversized or changed during read.")
            self.snapshots[relative] = signature(before)
            self.document_digests[relative] = hashlib.sha256(raw).hexdigest()
            document = parse_json(raw)
            checked = contracts.validate_document(document, kind)
            if not checked["valid"]:
                raise ValueError(str(checked["errors"][:10]))
            if document["document_status"] != "specified":
                raise ValueError("Document remains draft; do not fill defaults.")
            return document
        except Exception as exc:
            self.issue("document_invalid", relative, str(exc), "请补齐或更正这份文档，并保留已确认事实的出处。")
            return None

    def source(self, reference, field, required=True, task=None):
        sha = reference["sha256"]
        if sha in self.sources:
            return self.sources[sha]
        path = self.source_paths.get(sha)
        if path is None:
            self.issue("source_binding_missing", field, "No explicitly supplied file binding for " + sha,
                       "请指定此来源文件的位置；不要搜索同名文件或猜测替代来源。", task, required)
            return None
        try:
            with scoped_open(self.root, path) as handle:
                before = os.fstat(handle.fileno())
                if before.st_size > self.remaining:
                    raise ValueError("Source-read byte budget exceeded; no partial substitution.")
                self.remaining -= before.st_size
                hasher = hashlib.sha256()
                prefix = b""
                consumed = 0
                while True:
                    chunk = handle.read(min(65536, before.st_size - consumed + 1))
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > before.st_size:
                        raise ValueError("Source grew during read.")
                    hasher.update(chunk)
                    if len(prefix) < MAX_NPY_HEADER + 12:
                        prefix += chunk[:MAX_NPY_HEADER + 12 - len(prefix)]
                self.read_bytes += consumed
                if consumed != before.st_size or signature(before) != signature(os.fstat(handle.fileno())):
                    raise ValueError("Source changed during read.")
            actual = hasher.hexdigest()
            if actual != sha:
                raise ValueError("SHA256 mismatch; existing confirmation cannot apply.")
            self.snapshots[path] = signature(before)
            item = {"sha256": actual, "path": path, "size_bytes": consumed,
                    "npy_header": npy_header(prefix, consumed)}
            self.sources[sha] = item
            return item
        except Exception as exc:
            self.issue("source_check_failed", field, str(exc),
                       "请核对来源、文件完整性与读取预算；不得自动替换、修复或扩大读取范围。", task, required)
            return None

    def inputs(self):
        result = {}
        for path in self.context["inputs"]:
            doc = self.read_document(path, "SignalInput")
            if doc:
                p = doc["payload"]
                key = (p["source_package"]["manifest"]["sha256"], p["signal_id"])
                if key in result:
                    self.issue("duplicate_input", path, str(key), "请消除同一身份的重复或冲突说明。")
                else:
                    result[key] = (doc, path)
        return result

    def descriptors(self):
        result = {}
        for path in self.context["descriptors"]:
            doc = self.read_document(path, "AlgorithmDescriptor")
            if doc:
                p = doc["payload"]
                key = (p["detector_id"], p["detector_version"], p["implementation_identity"]["sha256"])
                if key in result:
                    self.issue("duplicate_descriptor", path, str(key), "请明确唯一算法说明，不自动选最新版本。")
                else:
                    result[key] = (doc, path)
        return result

    def inspect_input(self, p, path, task_id):
        required = [("source_package/manifest", p["source_package"]["manifest"]),
                    ("waveform/file_ref", p["waveform"]["file_ref"]),
                    ("processing_history/source_configuration", p["processing_history"]["source_configuration"])]
        for field in ("mask_ref",):
            if p["validity"][field]:
                required.append(("validity/" + field, p["validity"][field]))
        if p["frequency_coverage"]["active_frequency_ref"]:
            required.append(("frequency_coverage/active_frequency_ref", p["frequency_coverage"]["active_frequency_ref"]))
        if p["beam_source"].get("source_result"):
            required.append(("beam_source/source_result", p["beam_source"]["source_result"]))
        for field, reference in required:
            value = self.source(reference, path + "/payload/" + field, task=task_id)
            if not value:
                continue
            expected = ([p["waveform"]["sample_count"], 1], "float64") if field == "waveform/file_ref" else (
                ([p["waveform"]["sample_count"]], "bool") if field == "validity/mask_ref" else None)
            if expected and (not value["npy_header"] or
                             value["npy_header"]["shape"] != expected[0] or
                             value["npy_header"]["dtype"] != expected[1]):
                self.issue("array_header_mismatch", path + "/payload/" + field,
                           "File header does not match SignalInput declaration.",
                           "请回到上游核对轴、样本数与类型；不转置、不展平、不改精度。", task_id)
        for i, reference in enumerate(p["provenance"]):
            self.source(reference, path + f"/payload/provenance/{i}", required=False, task=task_id)

    def inspect_adapter(self, document, path, task_id):
        options = self.context.get("handoff_validation")
        if options is None:
            return
        p = document["payload"]
        sha = p["source_package"]["manifest"]["sha256"]
        key = sha + ":" + p["signal_id"]
        if key in self.adapter_checks:
            return
        try:
            import input_adapter
            relative = self.source_paths.get(sha)
            if relative is None or sha not in self.sources:
                raise ValueError("Manifest requires an explicitly bound, verified source.")
            result = input_adapter.check_document(document, self.root / relative, **options)
            if result["adapter_status"] != "verified":
                raise ValueError("SignalInput differs from upstream: " + str(result["differences"][:20]))
            package_dir = Path(relative).parent
            for name, expected in result.pop("package_snapshots").items():
                package_relative = (package_dir / name).as_posix()
                if package_relative in self.snapshots and self.snapshots[package_relative] != tuple(expected):
                    raise ValueError("Source changed between base review and adapter check.")
                self.snapshots[package_relative] = tuple(expected)
            self.adapter_checks[key] = result
        except Exception as exc:
            self.adapter_checks[key] = {"adapter_status": "blocked", "error": str(exc), "can_execute": False}
            self.issue("upstream_adapter_check_failed", path, str(exc),
                       "请核对输入与完整交接包；不得改写源信息来消除差异，也不得跳过失败的适配检查。", task_id)

    def task(self, task, input_entry, descriptor_entry, decisions, index):
        tid = task["task_id"]
        base = "/payload/tasks/" + str(index)
        if input_entry is None:
            self.issue("input_not_supplied", base + "/input_ref", "Exact package hash + signal_id not supplied.",
                       "请提供明确的 SignalInput；不能默认第一条或替换同名信号。", tid)
        if descriptor_entry is None:
            self.issue("algorithm_not_supplied", base + "/detector", "Exact detector/version/implementation not supplied.",
                       "请先明确检测方法及对应说明；本工具不选择或替换算法。", tid)
        if input_entry is not None:
            self.inspect_input(input_entry[0]["payload"], input_entry[1], tid)
            self.inspect_adapter(input_entry[0], input_entry[1], tid)
        if input_entry is None or descriptor_entry is None:
            return
        inp, input_path = input_entry
        desc, desc_path = descriptor_entry
        p, d = inp["payload"], desc["payload"]
        req = d["input_requirements"]
        if p["data_role"] not in req["data_roles"] or p["waveform"]["dtype"] not in req["dtypes"]:
            self.issue("input_unsupported", base, "Input role/dtype not supported by descriptor.",
                       "请核对输入选择或算法能力，不能转换类型后继续。", tid)
        if task["task_kind"] not in {c["task_kind"] for c in d["capabilities"]}:
            self.issue("task_unsupported", base + "/task_kind", "Undeclared task capability.",
                       "请明确与算法能力一致的任务。", tid)
        scope = task["scope"]
        if any(stop > p["waveform"]["sample_count"] for _, stop in scope["sample_intervals"]):
            self.issue("sample_scope_outside", base + "/scope", "Requested sample range exceeds input.",
                       "请更正范围；不自动截短。", tid)
        if scope["time_reference"] != p["time_mapping"]["time_reference"]:
            self.issue("time_reference_mismatch", base + "/scope/time_reference", "Time reference differs.",
                       "请明确时间映射；不自动换算、拼接或伪造绝对时间。", tid)
        lo, hi = scope["search_band_hz"]
        coverage = p["frequency_coverage"]
        if hi > p["sample_rate_hz"] / 2 or (coverage["status"] == "known" and
                (lo < coverage["band_hz"][0] or hi > coverage["band_hz"][1])):
            self.issue("frequency_scope_outside", base + "/scope/search_band_hz", "Search exceeds input coverage/Nyquist.",
                       "请明确合法频带；不自动取交集。", tid)
        validity = p["validity"]
        if validity["status"] == "known" and validity["sample_intervals"] is not None:
            valid = validity["sample_intervals"]
            if not any(max(a, c) < min(b, e) for a, b in scope["sample_intervals"] for c, e in valid):
                self.issue("no_valid_support", base + "/scope", "No known valid samples in requested range.",
                           "请核对有效性与范围；不能作为普通零候选任务。", tid)
        metadata_paths = set(req["required_metadata"]) | {"/validity", "/frequency_coverage"}
        policy = req["unknown_metadata_policy"]
        if policy not in ("reject_unknown", "allow_with_explicit_decision"):
            self.issue("unknown_policy_unmapped", desc_path + "/payload/input_requirements/unknown_metadata_policy",
                       "Free-text policy has no executable interpretation in this profile.",
                       "请将未知信息策略明确为 reject_unknown 或 allow_with_explicit_decision，保留理由；不自行解释。", tid)
        for field in sorted(metadata_paths):
            try:
                value = pointer(p, field)
            except Exception:
                self.issue("metadata_missing", input_path + "/payload" + field, "Required metadata path missing.",
                           "请补充可靠元数据或修正算法依赖声明，不能猜测。", tid)
                continue
            unknown = value is None or (isinstance(value, dict) and value.get("status") in ("unknown", "not_applicable"))
            if unknown:
                matches = [v for v in decisions if v["field"] == field and tid in v["affected_tasks"]
                           and "detection" in v["affected_actions"]]
                if policy != "allow_with_explicit_decision" or len(matches) != 1 or (
                        isinstance(value, dict) and value.get("status") == "not_applicable"):
                    self.issue("unknown_metadata_unresolved", input_path + "/payload" + field,
                               "Required unknown metadata lacks a compatible, task-scoped handling decision.",
                               "请明确此未知项是否可接受、影响与限制；不能把接受未知改成事实已知。", tid)
        if req["constraints"]:
            self.issue("free_text_constraint", desc_path + "/payload/input_requirements/constraints",
                       "Free-text scientific constraints cannot be machine-verified.",
                       "请在算法接入阶段提供这些约束的受控核对实现；本层不猜测解释。", tid)
        try:
            schema = d["parameter_definitions"]["json_schema"]
            param_schema_profile(schema)
            for error in Draft202012Validator(schema, registry=Registry()).iter_errors(task["resolved_parameters"]):
                self.issue("parameter_invalid", base + "/resolved_parameters" + contracts._pointer(error.path),
                           error.message, "请明确缺失/冲突参数；建议值和库默认值不能替代本次选择。", tid)
        except Exception as exc:
            self.issue("parameter_schema_unsupported", desc_path + "/payload/parameter_definitions",
                       str(exc), "请更正或明确支持范围；不忽略未知 Schema 语义。", tid)
        evidence = task["parameter_evidence"]
        if task["resolved_parameters"] and not evidence:
            self.issue("parameter_evidence_missing", base + "/parameter_evidence",
                       "Nonempty parameters have no source/choice records.",
                       "请记录参数来自上游事实、用户选择还是明确接受的假设。", tid)
        def parameter_leaves(value, path):
            if isinstance(value, dict) and value:
                return [leaf for key, child in value.items() for leaf in parameter_leaves(
                    child, path + "/" + key.replace("~", "~0").replace("/", "~1"))]
            if isinstance(value, list) and value:
                return [leaf for i, child in enumerate(value)
                        for leaf in parameter_leaves(child, path + "/" + str(i))]
            return [path]
        for leaf in parameter_leaves(task["resolved_parameters"], "/resolved_parameters"):
            if task["resolved_parameters"] and not any(
                    leaf == item["field"] or leaf.startswith(item["field"] + "/")
                    for item in evidence if item["field"].startswith("/resolved_parameters")):
                self.issue("parameter_evidence_incomplete", base + leaf,
                           "No evidence record covers this resolved value.",
                           "请记录此参数的来源或明确选择，不能用其他参数的证据代替。", tid)
        for evidence_index, item in enumerate(evidence):
            try:
                if not item["field"].startswith(("/resolved_parameters", "/processing_steps")):
                    raise ValueError("Parameter evidence must identify parameters or processing steps.")
                pointer(task, item["field"])
            except Exception:
                self.issue("parameter_evidence_dangling", base + f"/parameter_evidence/{evidence_index}/field",
                           "Evidence field does not identify this task's actual parameter/step.",
                           "请核对出处对应的字段，不沿用其他任务参数。", tid)
        declared_steps = d["processing_definition"]
        if [v["step_id"] for v in task["processing_steps"]] != [v["step_id"] for v in declared_steps]:
            self.issue("processing_steps_mismatch", base + "/processing_steps",
                       "Ordered processing steps differ from descriptor.",
                       "请列明全部实际处理步骤，不能增加隐含预处理。", tid)
        else:
            for step_index, (actual, declared) in enumerate(zip(task["processing_steps"], declared_steps)):
                try:
                    expected = {path: pointer(task["resolved_parameters"], path) for path in declared["parameter_paths"]}
                    if actual["parameters"] != expected:
                        raise ValueError("Step values differ from resolved_parameters or contain undeclared keys.")
                except Exception as exc:
                    self.issue("step_parameters_mismatch", base + f"/processing_steps/{step_index}",
                               str(exc), "请统一步骤引用的参数；不在步骤内藏默认值。", tid)
        products = {v["product_id"]: v for v in d["product_definitions"]}
        selected = set().union(*(set(v) for v in task["products"].values()))
        visited, active = set(), set()
        def check_dependencies(product):
            if product in active:
                raise ValueError("Cyclic product dependency at " + product)
            if product in visited or product not in products:
                return
            active.add(product)
            for dependency in products[product]["dependencies"]:
                check_dependencies(dependency)
            active.remove(product)
            visited.add(product)
        try:
            for product in sorted(selected):
                check_dependencies(product)
        except Exception as exc:
            self.issue("product_dependency_cycle", base + "/products", str(exc),
                       "请更正产物依赖声明；不能猜测执行顺序。", tid)
        for product in sorted(selected):
            if product not in products:
                self.issue("product_unsupported", base + "/products/" + product, "Product not declared.",
                           "请明确算法支持的产物，不替换为近似输出。", tid)
                continue
            need = products[product]
            if need["requires_additional_calculation"] and product not in task["products"]["compute"]:
                self.issue("product_calculation_unconfirmed", base + "/products/" + product,
                           "Viewing/saving requires a computation not selected.",
                           "此产物需要额外计算，是否纳入 compute？确认前不补算。", tid)
            for dep in need["dependencies"]:
                if dep not in products or dep not in task["products"]["compute"]:
                    self.issue("product_dependency_missing", base + "/products/" + product + "/" + dep,
                               "Dependency is undeclared or not explicitly selected for computation.",
                               "请明确依赖计算；不因查看或保存选择而自动补算。", tid)

    def unchanged(self):
        for path, expected in self.snapshots.items():
            try:
                with scoped_open(self.root, path) as handle:
                    if signature(os.fstat(handle.fileno())) != expected:
                        raise ValueError("Source/document changed since it was checked.")
            except Exception as exc:
                self.issue("source_changed_during_review", path, str(exc),
                           "请停止依赖此来源的操作，重新核对；旧确认不适用。")

    def run(self, request, confirmation=None):
        report = {"preflight_version": REVIEW_VERSION, "can_execute": False, "execution_status": "not_run",
                  "review_status": "blocked", "confirmation_status": "not_recorded",
                  "plan_sha256": None, "issues": self.issues, "verified_sources": [],
                  "checked_scope": "declared_plan_and_explicitly_bound_files",
                  "execution_blockers": ["no_registered_detector_or_executor",
                                        "upstream_adapter_semantics_not_verified",
                                        "scientific_constraints_and_resource_feasibility_not_fully_verified",
                                        "waveform_values_mask_values_and_algorithm_frame_rules_not_verified"],
                  "authority_verified": False}
        checked = contracts.validate_document(request, "DetectionRequest")
        if not checked["valid"]:
            for error in checked["errors"]:
                self.issue("request_invalid", error["path"], error["message"], "请核对请求字段；不自动修正。")
            return report
        if request["document_status"] == "draft":
            for item in request["unresolved_items"]:
                self.issue("unresolved_request", item["field"], item["reason"], item["question"])
            return report
        try:
            helper_check(self.context, "PreflightContext")
            if self.context["document_status"] != "specified":
                raise ValueError("Context remains draft; input/algorithm selection and source-read budget are unresolved.")
            self.remaining = self.context["max_source_bytes"]
            for value in self.context["source_files"]:
                if value["sha256"] in self.source_paths:
                    raise ValueError("Duplicate source hash binding; choose one explicit location.")
                # Validate path without reading unconsumed bindings.
                parts = value["path"].split("/")
                if any(x in ("", ".", "..") for x in parts) or "\\" in value["path"] or ":" in parts[0]:
                    raise ValueError("Invalid source binding path.")
                self.source_paths[value["sha256"]] = value["path"]
        except Exception as exc:
            self.issue("context_invalid", "/context", str(exc),
                       "请明确输入、算法说明、来源文件及读取预算，不从历史测试补默认值。")
            return report
        inputs, descriptors = self.inputs(), self.descriptors()
        p = request["payload"]
        for task_index, task in enumerate(p["tasks"]):
            ikey = (task["input_ref"]["package_sha256"], task["input_ref"]["signal_id"])
            d = task["detector"]
            dkey = (d["detector_id"], d["detector_version"], d["implementation_sha256"])
            self.task(task, inputs.get(ikey), descriptors.get(dkey), p["unknown_decisions"], task_index)
        report["plan_summary"] = {
            "request_id": p["request_id"], "tasks": p["tasks"],
            "unknown_decisions": p["unknown_decisions"], "resources": p["resources"],
            "batch_failure_policy": p["batch_failure_policy"],
            "inherited_inputs": [
                {"package_sha256": key[0], "signal_id": key[1],
                 "sample_rate_hz": doc["payload"]["sample_rate_hz"],
                 "time_mapping": doc["payload"]["time_mapping"],
                 "validity": doc["payload"]["validity"], "units": doc["payload"]["units"],
                 "frequency_coverage": doc["payload"]["frequency_coverage"],
                 "beam_source": doc["payload"]["beam_source"],
                 "limitations": doc["payload"]["limitations"]}
                for key, (doc, _) in inputs.items()
                if key in {(t["input_ref"]["package_sha256"], t["input_ref"]["signal_id"]) for t in p["tasks"]}
            ],
        }
        if any(task["products"]["save"] for task in p["tasks"]) and p["resources"]["persistence"] != "saved":
            self.issue("save_plan_conflict", "/payload/resources", "Save selected but persistence is session.",
                       "请明确保存位置和策略，不代替用户选择。")
        self.unchanged()
        report["adapter_checks"] = self.adapter_checks
        selected_keys = {t["input_ref"]["package_sha256"] + ":" + t["input_ref"]["signal_id"] for t in p["tasks"]}
        if selected_keys and all(self.adapter_checks.get(k, {}).get("adapter_status") == "verified"
                                 for k in selected_keys):
            report["execution_blockers"].remove("upstream_adapter_semantics_not_verified")
            report["execution_blockers"].remove("waveform_values_mask_values_and_algorithm_frame_rules_not_verified")
            report["execution_blockers"].append("algorithm_frame_rules_not_verified")
            report["checked_scope"] = "declared_plan_bound_files_and_verified_handoff_mapping"
        report["verified_sources"] = sorted(self.sources.values(), key=lambda x: x["sha256"])
        report["source_bytes_read"] = self.read_bytes
        request_scope = copy.deepcopy(request)
        request_scope["payload"].pop("approval")
        scope = {"preflight_version": REVIEW_VERSION, "request": request_scope, "context": self.context,
                 "documents": self.document_digests, "sources": report["verified_sources"],
                 "adapter_checks": self.adapter_checks}
        report["plan_sha256"] = digest(scope)
        report["request_id"] = p["request_id"]
        blocked = any(x["blocking"] for x in self.issues)
        report["review_status"] = "blocked" if blocked else "review_complete_pending_confirmation"
        if p["approval"]["status"] == "confirmed":
            report["confirmation_status"] = "unverified_request_claim"
        if confirmation is not None:
            try:
                helper_check(confirmation, "ConfirmationReceipt")
                recorded_evidence = {
                    "evidence_version": VERSION, "actor": "user", "decision": "confirm_reviewed_plan",
                    "request_id": confirmation["request_id"], "plan_sha256": confirmation["plan_sha256"],
                    "statement": confirmation["user_statement"], "reference": confirmation["user_reference"],
                }
                if confirmation["evidence_sha256"] != digest(recorded_evidence):
                    raise ValueError("Receipt statement/evidence digest mismatch.")
                if (confirmation["plan_sha256"] != report["plan_sha256"] or
                        confirmation["request_id"] != p["request_id"]):
                    report["confirmation_status"] = "stale"
                elif blocked:
                    report["confirmation_status"] = "invalidated_by_review_blocker"
                else:
                    report["confirmation_status"] = "recorded_current"
                    report["review_status"] = "review_complete_confirmation_recorded"
            except Exception as exc:
                report["confirmation_status"] = "invalid"
                self.issue("confirmation_invalid", "/confirmation", str(exc),
                           "请核对独立确认记录；不将请求中的 confirmed 当作真实同意。")
                report["review_status"] = "blocked"
        elif blocked and p["approval"]["status"] == "confirmed":
            report["confirmation_status"] = "invalidated_by_review_blocker"
        return report


def review(request, context, root, confirmation=None):
    return Review(root, context).run(request, confirmation)


def record_confirmation(report, evidence, output, source_root):
    """Called only after the operator obtains the actual user statement; not authentication."""
    helper_check(evidence, "ConfirmationEvidence")
    if report["review_status"] != "review_complete_pending_confirmation":
        raise ValueError("Only a fresh, unblocked review can have its user statement recorded.")
    if evidence["plan_sha256"] != report["plan_sha256"] or evidence["request_id"] != report["request_id"]:
        raise ValueError("Evidence refers to another request or plan. Ask again; do not rewrite evidence.")
    destination = Path(output).absolute()
    parent = destination.parent.resolve(strict=True)
    root = Path(source_root).resolve(strict=True)
    if parent == root or root in parent.parents:
        raise ValueError("Confirmation output must be outside the readonly source root.")
    receipt = {"receipt_version": VERSION, "request_id": report["request_id"],
               "plan_sha256": report["plan_sha256"], "evidence_sha256": digest(evidence),
               "user_statement": evidence["statement"], "user_reference": evidence["reference"],
               "recorded_at": datetime.now(timezone.utc).isoformat(),
               "authority": "recorded_user_statement_not_authenticated",
               "scope": "preflight_plan_only_not_execution", "can_execute": False}
    helper_check(receipt, "ConfirmationReceipt")
    # Exclusive create: never overwrite input, previous receipt, or a symlink.
    with (parent / destination.name).open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "record-confirmation"):
        sub = commands.add_parser(name)
        sub.add_argument("request", type=Path)
        sub.add_argument("--context", required=True, type=Path)
        sub.add_argument("--source-root", required=True, type=Path)
        if name == "review":
            sub.add_argument("--confirmation", type=Path)
        else:
            sub.add_argument("--user-evidence", required=True, type=Path)
            sub.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        request = explicit_json(args.request)
        context = explicit_json(args.context)
        confirmation = explicit_json(args.confirmation) if getattr(args, "confirmation", None) else None
        report = review(request, context, args.source_root, confirmation)
        # Re-read explicit top-level documents to detect normal concurrent changes.
        if request != explicit_json(args.request) or context != explicit_json(args.context):
            raise ValueError("Request/context changed during review.")
        if args.command == "record-confirmation":
            receipt = record_confirmation(report, explicit_json(args.user_evidence), args.out, args.source_root)
            output = {"confirmation_recorded": True, "receipt": receipt, "can_execute": False}
            status = 0
        else:
            output = report
            status = 1 if report["review_status"] == "blocked" or report["confirmation_status"] in (
                "stale", "invalid", "invalidated_by_review_blocker") else 0
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return status
    except Exception as exc:
        print(json.dumps({"review_status": "blocked", "can_execute": False,
                          "execution_status": "not_run", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
