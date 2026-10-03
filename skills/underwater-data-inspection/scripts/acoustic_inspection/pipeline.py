"""Configuration, stage orchestration and evidence export."""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
import platform
import importlib.metadata
import numpy as np
from .readers import InputRequired, Source, fingerprint, probe, scalar_rate, select_field
from .quality import check
from .coverage import attach_coverage, report_coverage

DEFAULTS = dict(mode="check", max_read_mib=512, block_samples=65536,
                analysis_max_samples=262144, analysis_max_channels=4, overlap_fraction=0.5)
ALLOWED = set(DEFAULTS) | set(("field", "sample_axis", "sample_rate_hz", "sample_rate_field",
    "sample_rate_resolution", "units", "channel_ids", "array_geometry_m",
    "start_sample", "stop_sample", "channels", "nperseg", "band_hz"))
STAGES = ("probe", "reading", "standardization", "integrity", "channel_quality", "analysis")
NOT_CHECKED = [
    "真实丢帧、重复采集帧和采样时钟漂移：尚未实现参考时间戳/计数器检查。",
    "确认削波率：尚未实现参考 ADC 满量程与编码标定的检查。",
    "极性、串扰、同步及幅相标定故障：尚未实现独立参考驱动的故障判定。",
    "校准声压级、严格 SNR/SINR、目标检测和方位估计不属于当前基础实现。",
]


def real(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_config(value):
    if not isinstance(value, dict):
        raise InputRequired("invalid_config", "Configuration must be a JSON object.")
    if set(value)-ALLOWED:
        raise InputRequired("unknown_config", f"Unknown configuration keys: {sorted(set(value)-ALLOWED)}")
    c = {**DEFAULTS, **value}
    if c["mode"] not in ("read", "check", "analyze"):
        raise InputRequired("invalid_mode", "mode must be read/check/analyze.")
    for key in ("block_samples", "analysis_max_samples", "analysis_max_channels", "nperseg"):
        if key in c and (type(c[key]) is not int or c[key] < (8 if key == "nperseg" else 1)):
            raise InputRequired("invalid_config", f"{key} must be a positive integer (nperseg >= 8).")
    if c["analysis_max_channels"] > 16:
        raise InputRequired("invalid_config", "analysis_max_channels must be <=16.")
    for key in ("sample_rate_hz", "max_read_mib"):
        if key in c and (not real(c[key]) or c[key] <= 0):
            raise InputRequired("invalid_config", f"{key} must be finite and positive.")
    if not real(c["overlap_fraction"]) or not 0 <= c["overlap_fraction"] < 1:
        raise InputRequired("invalid_config", "overlap_fraction must lie in [0,1).")
    for key in ("field", "sample_rate_field", "units"):
        if key in c and (not isinstance(c[key], str) or not c[key].strip()):
            raise InputRequired("invalid_config", f"{key} must be a nonempty string.")
    for key in ("start_sample", "stop_sample"):
        if key in c and (type(c[key]) is not int or c[key] < 0):
            raise InputRequired("invalid_config", f"{key} must be a nonnegative integer.")
    if "sample_axis" in c and (type(c["sample_axis"]) is not int or c["sample_axis"] not in (0, 1)):
        raise InputRequired("invalid_config", "sample_axis must be integer 0 or 1.")
    if "channels" in c:
        ch = c["channels"]
        if not isinstance(ch, list) or not ch or any(type(x) is not int or x < 0 for x in ch) or ch != sorted(set(ch)):
            raise InputRequired("invalid_channels", "channels must be a nonempty, unique, ascending list of original indices.")
    if "channel_ids" in c:
        ids = c["channel_ids"]
        if not isinstance(ids, list) or any(not isinstance(v, str) or not v.strip() for v in ids) or len(set(ids)) != len(ids):
            raise InputRequired("invalid_channel_ids", "channel_ids must be a complete unique list of nonempty strings.")
    if "band_hz" in c:
        b = c["band_hz"]
        if not isinstance(b, list) or len(b) != 2 or not all(real(v) for v in b) or not 0 <= b[0] < b[1]:
            raise InputRequired("invalid_band", "band_hz must contain finite values 0 <= lo < hi.")
    if "array_geometry_m" in c:
        g = c["array_geometry_m"]
        if not isinstance(g, list) or not g or any(not isinstance(row, list) or len(row) != 3 or not all(real(v) for v in row) for row in g):
            raise InputRequired("invalid_geometry", "array_geometry_m must contain finite numeric triples, without unit guessing.")
    if "sample_rate_resolution" in c:
        r = c["sample_rate_resolution"]
        if not isinstance(r, dict) or set(r) != {"use", "reason"} or r["use"] not in ("user", "file") or not isinstance(r["reason"], str) or not r["reason"].strip():
            raise InputRequired("invalid_resolution", "Resolution requires use=user/file and the user's nonempty reason.")
    return c


def rate_metadata(path, info, cfg, config_source):
    native = info.get("header_sample_rate_hz")
    origin = "WAV format header" if native is not None else None
    if "sample_rate_field" in cfg:
        if info["format"] == "wav":
            raise InputRequired("invalid_rate_field", "WAV sampling rate comes from its header, not a named field.")
        native = scalar_rate(path, info, cfg["sample_rate_field"], cfg["max_read_mib"]*1024**2)
        origin = f"explicitly confirmed Hz field: {cfg['sample_rate_field']}"
    user = cfg.get("sample_rate_hz")
    sources = []
    if native is not None:
        sources.append(dict(value=native, source=origin))
    if user is not None:
        sources.append(dict(value=user, source=config_source))
    conflict = native is not None and user is not None and native != user
    resolution = cfg.get("sample_rate_resolution")
    if resolution and not conflict:
        raise InputRequired("unneeded_resolution", "Sampling-rate resolution supplied without a conflict.")
    if conflict and not resolution:
        return dict(value=None, state="conflict", sources=sources)
    if resolution:
        return dict(value=user if resolution["use"] == "user" else native,
                    state="confirmed", sources=sources, resolution=resolution)
    value = native if native is not None else user
    return dict(value=value, state="confirmed" if value is not None else "missing", sources=sources)


def build_dataset(source, cfg, fs, config_source):
    start, stop = cfg.get("start_sample", 0), cfg.get("stop_sample", source.n)
    if not 0 <= start < stop <= source.n:
        raise InputRequired("invalid_slice", f"Requested sample range must be within [0,{source.n}), nonempty.")
    channels = cfg.get("channels", list(range(source.c)))
    if channels[-1] >= source.c:
        raise InputRequired("invalid_channels", f"Channel index out of range; source has {source.c} channels.")
    ids = cfg.get("channel_ids")
    if ids is not None and len(ids) != source.c:
        raise InputRequired("channel_count_mismatch", "channel_ids must match the entire original channel axis.")
    geometry = cfg.get("array_geometry_m")
    if geometry is not None and len(geometry) != source.c:
        raise InputRequired("geometry_count_mismatch", "Geometry row count must match the original channel axis.")
    mapping = dict(state="confirmed" if ids is not None else "missing",
                   source=config_source if ids is not None else None)
    geo = dict(state="missing", reason="Array geometry not supplied.")
    if geometry is not None:
        g = np.asarray(geometry)
        duplicate = len(g)-len(np.unique(g, axis=0))
        geo = dict(state="confirmed", source=config_source, coordinates_m=geometry,
                   duplicate_coordinate_count=duplicate,
                   limitation="Coordinate consistency only; synchronization/calibration not verified.")
    return dict(field=source.selected["field"], original_shape=source.shape,
                original_dtype=source.selected["dtype"], original_sample_axis=source.axis,
                sample_axis_source=(source.info["format"].upper()+" format" if source.info["format"] in ("wav", "sio") else config_source),
                standard_axes=["samples", "channels"], view_shape=[stop-start, len(channels)],
                sample_range=[start, stop], channel_indices=channels,
                channel_ids=[ids[i] if ids else f"index:{i}" for i in channels],
                channel_identity=mapping, sample_rate_hz=fs, array_geometry=geo,
                units=dict(value=cfg.get("units"), state="confirmed" if "units" in cfg else "missing",
                           sources=[config_source] if "units" in cfg else []),
                duration_s=(stop-start)/fs["value"] if fs["value"] is not None else None,
                duration_basis="selected sample count / confirmed fs; not evidence of acquisition continuity",
                transformations=(["decode SIO channel records; exclude header-declared padding"] if source.info["format"] == "sio" else []) + ["slice using original indices", "preserve original channel order",
                    "transpose confirmed sample axis" if source.axis == 1 else "sample axis already first",
                    "add singleton channel axis" if len(source.shape) == 1 else "retain channel axis"],
                source_values_modified=False)


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_outputs(out, result):
    (out/"result.json").write_text(json.dumps(clean(result), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if "quality" in result:
        rows = []
        for row in result["quality"]["channels"]:
            flat = {k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items() if not isinstance(v, dict)}
            for key in ("longest_constant_run", "longest_zero_run"):
                flat.update({key+"_"+k: v for k, v in row[key].items()})
            rows.append(flat)
        with (out/"channel_quality.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    with (out/"feature_status.csv").open("w", encoding="utf-8-sig", newline="") as f:
        names = ["id", "stage", "title", "implementation", "status", "reason", "required_input",
                 "evidence", "coverage", "requested_pair_count", "completed_pair_count", "completed_pairs"]
        writer = csv.DictWriter(f, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in result["checks"]:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
    _write_report(out, result)
    _write_summary(out, result)


def _write_summary(out, result):
    """A short delivery view over existing evidence; never read or analyze the source again."""
    def number(value):
        return "—" if value is None else f"{value:.6g}"

    def interval(value):
        return f"[{value[0]}, {value[1]})"

    def channels(values):
        if len(values) > 2 and values == list(range(values[0], values[-1]+1)):
            return f"{values[0]}–{values[-1]}（{len(values)} 路）"
        shown = "、".join(str(v) for v in values[:8]) or "无"
        return shown + (f"等 {len(values)} 路" if len(values) > 8 else "")

    valid = result.get("results_valid") is not False
    d = result.get("dataset") if valid else None
    q = result.get("quality") if valid else None
    a = result.get("analysis") if valid else None
    status = result["status"]
    if not valid:
        conclusion = "源文件在执行期间变化或不可访问，本次证据失效，需要重新运行。"
    elif status == "failed":
        conclusion = "本次执行失败；不能据此判断数据质量，已产生的明细仅供排查。"
    elif status == "needs_input":
        conclusion = "需要补充信息后才能完成本次请求；当前仅交付已确认的文件信息。"
    elif result["request"]["operation"] == "probe":
        conclusion = "文件结构探查已完成；尚未执行样本质量检查或频谱分析。"
    elif q:
        conclusion = "样本检查已完成；以下结论只适用于实际检查和分析范围。"
        if status == "partial":
            conclusion += "频谱分析存在未完成或跳过部分。"
    else:
        conclusion = "数据读取已完成；本次未执行样本质量检查或频谱分析。"
    lines = ["# 水声数据分析摘要", "", conclusion, "", "## 数据与覆盖", "",
             f"- 文件：`{Path(result.get('source', {}).get('path', '不可访问')).name}`。"]
    if d:
        shape, axis = d["original_shape"], d["original_sample_axis"]
        source_channels = shape[1-axis] if len(shape) == 2 else 1
        lines += [f"- 源数据：每通道 {shape[axis]:,} 个样本，{source_channels} 路；请求样本 {interval(d['sample_range'])}，通道 {channels(d['channel_indices'])}。",
                  f"- 采样率：{number(d['sample_rate_hz']['value'])} Hz；片段时长：{number(d['duration_s'])} 秒。"]
    elif valid and result.get("probe"):
        fields = result["probe"].get("fields", [])
        shown = "；".join(f"`{item['field']}`：{item.get('shape', [])}" for item in fields[:4])
        if shown:
            lines.append("- 已发现字段及形状：" + shown + (f"；另有 {len(fields)-4} 个字段见明细。" if len(fields) > 4 else "。"))
        lines.append("- 尚未建立样本与通道读取范围；字段或样本轴须依据格式或明确配置确认。")
    if q:
        rows = q["channels"]
        cov = q["coverage"]
        nan = sum(row["nan_count"] for row in rows)
        inf = sum(row["positive_inf_count"]+row["negative_inf_count"] for row in rows)
        affected = [row["channel_index"] for row in rows if row["finite_count"] != row["sample_count"]]
        lines += ["", "## 数值质量", "",
                  f"- 实际检查：样本 {interval(cov['sample_range'])}，通道 {channels(cov['channel_indices'])}。",
                  f"- 非有限样本：NaN {nan:,}，Inf {inf:,}" + (f"；涉及通道 {channels(affected)}。" if affected else "；本次检查范围未见非有限样本。")]
        for key, label in (("mean", "通道均值"), ("std_population", "通道标准差")):
            values = [row[key] for row in rows if row.get(key) is not None]
            if values:
                lines.append(f"- {label}范围：{number(min(values))} 至 {number(max(values))}（原始数值单位；统计仅使用有限样本）。")
    if a:
        cov, settings = a["coverage"], a["settings"]
        completed = [row for row in a["channels"] if row["status"] == "completed"]
        skipped = [row["channel_index"] for row in a["channels"] if row["status"] != "completed"]
        lines += ["", "## 基础频谱", "",
                  f"- 实际读取样本 {interval(cov['sample_range'])}，通道 {channels(cov['channel_indices'])}；完整谱窗口覆盖 {interval(cov['spectrum_sample_range'])}，有 {cov['unused_tail_samples']} 个已读取样本未进入完整谱窗口。",
                  f"- Welch 窗长 {settings['nperseg']}，重叠 {settings['noverlap']}；频率网格间距 {number(settings['frequency_grid_spacing_hz'])} Hz。"]
        if completed:
            lines += ["", "| 原始通道 | 最强频点（Hz） |", "|---|---:|"]
            lines += [f"| {row['channel_index']} | {number(row['strongest_bin_hz'])} |" for row in completed[:6]]
            if len(completed) > 6:
                lines.append(f"其余 {len(completed)-6} 路频点见完整结果。")
            lines.append("")
        if skipped:
            lines.append(f"- 未获得频谱的通道：{channels(skipped)}；具体原因见完整结果，未插值或拼接异常样本。")
        psd = next((item for item in result["checks"] if item["id"] == "analysis.psd"), {})
        if psd.get("coverage", {}).get("complete_source_range") is not True:
            lines.append("- 频谱未覆盖整个源文件全部有效样本与通道；局部结果不能推广到未分析部分。")
    lines += ["", "## 限制与必要补充", ""]
    issues = {item["code"] for item in result["issues"]}
    if "field_required" in issues:
        lines.append("- 请确认要处理的字段；当前未自动选择候选数组。")
    if "sample_axis_required" in issues:
        lines.append("- 请确认哪一轴是样本轴；当前未按数组长短猜测。")
    if any(code.startswith("sample_rate_") for code in issues):
        lines.append("- 采样率缺失或冲突；需确认数值及来源，依赖秒/Hz 的分析尚不能完成。")
    if d and d["units"]["state"] != "confirmed":
        lines.append("- 原始数值单位未确认；不能换算为校准声压级。")
    if status in ("failed", "needs_input", "partial"):
        lines.append("- 未完成部分的原因和所需信息见[技术明细](report.md)，请先解决限制再继续相关步骤。")
    lines.append("- 数值描述及最强频点不构成目标检测、阵列定位或工程验收结论；同步、标定与真实采集连续性尚未验证。")
    lines += ["", "## 产物", "",
              "[技术明细](report.md) · [完整结果与参数](result.json) · [能力与覆盖清单](feature_status.csv)"]
    if q:
        lines.append("[逐通道数值与异常区间](channel_quality.csv)")
    if a:
        artifacts = a["artifacts"]
        displayed = [name for name in ("psd.png", "waveform.png", "analysis_products.npz") if name in artifacts]
        displayed += [name for name in artifacts if name.startswith("spectrogram_")][:1]
        if displayed:
            lines.append(" · ".join(f"[{name}]({name})" for name in displayed))
    (out/"summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def _write_report(out, result):
    states = dict(completed="已完成", partial="部分完成", needs_input="等待补充信息",
                  failed="执行失败", blocked="受阻", not_run="未执行",
                  confirmed="已确认", missing="缺失", conflict="存在冲突")
    fmt = lambda v: "无法计算" if v is None else f"{v:.6g}"
    lines = ["# 水声数据检查结果", "",
             f"本次基础流程执行状态：{states.get(result['status'], result['status'])}。不代表六项能力全部完成，也不代表工程验收合格。", "",
             f"源文件：{result.get('source', {}).get('path', '不可访问')}", ""]
    if result.get("results_valid") is False:
        lines += ["**源文件在运行中变化或消失，本次结果无效，需要重新运行。**", ""]
    lines += report_coverage(result)
    if "dataset" in result:
        d = result["dataset"]
        start, stop = d["sample_range"]
        rate = d["sample_rate_hz"]
        lines += ["", "## 数据概况", "",
                  f"- 原始形状：{d['original_shape']}；数据类型：{d['original_dtype']}。",
                  f"- 标准视图：{d['view_shape'][0]} 个样本 × {d['view_shape'][1]} 路通道。",
                  "- 覆盖说明：完成状态只对应本次请求；请求片段不等于整个源文件。",
                  f"- 原始样本区间：[{start}, {stop})；通道位置：{d['channel_indices']}。",
                  f"- 采样率：{fmt(rate['value'])} Hz；状态：{states.get(rate['state'], rate['state'])}。"]
        for item in rate["sources"]:
            lines.append(f"  - 来源：{item['source']}；值：{item['value']} Hz。")
        if "resolution" in rate:
            lines.append(f"  - 用户解决冲突的理由：{rate['resolution']['reason']}。")
        lines += [f"- 原始数值单位：{d['units']['value'] or '未确认'}；未执行单位换算。",
                  f"- 通道身份：{', '.join(d['channel_ids'])}；映射状态：{states[d['channel_identity']['state']]}。",
                  f"- 按采样率推导的片段时长：{fmt(d['duration_s'])} 秒；未据此验证采集连续性。"]
        geo = d["array_geometry"]
        lines.append("- 阵列几何：" + (
            f"已提供 {len(geo['coordinates_m'])} 组坐标，重复坐标数 {geo['duplicate_coordinate_count']}。同步与标定尚未验证。"
            if geo["state"] == "confirmed" else "未提供，阵列处理条件尚不能确认。"))
    lines += ["", "## 问题与待补充信息", ""]
    lines += [f"- {i['message']}（{i['code']}）" for i in result["issues"]] or ["- 没有阻断本次请求的问题；未验证项目见后文。"]
    if "quality" in result:
        lines += ["", "## 通道检查", "",
                  "检查覆盖整个请求范围。均值、标准差和 RMS 只基于有限样本，分母明确列出；原始数据未修改。", "",
                  "| 通道位置 | 样本数 | 有限样本 | NaN | Inf | 零值比例 | RMS |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for row in result["quality"]["channels"]:
            lines.append(f"| {row['channel_index']} | {row['sample_count']} | {row['finite_count']} | {row['nan_count']} | {row['positive_inf_count']+row['negative_inf_count']} | {row['zero_fraction']:.6g} | {fmt(row['rms'])} |")
        lines += ["", "[完整通道指标、异常区间和最长游程](channel_quality.csv)"]
    if "analysis" in result:
        ana = result["analysis"]
        cov, settings = ana["coverage"], ana["settings"]
        start, stop = cov["sample_range"]
        lines += ["", "## 基础分析", "",
                  f"实际读取样本 [{start}, {stop})，通道位置 {cov['channel_indices']}。",
                  f"谱估计覆盖样本 [{cov['spectrum_sample_range'][0]}, {cov['spectrum_sample_range'][1]})，末尾 {cov['unused_tail_samples']} 个样本未组成完整窗口。",
                  ("读取覆盖全部请求范围。" if cov["complete_requested_range"] else "本次仅分析请求范围的前段或部分通道，不能据此推断未分析部分。"),
                  f"Hann 窗长 {settings['nperseg']}，重叠 {settings['noverlap']} 个样本，每段减均值。频率网格间距 {fmt(settings['frequency_grid_spacing_hz'])} Hz。",
                  "频谱采用原始数值单位的单边 PSD；未做声学校准。最强频点只描述本次频谱，不代表已确认目标。", ""]
        for row in ana["channels"]:
            if row["status"] == "completed":
                lines.append(f"- 通道 {row['channel_index']}：最强频点 {fmt(row['strongest_bin_hz'])} Hz，全频 PSD 积分 {fmt(row['full_band_psd_integral'])} 原始数值单位平方。")
            else:
                lines.append(f"- 通道 {row['channel_index']}：跳过频谱，原因：{row['reason']}")
        psd_check = next(c for c in result["checks"] if c["id"] == "analysis.psd")
        actual = psd_check.get("coverage")
        if actual:
            lines += ["", ("谱分析覆盖整个源文件的全部通道。"
                            if actual["complete_source_range"] else
                            f"谱分析未覆盖整个源文件：源数据每通道 {actual['source_sample_count']} 个样本、{actual['source_channel_count']} 路；本次有效频谱通道 {actual['channel_indices']}。")]
        lines += ["", "### 通道相关性与相干谱", "",
                  "仅描述本次分析片段，不作为同步、串扰或标定故障结论。", "",
                  "| 原始通道对 | 相关系数 | 相干谱结果或限制 |", "|---|---:|---|"]
        for pair in ana["pairs"]:
            detail = pair.get("coherence_product", pair.get("coherence_reason", pair.get("reason", "未获得相干结果")))
            if pair.get("coherence_nonfinite_bins", 0):
                detail += f"；含 {pair['coherence_nonfinite_bins']} 个非有限频点，不能作为完整有效结果。"
            detail = detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {pair['channel_indices']} | {fmt(pair.get('correlation'))} | {detail} |")
        if not ana["pairs"]:
            lines.append("| — | — | 未得到通道对结果，原因及期望对数见子项清单。 |")
        lines += ["", "相干谱数组保存在下方 analysis_products.npz，键名见表。"]
        for name in ana["artifacts"]:
            lines += ["", f"![{name}]({name})" if name.endswith(".png") else f"[{name}]({name})"]
    lines += ["", "## 后续使用条件", "",
              "- 样本与通道统计：以本次完成状态、有限样本分母和异常区间为依据。",
              "- 频谱与时频分析：须确认采样率，并遵守本次实际覆盖和跳过通道的限制。",
              "- 校准声级：尚未验证标定链路。",
              "- 阵列定位：几何、同步和幅相标定需有独立依据。", "",
              "## 未验证项目", ""]
    lines += [f"- {v}" for v in result["not_checked"]]
    lines += ["", "[机器可读结果、完整参数和来源](result.json)", ""]
    (out/"report.md").write_text("\n".join(lines), encoding="utf-8")


def execute(path, output, raw_config=None, config_source="explicit Python API configuration", probe_only=False):
    out = Path(output).resolve()
    if out.exists():
        raise FileExistsError(f"Output directory already exists, refusing overwrite: {out}")
    out.mkdir(parents=True, exist_ok=False)
    result = dict(schema_version="0.2", status="failed", issues=[],
                  request=dict(operation="probe" if probe_only else "run"),
                  stages={s: dict(status="not_run", reason="Not requested or prerequisite not yet completed.") for s in STAGES},
                  not_checked=list(NOT_CHECKED), software=dict(python=platform.python_version(),
                    **{name: importlib.metadata.version(name) for name in ("numpy", "scipy", "h5py", "matplotlib")}))
    source = None
    active = "probe"
    try:
        result["source"] = fingerprint(path)
        info = probe(path)
        result["probe"] = info
        result["stages"]["probe"] = dict(status="completed")
        if probe_only:
            result["status"] = "completed"
        else:
            cfg = validate_config({} if raw_config is None else raw_config)
            result["config"] = dict(values=cfg, source=config_source)
            active = "reading"
            chosen = select_field(info, cfg)
            source = Source(path, info, chosen, cfg)
            result["selection"] = dict(field=chosen["field"], sample_axis=source.axis,
                                       shape=source.shape, basis="format or explicit configuration")
            fs = rate_metadata(path, info, cfg, config_source)
            active = "standardization"
            d = build_dataset(source, cfg, fs, config_source)
            result["dataset"] = d
            result["stages"]["standardization"] = dict(status="completed")
            if fs["state"] != "confirmed":
                result["issues"].append(dict(code="sample_rate_"+fs["state"],
                    message="采样率缺失或冲突；请确认采样率及来源，依赖秒/Hz 的步骤暂停。"))
            if d["units"]["state"] == "missing":
                result["issues"].append(dict(code="units_missing", message="单位未确认；仅保留原始数值，不能输出校准声级。"))
            if d["channel_identity"]["state"] == "missing":
                result["issues"].append(dict(code="channel_identity_missing", message="使用原始列位置标识通道；尚未确认实际传感器身份。"))
            active = "reading"
            if cfg["mode"] == "read":
                start, stop = d["sample_range"]
                block = source.block_size(cfg["block_samples"])
                for offset in range(start, stop, block):
                    source.read(offset, min(stop, offset+block), d["channel_indices"])
                result["stages"]["reading"] = dict(status="completed", coverage=d["sample_range"])
            else:
                active = "integrity"
                result["quality"] = check(source, cfg, d)
                result["stages"]["reading"] = dict(status="completed", coverage=d["sample_range"])
                result["stages"]["integrity"] = dict(status="completed", reason="Stored-array checks; acquisition gaps not verified.")
                result["stages"]["channel_quality"] = dict(status="completed", reason="Numeric descriptors and supplied geometry consistency only.")
                for row in result["quality"]["channels"]:
                    if row["finite_count"] != row["sample_count"]:
                        result["issues"].append(dict(code="nonfinite_samples", message=f"通道 {row['channel_index']} 含非有限值；见指标及分析跳过记录。"))
                if d["array_geometry"].get("duplicate_coordinate_count", 0):
                    result["issues"].append(dict(code="duplicate_coordinates", message="阵列坐标存在重复；需确认物理映射。"))
            result["status"] = "completed"
            if cfg["mode"] == "analyze":
                active = "analysis"
                from .analysis import analyze
                result["analysis"] = analyze(source, cfg, d, out)
                result["stages"]["analysis"] = dict(status=result["analysis"]["status"])
                if result["analysis"]["status"] != "completed":
                    result["status"] = "partial"
        # Snapshot metadata is checked after all success and error paths below.
    except InputRequired as e:
        result["status"] = "partial" if "quality" in result else "needs_input"
        result["issues"].append(dict(code=e.code, message=str(e)))
        result["stages"][active] = dict(status="blocked", reason=str(e))
    except Exception as e:
        result["status"] = "failed"
        result["issues"].append(dict(code=type(e).__name__, message=str(e)))
        result["stages"][active] = dict(status="failed", reason=str(e))
    finally:
        if source is not None:
            source.close()
    if "source" in result:
        try:
            unchanged = fingerprint(path) == result["source"]
        except OSError:
            unchanged = False
        result["source_consistency"] = "unchanged_size_and_mtime" if unchanged else "changed_or_unavailable"
        if not unchanged:
            result["status"] = "failed"
            result["results_valid"] = False
            result["issues"].append(dict(code="source_changed",
                message="源文件在运行中变化或消失；本次产物不能作为一致数据快照使用，请重新运行。"))
    attach_coverage(result)
    checks = {item["id"]: item for item in result["checks"]}
    result["readiness"] = dict(
        sample_checks=checks["integrity.nonfinite"]["status"],
        frequency_analysis=checks["analysis.psd"]["status"],
        calibrated_levels="not_verified: no calibration chain supplied",
        array_processing="not_verified: synchronization/calibration need independent evidence")
    write_outputs(out, result)
    return result


def exit_code(result):
    return 0 if result["status"] == "completed" else (1 if result["status"] == "failed" else 2)
