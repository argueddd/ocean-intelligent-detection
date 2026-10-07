#!/usr/bin/env python3
"""Confirmed NPY executor v0.4.2, configuration v0.4. 'check' never reads samples."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np
import scipy
from scipy.signal import detrend

import preflight as pf
import beamforming_core as core
import result_products as products
import inspection_handoff as intake

IMPLEMENTATION_VERSION = "0.4.2"

NUMERICS = {
    "reader": pf.Choice(("npy_real_2d",)),
    "compute_precision": pf.Choice(("float64",)),
    "source_sha256": pf.STR,
    "direction_mapping": pf.Choice(("look_vector_cos_sin_v1",)),
    "direction_basis": pf.Array(pf.VEC3, length=3),
    "stft_profile": pf.Choice(("unscaled_rfft_wola_v1",)),
    "edge_bins": pf.Choice(("zero", "require_real_steering")),
    "covariance_schedule": pf.Choice(("offline_trailing_bootstrap_v1", "not_applicable")),
    "max_delay_to_window_ratio": pf.POS,
    "response_tolerance": pf.POS,
    "coverage_tolerance": pf.POS,
    "max_working_bytes": pf.PINT,
    "max_artifact_bytes": pf.PINT,
}
APPROVAL = {
    "status": pf.Choice(("confirmed",)),
    "scope_sha256": pf.STR,
    "evidence": pf.STR,
    "confirmation": {"method": pf.Choice(("user",)), "reference": pf.STR},
}


class ExecutionBlocked(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("执行门禁未通过；请查看 issues，不会读波形或计算。")


def fingerprint(config):
    return pf.canonical_digest({k: v for k, v in config.items() if k != "approval"})


def resolved(path, base):
    path = Path(path).expanduser()
    return (path if path.is_absolute() else Path(base) / path).resolve()


def sizes(plan, beams, analysis=None):
    n = plan["input"]["sample_range"][1] - plan["input"]["sample_range"][0]
    t = plan["transform"]
    h, l, f = t["hop_samples"], t["window_samples"], t["nfft"] // 2 + 1
    # Integer count only: never allocate frame/grid arrays before budget gate.
    frames = ((n - l) // h + 1 if t["boundary"] == "no_padding" else
              (n - 1) // h + 1 + (l - 1) // h)
    c, a = len(plan["processing"]["channels"]), len(plan["algorithms"])
    training_n = n
    updates = 0
    if "mvdr" in plan["algorithms"]:
        m = plan["mvdr"]
        if m["training"]["mode"] == "specified_range":
            lo, hi = m["training"]["sample_range"]
            training_n = hi - lo
        updates = (frames - 1) // m["update_interval_frames"] + 1
    training_frames = max(0, (training_n - l) // h + 1)
    weights = 16 * f * c * beams * (int("cbf" in plan["algorithms"]) + updates)
    waveform = n * beams * a * 8
    # Conservative managed-array allowance, not an OS/RSS or BLAS hard cap.
    working = 4 * (8 * (n + training_n + 2 * l) * c +
                   16 * f * c * (frames + training_frames) +
                   16 * frames * f * beams + weights + waveform +
                   16 * f * c * c + 8 * n * (beams + 4))
    saved = n * len(plan["output"]["time_domain_beam_indices"]) * a * 8
    artifacts = weights + saved + updates * f * 3 * 8 + 8 * frames * 4 + 6 * 1024**2
    if analysis is not None:
        extra = products.estimate(analysis, n, beams, a, plan["output"]["auxiliary_products"])
        working += extra["working_bytes"]
        artifacts += extra["artifact_bytes"]
    return {"samples": n, "frames": frames, "training_frames": training_frames,
            "updates": updates, "working_bytes_estimate": working,
            "artifact_bytes_estimate": artifacts}


def check(config, base_dir="."):
    pc = pf.Preflight({}, base_dir)
    issue = pc.issue
    nested = None
    estimate = None
    if not isinstance(config, dict):
        issue("ROOT_TYPE", "$", "执行配置必须是对象。", "invalid")
    else:
        for key in sorted(config.keys() - {"execution_version", "plan", "numerics", "analysis", "approval", "inspection_handoff"}):
            issue("UNKNOWN_KEY", key, "未知执行配置字段。", "invalid")
        pc.schema(config.get("execution_version"), pf.Choice(("0.4",)), "execution_version")
        numeric_ok = pc.schema(config.get("numerics"), NUMERICS, "numerics")
        approval_ok = pc.schema(config.get("approval"), APPROVAL, "approval")
        plan = config.get("plan")
        nested = pf.check_plan(plan, base_dir)
        if isinstance(plan, dict) and plan.get("schema_version") != "0.4":
            issue("RETENTION_MIGRATION_REQUIRED", "plan.schema_version",
                  "旧配置默认保存全部波束；请先询问保留方向并使用 0.4 配置，不自动迁移。")
        for problem in nested["issues"]:
            issue(problem["code"], "plan." + problem["path"], problem["message"], problem["severity"])
        if approval_ok:
            try:
                if config["approval"]["scope_sha256"] != fingerprint(config):
                    issue("STALE_EXECUTION_CONFIRMATION", "approval", "执行范围或数值规则已变化，须重新确认。")
            except (ValueError, TypeError, OverflowError, RecursionError) as exc:
                issue("INVALID_JSON_VALUE", "$", str(exc), "invalid")
        if nested["preflight_status"] == "passed":
            if nested["route"] != "beamforming":
                issue("BYPASS_NOT_EXECUTED", "plan.input.data_role",
                      "已有波束/单阵元不进入阵列执行器；经检查导出后另用 bypass_handoff.py 显式确认数据交接，不自动执行。", "unsupported")
            elif numeric_ok:
                p, q = plan, config["numerics"]
                if p["input"]["source"]["field"] != "__array__":
                    issue("NPY_FIELD", "plan.input.source.field", "NPY 整数组字段必须明确为 __array__。", "unsupported")
                if p["input"]["dtype"] not in ("float32", "float64"):
                    issue("READER_DTYPE", "plan.input.dtype", "v0.3 只执行 float32/float64 NPY。", "unsupported")
                if p["processing"]["precision"] != "float64":
                    issue("PRECISION", "plan.processing.precision", "v0.3 核与输出均为 float64；不自动更改确认精度。", "unsupported")
                if q["edge_bins"] == "zero" and p["transform"]["out_of_band"] == "full_band":
                    issue("EDGE_BAND_CONFLICT", "numerics.edge_bins", "full_band 与 DC/Nyquist 置零冲突；须明确处理范围。", "invalid")
                analysis_ok = True
                requested = p["output"]["auxiliary_products"]
                if requested:

                    analysis_ok = products.check_analysis(config.get("analysis"), p["input"]["sample_rate_hz"],
                        p["input"]["sample_range"][1] - p["input"]["sample_range"][0], p["processing"]["band_hz"], issue)
                elif "analysis" not in config or config["analysis"] is not None:
                    issue("ANALYSIS_NOT_APPLICABLE", "analysis", "无谱产物时必须明确 analysis=null。", "invalid")
                    analysis_ok = False
                if not requested and not p["output"].get("time_domain_beam_indices"):
                    issue("NO_SIGNAL_PRODUCTS", "plan.output", "未保留时域且未请求任何谱产物；请明确交付内容。", "invalid")
                if p["output"]["weights"] != "save_all":
                    issue("WEIGHTS_MODE", "plan.output.weights", "v0.3 必须保存全部实际权重。", "unsupported")
                if p["geometry"]["coordinate_system"]["handedness"] != "right":
                    issue("HANDEDNESS", "plan.geometry", "数值入口暂只支持右手坐标。", "unsupported")
                if any(k in p and k not in p["algorithms"] for k in ("cbf", "mvdr")):
                    issue("UNUSED_ALGORITHM_CONFIG", "plan.algorithms", "请移除未选算法的参数，不能悄悄忽略。", "invalid")
                if "mvdr" in p["algorithms"]:
                    if q["covariance_schedule"] != "offline_trailing_bootstrap_v1":
                        issue("COVARIANCE_SCHEDULE", "numerics.covariance_schedule", "需确认离线启动与滑窗更新语义。")
                    if p["mvdr"]["failure_policy"] != "stop":
                        issue("FAILURE_POLICY", "plan.mvdr.failure_policy", "v0.3 仅实现 stop；尚不实现 mark_invalid。", "unsupported")
                elif q["covariance_schedule"] != "not_applicable":
                    issue("UNUSED_COVARIANCE_SCHEDULE", "numerics.covariance_schedule", "无 MVDR 时须明确 not_applicable。", "invalid")
                for key in ("response_tolerance", "coverage_tolerance"):
                    if q[key] > 1e-4:
                        issue("LOOSE_TOLERANCE", "numerics." + key, "实现接受的数值容差上限为 1e-4。", "invalid")
                if q["max_delay_to_window_ratio"] > 1:
                    issue("DELAY_RATIO", "numerics.max_delay_to_window_ratio", "窄带近似上限必须在 (0,1] 内。", "invalid")
                sha = q["source_sha256"]
                if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                    issue("SOURCE_DIGEST", "numerics.source_sha256", "源文件摘要应为 64 位小写 SHA256。", "invalid")
                basis = np.asarray(q["direction_basis"], dtype=float)
                if (not np.allclose(basis @ basis.T, np.eye(3), atol=1e-10, rtol=0) or
                        not np.allclose(np.cross(basis[0], basis[1]), basis[2], atol=1e-10, rtol=0)):
                    issue("DIRECTION_BASIS", "numerics.direction_basis", "须明确正交、单位、右手的 [零度,正90度,向上] 基向量。", "invalid")
                if "inspection_handoff" in config:
                    try:
                        intake.validate_binding(config["inspection_handoff"], p, q, base_dir)
                    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError) as exc:
                        issue("INSPECTION_HANDOFF", "inspection_handoff", str(exc), "invalid")
                estimate = (sizes(p, nested["planned_beam_count"], config.get("analysis"))
                            if analysis_ok and p.get("schema_version") == "0.4" else None)
                for estimate_key, budget_key in (("working_bytes_estimate", "max_working_bytes"),
                                                  ("artifact_bytes_estimate", "max_artifact_bytes")):
                    if estimate is not None and estimate[estimate_key] > q[budget_key]:
                        issue("RESOURCE_BUDGET", "numerics." + budget_key,
                              "规模超过已确认预算；不能自动减小区间/方向/通道。")
                # Cheap geometric upper bound, no large direction grid allocation.
                coord = np.asarray(p["geometry"]["coordinates_m"], dtype=float)
                aperture = float(np.linalg.norm(np.ptp(coord, axis=0)))
                ratio = aperture / p["propagation"]["sound_speed_m_s"] * p["input"]["sample_rate_hz"] / p["transform"]["window_samples"]
                if not math.isfinite(ratio) or ratio > q["max_delay_to_window_ratio"]:
                    issue("NARROWBAND_APPROXIMATION", "numerics.max_delay_to_window_ratio",
                          "阵列包围盒传播时差/窗时长超过已确认近似上限。")
    severities = {x["severity"] for x in pc.issues}
    status = ("invalid" if "invalid" in severities else "unsupported" if "unsupported" in severities
              else "needs_input" if severities else "passed")
    return {"execution_version": "0.4", "preflight_status": status,
            "implementation_version": IMPLEMENTATION_VERSION,
            "execution_status": "not_run", "can_attempt_execution": status == "passed",
            "implementation_status": {"preflight": "implemented", "cbf": "implemented_limited_profile",
                                      "mvdr": "implemented_limited_profile", "time_reconstruction": "implemented",
                                      "selective_time_retention": "implemented", "spectral_products": "implemented",
                                      "selective_spectral_products": "v043_scoped_regression_passed",
                                      "inspection_handoff": "v043_scoped_regression_passed"},
            "issues": pc.issues, "resource_estimate": estimate,
            "manifest_preflight": nested,
            "not_checked": ["实际 NPY 内容、摘要及边界可逆性（run 阶段检查）",
                            "确认记录真实性、物理模型真实性、同步与标定",
                            "SWellEx-96 实测效果、下游线谱检测联调"]}


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def preprocess(x, choices):
    x = np.array(x, dtype=float, copy=True)
    if not np.isfinite(x).all():
        raise core.NumericalError("实际输入含 NaN/Inf；未修复。")
    for choice in choices:
        x = x - x.mean(axis=0) if choice == "demean" else detrend(x, axis=0, type="linear")
    if not np.isfinite(x).all():
        raise core.NumericalError("预处理后出现非有限值。")
    return x


def intervals(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return np.column_stack((np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))).tolist()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def execute(config, base_dir="."):
    # Never trust a caller-supplied "passed" report; re-evaluate config and confirmations.
    report = check(config, base_dir)
    if not report["can_attempt_execution"]:
        raise ExecutionBlocked(report)
    p, q = config["plan"], config["numerics"]
    handoff = (intake.validate_binding(config["inspection_handoff"], p, q, base_dir)
               if "inspection_handoff" in config else None)
    original_offset = handoff["export_sample_zero_source_sample"] if handoff is not None else 0
    source = resolved(p["input"]["source"]["path"], base_dir)
    destination = resolved(p["output"]["directory"], base_dir)
    nearest = destination.parent
    while not nearest.exists():
        nearest = nearest.parent
    if shutil.disk_usage(nearest).free < report["resource_estimate"]["artifact_bytes_estimate"]:
        raise core.NumericalError("可用磁盘不足；未改变请求规模。")
    digest = file_digest(source)
    if digest != q["source_sha256"]:
        raise core.NumericalError("源文件内容摘要不匹配；不采用已变化的数据。")
    # Read-only mmap; no pickle, transpose, channel repair or unit conversion.
    raw = np.load(source, mmap_mode="r", allow_pickle=False)
    if not isinstance(raw, np.ndarray):
        raw.close()
        raise core.NumericalError("不是单个 NPY 数组；不会自动选择 NPZ 字段。")
    if raw.shape != tuple(p["input"]["shape"]) or raw.ndim != 2:
        raise core.NumericalError("实际数组形状与确认的 [sample,channel] 不匹配。")
    if raw.dtype.name != p["input"]["dtype"] or raw.dtype.kind != "f":
        raise core.NumericalError("实际 dtype 与确认记录不一致。")
    if source.stat().st_size != raw.offset + raw.nbytes:
        raise core.NumericalError("NPY 大小异常或包含尾随内容；不忽略。")
    channel_indices = [p["input"]["channels"].index(c) for c in p["processing"]["channels"]]
    lo, hi = p["input"]["sample_range"]
    x = preprocess(raw[lo:hi][:, channel_indices], p["processing"]["preprocessing"])
    t = p["transform"]
    spectra, starts = core.analyze(x, t)
    # Before expensive beamforming, verify invertibility for this exact finite segment.
    identity = core.synthesize(spectra, starts, len(x), t, q["coverage_tolerance"])
    reconstruction_error = float(np.max(np.abs(identity - x)))
    reference_scale = max(1.0, float(np.max(np.abs(x))))
    if reconstruction_error > q["response_tolerance"] * reference_scale:
        raise core.NumericalError("STFT/逆变换本段重建误差超出确认容差。")
    del identity
    directions = core.expand_directions(p["direction_plan"])
    vectors = core.direction_vectors(directions, q["direction_basis"], p["direction_plan"]["parameterization"])
    fs = p["input"]["sample_rate_hz"]
    first_sample_seconds = (original_offset + lo) / fs
    frequencies = np.fft.rfftfreq(t["nfft"], 1 / fs)
    response, delays = core.steering(frequencies, p["geometry"]["coordinates_m"],
                                      p["geometry"]["reference_m"], vectors,
                                      p["propagation"]["sound_speed_m_s"])
    band_lo, band_hi = p["processing"]["band_hz"]
    active = (frequencies >= band_lo) & (frequencies <= band_hi)
    edges = [0] + ([len(frequencies) - 1] if t["nfft"] % 2 == 0 else [])
    if q["edge_bins"] == "zero":
        active[edges] = False
        if t["out_of_band"] == "full_band":
            raise core.NumericalError("full_band 与 DC/Nyquist 置零冲突；请先明确处理范围。")
    else:
        for f in edges:
            if active[f]:
                if np.max(np.abs(response[f].imag)) > q["response_tolerance"]:
                    raise core.NumericalError("实信号端点频率需要实数导向响应；不悄悄丢弃虚部。")
                response[f] = response[f].real
    if not active.any():
        raise core.NumericalError("确认频带内没有可执行频点；不扩大频带。")
    valid = core.conservative_mask(len(x), starts, t["window_samples"],
                                    np.max(np.abs(delays)) * fs)
    if not valid.any():
        raise core.NumericalError("没有不受填充/参考位置边界影响的内部样本。")
    arrays = {"directions_deg.npy": directions, "look_vectors.npy": vectors,
              "frequencies_hz.npy": frequencies, "active_frequency_mask.npy": active,
              "frame_start_sample.npy": starts + lo, "valid_sample_mask.npy": valid}
    diagnostics = {}
    retained = p["output"]["time_domain_beam_indices"]

    def collect(algorithm, coefficients):
        # Reconstruct in memory for consistent output PSD; do not save unselected y.
        waveforms = core.synthesize(coefficients, starts, len(x), t, q["coverage_tolerance"])
        if config.get("analysis") is not None:
            values = products.compute(waveforms, valid, fs, config["analysis"], first_sample_seconds,
                                      p["output"]["auxiliary_products"])
            products.attach(arrays, algorithm, values, p["output"]["auxiliary_products"])
        if retained:
            arrays[algorithm + "_time.npy"] = waveforms[:, retained].copy()

    if "cbf" in p["algorithms"]:
        weights = core.cbf_weights(response, p["cbf"]["element_weights"])
        weights[~active] = 0
        residual = float(np.max(np.abs(np.sum(weights[active].conj() * response[active], axis=1) - 1)))
        if residual > q["response_tolerance"]:
            raise core.NumericalError("CBF 单位响应超出数值容差。")
        y = np.einsum("fcb,tfc->tfb", weights.conj(), spectra, optimize=False)
        collect("cbf", y)
        arrays["cbf_weights.npy"] = weights
        diagnostics["cbf"] = {"max_unit_response_error": residual}
    if "mvdr" in p["algorithms"]:
        settings = p["mvdr"]
        tr_lo, tr_hi = (settings["training"]["sample_range"]
                        if settings["training"]["mode"] == "specified_range" else (lo, hi))
        training_x = (x if (tr_lo, tr_hi) == (lo, hi) else
                      preprocess(raw[tr_lo:tr_hi][:, channel_indices], p["processing"]["preprocessing"]))
        training, training_starts = core.analyze(training_x, t, training=True)
        training_starts += tr_lo
        every = settings["update_interval_frames"]
        update_frames = np.arange(0, len(starts), every)
        all_weights = np.zeros((len(update_frames), len(frequencies), len(channel_indices), len(directions)), complex)
        # Zero diagnostics on inactive frequencies; active_frequency_mask disambiguates.
        conditions = np.zeros((len(update_frames), len(frequencies)))
        loading = np.zeros_like(conditions)
        residuals = np.zeros_like(conditions)
        training_ranges = []
        y = np.zeros((len(starts), len(frequencies), len(directions)), complex)
        for j, first in enumerate(update_frames):
            end = min(len(starts), int(first) + every)
            anchor = lo + int(starts[first]) + t["window_samples"] // 2
            left, right = core.training_window(training_starts, t["window_samples"], anchor,
                                                settings["covariance_window_frames"])
            training_ranges.append([left, right])
            for f in np.flatnonzero(active):
                try:
                    w, condition, delta, residual = core.mvdr_weights(
                        training[left:right, f], response[f], settings, q["response_tolerance"])
                except core.NumericalError as exc:
                    raise core.NumericalError(f"MVDR 更新 {j}，频点 {f}：{exc}") from exc
                all_weights[j, f] = w
                conditions[j, f], loading[j, f], residuals[j, f] = condition, delta, residual
                y[first:end, f] = np.einsum("tc,cb->tb", spectra[first:end, f],
                                            w.conj(), optimize=False)
        collect("mvdr", y)
        arrays.update({"mvdr_weights.npy": all_weights, "mvdr_condition.npy": conditions,
                       "mvdr_loading.npy": loading, "mvdr_response_error.npy": residuals,
                       "mvdr_update_frame.npy": update_frames,
                       "mvdr_training_frame_ranges.npy": np.asarray(training_ranges),
                       "mvdr_training_frame_start_sample.npy": training_starts})
        diagnostics["mvdr"] = {"max_unit_response_error": float(residuals.max()),
                               "max_condition_number": float(conditions.max()),
                               "covariance_schedule": q["covariance_schedule"]}
    if any(not np.isfinite(array).all() for array in arrays.values()):
        raise core.NumericalError("产物含非有限数，停止保存。")
    # Revalidate content AND stat before publishing any successful result.
    stat = source.stat()
    if (file_digest(source) != digest or stat.st_size != p["input"]["source"]["size_bytes"] or
            stat.st_mtime_ns != p["input"]["source"]["mtime_ns"]):
        raise core.NumericalError("计算期间源数据发生变化；不发布结果。")
    metadata = {
        "execution_version": "0.4", "execution_status": "completed",
        "implementation_version": IMPLEMENTATION_VERSION,
        "validation_status": "numerical_checks_passed_not_engineering_acceptance",
        "parameter_status": "complete",
        "implementation_status": report["implementation_status"], "issues": [],
        "data_role": "beamformed", "axes": ["sample", "beam"],
        "scan_beams": [{"beam_id": f"beam_{i:06d}", "scan_column": i, "direction_deg": d,
                        "fixed_direction": True} for i, d in enumerate(directions.tolist())],
        "beams": [{"beam_id": f"beam_{i:06d}", "column": j, "scan_column": i,
                   "direction_deg": directions[i].tolist(), "fixed_direction": True}
                  for j, i in enumerate(retained)],
        "time_domain_retention": {"scan_beam_indices": retained, "saved": bool(retained),
                                  "selection_method": "explicit_user_list_not_auto_selection"},
        "coverage": {"source_shape": p["input"]["shape"], "source_sample_range": [lo, hi],
                     "channel_ids": p["processing"]["channels"], "algorithms": p["algorithms"],
                     "all_requested_directions_computed": True,
                     "all_requested_time_directions_saved": bool(retained),
                     "all_computed_directions_saved_as_time": len(retained) == len(directions),
                     "requested_auxiliary_products": p["output"]["auxiliary_products"],
                     "all_requested_directions_have_spectral_products": config.get("analysis") is not None},
        "frequency_coverage": {"requested_band_hz": p["processing"]["band_hz"],
                               "actual_bin_centers_hz": frequencies[active].tolist(),
                               "edge_bins": q["edge_bins"], "outside_active_bins": "zero",
                               "definition": "inclusive STFT-bin center selection; not an ideal brick-wall filter"},
        "weights_axes": {"cbf": ["frequency", "channel", "beam"],
                         "mvdr": ["update", "frequency", "channel", "beam"]},
        "amplitude_convention": "unscaled rfft / normalized irfft / finite-overlap normalization; w^H a=1 on active bins",
        "processing_history": {"upstream": p["input"]["processing_history"],
                               "this_run": p["processing"]["preprocessing"]},
        "algorithms": p["algorithms"], "dtype": "float64",
        "shape_per_algorithm": [hi - lo, len(retained)] if retained else None, "sample_rate_hz": fs,
        "units": p["input"]["units"], "time_reference": p["input"]["time_reference"],
        "source_sample_range": [lo, hi], "first_sample_offset_seconds": first_sample_seconds,
        "time_alignment": "reference_position", "reference_m": p["geometry"]["reference_m"],
        "channel_ids": p["processing"]["channels"], "direction_plan": p["direction_plan"],
        "directions_deg": directions.tolist(), "direction_basis": q["direction_basis"],
        "valid_sample_intervals": intervals(valid), "interval_convention": "output-relative half-open",
        "validity_limit": "保守边界掩码只约束填充/延时边界；不证明真实连续性、同步、标定或窄带近似误差。",
        "source_sha256": digest, "execution_scope_sha256": fingerprint(config),
        "stft_identity_max_abs_error": reconstruction_error, "diagnostics": diagnostics,
        "resource_estimate": report["resource_estimate"],
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__},
        "implementation_files_sha256": {"execute.py": file_digest(Path(__file__)),
                                         "beamforming_core.py": file_digest(Path(core.__file__)),
                                         "preflight.py": file_digest(Path(pf.__file__)),
                                         "result_products.py": file_digest(Path(products.__file__)),
                                         "inspection_handoff.py": file_digest(Path(intake.__file__))},
        "handoff_status": "blocked", "downstream_integration": "not_integrated",
        "real_data_validation": "not_performed_by_this_run",
        "limitations": ["离线、整段内存处理，不支持流式", "相移窄带分箱近似，不是精确宽带分数延时",
                        "未做自动目标选择或跟踪", "没有推断绝对声压或实测 SINR/定位精度"],
    }
    if handoff is not None:
        intake.validate_binding(config["inspection_handoff"], p, q, base_dir)
        metadata["inspection_handoff"] = {
            "path": str(resolved(config["inspection_handoff"]["path"], base_dir)),
            "sha256": config["inspection_handoff"]["sha256"]}
        metadata["original_source_sample_range"] = [original_offset + lo, original_offset + hi]
        metadata["original_source_channel_indices"] = [handoff["source_channel_indices"][i] for i in channel_indices]
        metadata["time_mapping"] = {
            "source_sample_range_basis": "exported NPY indices",
            "original_source_sample_range_basis": "original recording indices",
            "frame_start_sample_basis": "exported NPY indices",
            "original_sample_index": "export_sample_zero_source_sample + NPY sample index",
            "export_sample_zero_source_sample": original_offset,
            "seconds_basis": "original recording sample zero, described by time_reference",
            "acquisition_continuity_verified": False}
        metadata["upstream_inspection"] = {
            key: handoff[key] for key in ("original_source", "inspection_result", "checks",
                                         "upstream_issues", "not_checked", "inspection_readiness",
                                         "inspection_linkage", "inspection_linkage_limit",
                                         "metadata_evidence", "identity_evidence",
                                         "processing_history_evidence", "export_transformations")}
        metadata["upstream_inspection"]["inspection_result_path_base"] = str(
            resolved(config["inspection_handoff"]["path"], base_dir).parent)
    # Exclusive creation; no existing files or directories are overwritten.
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "run_started.json", {"event": "write_started",
                                                  "completion_manifest": "result.json",
                                                  "usable_without_completion_manifest": False})
    try:
        for name, array in arrays.items():
            with (destination / name).open("xb") as handle:
                np.save(handle, array, allow_pickle=False)
        write_json(destination / "confirmed_config.json", config)
        if config.get("analysis") is not None:
            metadata["spectral_products"] = products.metadata(config["analysis"], arrays, p["algorithms"],
                                                             p["input"]["units"], p["output"]["auxiliary_products"])
            metadata["presentation"] = products.render(destination, arrays, p["algorithms"], directions,
                                                       p["direction_plan"], "Beamforming output analysis", config["analysis"], fs,
                                                       p["output"]["auxiliary_products"])
        artifacts = [{"path": str(path.relative_to(destination)), "size_bytes": path.stat().st_size,
                      "sha256": file_digest(path)} for path in sorted(destination.rglob("*"))
                     if path.is_file() and path.name != "run_started.json"]
        metadata["artifacts"] = artifacts
        if handoff is not None:
            intake.validate_binding(config["inspection_handoff"], p, q, base_dir)
        # Completion manifest is written LAST; its absence means partial unusable results.
        write_json(destination / "result.pending.json", metadata)
        # Same-directory rename publishes a complete JSON document atomically.
        (destination / "result.pending.json").rename(destination / "result.json")
    except Exception as exc:
        write_json(destination / "failure.json", {"execution_status": "failed", "usable": False,
                                                  "error": str(exc)})
        raise
    return metadata


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
    except ExecutionBlocked as exc:
        print(json.dumps(exc.report, ensure_ascii=False, indent=2, allow_nan=False), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, MemoryError,
            RuntimeWarning, FloatingPointError) as exc:
        print(json.dumps({"execution_status": "failed", "error": str(exc),
                          "usable": False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
