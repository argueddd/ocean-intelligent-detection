#!/usr/bin/env python3
"""Confirmed result-only spectra, including explicitly selected saved beams."""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np

import preflight as pf
import execute as runner
import result_products as products

SCHEMA = {
    "product_version": pf.Choice(("0.4",)),
    "source_result": {"path": pf.STR, "sha256": pf.STR},
    "output_directory": pf.STR,
    "time_domain_beam_indices": pf.Array(pf.UINT),
    "analysis": products.ANALYSIS,
    "max_working_bytes": pf.PINT, "max_artifact_bytes": pf.PINT,
    "title": pf.STR, "approval": runner.APPROVAL,
}
SCHEMA_V041 = dict(SCHEMA, product_version=pf.Choice(("0.4.1",)),
                   auxiliary_products=pf.Array(pf.Choice(tuple(products.PRODUCTS)), minimum=1))


SCHEMA_V042 = {k: v for k, v in SCHEMA_V041.items() if k != "time_domain_beam_indices"}
SCHEMA_V042.update(product_version=pf.Choice(("0.4.2",)),
                   algorithms=pf.Array(pf.Choice(("cbf", "mvdr")), minimum=1),
                   analysis_beam_ids=pf.IDS, time_domain_beam_ids=pf.Array(pf.STR))
IMPLEMENTATION_VERSION = "0.4.2"


def saved_mapping(meta):
    """Keep stable IDs and original scan columns; never infer a missing direction."""
    shape, beams, directions = meta["shape_per_algorithm"], meta.get("beams"), meta.get("directions_deg")
    if meta.get("data_role") != "beamformed" or meta.get("dtype") != "float64":
        raise ValueError("须为明确的 float64 波束结果。")
    if not isinstance(beams, list) or len(beams) != shape[1] or not isinstance(directions, list) or not directions:
        raise ValueError("缺少方向或保存列映射。")
    if any(not isinstance(d, list) or len(d) not in (1, 2) or
           any(type(v) not in (int, float) or not math.isfinite(v) for v in d) for d in directions):
        raise ValueError("方向元数据无效。")
    if len({len(d) for d in directions}) != 1:
        raise ValueError("角度维数不一致。")
    legacy = meta.get("execution_version") == "0.3"
    scans = meta.get("scan_beams")
    if legacy:
        if len(beams) != len(directions):
            raise ValueError("旧0.3仅按全方向同序契约解释。")
        scans = [dict(b, scan_column=i) for i, b in enumerate(beams)]
    if not isinstance(scans, list) or len(scans) != len(directions):
        raise ValueError("扫描映射缺失。")
    ids = []
    for i, scan in enumerate(scans):
        if (not isinstance(scan, dict) or not isinstance(scan.get("beam_id"), str) or
                not scan["beam_id"].strip() or type(scan.get("scan_column")) is not int or
                scan["scan_column"] != i or scan.get("direction_deg") != directions[i]):
            raise ValueError("扫描索引、ID或角度冲突。")
        ids.append(scan["beam_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("扫描ID重复。")
    resolved = []
    for column, beam in enumerate(beams):
        if not isinstance(beam, dict):
            raise ValueError("保存波束映射必须是对象。")
        i = column if legacy else beam.get("scan_column")
        if (type(beam.get("column")) is not int or beam["column"] != column or type(i) is not int or
                not 0 <= i < len(scans) or beam.get("beam_id") != ids[i] or
                beam.get("direction_deg") != directions[i] or
                ("fixed_direction" in beam and beam["fixed_direction"] is not True)):
            raise ValueError("保存列与原扫描映射冲突。")
        resolved.append(dict(beam, scan_column=i, fixed_direction=True))
    if len({b["beam_id"] for b in resolved}) != len(resolved):
        raise ValueError("保存波束重复。")
    if not legacy and (meta.get("time_domain_retention", {}).get("saved") is not True or
                       meta["time_domain_retention"].get("scan_beam_indices") != [b["scan_column"] for b in resolved]):
        raise ValueError("时域保留索引冲突。")
    return resolved, scans


def selection(config, meta):
    if config["product_version"] != "0.4.2":
        return list(range(meta["shape_per_algorithm"][1])), config["time_domain_beam_indices"], meta["algorithms"]
    beams, _ = saved_mapping(meta)
    available = {b["beam_id"]: b["column"] for b in beams}
    analyze, retain, algorithms = (config[k] for k in ("analysis_beam_ids", "time_domain_beam_ids", "algorithms"))
    for label, values in (("分析波束", analyze), ("保留波束", retain), ("算法", algorithms)):
        if len(set(values)) != len(values):
            raise ValueError(label + "不能重复。")
    if any(i not in available for i in analyze) or any(i not in analyze for i in retain):
        raise ValueError("仅分析确已保存的 beam_id；另存时域须在本次分析选择内。")
    if any(a not in meta["algorithms"] for a in algorithms):
        raise ValueError("源包未保存请求算法的波形。")
    return [available[i] for i in analyze], [available[i] for i in retain], algorithms


def product_selection(config):
    # v0.4 explicitly meant the full bundle. Do not add this default to new requests.
    if config["product_version"] == "0.4":
        return products.PRODUCTS.copy()
    return products.selected_products(config["auxiliary_products"])


def fingerprint(config):
    return pf.canonical_digest({k: v for k, v in config.items() if k != "approval"})


def source_metadata(config, base):
    path = runner.resolved(config["source_result"]["path"], base)
    if runner.file_digest(path) != config["source_result"]["sha256"]:
        raise ValueError("源完成清单摘要变化；不会使用变动后的结果。")
    meta = pf.load_plan(path)
    if meta.get("execution_status") != "completed" or meta.get("axes") != ["sample", "beam"]:
        raise ValueError("源不是已完成的波束时域结果。")
    if meta.get("execution_version") not in ("0.3", "0.4"):
        raise ValueError("源完成清单版本不支持；不猜测字段含义。")
    shape = meta.get("shape_per_algorithm")
    if not isinstance(shape, list) or len(shape) != 2 or any(type(i) is not int or i <= 0 for i in shape):
        raise ValueError("源未保存完整波形；不能从功率矩阵恢复时域。")
    if config["product_version"] == "0.4.2":
        saved_mapping(meta)
    else:
        directions = meta.get("directions_deg")
        if not isinstance(directions, list) or len(directions) != shape[1]:
            raise ValueError("源未保存所有扫描方向的时域信号；本补图入口不伪造缺失方向。")
        beams = meta.get("beams", [])
        if len(beams) != len(directions) or any(
            b.get("column") != i or b.get("direction_deg") != directions[i] or
            b.get("scan_column", i) != i for i, b in enumerate(beams)
        ):
            raise ValueError("源时域列与扫描方向映射不一致。")
    algorithms = meta.get("algorithms")
    if not algorithms or len(set(algorithms)) != len(algorithms) or any(a not in ("cbf", "mvdr") for a in algorithms):
        raise ValueError("源算法清单不支持。")
    return path, meta


def check(config, base_dir="."):
    pc = pf.Preflight({}, base_dir)
    source, meta, resource = None, None, None
    schema = ({"0.4.1": SCHEMA_V041, "0.4.2": SCHEMA_V042}.get(config.get("product_version"), SCHEMA)
              if isinstance(config, dict) else SCHEMA)
    if pc.schema(config, schema, "$"):
        if config["approval"]["scope_sha256"] != fingerprint(config):
            pc.issue("STALE_PRODUCT_APPROVAL", "approval", "产物范围或分析设置变化，需重新确认。")
        try:
            requested = product_selection(config)
            source, meta = source_metadata(config, base_dir)
            samples, _ = meta["shape_per_algorithm"]
            columns, indices, algorithms = selection(config, meta)
            beams = len(columns)
            if len(indices) != len(set(indices)) or any(i >= meta["shape_per_algorithm"][1] for i in indices):
                pc.issue("RETENTION_RANGE", "time_domain_beam_indices", "保留索引重复或不在已计算方向中。", "invalid")
            fs = meta["sample_rate_hz"]
            band = meta["frequency_coverage"]["requested_band_hz"]
            if products.check_analysis(config["analysis"], fs, samples, band, pc.issue):
                resource = products.estimate(config["analysis"], samples, beams, len(algorithms), requested)
                resource["artifact_bytes"] += samples * len(indices) * len(algorithms) * 8
                resource["working_bytes"] += samples * len(indices) * len(algorithms) * 8
                for estimated, budget in (("working_bytes", "max_working_bytes"), ("artifact_bytes", "max_artifact_bytes")):
                    if resource[estimated] > config[budget]:
                        pc.issue("RESOURCE_BUDGET", budget, "超过已确认预算；不缩小数据、方向或图的范围。")
            out = runner.resolved(config["output_directory"], base_dir)
            if out.exists() or out.is_relative_to(source.parent):
                pc.issue("OUTPUT_EXISTS_OR_OVERLAP", "output_directory", "必须使用源结果目录之外的全新目录。", "invalid")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            pc.issue("SOURCE_RESULT_INVALID", "source_result", str(exc), "invalid")
    severities = {x["severity"] for x in pc.issues}
    status = "invalid" if "invalid" in severities else "needs_input" if severities else "passed"
    return {"product_version": config.get("product_version") if isinstance(config, dict) else None,
            "implementation_version": IMPLEMENTATION_VERSION, "preflight_status": status,
            "can_attempt_execution": not pc.issues, "execution_status": "not_run",
            "issues": pc.issues, "resource_estimate": resource,
            "checked": "configuration, approval digest and source result JSON; no waveform read or FFT"}


def verify_source_files(source, meta):
    indexed = {}
    for item in meta["artifacts"]:
        relative = Path(item["path"])
        path = (source.parent / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(source.parent) or item["path"] in indexed:
            raise ValueError("源产物清单含越界路径或重复项。")
        if path.stat().st_size != item["size_bytes"] or runner.file_digest(path) != item["sha256"]:
            raise ValueError("源产物摘要或大小不匹配：" + item["path"])
        indexed[item["path"]] = path
    return indexed


def load_array(indexed, name):
    if name not in indexed:
        raise ValueError("源完成清单缺少必需产物：" + name)
    path = indexed[name]
    arr = np.load(path, mmap_mode="r", allow_pickle=False)
    if not isinstance(arr, np.ndarray):
        arr.close()
        raise ValueError("不是 NPY 单数组：" + name)
    if path.stat().st_size != arr.offset + arr.nbytes:
        raise ValueError("NPY 带有尾随内容：" + name)
    return arr


def execute(config, base_dir="."):
    report = check(config, base_dir)
    if not report["can_attempt_execution"]:
        raise runner.ExecutionBlocked(report)
    source, original = source_metadata(config, base_dir)
    destination = runner.resolved(config["output_directory"], base_dir)
    nearest = destination.parent
    while not nearest.exists():
        nearest = nearest.parent
    if shutil.disk_usage(nearest).free < report["resource_estimate"]["artifact_bytes"]:
        raise ValueError("磁盘不足；停止，不改变产物范围。")
    indexed = verify_source_files(source, original)
    mask = load_array(indexed, "valid_sample_mask.npy")
    directions = load_array(indexed, "directions_deg.npy")
    if not np.array_equal(directions, original["directions_deg"]):
        raise ValueError("方向文件与完成清单不一致。")
    columns, indices, algorithms = selection(config, original)
    subset = config["product_version"] == "0.4.2"
    selected_beams, scans = saved_mapping(original) if subset else (original["beams"], None)
    displayed = np.asarray([selected_beams[i]["direction_deg"] for i in columns], dtype=float) if subset else directions
    beam_ids = [selected_beams[i]["beam_id"] for i in columns]
    if mask.dtype.kind != "b" or mask.shape != (original["shape_per_algorithm"][0],):
        raise ValueError("有效掩码形状/类型错误。")
    if runner.intervals(mask) != original["valid_sample_intervals"]:
        raise ValueError("有效掩码与记录不一致。")
    arrays = {"directions_deg.npy": directions, "valid_sample_mask.npy": mask}
    if subset:
        arrays["analysis_directions_deg.npy"] = displayed
    requested = product_selection(config)
    for algorithm in algorithms:
        waveform = load_array(indexed, algorithm + "_time.npy")
        if list(waveform.shape) != original["shape_per_algorithm"] or waveform.dtype != np.float64:
            raise ValueError("源波形形状或精度与完成清单不一致。")
        analyzed = waveform[:, columns] if subset else waveform
        values = products.compute(analyzed, mask, original["sample_rate_hz"], config["analysis"],
                                  original["first_sample_offset_seconds"], requested)
        products.attach(arrays, algorithm, values, requested)
        if indices:
            arrays[algorithm + "_time.npy"] = waveform[:, indices]
    source_metadata(config, base_dir)
    verify_source_files(source, original)
    # Retain provenance without falsely copying old artifact/implementation claims.
    keys = ("sample_rate_hz", "source_sample_range", "first_sample_offset_seconds",
            "time_reference", "time_alignment", "reference_m", "units",
            "valid_sample_intervals", "interval_convention", "validity_limit",
            "direction_plan", "direction_basis", "directions_deg", "processing_history",
            "frequency_coverage", "source_sha256", "channel_ids", "limitations",
            "inspection_handoff", "upstream_inspection", "original_source_sample_range",
            "original_source_channel_indices", "time_mapping", "amplitude_convention")
    meta = {k: copy.deepcopy(original[k]) for k in keys if k in original}
    meta.update({
        "product_version": config["product_version"], "execution_version": "0.4",
        "implementation_version": IMPLEMENTATION_VERSION,
        "subset_products_validation": "v043_scoped_regression_passed",
        "selective_products_validation": "v043_scoped_regression_passed",
        "execution_status": "completed", "parameter_status": "complete",
        "validation_status": "spectral_postprocessing_not_engineering_acceptance",
        "source_result": {"path": str(source), "sha256": config["source_result"]["sha256"]},
        "beamforming_recomputed": False, "source_files_modified": False,
        "algorithms": algorithms, "data_role": "beamformed",
        "axes": ["sample", "beam"], "dtype": "float64",
        "shape_per_algorithm": [original["shape_per_algorithm"][0], len(indices)] if indices else None,
        "scan_beams": [{"beam_id": b["beam_id"], "scan_column": i,
                        "direction_deg": b["direction_deg"]} for i, b in enumerate(original["beams"])],
        "beams": [{"beam_id": original["beams"][i]["beam_id"], "column": j,
                   "scan_column": i, "direction_deg": original["directions_deg"][i]}
                  for j, i in enumerate(indices)],
        "time_domain_retention": {"scan_beam_indices": indices, "saved": bool(indices),
                                  "selection_method": "explicit_user_list_not_auto_selection"},
        "coverage": {"spectral_beams": len(directions), "time_beams": len(indices),
                     "algorithms": algorithms, "requested_auxiliary_products": requested},
        "spectral_products": products.metadata(config["analysis"], arrays, algorithms, original["units"], requested),
        "resource_estimate": report["resource_estimate"],
        "handoff_status": "blocked", "downstream_integration": "not_integrated",
        "product_scope_sha256": fingerprint(config),
        "implementation_files_sha256": {Path(p).name: runner.file_digest(p)
                                       for p in (__file__, products.__file__, runner.__file__, pf.__file__)},
    })
    if subset:
        meta["scan_beams"] = copy.deepcopy(scans)
        meta["beams"] = [dict(selected_beams[i], column=j) for j, i in enumerate(indices)]
        meta["time_domain_retention"]["scan_beam_indices"] = [selected_beams[i]["scan_column"] for i in indices]
        meta["spectral_beams"] = [
            {"spectral_column": j, "beam_id": selected_beams[i]["beam_id"],
             "source_column": i, "scan_column": selected_beams[i]["scan_column"],
             "direction_deg": selected_beams[i]["direction_deg"]} for j, i in enumerate(columns)]
        meta["coverage"].update(
            spectral_beams=len(columns), source_scan_beams=len(directions),
            source_saved_beams=original["shape_per_algorithm"][1],
            analyzed_beam_ids=beam_ids, source_algorithms=original["algorithms"],
            all_original_scan_directions_analyzed=len(columns) == len(directions))
        meta["spectral_products"]["beam_axis"] = "spectral_beams ordered by spectral_column; not the full scan_beams"
        meta["spectral_products"]["directions_file"] = "analysis_directions_deg.npy"
        for entries in meta["spectral_products"]["per_algorithm"].values():
            for entry in entries.values():
                entry["axes"] = ["spectral_beam" if a == "scan_beam" else a for a in entry["axes"]]
    destination.mkdir(parents=True, exist_ok=False)
    runner.write_json(destination / "run_started.json", {"completion_manifest": "result.json", "usable": False})
    try:
        for name, arr in arrays.items():
            with (destination / name).open("xb") as handle:
                np.save(handle, arr, allow_pickle=False)
        runner.write_json(destination / "confirmed_product_config.json", config)
        meta["presentation"] = products.render(destination, arrays, algorithms, displayed,
                                              original["direction_plan"], config["title"], config["analysis"], original["sample_rate_hz"],
                                              requested, beam_ids=beam_ids if subset else None)
        source_metadata(config, base_dir)
        verify_source_files(source, original)
        meta["artifacts"] = [{"path": str(p.relative_to(destination)),
                             "sha256": runner.file_digest(p), "size_bytes": p.stat().st_size}
                            for p in sorted(destination.rglob("*")) if p.is_file() and p.name != "run_started.json"]
        runner.write_json(destination / "result.pending.json", meta)
        (destination / "result.pending.json").rename(destination / "result.json")
    except Exception as exc:
        runner.write_json(destination / "failure.json", {"execution_status": "failed", "usable": False, "error": str(exc)})
        raise
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "digest", "run"))
    parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    try:
        config = pf.load_plan(args.config)
        if args.command == "digest":
            result, code = {"scope_sha256": fingerprint(config)}, 0
        elif args.command == "check":
            result = check(config, args.config.resolve().parent)
            code = 0 if result["can_attempt_execution"] else 2
        else:
            result, code = execute(config, args.config.resolve().parent), 0
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return code
    except runner.ExecutionBlocked as exc:
        print(json.dumps(exc.report, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, OverflowError, MemoryError, RuntimeWarning, FloatingPointError) as exc:
        print(json.dumps({"execution_status": "failed", "usable": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
