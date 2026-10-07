#!/usr/bin/env python3
"""Explicit saved-beam handoff. No FFT, detection, beam selection or repair."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

VERSION = "0.1"
IMPLEMENTATION_VERSION = "0.1.2"
PURPOSE = "waveform_and_metadata_transfer_only"
MAX_JSON = 32 * 1024**2
SHA = re.compile(r"[0-9a-f]{64}")
PROVENANCE_KEYS = (
    "sample_rate_hz", "units", "time_reference", "source_sample_range",
    "first_sample_offset_seconds", "time_alignment", "reference_m", "channel_ids",
    "direction_plan", "direction_basis", "frequency_coverage", "processing_history",
    "amplitude_convention", "valid_sample_intervals", "interval_convention",
    "validity_limit", "source_sha256", "validation_status", "limitations",
    "original_source_sample_range", "original_source_channel_indices", "time_mapping",
    "upstream_inspection", "inspection_handoff", "execution_scope_sha256",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def positive_int(value):
    return type(value) is int and value > 0


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def keys(value, expected, name):
    require(isinstance(value, dict) and set(value) == set(expected),
            name + " 字段缺失或含不支持的字段。")


def resolve(path, base):
    require(nonempty(path), "路径未确认。")
    p = Path(path).expanduser()
    return (p if p.is_absolute() else Path(base) / p).resolve()


def contained(base, name):
    require(nonempty(name) and not Path(name).is_absolute(), "产物必须使用包内相对路径。")
    base = Path(base).resolve()
    p = (base / name).resolve()
    require(p.is_relative_to(base) and p != base, "产物路径越出包目录。")
    return p


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def load_json(path, expected=None):
    require(Path(path).stat().st_size <= MAX_JSON, "JSON 超过32 MiB，拒绝截断。")
    raw = Path(path).read_bytes()
    require(len(raw) <= MAX_JSON, "读取期间 JSON 超过上限。")
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None:
        require(isinstance(expected, str) and SHA.fullmatch(expected) and digest == expected,
                "JSON 摘要不匹配。")

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "JSON 重复键：" + key)
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("JSON 非有限数：" + value)

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    def finite(item):
        if isinstance(item, dict):
            for child in item.values():
                finite(child)
        elif isinstance(item, list):
            for child in item:
                finite(child)
        elif isinstance(item, float):
            require(math.isfinite(item), "JSON 数值溢出。")
    finite(value)
    require(isinstance(value, dict), "JSON 根节点须是对象。")
    return value, digest, raw


def write_json(path, value):
    with Path(path).open("xb") as f:
        f.write(encode(value))


def fingerprint(request):
    value = {k: v for k, v in request.items() if k != "approval"}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def artifact_index(report, base):
    records = report.get("artifacts")
    require(isinstance(records, list), "缺少产物清单。")
    index = {}
    for item in records:
        require(isinstance(item, dict), "产物记录无效。")
        name = item.get("path")
        contained(base, name)
        require(name not in index, "重复产物路径。")
        require(positive_int(item.get("size_bytes")) and
                isinstance(item.get("sha256"), str) and SHA.fullmatch(item["sha256"]),
                "产物尺寸或摘要无效。")
        index[name] = item
    return index


def verify_files(index, base, names, content=False):
    for name in names:
        require(name in index, "完成清单未登记文件：" + name)
        path = contained(base, name)
        require(path.is_file() and path.stat().st_size == index[name]["size_bytes"],
                "产物不存在或尺寸改变：" + name)
        if content:
            require(file_hash(path) == index[name]["sha256"], "产物摘要改变：" + name)


def interval_check(intervals, n):
    require(isinstance(intervals, list) and intervals, "没有明确的有效区间。")
    previous = 0
    for pair in intervals:
        require(isinstance(pair, list) and len(pair) == 2 and
                all(type(v) is int for v in pair), "有效区间必须为整数半开区间。")
        a, b = pair
        require(previous <= a < b <= n, "有效区间重叠、逆序或越界。")
        previous = b


def read_result(path, expected=None):
    path = Path(path).resolve()
    result, digest, raw = load_json(path, expected)
    require(result.get("execution_version") == "0.4", "仅接受 execution_version=0.4；不猜测旧格式。")
    require("product_version" not in result, "本版只接主 execute.py 结果；补图包须另行明确原始时域来源，不追链猜测。")
    require(result.get("execution_status") == "completed" and
            result.get("parameter_status") == "complete", "上游没有完整成功结果。")
    require(result.get("data_role") == "beamformed" and result.get("axes") == ["sample", "beam"],
            "不是已形成波束的 sample×beam 时域数据。")
    algorithms = result.get("algorithms")
    require(isinstance(algorithms, list) and algorithms and
            all(a in ("cbf", "mvdr") for a in algorithms) and len(set(algorithms)) == len(algorithms),
            "算法身份不明确。")
    require(result.get("time_alignment") == "reference_position", "不支持的时间对齐规则。")
    require(isinstance(result.get("processing_history"), dict) and
            isinstance(result["processing_history"].get("upstream"), list) and
            isinstance(result["processing_history"].get("this_run"), list), "处理历史不完整。")
    require(isinstance(result.get("direction_plan"), dict) and
            result["direction_plan"].get("mode") in ("specified", "grid") and
            isinstance(result.get("direction_basis"), list) and len(result["direction_basis"]) == 3,
            "方向定义或坐标基缺失。")
    require(isinstance(result.get("frequency_coverage"), dict), "缺少已处理频带记录。")
    fs = result.get("sample_rate_hz")
    require(number(fs) and fs > 0, "采样率无效。")
    for field in PROVENANCE_KEYS[:18]:
        require(field in result and result[field] is not None, "缺少上游字段：" + field)
    require(nonempty(result["units"]), "单位须明确记录，未标定可保留 unknown。")
    time = result["time_reference"]
    require(isinstance(time, dict) and time.get("kind") in ("relative", "utc") and
            nonempty(time.get("origin")), "时间参考缺失。")
    require(number(result["first_sample_offset_seconds"]) and result["first_sample_offset_seconds"] >= 0,
            "样本零点时间偏移无效。")
    band = result["frequency_coverage"].get("requested_band_hz")
    bins = result["frequency_coverage"].get("actual_bin_centers_hz")
    require(isinstance(band, list) and len(band) == 2 and all(number(v) for v in band) and
            0 <= band[0] < band[1] <= fs / 2, "已处理频带无效。")
    require(isinstance(bins, list) and bins and all(number(v) for v in bins) and
            band[0] <= bins[0] <= bins[-1] <= band[1] and
            all(a < b for a, b in zip(bins, bins[1:])), "实际活动频点无效。")
    require(result.get("interval_convention") == "output-relative half-open", "有效区间索引基准不支持。")
    shape = result.get("shape_per_algorithm")
    saved = result.get("time_domain_retention", {}).get("saved")
    beams = result.get("beams")
    require(isinstance(beams, list), "缺少时域列映射。")
    index = artifact_index(result, path.parent)
    if saved is False and shape is None and beams == []:
        return result, digest, raw, index
    require(saved is True and isinstance(shape, list) and len(shape) == 2 and
            all(positive_int(v) for v in shape) and result.get("dtype") == "float64",
            "时域保存状态、形状或精度无效。")
    require(len(beams) == shape[1], "时域列数与 beams 不符。")
    scans = result.get("scan_beams")
    directions = result.get("directions_deg")
    require(isinstance(scans, list) and isinstance(directions, list) and len(scans) == len(directions),
            "完整扫描映射缺失。")
    seen = set()
    for j, beam in enumerate(beams):
        i = beam.get("scan_column")
        beam_id = beam.get("beam_id")
        require(nonempty(beam_id) and beam_id not in seen and type(beam.get("column")) is int and
                beam["column"] == j and type(i) is int and 0 <= i < len(scans), "保存列/扫描列映射无效。")
        require(beam.get("fixed_direction") is True and scans[i].get("beam_id") == beam_id and
                scans[i].get("scan_column") == i and beam.get("direction_deg") == directions[i] and
                beam["direction_deg"] == scans[i].get("direction_deg"), "波束方向或 ID 映射冲突。")
        require(isinstance(directions[i], list) and len(directions[i]) in (1, 2) and
                all(number(v) for v in directions[i]), "角度不是明确的有限数值。")
        seen.add(beam_id)
    require(result["time_domain_retention"].get("scan_beam_indices") ==
            [b["scan_column"] for b in beams], "保留索引与时域列映射冲突。")
    source_range = result["source_sample_range"]
    require(isinstance(source_range, list) and len(source_range) == 2 and
            all(type(v) is int for v in source_range) and
            0 <= source_range[0] < source_range[1] and source_range[1] - source_range[0] == shape[0],
            "样本范围与时域长度不一致。")
    original_range = result.get("original_source_sample_range", source_range)
    require(isinstance(original_range, list) and len(original_range) == 2 and
            all(type(v) is int for v in original_range) and 0 <= original_range[0] < original_range[1] and
            original_range[1] - original_range[0] == shape[0], "原始样本映射无效。")
    require(math.isclose(result["first_sample_offset_seconds"], original_range[0] / fs,
                         rel_tol=1e-12, abs_tol=1e-12), "原始样本与时间零点冲突。")
    interval_check(result["valid_sample_intervals"], shape[0])
    return result, digest, raw, index


def review(path):
    result, digest, _, index = read_result(path)
    names = [a + "_time.npy" for a in result["algorithms"]] if result["beams"] else []
    verify_files(index, Path(path).resolve().parent, names + ["valid_sample_mask.npy", "confirmed_config.json"])
    return {"source_result_sha256": digest, "time_domain_available": bool(names),
            "algorithms": result["algorithms"], "saved_beams": result["beams"],
            "sample_rate_hz": result["sample_rate_hz"], "units": result["units"],
            "frequency_coverage": result["frequency_coverage"],
            "valid_sample_intervals": result["valid_sample_intervals"],
            "provenance": {k: result[k] for k in PROVENANCE_KEYS if k in result},
            "source_issues": result.get("issues"),
            "source_configuration": {"path": str(contained(Path(path).resolve().parent, "confirmed_config.json")),
                                     "sha256": index["confirmed_config.json"]["sha256"]},
            "purpose": PURPOSE, "content_hashes_checked": False, "can_detect": False,
            "next_action": "明确算法和已保存 beam_id；无时域时须另行授权重新生成，不能从功率反推。"}


def validate(request, base):
    keys(request, ("handoff_version", "source_result", "selection", "sample_policy",
                   "units_policy", "limitations_acknowledgement", "output", "approval"), "交接请求")
    require(request["handoff_version"] == VERSION, "不支持的交接版本。")
    keys(request["source_result"], ("path", "sha256"), "source_result")
    source = resolve(request["source_result"]["path"], base)
    result, digest, raw, index = read_result(source, request["source_result"]["sha256"])
    require(result["beams"], "上游未保存时域，不能用谱/图替代。")
    selection = request["selection"]
    require(isinstance(selection, list) and selection, "必须明确算法和 beam_id，不自动选择。")
    pairs = []
    for selected in selection:
        keys(selected, ("algorithm", "beam_id"), "selection")
        require(selected["algorithm"] in result["algorithms"] and
                selected["beam_id"] in [b["beam_id"] for b in result["beams"]],
                "所选算法/波束没有保存时域。")
        pair = (selected["algorithm"], selected["beam_id"])
        require(pair not in pairs, "重复选择。")
        pairs.append(pair)
    require(request["sample_policy"] == "preserve_full_output_and_mask", "不自动裁剪或拼接有效样本。")
    require(request["units_policy"] == "preserve_no_scaling", "不自动标定或归一化。")
    require(nonempty(request["limitations_acknowledgement"]), "须确认已知边界/频带及上游未验证限制。")
    keys(request["output"], ("directory", "block_samples", "max_working_bytes", "max_artifact_bytes"), "output")
    out = request["output"]
    require(all(positive_int(out[k]) for k in ("block_samples", "max_working_bytes", "max_artifact_bytes")),
            "分块与资源预算必须明确为正整数。")
    destination = resolve(out["directory"], base)
    require(not destination.exists() and not destination.is_relative_to(source.parent),
            "输出须为源结果目录之外的全新目录，不覆盖。")
    approval = request["approval"]
    keys(approval, ("status", "scope_sha256", "evidence", "confirmation"), "approval")
    keys(approval["confirmation"], ("method", "reference"), "confirmation")
    require(approval["status"] == "confirmed" and approval["scope_sha256"] == fingerprint(request) and
            nonempty(approval["evidence"]) and approval["confirmation"]["method"] == "user" and
            nonempty(approval["confirmation"]["reference"]), "缺少与当前请求一致的真实用户确认。")
    names = list(dict.fromkeys([a + "_time.npy" for a, _ in pairs] +
                              ["valid_sample_mask.npy", "confirmed_config.json"]))
    verify_files(index, source.parent, names)
    n = result["shape_per_algorithm"][0]
    estimate = n * (8 * len(selection) + 1) + len(raw) * 4 + index["confirmed_config.json"]["size_bytes"] + len(encode(request)) * 2 + 1024**2
    working = (out["block_samples"] * 40 + len(raw) * 12 + len(encode(request)) * 8 +
               index["confirmed_config.json"]["size_bytes"] * 12 + 8 * 1024**2)
    require(estimate <= out["max_artifact_bytes"], "交接文件估算超出预算，不缩范围。")
    require(working <= out["max_working_bytes"], "分块/元数据工作空间估算超出预算。")
    return {"source": source, "result": result, "raw_result": raw, "digest": digest,
            "index": index, "names": names, "destination": destination,
            "estimated_artifact_bytes": estimate, "estimated_working_bytes": working}


def validate_arrays(wave, mask, result, block):
    import numpy as np
    require(list(wave.shape) == result["shape_per_algorithm"] and wave.dtype == np.dtype("float64"),
            "实际波形形状/精度不匹配，不展平或转置。")
    n = wave.shape[0]
    require(mask.shape == (n,) and mask.dtype == np.dtype("bool"), "有效掩码尺寸/类型错误。")
    for start in range(0, n, block):
        stop = min(n, start + block)
        expected = np.zeros(stop - start, dtype=bool)
        for a, b in result["valid_sample_intervals"]:
            left, right = max(a, start), min(b, stop)
            if left < right:
                expected[left-start:right-start] = True
        require(np.array_equal(mask[start:stop], expected), "有效掩码与区间记录冲突。")


def transfer_report(result, signals, request, config_sha256):
    """Summarize transmitted facts and references, not downstream detector settings."""
    return {
        "report_version": "0.1", "purpose": PURPOSE,
        "handoff_parameter_status": "confirmed",
        "signals": signals,
        "preserved_metadata_fields": [k for k in PROVENANCE_KEYS if k in result],
        "metadata_locations": {
            "waveform_identity": "handoff.json:signals",
            "sampling_time_direction_band_units_history": "handoff.json:provenance",
            "valid_sample_mask": "valid_sample_mask.npy",
            "full_source_result": "source_result.json",
            "full_source_configuration_and_parameter_records": "source_config.json",
            "handoff_selection_and_approval": "confirmed_handoff_request.json"},
        "source_configuration": {"path": "source_config.json", "sha256": config_sha256},
        "source_units": result["units"],
        "source_validity_limit": result["validity_limit"],
        "source_limitations": result.get("limitations"),
        "source_issues": result.get("issues"),
        "upstream_inspection_present": "upstream_inspection" in result,
        "optional_source_fields_not_present": [
            k for k in PROVENANCE_KEYS[18:] if k not in result],
        "limitations_acknowledgement": request["limitations_acknowledgement"],
        "downstream_detection": "out_of_scope",
        "note": "仅交接数据及已知信息；未提供的可选来源字段不补猜。检测方法、参数确认和计算由下游另行负责。"
    }


def prepare(request, base):
    import numpy as np
    context = validate(request, base)
    source, result, dest = context["source"], context["result"], context["destination"]
    index, names = context["index"], context["names"]
    verify_files(index, source.parent, names, content=True)
    _, _, config_raw = load_json(source.parent / "confirmed_config.json", index["confirmed_config.json"]["sha256"])
    parent = dest.parent
    while not parent.exists():
        parent = parent.parent
    require(shutil.disk_usage(parent).free >= context["estimated_artifact_bytes"], "可用磁盘不足。")
    block = request["output"]["block_samples"]
    mask = np.load(contained(source.parent, "valid_sample_mask.npy"), mmap_mode="r", allow_pickle=False)
    require(mask.shape == (result["shape_per_algorithm"][0],) and mask.dtype == np.dtype("bool"),
            "有效掩码尺寸/类型错误，不导出。")
    dest.mkdir(parents=True, exist_ok=False)
    try:
        (dest / "source_result.json").write_bytes(context["raw_result"])
        (dest / "source_config.json").write_bytes(config_raw)
        write_json(dest / "confirmed_handoff_request.json", request)
        with (dest / "valid_sample_mask.npy").open("xb") as f:
            np.save(f, mask, allow_pickle=False)
        signals = []
        for seq, selected in enumerate(request["selection"]):
            algorithm, beam_id = selected["algorithm"], selected["beam_id"]
            beam = next(b for b in result["beams"] if b["beam_id"] == beam_id)
            name = algorithm + "_time.npy"
            wave = np.load(contained(source.parent, name), mmap_mode="r", allow_pickle=False)
            validate_arrays(wave, mask, result, block)
            signal_id = "signal_%06d" % seq
            target = dest / (signal_id + ".npy")
            output = np.lib.format.open_memmap(target, mode="w+", dtype="float64", shape=(wave.shape[0], 1))
            for start in range(0, wave.shape[0], block):
                stop = min(wave.shape[0], start + block)
                values = wave[start:stop, beam["column"]]
                require(np.isfinite(values).all(), "所选波束含 NaN/Inf，不填补、不删除。")
                output[start:stop, 0] = values
            output.flush()
            del output, wave
            signals.append({"signal_id": signal_id, "path": target.name, "algorithm": algorithm,
                            "beam_id": beam_id, "column": 0, "source_column": beam["column"],
                            "scan_column": beam["scan_column"], "direction_deg": beam["direction_deg"],
                            "fixed_direction": True, "shape": [result["shape_per_algorithm"][0], 1]})
        report = transfer_report(result, signals, request, index["confirmed_config.json"]["sha256"])
        write_json(dest / "handoff-report.json", report)
        verify_files(index, source.parent, names, content=True)
        load_json(source, context["digest"])
        artifacts = [{"path": p.name, "size_bytes": p.stat().st_size, "sha256": file_hash(p)}
                     for p in sorted(dest.iterdir()) if p.is_file()]
        manifest = {
            "handoff_version": VERSION, "handoff_status": "prepared",
            "implementation_version": IMPLEMENTATION_VERSION, "purpose": PURPOSE,
            "handoff_report": "handoff-report.json",
            "data_role": "beamformed", "axes": ["sample", "beam"], "dtype": "float64",
            "detection_status": "not_run", "can_detect": False,
            "implementation_validation": "v043_scoped_transfer_regression_passed",
            "source_result": {"original_path": str(source), "copy": "source_result.json", "sha256": context["digest"]},
            "provenance": {k: result[k] for k in PROVENANCE_KEYS if k in result},
            "signals": signals, "valid_sample_mask": "valid_sample_mask.npy",
            "transformations": ["explicit_algorithm_and_saved_beam_selection", "column_copy_without_numeric_scaling"],
            "preserved_full_sample_axis": True, "artifacts": artifacts,
            "source_verification_scope": names,
            "limits": ["仅核对消费的波形、掩码、配置及结果摘要，不复验所有权重或上游物理假设。",
                       "副本中的其他路径仅供追溯，不承诺把全部上游原始数据/权重打包。",
                       "有效掩码不证明采集连续性、同步、标定或窄带近似精度。",
                       "这是输入交接，不是检测运行或端到端验收。"]}
        require(sum(a["size_bytes"] for a in artifacts) + len(encode(manifest)) <=
                request["output"]["max_artifact_bytes"], "实际产物超过预算，不发布完成清单。")
        write_json(dest / "handoff.json", manifest)
        return {"handoff": str(dest / "handoff.json"), "sha256": file_hash(dest / "handoff.json"),
                "signals": signals, "purpose": PURPOSE,
                "handoff_report": str(dest / "handoff-report.json"), "detection_status": "not_run"}
    except Exception as error:
        write_json(dest / "failure.json", {"status": "failed", "error": str(error), "usable": False})
        raise


def receive(path, expected):
    """Verify a portable handoff without executing detection; metadata only return."""
    path = Path(path).resolve()
    manifest, _, _ = load_json(path, expected)
    require(manifest.get("handoff_version") == VERSION and manifest.get("handoff_status") == "prepared" and
            manifest.get("data_role") == "beamformed" and manifest.get("axes") == ["sample", "beam"] and
            manifest.get("preserved_full_sample_axis") is True, "交接完成清单/身份无效。")
    index = artifact_index(manifest, path.parent)
    verify_files(index, path.parent, list(index), content=True)
    source_ref = manifest["source_result"]
    require(source_ref["copy"] == "source_result.json", "来源副本路径不支持。")
    result, _, _, source_index = read_result(path.parent / source_ref["copy"], source_ref["sha256"])
    require(manifest["provenance"] == {k: result[k] for k in PROVENANCE_KEYS if k in result},
            "来源元数据在交接中改变。")
    request, _, _ = load_json(path.parent / "confirmed_handoff_request.json")
    require(request["source_result"]["sha256"] == source_ref["sha256"] and
            request["approval"]["status"] == "confirmed" and
            request["approval"]["scope_sha256"] == fingerprint(request), "交接请求确认与来源不一致。")
    require(all(name in index for name in ("source_result.json", "source_config.json",
                "confirmed_handoff_request.json", "valid_sample_mask.npy")), "交接缺少必要产物。")
    require(index["source_result.json"]["sha256"] == source_ref["sha256"], "来源副本摘要不一致。")
    require("confirmed_config.json" in source_index and
            index["source_config.json"]["sha256"] == source_index["confirmed_config.json"]["sha256"],
            "上游确认配置副本与原结果登记不一致。")
    require(request["sample_policy"] == "preserve_full_output_and_mask" and
            request["units_policy"] == "preserve_no_scaling" and
            nonempty(request["limitations_acknowledgement"]) and
            nonempty(request["approval"]["evidence"]) and
            request["approval"]["confirmation"]["method"] == "user" and
            nonempty(request["approval"]["confirmation"]["reference"]), "交接确认或保留策略不完整。")
    if "handoff_report" in manifest or "purpose" in manifest:
        require(manifest.get("purpose") == PURPOSE and manifest.get("handoff_report") == "handoff-report.json",
                "交接用途或报告引用不一致。")
        require("handoff-report.json" in index, "交接报告未登记摘要。")
        report, _, _ = load_json(path.parent / "handoff-report.json", index["handoff-report.json"]["sha256"])
        require(report == transfer_report(result, manifest["signals"], request,
                                          source_index["confirmed_config.json"]["sha256"]),
                "交接报告与来源、范围或限制记录不一致。")
    require(manifest["valid_sample_mask"] == "valid_sample_mask.npy", "掩码路径不支持。")
    import numpy as np
    mask = np.load(path.parent / "valid_sample_mask.npy", mmap_mode="r", allow_pickle=False)
    require(len(manifest["signals"]) == len(request["selection"]), "选择范围改变。")
    block = request["output"]["block_samples"]
    require(positive_int(block), "分块长度无效。")
    for i, (signal, selected) in enumerate(zip(manifest["signals"], request["selection"])):
        require(signal["signal_id"] == "signal_%06d" % i and
                signal["path"] == signal["signal_id"] + ".npy" and signal["path"] in index and
                signal["column"] == 0 and signal["algorithm"] in result["algorithms"] and
                signal["algorithm"] == selected["algorithm"] and
                signal["beam_id"] == selected["beam_id"], "信号选择或身份改变。")
        beam = next((b for b in result["beams"] if b["beam_id"] == signal["beam_id"]), None)
        require(beam is not None and signal["source_column"] == beam["column"] and
                signal["scan_column"] == beam["scan_column"] and signal["direction_deg"] == beam["direction_deg"] and
                signal["fixed_direction"] is True, "方向/保存列映射改变。")
        wave = np.load(contained(path.parent, signal["path"]), mmap_mode="r", allow_pickle=False)
        require(signal["shape"] == [result["shape_per_algorithm"][0], 1], "单束形状元数据错误。")
        validate_arrays(wave, mask, {**result, "shape_per_algorithm": signal["shape"]}, block)
        for start in range(0, wave.shape[0], block):
            require(np.isfinite(wave[start:start+block]).all(), "交接波形包含非有限数。")
    verify_files(index, path.parent, list(index), content=True)
    load_json(path, expected)
    return manifest


def source_configuration_reference(manifest, base):
    """Give the receiver the verified full configuration, without reinterpreting it."""
    record = next(a for a in manifest["artifacts"] if a["path"] == "source_config.json")
    return {"path": str(contained(base, record["path"])), "sha256": record["sha256"]}


def load_beam(path, expected_sha256, signal_id):
    """Return a read-only 2D waveform, mask and identity. Caller must handle mask."""
    manifest = receive(path, expected_sha256)
    signal = next((s for s in manifest["signals"] if s["signal_id"] == signal_id), None)
    require(signal is not None, "必须明确一个已交接的 signal_id。")
    import numpy as np
    base = Path(path).resolve().parent
    return {"waveform": np.load(contained(base, signal["path"]), mmap_mode="r", allow_pickle=False),
            "valid_sample_mask": np.load(base / manifest["valid_sample_mask"], mmap_mode="r", allow_pickle=False),
            "signal": signal, "provenance": manifest["provenance"],
            "source_configuration": source_configuration_reference(manifest, base),
            "purpose": PURPOSE, "detection_status": "not_run"}


def bypass_module():
    """Load only the fixed installed sibling adapter, never code from a packet."""
    folder = Path(__file__).resolve().parents[2] / "underwater-beamforming" / "scripts"
    names = ("preflight", "inspection_handoff", "bypass_handoff")
    for name in names:
        expected = folder / (name + ".py")
        require(expected.is_file(), "旁路接收需要同级 underwater-beamforming 适配器；不会自动下载安装。")
        existing = sys.modules.get(name)
        require(existing is None or Path(existing.__file__).resolve() == expected.resolve(),
                "旁路适配器依赖已从其他位置加载；请使用独立进程。")
    sys.path.insert(0, str(folder))
    try:
        module = importlib.import_module("bypass_handoff")
    finally:
        sys.path.pop(0)
    for name in names:
        require(Path(sys.modules[name].__file__).resolve() == (folder/(name+".py")).resolve(),
                "旁路适配器来源不符。")
    return module


def receive_bypass(path, expected_sha256):
    """Accept metadata/values only; unknown validity remains None, never all-valid."""
    manifest = bypass_module().receive(path, expected_sha256)
    base = Path(path).resolve().parent
    name = manifest["source_configuration"]
    record = next(a for a in manifest["artifacts"] if a["path"] == name)
    return {"input_status": "accepted", "purpose": PURPOSE,
            "data_role": manifest["data_role"], "signals": manifest["signals"],
            "provenance": manifest["provenance"],
            "valid_sample_mask": (str(contained(base, manifest["valid_sample_mask"]))
                                  if manifest["valid_sample_mask"] is not None else None),
            "source_configuration": {"path": str(contained(base, name)), "sha256": record["sha256"]},
            "handoff": {"path": str(Path(path).resolve()), "sha256": expected_sha256},
            "can_detect": False, "detection_status": "not_run"}


def load_bypass_signal(path, expected_sha256, signal_id):
    """Read-only [N,1], explicit signal identity, nullable validity and provenance."""
    return bypass_module().load_signal(path, expected_sha256, signal_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review", "check", "digest", "prepare", "receive", "receive-bypass"))
    parser.add_argument("path")
    parser.add_argument("--sha256", help="receive 必须提供已记录的交接清单摘要")
    args = parser.parse_args()
    try:
        if args.command == "review":
            value = review(args.path)
        elif args.command == "receive-bypass":
            require(args.sha256 is not None, "receive-bypass 缺少 --sha256。")
            value = receive_bypass(args.path, args.sha256)
        elif args.command == "receive":
            require(args.sha256 is not None, "receive 缺少 --sha256。")
            value = receive(args.path, args.sha256)
            value = {"input_status": "accepted", "purpose": PURPOSE,
                     "signals": value["signals"], "provenance": value["provenance"],
                     "valid_sample_mask": str(contained(Path(args.path).resolve().parent,
                                                        value["valid_sample_mask"])),
                     "source_configuration": source_configuration_reference(value, Path(args.path).resolve().parent),
                     "handoff": {"path": str(Path(args.path).resolve()), "sha256": args.sha256},
                     "can_detect": False, "detection_status": "not_run"}
        else:
            request, _, _ = load_json(args.path)
            base = Path(args.path).resolve().parent
            if args.command == "digest":
                value = {"scope_sha256": fingerprint(request), "is_approval": False}
            elif args.command == "prepare":
                value = prepare(request, base)
            else:
                context = validate(request, base)
                value = {"can_attempt_preparation": True, "content_hashes_checked": False,
                         "can_detect": False, "estimated_artifact_bytes": context["estimated_artifact_bytes"],
                         "estimated_working_bytes": context["estimated_working_bytes"]}
        print(encode(value).decode("utf-8"), end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, ImportError) as error:
        print(encode({"status": "blocked", "can_detect": False, "error": str(error)}).decode("utf-8"), end="")
        return 2


if __name__ == "__main__":
    sys.exit(main())
