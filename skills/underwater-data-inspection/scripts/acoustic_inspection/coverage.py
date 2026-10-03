"""Evidence-backed feature coverage, separate from command execution success."""
from collections import Counter

CATALOG = (
    ("probe.container", "probe", "格式、字段与存储结构", True),
    ("reading.selection", "reading", "字段与样本轴确认", True),
    ("reading.samples", "reading", "请求范围只读读取", True),
    ("standardization.view", "standardization", "统一视图与原始索引映射", True),
    ("standardization.sample_rate", "standardization", "采样率及来源确认", True),
    ("standardization.units", "standardization", "原始数值单位确认", True),
    ("integrity.nonfinite", "integrity", "非有限值统计与区间", True),
    ("integrity.runs", "integrity", "零值与恒值游程", True),
    ("integrity.source_stability", "integrity", "运行前后大小及修改时间核对", True),
    ("integrity.acquisition_continuity", "integrity", "真实丢帧、重复采集帧与时钟漂移", False),
    ("channel_quality.statistics", "channel_quality", "逐通道数值统计", True),
    ("channel_quality.identity", "channel_quality", "通道身份映射确认", True),
    ("channel_quality.geometry", "channel_quality", "基础坐标一致性", True),
    ("channel_quality.correlation", "channel_quality", "片段通道相关性", True),
    ("channel_quality.coherence", "channel_quality", "片段通道相干谱", True),
    ("channel_quality.clipping", "channel_quality", "参考满量程的削波判定", False),
    ("channel_quality.synchronization", "channel_quality", "参考驱动的通道同步判定", False),
    ("channel_quality.calibration", "channel_quality", "极性、串扰与幅相标定故障判定", False),
    ("analysis.waveform", "analysis", "原始波形预览", True),
    ("analysis.psd", "analysis", "Welch PSD 与功率描述", True),
    ("analysis.spectrogram", "analysis", "时频功率谱", True),
)
LABELS = dict(completed="已完成", partial="部分完成", blocked="受阻",
              not_run="本次未运行", not_implemented="尚未实现",
              failed="执行失败", invalidated="结果失效", not_applicable="不适用")
STAGE_LABELS = dict(probe="文件探查", reading="数据读取", standardization="标准数据模型",
                    integrity="完整性检查", channel_quality="通道与阵列检查", analysis="初步信号分析")
UNIMPLEMENTED = {
    "integrity.acquisition_continuity": "当前没有时间戳/帧计数器检查接口和漂移判据；需开发并提供采集时间参考，不能用均匀采样轴替代。",
    "channel_quality.clipping": "当前只输出极值和恒值段，未实现参考 ADC 满量程的削波判定；补充标定后仍需开发对应检查。",
    "channel_quality.synchronization": "当前未实现独立参考驱动的同步检查；相关性或相干性不能替代同步证据。",
    "channel_quality.calibration": "当前未实现极性、串扰及幅相标定故障判定；需参考实验与相应检查实现。"
}


def scope(dataset, sample_range=None, channels=None):
    if not dataset:
        return None
    original = dataset["original_shape"]
    axis = dataset["original_sample_axis"]
    n = original[axis]
    c = original[1-axis] if len(original) == 2 else 1
    interval = sample_range if sample_range is not None else dataset["sample_range"]
    ch = channels if channels is not None else dataset["channel_indices"]
    return dict(sample_range=interval, channel_indices=ch,
                requested_sample_range=dataset["sample_range"],
                requested_channel_indices=dataset["channel_indices"],
                source_sample_count=n, source_channel_count=c,
                complete_requested_range=(interval == dataset["sample_range"] and ch == dataset["channel_indices"]),
                complete_source_range=(interval == [0, n] and ch == list(range(c))))


def summarize(items):
    states = [item["status"] for item in items]
    if any(s in ("failed", "invalidated") for s in states):
        return "failed"
    supported = [i["status"] for i in items if i["implementation"] == "implemented"]
    if supported and all(s == "not_run" for s in supported):
        return "not_run"
    if supported and all(s in ("blocked", "not_run") for s in supported) and "blocked" in supported:
        return "blocked"
    if all(s in ("completed", "not_applicable") for s in states):
        return "completed" if "completed" in states else "not_applicable"
    return "partial"


def attach_coverage(result):
    d, q, a = (result.get(k) for k in ("dataset", "quality", "analysis"))
    probe_only = result.get("request", {}).get("operation") == "probe"
    mode = result.get("config", {}).get("values", {}).get("mode", "check")
    wants_quality = not probe_only and mode != "read"
    wants_analysis = not probe_only and mode == "analyze"
    stages = result["stages"]
    rows = {}

    def pending(stage, requested=True):
        if not requested:
            return dict(status="not_run", reason="本次模式未请求该子项。")
        own = stages[stage]
        errors = [s for s in stages.values() if s["status"] in ("blocked", "failed")]
        issue = own if own["status"] in ("blocked", "failed") else (errors[0] if errors else None)
        if issue:
            state = "failed" if own["status"] == "failed" else "blocked"
            return dict(status=state, reason=issue.get("reason", "前置步骤未完成。"),
                        required_input="先解决所列前置步骤或配置问题；不要猜测后继续。")
        return dict(status="not_run", reason="未获得本次执行证据，不能宣称完成。")

    def put(key, status=None, reason=None, evidence=None, coverage=None, required_input=None, **extra):
        stage = next(row[1] for row in CATALOG if row[0] == key)
        value = dict(status=status, reason=reason) if status else pending(stage, not probe_only)
        if evidence:
            value["evidence"] = evidence
        if coverage is not None:
            value["coverage"] = coverage
        if required_input:
            value["required_input"] = required_input
        value.update(extra)
        rows[key] = value

    put("probe.container", **(dict(status="completed", reason="已探查当前文件；格式特有限制见 probe。",
                                  evidence=["probe"]) if result.get("probe") else pending("probe")))
    put("reading.selection", **(dict(status="completed", reason="字段与轴按格式或明确配置确认，不按数组长短猜测。",
                                     evidence=["selection"]) if result.get("selection") else pending("reading", not probe_only)))
    put("reading.samples", **(dict(status="completed", reason="已只读遍历请求的样本和通道范围。",
                                   evidence=["stages.reading", "dataset"], coverage=scope(d))
                               if stages["reading"]["status"] == "completed" else pending("reading", not probe_only)))
    put("standardization.view", **(dict(status="completed", reason="标准视图保留原始数值与索引；转换记录见 dataset。",
                                        evidence=["dataset"], coverage=scope(d)) if d else pending("standardization", not probe_only)))
    for key, field, question in (
        ("standardization.sample_rate", "sample_rate_hz", "请确认采样率（Hz）及来源；有冲突时明确选择与理由。"),
        ("standardization.units", "units", "请提供原始数值的单位及依据；不明确时继续按原始数值分析，不换算。"),
        ("channel_quality.identity", "channel_identity", "请提供原始列位置与传感器身份的完整对应关系。"),
        ("channel_quality.geometry", "array_geometry", "请提供与原始通道对应的完整三维米制坐标及来源；仅有深度不补造横向坐标。")):
        if not d:
            put(key, **pending("standardization", not probe_only))
        elif d[field]["state"] == "confirmed":
            detail = "已记录确认值与来源；不代表独立测量验证。"
            if field == "array_geometry":
                detail = f"已核对坐标数、有限性和重复坐标；重复坐标数 {d[field]['duplicate_coordinate_count']}。不证明同步或标定。"
            put(key, "completed", detail, [f"dataset.{field}"])
        else:
            put(key, "blocked", f"信息状态为 {d[field]['state']}，未以猜测补齐。",
                [f"dataset.{field}"], required_input=question)
    for key in ("integrity.nonfinite", "integrity.runs", "channel_quality.statistics"):
        if q:
            put(key, "completed", "已按逐通道有限样本分母和原始位置输出统计；执行完成不代表没有异常。",
                ["quality.channels", "quality.coverage"], scope(d))
        else:
            stage = next(row[1] for row in CATALOG if row[0] == key)
            put(key, **pending(stage, wants_quality))
    consistency = result.get("source_consistency")
    if consistency:
        unchanged = consistency == "unchanged_size_and_mtime"
        put("integrity.source_stability", "completed" if unchanged else "failed",
            "只核对大小及修改时间，不是内容哈希或并发快照。" if unchanged else "源文件在运行中改变或不可用，结果失效。",
            ["source", "source_consistency"])
    else:
        put("integrity.source_stability", **pending("probe"))

    for key in ("analysis.waveform", "analysis.psd", "analysis.spectrogram"):
        if not a:
            put(key, **pending("analysis", wants_analysis))
            continue
        cov = a["coverage"]
        is_wave = key.endswith("waveform")
        ch = cov["channel_indices"] if is_wave else [row["channel_index"] for row in a["channels"] if row["status"] == "completed"]
        interval = cov["sample_range"] if is_wave else cov["spectrum_sample_range"]
        covered = scope(d, interval, ch)
        state = ("completed" if covered["complete_requested_range"] else "partial") if ch else "blocked"
        reason = ("原始波形仅抽点预览，不保峰值；不据此排除尖峰。" if is_wave else
                  "仅对列出的有效通道及完整窗口完成谱分析；NaN/Inf 通道未插值或拼接。")
        put(key, state, reason, ["analysis.coverage", "analysis.settings", "analysis.channels", "analysis.artifacts"],
            covered, required_input="分析通道含非有限值；请明确后续处理策略，原始检查结果保留。" if not ch else None)

    for key, product in (("channel_quality.correlation", "correlation"), ("channel_quality.coherence", "coherence_product")):
        if not a:
            put(key, **pending("analysis", wants_analysis))
            continue
        ch = a["coverage"]["channel_indices"]
        expected = len(ch)*(len(ch)-1)//2
        if expected == 0:
            put(key, "not_applicable", "本次只选择一个通道，不能计算通道对指标。",
                ["analysis.coverage"], scope(d, a["coverage"]["sample_range"], ch),
                requested_pair_count=0, completed_pair_count=0)
            continue
        pairs = a["pairs"]
        successful = [p for p in pairs if product in p and
                      (product != "coherence_product" or p.get("coherence_nonfinite_bins", 0) == 0)]
        interval = a["coverage"]["sample_range"] if product == "correlation" else a["coverage"]["spectrum_sample_range"]
        cov = scope(d, interval, ch)
        full = len(successful) == expected and cov["complete_requested_range"]
        state = "completed" if full else ("partial" if successful else "blocked")
        reason = f"本次所选 {len(ch)} 路通道应有 {expected} 对，得到 {len(successful)} 对完整有效结果；未计算的通道对不能视为通过。"
        put(key, state, reason, ["analysis.pairs", "analysis.coverage", "analysis.settings"], cov,
            required_input=("需共同有限的非恒值通道；相干谱还需至少两个完整分段，必要时明确调整分析范围。"
                            if len(successful) != expected else None),
            requested_pair_count=expected, completed_pair_count=len(successful),
            completed_pairs=[p["channel_indices"] for p in successful])

    checks = []
    for key, stage, title, implemented in CATALOG:
        row = dict(id=key, stage=stage, title=title,
                   implementation="implemented" if implemented else "not_implemented")
        row.update(rows[key] if implemented else dict(status="not_implemented", reason=UNIMPLEMENTED[key]))
        if result.get("results_valid") is False and row["status"] in ("completed", "partial"):
            row.update(status="invalidated", reason="源文件变更使本次证据失效；保留原始产物仅供诊断。")
        checks.append(row)
    result["checks"] = checks
    result["coverage_summary"] = dict(
        counts=dict(Counter(row["status"] for row in checks)),
        all_listed_checks_complete=all(row["status"] in ("completed", "not_applicable") for row in checks),
        meaning="子项覆盖不是工程质量验收；运行完成也不代表全部能力实现或整个源文件都已分析。")
    for name in stages:
        members = [r for r in checks if r["stage"] == name]
        stages[name]["assessment_status"] = summarize(members)
        stages[name]["check_counts"] = dict(Counter(row["status"] for row in members))


def report_coverage(result):
    lines = ["## 六项工作的子项覆盖", "",
             "下表区分本次执行与能力覆盖。“已完成”只表示对应子项在所列范围内执行完毕，不表示数据合格。",
             "受阻：已有实现但缺信息、数据条件或前置步骤；尚未实现：当前没有对应检查能力，补参数也不会自动启用。", "",
             ]
    d, a = result.get("dataset"), result.get("analysis")
    if d:
        cov = scope(d)
        lines += [f"本次请求：样本 {cov['sample_range']}、原始通道 {cov['channel_indices']}；源文件每通道 {cov['source_sample_count']} 个样本、{cov['source_channel_count']} 路通道。",
                  "本报告索引均为零基，样本区间为半开区间。", ""]
    if a:
        cov = a["coverage"]
        lines += [f"实际分析：读取样本 {cov['sample_range']}、通道 {cov['channel_indices']}；完整谱窗口覆盖 {cov['spectrum_sample_range']}。局部完成不能推广到未分析部分。", ""]
    lines += ["| 工作 | 子项覆盖状态 | 各状态数量 |", "|---|---|---|"]
    for name, stage in result["stages"].items():
        counts = "；".join(f"{LABELS[k]} {v}" for k, v in stage["check_counts"].items())
        lines.append(f"| {STAGE_LABELS[name]} | {LABELS[stage['assessment_status']]} | {counts} |")
    for name in result["stages"]:
        lines += ["", f"### {STAGE_LABELS[name]}", "",
                  "| 子项 | 状态 | 依据、限制或需补充内容 |", "|---|---|---|"]
        for row in result["checks"]:
            if row["stage"] != name:
                continue
            reason = row["reason"] + (" " + row["required_input"] if row.get("required_input") else "")
            reason = reason.replace("|", "\\|").replace("\n", " ")
            evidence = " 证据：" + "、".join(row["evidence"]) if row.get("evidence") else ""
            lines.append(f"| {row['title']} | {LABELS[row['status']]} | {reason}{evidence} |")
    lines += ["", "[完整子项状态、证据路径及覆盖范围](feature_status.csv)", ""]
    return lines
