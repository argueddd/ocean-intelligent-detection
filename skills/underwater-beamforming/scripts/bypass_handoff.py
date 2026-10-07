#!/usr/bin/env python3
"""Inspection-exported single sensor / existing beams -> data-only handoff."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import shutil
import sys

import inspection_handoff as intake
import preflight as pf

VERSION = "0.1"
PURPOSE = "waveform_and_metadata_transfer_only"
REFERENCE = intake.REFERENCE
BASE_SCHEMA = {
    "bypass_version": pf.Choice((VERSION,)),
    "source_handoff": REFERENCE,
    "selected_channel_ids": pf.IDS,
    "unknown_metadata_policy": pf.Choice(("preserve_unknown_for_transfer_only",)),
    "limitations_acknowledgement": pf.STR,
    "output": {"directory": pf.STR, "block_samples": pf.PINT,
               "max_working_bytes": pf.PINT, "max_artifact_bytes": pf.PINT},
    "approval": intake.APPROVAL,
}
EXTRA = {"signal_metadata", "frequency_coverage", "validity"}
require = intake.require


def checked_schema(value, spec, name):
    check = pf.Preflight({}, ".")
    require(check.schema(value, spec, name), str(check.issues))


def exact_keys(value, wanted, label):
    require(isinstance(value, dict) and set(value) == set(wanted), label + " 字段缺失或含不支持项。")


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def packet_path(base, name):
    require(text_value(name) and not Path(name).is_absolute(), "产物路径须为包内相对路径。")
    root = Path(base).resolve()
    path = (root / name).resolve()
    require(path.is_relative_to(root) and path != root and not (root / name).is_symlink(), "产物路径越界或是符号链接。")
    return path


def source_input(manifest):
    require(manifest.get("handoff_version") == "0.1" and manifest.get("export_status") == "completed",
            "只接读取检查交接适配器已完成的0.1导出包。")
    inp = manifest["input"]
    checked_schema(inp, pf.INPUT, "input")
    require(inp["data_role"] in ("single_sensor", "beamformed"), "旁路只接单阵元或已有波束，不能把原始阵列当波束。")
    n, c = inp["shape"]
    require(inp["dtype"] == "float64" and inp["axes"] == ["sample", "channel"] and
            inp["sample_range"] == [0, n] and len(inp["channels"]) == c and
            len(set(inp["channels"])) == c, "导出形状/精度/列身份无效。")
    require(inp["data_role"] != "single_sensor" or c == 1, "单阵元身份必须恰好一列。")
    offset = manifest["export_sample_zero_source_sample"]
    require(type(offset) is int and offset >= 0 and manifest["source_sample_range"] == [offset, offset+n],
            "原始样本映射无效。")
    indices = manifest["source_channel_indices"]
    require(isinstance(indices, list) and len(indices) == c and
            all(type(i) is int and i >= 0 for i in indices) and indices == sorted(set(indices)),
            "原始列映射长度、顺序或类型错误。")
    return inp


def read_source(reference, base):
    checked_schema(reference, REFERENCE, "source_handoff")
    path = intake.resolved(reference["path"], base)
    manifest, _, raw = intake.load_json(path, reference["sha256"])
    inp = copy.deepcopy(source_input(manifest))
    inp["source"]["path"] = str(path.parent / "waveforms.npy")
    intake.validate_binding(reference, {"input": inp},
                            {"source_sha256": manifest["waveform"]["sha256"]}, base)
    return path, manifest, raw


def validate_details(config, manifest):
    require(isinstance(config, dict) and set(config) == set(BASE_SCHEMA) | EXTRA, "旁路请求字段不完整或含未知键。")
    checked_schema({k: config[k] for k in BASE_SCHEMA}, BASE_SCHEMA, "request")
    require(config["approval"]["scope_sha256"] == intake.fingerprint(config), "旁路范围与确认摘要不一致。")
    inp = source_input(manifest)
    ids = config["selected_channel_ids"]
    require(len(set(ids)) == len(ids) and all(i in inp["channels"] for i in ids), "所选ID重复或未实际导出。")
    entries = config["signal_metadata"]
    require(isinstance(entries, list) and len(entries) == len(ids), "每条所选信号须有对应身份记录。")
    role = inp["data_role"]
    for channel_id, item in zip(ids, entries):
        exact_keys(item, ("channel_id", "algorithm", "direction", "evidence"), "signal_metadata")
        require(item["channel_id"] == channel_id and text_value(item["evidence"]), "身份顺序或证据缺失。")
        algorithm, direction = item["algorithm"], item["direction"]
        if role == "single_sensor":
            require(algorithm is None and direction is None, "单阵元不是波束，算法/指向必须显式null。")
        else:
            require(algorithm is None or text_value(algorithm), "已有波束算法用明确名称或显式null，不能猜成CBF。")
            if direction is not None:
                exact_keys(direction, ("parameterization", "angles_deg", "angle_unit", "coordinate_frame",
                                       "zero_direction", "positive_direction", "fixed_direction"), "direction")
                require(direction["parameterization"] in ("array_angle", "azimuth_elevation") and
                        direction["angle_unit"] == "deg" and direction["fixed_direction"] is True,
                        "本版只传递定义明确的固定指向，变指向不静默简化。")
                values = direction["angles_deg"]
                length = 1 if direction["parameterization"] == "array_angle" else 2
                require(isinstance(values, list) and len(values) == length and all(pf._number(v) for v in values),
                        "角度维数/数值错误。")
                require(all(text_value(direction[k]) for k in ("coordinate_frame", "zero_direction", "positive_direction")),
                        "角度参考定义不完整。")
                require(length != 2 or -90 <= values[1] <= 90, "俯仰角越界。")
    band = config["frequency_coverage"]
    exact_keys(band, ("status", "band_hz", "evidence"), "frequency_coverage")
    require(band["status"] in ("known", "unknown") and text_value(band["evidence"]), "已处理频带状态/依据缺失。")
    if band["status"] == "unknown":
        require(band["band_hz"] is None, "未知频带必须null，不猜成0到Nyquist。")
    else:
        values = band["band_hz"]
        require(isinstance(values, list) and len(values) == 2 and all(pf._number(v) for v in values) and
                0 <= values[0] < values[1] <= inp["sample_rate_hz"]/2, "频带数值无效。")
    validity = config["validity"]
    exact_keys(validity, ("status", "sample_intervals", "evidence"), "validity")
    require(validity["status"] in ("known", "unknown") and text_value(validity["evidence"]), "有效区间状态/依据缺失。")
    if validity["status"] == "unknown":
        require(validity["sample_intervals"] is None, "未知有效性保持null，不生成全true掩码。")
    else:
        ranges = validity["sample_intervals"]
        require(isinstance(ranges, list) and ranges, "有效区间须非空；本版使用所选信号共用区间。")
        previous = 0
        for pair in ranges:
            require(isinstance(pair, list) and len(pair) == 2 and all(type(v) is int for v in pair) and
                    previous <= pair[0] < pair[1] <= inp["shape"][0], "有效区间须为输出相对的有序半开区间。")
            previous = pair[1]
    return inp


def build_metadata(config, manifest):
    inp = validate_details(config, manifest)
    offset = manifest["export_sample_zero_source_sample"]
    signals = []
    for i, detail in enumerate(config["signal_metadata"]):
        column = inp["channels"].index(detail["channel_id"])
        signals.append(dict(detail, signal_id="signal_%06d" % i, path="signal_%06d.npy" % i,
                            column=0, source_column=column,
                            original_source_channel_index=manifest["source_channel_indices"][column],
                            data_role=inp["data_role"], shape=[inp["shape"][0], 1],
                            algorithm_status=("not_applicable" if inp["data_role"] == "single_sensor" else
                                              "unknown" if detail["algorithm"] is None else "known"),
                            direction_status=("not_applicable" if inp["data_role"] == "single_sensor" else
                                              "unknown" if detail["direction"] is None else "known")))
    provenance = {
        "sample_rate_hz": inp["sample_rate_hz"], "units": inp["units"],
        "time_reference": inp["time_reference"], "first_sample_offset_seconds": offset/inp["sample_rate_hz"],
        "source_sample_range": inp["sample_range"], "original_source_sample_range": manifest["source_sample_range"],
        "source_channels": inp["channels"], "source_sha256": manifest["waveform"]["sha256"],
        "processing_history": {"upstream": inp["processing_history"], "this_run": []},
        "frequency_coverage": config["frequency_coverage"], "validity": config["validity"],
        "interval_convention": "output-relative half-open",
        "amplitude_convention": "unchanged float64 values; no scaling, filtering or beamforming in bypass",
        "time_mapping": "original sample = export_sample_zero_source_sample + output index; no gaps compressed",
        "upstream_inspection": {k: manifest[k] for k in (
            "original_source", "checks", "upstream_issues", "not_checked", "inspection_readiness",
            "inspection_linkage", "inspection_linkage_limit", "metadata_evidence", "identity_evidence",
            "processing_history_evidence", "export_transformations")},
        "unknown_metadata_policy": config["unknown_metadata_policy"],
        "limitations_acknowledgement": config["limitations_acknowledgement"]}
    return signals, provenance


def check(config, base):
    path, manifest, raw = read_source(config["source_handoff"], base)
    inp = validate_details(config, manifest)
    dest = intake.resolved(config["output"]["directory"], base)
    require(not dest.exists() and not dest.is_relative_to(path.parent), "输出须为源包之外的全新目录。")
    n, b = inp["shape"][0], len(config["selected_channel_ids"])
    evidence_bytes = sum(r["size_bytes"] for r in manifest["artifacts"] if r["path"] != "waveforms.npy")
    request_bytes = len(intake.json_bytes(config))
    bytes_est = (n*(8*b + (config["validity"]["status"] == "known")) + len(raw)*5 +
                 evidence_bytes + request_bytes*4 + b*512 + 4*1024**2)
    working = (min(n, config["output"]["block_samples"])*40 +
               (len(raw)+evidence_bytes)*16 + request_bytes*12 + 16*1024**2)
    require(bytes_est <= config["output"]["max_artifact_bytes"] and working <= config["output"]["max_working_bytes"],
            "旁路产物或工作空间估算超预算，不减少范围。")
    return {"source": path, "manifest": manifest, "raw": raw, "destination": dest,
            "artifact_bytes_estimate": bytes_est, "working_bytes_estimate": working}


def verify_source(path, manifest):
    for record in manifest["artifacts"]:
        item = packet_path(path.parent, record["path"])
        require(item.stat().st_size == record["size_bytes"] and intake.digest_file(item) == record["sha256"],
                "上游导出产物内容改变。")


def mask_chunk(config, start, stop):
    import numpy as np
    values = np.zeros(stop-start, dtype=bool)
    for a, b in config["validity"]["sample_intervals"]:
        left, right = max(start, a), min(stop, b)
        if left < right:
            values[left-start:right-start] = True
    return values


def load_npy(path, dtype, shape):
    import numpy as np
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        require(isinstance(array, np.memmap) and array.dtype == np.dtype(dtype) and
                list(array.shape) == list(shape) and array.offset + array.nbytes == path.stat().st_size,
                "NPY编码、尺寸或尾随内容不符。")
        return array
    except Exception:
        if isinstance(array, np.memmap):
            array._mmap.close()
        elif hasattr(array, "close"):
            array.close()
        raise


def prepare(config, base):
    context = check(config, base)
    path, source, dest = context["source"], context["manifest"], context["destination"]
    verify_source(path, source)
    parent = dest.parent
    while not parent.exists():
        parent = parent.parent
    require(shutil.disk_usage(parent).free >= context["artifact_bytes_estimate"], "磁盘不足。")
    import numpy as np
    signals, provenance = build_metadata(config, source)
    wave = load_npy(packet_path(path.parent, "waveforms.npy"), "float64", source["input"]["shape"])
    n, step = wave.shape[0], config["output"]["block_samples"]
    dest.mkdir(parents=True, exist_ok=False)
    output = None
    try:
        with (dest/"upstream_handoff.json").open("xb") as f:
            f.write(context["raw"])
        for old, new in (("inspection_result.json", "upstream_inspection_result.json"),
                         ("confirmed_handoff_request.json", "upstream_export_request.json")):
            _, _, raw = intake.load_json(packet_path(path.parent, old))
            with (dest/new).open("xb") as f:
                f.write(raw)
        intake.write_json(dest/"confirmed_bypass_request.json", config)
        for signal in signals:
            output = np.lib.format.open_memmap(dest/signal["path"], mode="w+", dtype="float64", shape=(n,1))
            for start in range(0, n, step):
                values = wave[start:start+step, signal["source_column"]]
                require(np.isfinite(values).all(), "所选信号存在NaN/Inf，不能静默修复。")
                output[start:start+len(values),0] = values
            output.flush()
            output._mmap.close()
            output = None
        mask_name = None
        if config["validity"]["status"] == "known":
            mask_name = "valid_sample_mask.npy"
            output = np.lib.format.open_memmap(dest/mask_name, mode="w+", dtype="bool", shape=(n,))
            for start in range(0, n, step):
                output[start:start+step] = mask_chunk(config, start, min(n,start+step))
            output.flush()
            output._mmap.close()
            output = None
        verify_source(path, source)
        read_source(config["source_handoff"], base)
        records = [{"path": p.name, "size_bytes": p.stat().st_size, "sha256": intake.digest_file(p)}
                   for p in sorted(dest.iterdir()) if p.is_file()]
        metadata = {
            "bypass_version": VERSION, "purpose": PURPOSE, "handoff_status": "prepared",
            "data_role": source["input"]["data_role"],
            "axes": ["sample", "beam" if source["input"]["data_role"] == "beamformed" else "channel"],
            "dtype": "float64", "signals": signals, "provenance": provenance,
            "source_handoff": {"copy": "upstream_handoff.json", "sha256": config["source_handoff"]["sha256"]},
            "valid_sample_mask": mask_name, "preserved_full_sample_axis": True,
            "beamforming_performed": False, "detection_status": "not_run", "can_detect": False,
            "implementation_validation": "v043_synthetic_transfer_regression_passed",
            "source_configuration": "confirmed_bypass_request.json", "artifacts": records,
            "limits": ["未知方向/算法/频带/有效性原样保留，不填0度、CBF、全频带或全有效。",
                       "只做数据交接；未知有效性不代表可直接用于后续计算。",
                       "原始录音及未打包产物路径仅作追溯，不要求接收机器具有相同路径。"]}
        require(sum(r["size_bytes"] for r in records)+len(intake.json_bytes(metadata)) <= config["output"]["max_artifact_bytes"],
                "实际产物超预算，不发布完成包。")
        intake.write_json(dest/"handoff.pending.json", metadata)
        (dest/"handoff.pending.json").rename(dest/"handoff.json")
        return {"handoff": str(dest/"handoff.json"), "sha256": intake.digest_file(dest/"handoff.json"),
                "handoff_status": "prepared", "data_role": metadata["data_role"], "can_detect": False}
    except Exception as exc:
        intake.write_json(dest/"failure.json", {"status": "failed", "usable": False, "error": str(exc)})
        raise
    finally:
        if output is not None:
            output._mmap.close()
        wave._mmap.close()


def receive(path, sha256):
    path = Path(path).resolve()
    meta, _, _ = intake.load_json(path, sha256)
    require(meta.get("bypass_version") == VERSION and meta.get("purpose") == PURPOSE and
            meta.get("handoff_status") == "prepared" and meta.get("beamforming_performed") is False and
            meta.get("preserved_full_sample_axis") is True and meta.get("can_detect") is False and
            meta.get("detection_status") == "not_run", "旁路交接清单无效。")
    index = {}
    for record in meta["artifacts"]:
        require(record["path"] not in index, "产物路径重复。")
        item = packet_path(path.parent, record["path"])
        require(item.stat().st_size == record["size_bytes"] and intake.digest_file(item) == record["sha256"],
                "旁路产物尺寸/摘要不符。")
        index[record["path"]] = record
    for name in ("upstream_handoff.json", "upstream_inspection_result.json",
                 "upstream_export_request.json", "confirmed_bypass_request.json"):
        require(name in index, "旁路交接缺少必要证据：" + name)
    require(meta["source_handoff"]["copy"] == "upstream_handoff.json", "来源副本路径不符。")
    source, _, _ = intake.load_json(path.parent/"upstream_handoff.json", meta["source_handoff"]["sha256"])
    request, _, _ = intake.load_json(path.parent/"confirmed_bypass_request.json")
    require(request["source_handoff"]["sha256"] == meta["source_handoff"]["sha256"], "请求来源摘要不符。")
    signals, provenance = build_metadata(request, source)
    require(meta["signals"] == signals and meta["provenance"] == provenance and
            meta["data_role"] == source["input"]["data_role"] and meta["dtype"] == "float64" and
            meta["axes"] == ["sample", "beam" if meta["data_role"] == "beamformed" else "channel"],
            "旁路身份、来源或元数据在交接中改变。")
    original_records = {r["path"]: r for r in source["artifacts"]}
    for old, new in (("inspection_result.json", "upstream_inspection_result.json"),
                     ("confirmed_handoff_request.json", "upstream_export_request.json")):
        require(index[new]["sha256"] == original_records[old]["sha256"], "上游证据副本改变。")
    evidence, _, _ = intake.load_json(path.parent/"upstream_inspection_result.json")
    export_request, _, _ = intake.load_json(path.parent/"upstream_export_request.json")
    checked_schema(export_request, intake.REQUEST, "upstream_export_request")
    require(export_request["approval"]["scope_sha256"] == intake.fingerprint(export_request) ==
            source["request_scope_sha256"], "上游导出授权范围不一致。")
    require(source["inspection_result"]["sha256"] == index["upstream_inspection_result.json"]["sha256"] ==
            export_request["inspection_result"]["sha256"], "上游检查引用冲突。")
    require(evidence.get("schema_version") == "0.2" and evidence.get("results_valid") is not False and
            evidence.get("status") in ("completed", "partial") and
            evidence.get("source_consistency") == "unchanged_size_and_mtime",
            "上游检查证据无效。")
    inp = source["input"]
    require(source["checks"] == evidence["checks"] and source["not_checked"] == evidence["not_checked"] and
            source["upstream_issues"] == evidence["issues"] and
            export_request["sample_range"] == source["source_sample_range"] and
            export_request["channel_indices"] == source["source_channel_indices"] and
            export_request["identity"]["data_role"] == inp["data_role"] and
            export_request["identity"]["channel_ids"] == inp["channels"] and
            export_request["time_reference"] == inp["time_reference"] and
            export_request["processing_history"]["values"] == inp["processing_history"],
            "上游证据与导出身份、范围或来源冲突。")
    facts = evidence["dataset"]
    require(facts["sample_rate_hz"]["state"] == "confirmed" and
            facts["sample_rate_hz"]["value"] == inp["sample_rate_hz"] and
            inp["units"] == (facts["units"]["value"] if facts["units"]["state"] == "confirmed" else "unknown"),
            "采样率或单位不符合上游事实。")
    require(meta["source_configuration"] == "confirmed_bypass_request.json", "旁路配置路径错误。")
    known = request["validity"]["status"] == "known"
    require(meta["valid_sample_mask"] == ("valid_sample_mask.npy" if known else None), "掩码存在性与有效性声明不符。")
    import numpy as np
    n, step = source["input"]["shape"][0], request["output"]["block_samples"]
    if known:
        require("valid_sample_mask.npy" in index, "未登记掩码。")
        mask = load_npy(packet_path(path.parent, "valid_sample_mask.npy"), "bool", [n])
        try:
            for start in range(0, n, step):
                require(np.array_equal(mask[start:start+step], mask_chunk(request,start,min(n,start+step))),
                        "掩码与明确区间冲突。")
        finally:
            mask._mmap.close()
    for signal in signals:
        require(signal["path"] in index, "波形未登记摘要。")
        wave = load_npy(packet_path(path.parent, signal["path"]), "float64", signal["shape"])
        try:
            for start in range(0, n, step):
                require(np.isfinite(wave[start:start+step]).all(), "交接波形包含非有限值。")
        finally:
            wave._mmap.close()
    for name, record in index.items():
        require(intake.digest_file(packet_path(path.parent,name)) == record["sha256"], "接收期间产物发生改变。")
    intake.load_json(path, sha256)
    return meta


def load_signal(path, sha256, signal_id):
    meta = receive(path, sha256)
    signal = next((s for s in meta["signals"] if s["signal_id"] == signal_id), None)
    require(signal is not None, "须明确选择已交接的signal_id。")
    import numpy as np
    base = Path(path).resolve().parent
    return {"waveform": np.load(packet_path(base,signal["path"]), mmap_mode="r", allow_pickle=False),
            "valid_sample_mask": (np.load(base/meta["valid_sample_mask"], mmap_mode="r", allow_pickle=False)
                                  if meta["valid_sample_mask"] is not None else None),
            "signal": signal, "data_role": meta["data_role"], "provenance": meta["provenance"],
            "source_configuration": {"path": str(base/"confirmed_bypass_request.json"),
                                     "sha256": next(r["sha256"] for r in meta["artifacts"] if r["path"] == "confirmed_bypass_request.json")},
            "purpose": PURPOSE, "detection_status": "not_run", "can_detect": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review", "check", "digest", "prepare", "receive"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        base = args.path.resolve().parent
        if args.command == "receive":
            require(args.sha256 is not None, "receive须提供--sha256。")
            result = receive(args.path,args.sha256)
            result = {"input_status": "accepted", "data_role": result["data_role"], "signals": result["signals"],
                      "provenance": result["provenance"], "can_detect": False}
        elif args.command == "review":
            require(args.sha256 is not None, "review须提供源交接--sha256。")
            _, manifest, _ = read_source({"path": str(args.path.resolve()), "sha256": args.sha256},base)
            result = {"input": manifest["input"], "source_sample_range": manifest["source_sample_range"],
                      "upstream_issues": manifest["upstream_issues"], "not_checked": manifest["not_checked"],
                      "content_hashes_checked": False, "can_beamform": False, "can_detect": False}
        else:
            config, _, _ = intake.load_json(args.path)
            if args.command == "digest":
                result = {"scope_sha256": intake.fingerprint(config), "is_approval": False}
            elif args.command == "prepare":
                result = prepare(config,base)
            else:
                ctx = check(config,base)
                result = {"can_attempt_preparation": True, "can_beamform": False, "can_detect": False,
                          "artifact_bytes_estimate": ctx["artifact_bytes_estimate"],
                          "working_bytes_estimate": ctx["working_bytes_estimate"]}
        print(intake.json_bytes(result).decode(), end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, ImportError, MemoryError) as exc:
        print(intake.json_bytes({"status": "blocked", "can_detect": False, "error": str(exc)}).decode(), end="")
        return 2


if __name__ == "__main__":
    sys.exit(main())
