#!/usr/bin/env python3
"""Inspection v0.2 -> explicit, lossless NPY handoff; NEVER runs beamforming."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import preflight as pf

VERSION = "0.1"
MAX_JSON_BYTES = 32 * 1024**2
REFERENCE = {"path": pf.STR, "sha256": pf.STR}
APPROVAL = {"status": pf.Choice(("confirmed",)), "scope_sha256": pf.STR,
            "evidence": pf.STR,
            "confirmation": {"method": pf.Choice(("user",)), "reference": pf.STR}}
REQUEST = {
    "handoff_version": pf.Choice((VERSION,)),
    "inspection_result": REFERENCE,
    "sample_range": pf.RANGE,
    "channel_indices": pf.Array(pf.UINT, minimum=1),
    "identity": {"data_role": pf.Choice(("sensor_array", "single_sensor", "beamformed")),
                 "channel_ids": pf.IDS, "role_evidence": pf.STR, "mapping_evidence": pf.STR},
    "processing_history": {"values": pf.Array(pf.STR), "evidence": pf.STR},
    "time_reference": {"kind": pf.Choice(("relative", "utc")), "origin": pf.STR},
    "units_policy": pf.Choice(("preserve_report_value_or_unknown",)),
    "inspection_linkage": pf.Choice(("accept_size_mtime_link_not_historical_content_hash",)),
    "limitations_acknowledgement": pf.STR,
    "output": {"directory": pf.STR, "dtype": pf.Choice(("float64",)),
               "conversion": pf.Choice(("exact_numeric_no_scaling",)),
               "block_samples": pf.PINT, "max_read_mib": pf.POS,
               "max_artifact_bytes": pf.PINT},
    "approval": APPROVAL,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolved(path, base="."):
    p = Path(path).expanduser()
    return (p if p.is_absolute() else Path(base) / p).resolve()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(path):
    p = Path(path).resolve(strict=True)
    require(p.is_file(), "来源必须是普通文件。")
    s = p.stat()
    return {"path": str(p), "size_bytes": s.st_size, "mtime_ns": s.st_mtime_ns}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_json(path, value):
    with Path(path).open("xb") as handle:
        handle.write(json_bytes(value))


def load_json(path, expected_sha256=None):
    p = Path(path)
    require(p.stat().st_size <= MAX_JSON_BYTES, "JSON 超过32 MiB读取上限；不截断。")
    data = p.read_bytes()
    require(len(data) <= MAX_JSON_BYTES, "读取期间 JSON 超过大小上限。")
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        require(sha == expected_sha256, "JSON 内容摘要不匹配；不使用变化后的记录。")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "JSON 含重复键：" + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("JSON 含非标准数值：" + value)

    value = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    require(isinstance(value, dict), "JSON 根节点必须是对象。")
    def finite_json(item):
        if isinstance(item, dict):
            for v in item.values():
                finite_json(v)
        elif isinstance(item, list):
            for v in item:
                finite_json(v)
        elif isinstance(item, float):
            require(math.isfinite(item), "JSON 数值溢出为非有限值。")
    finite_json(value)
    return value, sha, data


def fingerprint(config):
    return pf.canonical_digest({k: v for k, v in config.items() if k != "approval"})


def read_inspection(path, expected_sha256=None):
    path = resolved(path)
    report, sha, data = load_json(path, expected_sha256)
    require(report.get("schema_version") == "0.2", "只接受数据检查 schema_version=0.2；不猜测旧字段。")
    require(report.get("request", {}).get("operation") == "run", "probe 结果不能替代读取检查结果。")
    require(report.get("status") in ("completed", "partial"), "上游结果未完成可用读取，或已失败。")
    require(report.get("results_valid") is not False and
            report.get("source_consistency") == "unchanged_size_and_mtime", "上游源一致性失效。")
    source = report["source"]
    require(snapshot(source["path"]) == source, "原始文件大小/mtime/路径与检查时不一致；需重新核查。")
    require(report["probe"]["source"] == source, "探查与检查来源不一致。")
    d = report["dataset"]
    shape, axis = d["original_shape"], d["original_sample_axis"]
    require(isinstance(shape, list) and len(shape) in (1, 2) and
            all(type(v) is int and v > 0 for v in shape) and type(axis) is int and
            0 <= axis < len(shape), "上游形状或样本轴无效。")
    n, c = shape[axis], shape[1-axis] if len(shape) == 2 else 1
    lo, hi = d["sample_range"]
    channels = d["channel_indices"]
    require(type(lo) is int and type(hi) is int and 0 <= lo < hi <= n, "上游样本范围无效。")
    require(isinstance(channels, list) and channels and
            all(type(i) is int and 0 <= i < c for i in channels) and
            channels == sorted(set(channels)), "上游通道索引无效或重排。")
    require(d["standard_axes"] == ["samples", "channels"] and
            d["view_shape"] == [hi-lo, len(channels)] and d["source_values_modified"] is False,
            "上游不是保持原值的标准二维视图。")
    require(len(d["channel_ids"]) == len(channels) and
            len(set(d["channel_ids"])) == len(channels), "上游通道标识与列数不符。")
    selection = report["selection"]
    require(selection["field"] == d["field"] and selection["sample_axis"] == axis and
            selection["shape"] == shape, "上游字段、轴或形状记录冲突。")
    rows = report["checks"]
    checks = {row["id"]: row for row in rows}
    require(len(checks) == len(rows) == 21, "检查清单须为当前0.2版完整的21个唯一子项。")
    for key in ("integrity.acquisition_continuity", "channel_quality.clipping",
                "channel_quality.synchronization", "channel_quality.calibration"):
        require(key in checks, "缺少必须保留的能力状态：" + key)
    for key in ("reading.selection", "reading.samples", "standardization.view", "integrity.source_stability"):
        require(checks.get(key, {}).get("status") == "completed", "交接前置子项未完成：" + key)
    for key in ("reading.samples", "standardization.view"):
        cov = checks[key]["coverage"]
        require(cov["sample_range"] == [lo, hi] and cov["channel_indices"] == channels,
                "读取/标准化的实际覆盖与 dataset 不一致。")
    return path, report, sha, data


def review(path):
    source, report, sha, _ = read_inspection(path)
    d = report["dataset"]
    return {
        "handoff_version": VERSION, "execution_status": "not_run", "can_beamform": False,
        "inspection_result": {"path": str(source), "sha256": sha},
        "available_input_facts": d,
        "inspection_status": report["status"], "checks": report["checks"],
        "issues": report["issues"], "not_checked": report["not_checked"],
        "needs_confirmation": [
            "本次导出的原始样本区间与通道列表；不自动选首段或全部通道。",
            "原始阵元/单阵元/已形成波束的身份及依据；不能凭通道数量判断。",
            "逐列身份映射；index:N 仅为位置标签，不能冒充已确认阵元。",
            "原始处理历史；未知明确保留 unknown，不能填成未经处理。",
            "时间原点；只知道相对时间时不编造 UTC。",
            "按原值精确转 float64 的导出、预算及上游仅有 stat 一致性证据的限制。",
        ],
        "source_linkage_limit": "旧检查仅记录大小/mtime；现在计算哈希不能追认旧检查时的内容哈希。",
    }


def check(config, base_dir="."):
    pc = pf.Preflight({}, base_dir)
    resource = None
    if pc.schema(config, REQUEST, "$"):
        if config["approval"]["scope_sha256"] != fingerprint(config):
            pc.issue("STALE_HANDOFF_APPROVAL", "approval", "导出范围或设置改变，需重新确认。")
        try:
            ref = config["inspection_result"]
            path, report, _, _ = read_inspection(resolved(ref["path"], base_dir), ref["sha256"])
            d = report["dataset"]
            lo, hi = config["sample_range"]
            ch = config["channel_indices"]
            require(0 <= d["sample_range"][0] <= lo < hi <= d["sample_range"][1],
                    "导出范围必须在实际已读取范围内；不静默扩大。")
            require(ch == sorted(set(ch)) and set(ch).issubset(d["channel_indices"]),
                    "通道必须为已读取通道的唯一升序子集；不重排或自动删道。")
            identity = config["identity"]
            ids = identity["channel_ids"]
            require(len(ids) == len(ch) and len(set(ids)) == len(ids), "确认的通道 ID 数量或唯一性有误。")
            require(d["channel_identity"]["state"] in ("confirmed", "missing"),
                    "上游通道身份有歧义或冲突，须先解决，不能用新映射覆盖。")
            if d["channel_identity"]["state"] == "confirmed":
                known = [d["channel_ids"][d["channel_indices"].index(i)] for i in ch]
                require(ids == known, "新的列身份与上游确认映射冲突，须先解决，不能覆盖。")
            role = identity["data_role"]
            require((role != "sensor_array" or len(ch) >= 2) and
                    (role != "single_sensor" or len(ch) == 1), "数据身份与通道数量冲突。")
            fs = d["sample_rate_hz"]
            require(fs["state"] == "confirmed" and type(fs["value"]) in (int, float) and
                    math.isfinite(fs["value"]) and fs["value"] > 0 and fs["sources"],
                    "采样率未确认或有冲突；先解决上游记录，不填经验值。")
            units = d["units"]
            require(units["state"] in ("confirmed", "missing"), "单位有歧义/冲突，不能转成 unknown 掩盖。")
            if units["state"] == "confirmed":
                require(isinstance(units["value"], str) and units["value"].strip(), "已确认单位缺少值。")
            require("not_checked" in report and isinstance(report["not_checked"], list), "缺少上游未检查项清单。")
            out = resolved(config["output"]["directory"], base_dir)
            require(not out.exists() and not out.is_relative_to(path.parent),
                    "导出目录须全新且在原检查结果目录之外；不覆盖旧结果。")
            estimated = (hi-lo) * len(ch) * 8 + 3 * path.stat().st_size + 4 * 1024**2
            resource = {"samples": hi-lo, "channels": len(ch), "artifact_bytes_estimate": estimated,
                        "working_memory_limit_mib": config["output"]["max_read_mib"],
                        "note": "读取器预算是保守数组估算，不是操作系统硬内存配额。"}
            require(estimated <= config["output"]["max_artifact_bytes"], "产物超过确认预算；不缩短片段或减少通道。")
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError) as exc:
            pc.issue("HANDOFF_INPUT", "inspection_result_or_selection", str(exc), "invalid")
    return {"handoff_version": VERSION, "execution_status": "not_run",
            "preflight_status": "passed" if not pc.issues else "needs_input",
            "can_attempt_export": not pc.issues, "can_beamform": False,
            "issues": pc.issues, "resource_estimate": resource,
            "checked": "JSON, approval, stored metadata and file stat only; no waveform read, FFT or beamforming"}


def reader_module():
    # Only an installed sibling skill, never a path supplied by report content.
    folder = Path(__file__).resolve().parents[2] / "underwater-data-inspection" / "scripts"
    expected = folder / "acoustic_inspection" / "readers.py"
    require(expected.is_file(), "缺少同级 underwater-data-inspection 读取器；先安装，不自动下载或另猜格式。")
    sys.path.insert(0, str(folder))
    try:
        from acoustic_inspection import readers
    finally:
        sys.path.pop(0)
    require(Path(readers.__file__).resolve() == expected.resolve(), "已加载的读取器来自其他位置，停止交接。")
    return readers


def make_draft(manifest, handoff_path, handoff_sha):
    data = copy.deepcopy(manifest["input"])
    data["source"]["path"] = str(handoff_path.parent / "waveforms.npy")
    role = data["data_role"]
    plan = {"schema_version": "0.4", "input": data, "parameter_records": []}
    draft = {"execution_version": "0.4", "plan": plan,
             "inspection_handoff": {"path": str(handoff_path), "sha256": handoff_sha},
             "numerics": None, "analysis": None, "approval": None}
    if role != "sensor_array":
        bypass, _, _ = load_json(Path(__file__).resolve().parents[1] / "assets" / "bypass-request.json")
        bypass["source_handoff"] = {"path": str(handoff_path), "sha256": handoff_sha}
        return bypass, [
            "这是旁路输入，不进入阵列波束形成；使用 bypass_handoff.py，只传数据与元信息，不检测。",
            "从已导出的 channel_ids 中明确选择交接信号及顺序；不默认全部或第一列。",
            "逐信号记录已有算法/固定方向及依据；单阵元算法和方向为null（不适用）。",
            "已有波束的未知算法/方向、频带或有效性需询问处理方式；仅经明确同意才能保持unknown传递。",
            "有效区间若已知，须明确输出相对半开区间；未知不生成全有效掩码。",
            "补齐新目录、资源预算、限制接受记录并单独确认旁路摘要；导出授权不等于旁路授权。",
        ]
    plan.update({
        "algorithms": None,
        "geometry": {"channel_ids": data["channels"],
                     "coordinates_m": manifest["selected_geometry_candidate_m"],
                     "coordinate_system": None, "reference_m": None, "model_kind": None,
                     "model_description": None},
        "propagation": None, "synchronization": None, "calibration": None,
        "direction_plan": None,
        "processing": {"channels": data["channels"], "band_hz": None,
                       "preprocessing": None, "precision": None},
        "transform": None,
        "output": {"directory": None, "format": "npy", "save_time_domain": None,
                   "beam_selection": "explicit_indices", "time_domain_beam_indices": None,
                   "auxiliary_products": None, "weights": "save_all", "max_waveform_bytes": None},
    })
    template, _, _ = load_json(Path(__file__).resolve().parents[1] / "assets" / "execution-request.json")
    draft["numerics"] = template["numerics"]
    draft["numerics"]["source_sha256"] = manifest["waveform"]["sha256"]
    questions = [
        "选择 CBF、MVDR 或两者，再补对应算法参数；不自动均匀加权、加载或选训练区间。",
        "确认阵元坐标及对应关系、坐标系、参考位置、实测/名义模型；上游坐标只作候选，不补零。",
        "确认传播模型、声速、同步与标定的依据或明确接受的假设。",
        "明确指定方向或网格及角度定义；不选最强波束、不自动扫描。",
        "确认处理频带、预处理、STFT/合成、端点与边界、精度、数值门槛和资源预算。",
        "明确时域保留方向、所需谱图及其分析/显示设置、新结果目录。",
        "核对输入事实和限制后填写 parameter_records；整套执行配置另需真实 approval。",
    ]
    return draft, questions


def prepare(config, base_dir="."):
    report = check(config, base_dir)
    require(report["can_attempt_export"], json.dumps(report, ensure_ascii=False))
    ref = config["inspection_result"]
    inspection, original, inspection_sha, inspection_bytes = read_inspection(resolved(ref["path"], base_dir), ref["sha256"])
    d = original["dataset"]
    raw = Path(original["source"]["path"])
    destination = resolved(config["output"]["directory"], base_dir)
    nearest = destination.parent
    while not nearest.exists():
        nearest = nearest.parent
    require(shutil.disk_usage(nearest).free >= report["resource_estimate"]["artifact_bytes_estimate"],
            "磁盘不足；不改变请求范围。")
    readers = reader_module()
    import numpy as np
    reader_files = {str(p.relative_to(Path(readers.__file__).parent)): digest_file(p)
                    for p in Path(readers.__file__).parent.glob("*.py")}
    source_sha = digest_file(raw)
    require(snapshot(raw) == original["source"], "导出前原始文件已变动。")
    info = readers.probe(raw)
    selected = readers.select_field(info, {"field": d["field"]})
    require(info["format"] == original["probe"]["format"] and
            selected["shape"] == d["original_shape"] and selected["dtype"] == d["original_dtype"],
            "当前格式、字段形状或编码与上游记录不一致。")
    if info["format"] == "wav":
        require(info["header_sample_rate_hz"] == d["sample_rate_hz"]["value"], "WAV 实际采样率与已确认值冲突。")
    dtype = np.dtype(selected["dtype"])
    require(dtype.kind in "iuf" and dtype.itemsize <= 8, "不支持精确转 float64 的源编码。")
    cfg = {"sample_axis": d["original_sample_axis"], "max_read_mib": config["output"]["max_read_mib"]}
    source = readers.Source(raw, info, selected, cfg)
    output = None
    created = False
    try:
        lo, hi = config["sample_range"]
        channels = config["channel_indices"]
        block_size = source.block_size(config["output"]["block_samples"])
        destination.mkdir(parents=True, exist_ok=False)
        created = True
        output = np.lib.format.open_memmap(destination / "waveforms.npy", mode="w+",
                                            dtype=np.float64, shape=(hi-lo, len(channels)))
        for start in range(lo, hi, block_size):
            stop = min(hi, start + block_size)
            block = source.read(start, stop, channels)
            require(block.shape == (stop-start, len(channels)) and block.dtype == dtype,
                    "实际读取块的形状或类型发生变化，停止导出。")
            require(np.isfinite(block).all(), "导出范围含 NaN/Inf；不修复、删样本或删道。")
            if dtype.kind in "iu":
                require(not np.any(block > 2**53) and
                        (dtype.kind != "i" or not np.any(block < -(2**53))),
                        "整数超出本接口允许的 float64 精确范围，停止，不静默丢失精度。")
            output[start-lo:stop-lo] = block
        output.flush()
        output._mmap.close()
        output = None
        source.close()
        require(snapshot(raw) == original["source"] and digest_file(raw) == source_sha,
                "导出期间源变化；不发布完成清单。")
        read_inspection(inspection, inspection_sha)
        require(reader_files == {str(p.relative_to(Path(readers.__file__).parent)): digest_file(p)
                                 for p in Path(readers.__file__).parent.glob("*.py")},
                "导出期间读取器代码改变，停止发布。")
        with (destination / "inspection_result.json").open("xb") as handle:
            handle.write(inspection_bytes)
        write_json(destination / "confirmed_handoff_request.json", config)
        wave_stat = snapshot(destination / "waveforms.npy")
        wave_sha = digest_file(destination / "waveforms.npy")
        identity = config["identity"]
        units = d["units"]["value"] if d["units"]["state"] == "confirmed" else "unknown"
        inp = {"source": {"path": "waveforms.npy", "field": "__array__",
                          "size_bytes": wave_stat["size_bytes"], "mtime_ns": wave_stat["mtime_ns"]},
               "representation": "time_waveform_real", "data_role": identity["data_role"],
               "axes": ["sample", "channel"], "shape": [hi-lo, len(channels)], "dtype": "float64",
               "sample_rate_hz": d["sample_rate_hz"]["value"], "sample_range": [0, hi-lo],
               "channels": identity["channel_ids"], "units": units,
               "time_reference": config["time_reference"],
               "processing_history": config["processing_history"]["values"]}
        geometry = d["array_geometry"]
        candidate = ([geometry["coordinates_m"][i] for i in channels]
                     if geometry["state"] == "confirmed" else None)
        manifest = {
            "handoff_version": VERSION, "export_status": "completed",
            "handoff_status": "prepared_not_authorized_for_beamforming",
            "development_validation": "v043_scoped_regression_passed",
            "input": inp, "waveform": {"path": "waveforms.npy", "sha256": wave_sha},
            "original_source": dict(original["source"], sha256_at_export=source_sha),
            "source_sample_range": [lo, hi], "source_channel_indices": channels,
            "original_field": d["field"], "original_dtype": d["original_dtype"],
            "original_sample_axis": d["original_sample_axis"],
            "original_sample_zero_time_reference": config["time_reference"],
            "export_sample_zero_source_sample": lo,
            "identity_evidence": identity,
            "processing_history_evidence": config["processing_history"],
            "selected_geometry_candidate_m": candidate,
            "inspection_result": {"path": "inspection_result.json", "sha256": inspection_sha},
            "inspection_origin_path": str(inspection),
            "inspection_linkage": config["inspection_linkage"],
            "inspection_linkage_limit": "检查时仅有大小/mtime；本次前后哈希不追认历史内容，也不是并发快照。",
            "limitations_acknowledgement": config["limitations_acknowledgement"],
            "checks": original["checks"], "upstream_issues": original["issues"],
            "not_checked": original["not_checked"], "inspection_readiness": original["readiness"],
            "metadata_evidence": {"sample_rate_hz": d["sample_rate_hz"], "units": d["units"],
                                  "channel_identity": d["channel_identity"], "array_geometry": geometry},
            "export_transformations": d["transformations"] + ["explicit subrange/channel selection",
                                      "exact numeric conversion to float64; no signal preprocessing"],
            "reader_files_sha256": reader_files,
            "request_scope_sha256": fingerprint(config),
            "artifacts": [{"path": name, "sha256": digest_file(destination/name),
                           "size_bytes": (destination/name).stat().st_size}
                          for name in ("waveforms.npy", "inspection_result.json", "confirmed_handoff_request.json")],
            "editable_draft": ("execution-draft.json" if inp["data_role"] == "sensor_array" else "bypass-request.json"),
            "draft_integrity_note": "配置草稿与问题清单可编辑，不属于不可变源数据产物。",
        }
        manifest_sha = hashlib.sha256(json_bytes(manifest)).hexdigest()
        draft, questions = make_draft(manifest, destination / "handoff.json", manifest_sha)
        write_json(destination / manifest["editable_draft"], draft)
        write_json(destination / "questions.json", {"parameter_status": "needs_input", "can_execute": False,
                                                   "questions": questions})
        write_json(destination / "handoff.pending.json", manifest)
        (destination / "handoff.pending.json").rename(destination / "handoff.json")
        return {"export_status": "completed", "handoff": str(destination/"handoff.json"),
                "draft": str(destination/manifest["editable_draft"]), "can_beamform": False,
                "next_step": "解决 questions 并核对参数；阵列走 execute.py，旁路走 bypass_handoff.py；导出 approval 不授权后续操作。"}
    except Exception as exc:
        if created:
            write_json(destination / "failure.json", {"export_status": "failed", "usable": False, "error": str(exc)})
        raise
    finally:
        if output is not None:
            output._mmap.close()
        source.close()


def validate_binding(reference, plan, numerics, base_dir="."):
    """Small metadata reads + NPY stat only. Executor separately verifies NPY content."""
    pc = pf.Preflight({}, base_dir)
    require(pc.schema(reference, REFERENCE, "inspection_handoff"), "交接引用缺少 path/sha256 或含未知键。")
    path = resolved(reference["path"], base_dir)
    manifest, _, _ = load_json(path, reference["sha256"])
    require(manifest.get("handoff_version") == VERSION and manifest.get("export_status") == "completed",
            "交接数据包未完成，或版本不支持。")
    inp = manifest["input"]
    require(pc.schema(inp, pf.INPUT, "handoff.input"), "交接输入契约无效。")
    require(inp["source"]["path"] == "waveforms.npy" and manifest["waveform"]["path"] == "waveforms.npy",
            "交接文件名不符，不接收越界路径。")
    wave = path.parent / "waveforms.npy"
    require(not wave.is_symlink(), "交接波形不能是符号链接。")
    require(resolved(plan["input"]["source"]["path"], base_dir) == wave.resolve(), "执行输入不是交接包中的波形。")
    expected = copy.deepcopy(inp)
    expected["source"]["path"] = str(wave.resolve())
    actual = copy.deepcopy(plan["input"])
    actual["source"]["path"] = str(resolved(actual["source"]["path"], base_dir))
    # A later, explicitly approved processing subrange is allowed within the exported array.
    actual["sample_range"] = expected["sample_range"]
    require(actual == expected, "执行输入的采样率、身份、列序、单位、时间或来源与交接不一致，不能静默覆盖。")
    stat = wave.stat()
    require(stat.st_size == inp["source"]["size_bytes"] and stat.st_mtime_ns == inp["source"]["mtime_ns"],
            "交接波形大小/mtime 已改变。")
    require(numerics["source_sha256"] == manifest["waveform"]["sha256"], "执行源摘要与交接波形不一致。")
    offset = manifest["export_sample_zero_source_sample"]
    require(type(offset) is int and offset >= 0 and
            manifest["source_sample_range"] == [offset, offset + inp["shape"][0]],
            "交接原始样本映射无效。")
    ids = manifest["source_channel_indices"]
    require(len(ids) == inp["shape"][1] and all(type(i) is int and i >= 0 for i in ids) and
            ids == sorted(set(ids)), "交接通道映射无效。")
    evidence = manifest["inspection_result"]
    require(evidence["path"] == "inspection_result.json", "检查证据路径不合法。")
    copied = path.parent / evidence["path"]
    require(not copied.is_symlink(), "检查证据不能是符号链接。")
    copied_report, _, _ = load_json(copied, evidence["sha256"])
    require(copied_report.get("schema_version") == "0.2" and
            copied_report.get("results_valid") is not False and
            copied_report.get("status") in ("completed", "partial") and
            copied_report.get("source_consistency") == "unchanged_size_and_mtime",
            "复制的检查证据无效。")
    require(manifest["checks"] == copied_report["checks"] and
            manifest["not_checked"] == copied_report["not_checked"] and
            manifest["upstream_issues"] == copied_report["issues"],
            "交接记录篡改了上游子项状态、问题或未检查项。")
    artifacts = manifest["artifacts"]
    names = [a["path"] for a in artifacts]
    require(len(names) == 3 and set(names) ==
            {"waveforms.npy", "inspection_result.json", "confirmed_handoff_request.json"},
            "交接产物清单不完整或含额外路径。")
    for artifact in artifacts:
        item = path.parent / artifact["path"]
        require(not item.is_symlink() and item.stat().st_size == artifact["size_bytes"],
                "交接产物大小变化或为符号链接。")
        if artifact["path"] == "waveforms.npy":
            require(artifact["sha256"] == manifest["waveform"]["sha256"], "波形摘要记录冲突。")
        else:
            require(digest_file(item) == artifact["sha256"], "交接证据文件摘要变化。")
    request, _, _ = load_json(path.parent / "confirmed_handoff_request.json")
    require(pc.schema(request, REQUEST, "handoff.request"), "包内导出请求无效。")
    request_sha = fingerprint(request)
    require(request_sha == manifest["request_scope_sha256"] ==
            request["approval"]["scope_sha256"], "导出请求与确认范围不一致。")
    require(request["inspection_result"]["sha256"] == evidence["sha256"] and
            request["sample_range"] == manifest["source_sample_range"] and
            request["channel_indices"] == ids and request["identity"]["channel_ids"] == inp["channels"] and
            request["identity"]["data_role"] == inp["data_role"] and
            request["time_reference"] == inp["time_reference"] and
            request["processing_history"]["values"] == inp["processing_history"],
            "导出请求与交接身份、范围、时间或处理历史不一致。")
    facts = copied_report["dataset"]
    require(facts["sample_rate_hz"]["state"] == "confirmed" and
            facts["sample_rate_hz"]["value"] == inp["sample_rate_hz"], "采样率不符合上游已确认事实。")
    require(inp["units"] == (facts["units"]["value"] if facts["units"]["state"] == "confirmed" else "unknown"),
            "交接单位不符合上游记录。")
    for key in ("original_source", "inspection_readiness", "inspection_linkage", "inspection_linkage_limit",
                "metadata_evidence", "identity_evidence", "processing_history_evidence", "export_transformations"):
        require(key in manifest, "交接缺少追溯字段：" + key)
    require({key: manifest["original_source"][key] for key in ("path", "size_bytes", "mtime_ns")} ==
            copied_report["source"], "原始来源与上游检查记录冲突。")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review", "check", "digest", "prepare"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "review":
            result = review(args.path)
        else:
            config, _, _ = load_json(args.path)
            base = args.path.resolve().parent
            if args.command == "digest":
                result = {"scope_sha256": fingerprint(config), "authorizes_export": False}
            elif args.command == "check":
                result = check(config, base)
            else:
                result = prepare(config, base)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 2 if args.command == "check" and not result["can_attempt_export"] else 0
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError,
            RecursionError, MemoryError, ImportError, RuntimeWarning, FloatingPointError) as exc:
        print(json.dumps({"status": "blocked", "can_beamform": False, "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
