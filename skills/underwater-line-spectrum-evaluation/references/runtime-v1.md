# 线谱评价执行器 V1

状态：运行时版本 1.0.0。它只读取已经完成并持久保存的检测结果，执行跨文档预检和获准的评价，不重新估计频谱、不重跑 CFAR、不改门限，也不回写上游包。

## 输入门禁

执行入口是 `EvaluationRequest` 0.1.0。请求必须为 `specified`，所有待计算指标必须已有记录的确认，保存位置必须明确。每个目标必须引用：

- 完整的 `DetectionResult` 及其 SHA-256；
- 该结果实际绑定的 `resolved-configuration.json`；
- 明确的 run、task、signal、task_kind、时频范围；
- 一项明确的真值状态：`provided`、`none` 或 `unknown`。

预检实际打开并核对引用文件，验证结果、配置、候选 product manifest、候选表和 ledger 的摘要及身份；核对候选与 ledger 的行号、时间支持、候选计数，以及候选频率与实际 fs/nfft 网格的一致性。目标范围只采用完全落入请求时间范围的已测试行，不静默拼接部分帧。

运行：

```bash
python3 -B scripts/evaluation_runtime.py request.json --preflight-only
python3 -B scripts/evaluation_runtime.py request.json --output-dir /explicit/new/output/directory
```

预检只读。执行目录必须与 `output_plan.save_destination` 完全一致且尚不存在；执行器拒绝覆盖。计算在同级临时目录完成，通过结果 Schema 校验后再原子发布。

## 无真值路径

V1 可计算：

- `candidate_count`
- `mean_candidates_per_frame`
- `candidate_frame_fraction`
- `mean_threshold_margin_db`
- `mean_background_contrast_db`

逐帧分母来自完整 ledger，包含成功但零候选的帧。门限余量使用已有 `power/threshold`，背景对比使用已有 `power/background`，要求正的有限线性量；不从谱图估读，也不把背景对比称为物理 SNR。

没有完整真值或可信背景时，请求 TP、FP、FN、recall、precision、F1 或实际误报指标会得到 `insufficient_evidence` 和空值，不填 0。

## 有真值路径

`TruthCoverage` 继续声明证据来源、区域和语义。实际峰值标签由它的 `labels_ref` 指向 `TruthLabels` 1.0.0；格式见 [TruthLabels Schema](../assets/schemas/TruthLabels.schema.json)。标签保留 target/run/task、region_id、频率，以及按匹配规则需要的原样本区间或时间点。

只读检查：

```bash
python3 -B scripts/validate_truth_labels.py truth-labels.json
```

该检查不认证标签真实性或完整性。跨文档预检才核对标签与请求、覆盖和检测任务的身份及摘要。

V1 一对一分配支持：

- `assignment_method=maximum_cardinality_minimum_frequency_error`
- `tie_break=candidate_id_then_truth_id`
- 明确的 `frequency_gate_hz`
- `time_rule=frame_identity`、`tolerance` 或 `not_applicable`
- `duplicate_policy=count_as_false` 或 `report_separately`

先最大化匹配数量，再最小化总绝对频率误差。完整标签区域可计算 recall、precision、F1、误报数和频率误差；`partial_positive` 只支持已匹配项的频率误差，不支持把未匹配候选判作总体误报。

## 可信背景路径

`verified_background` 区域有明确 H0、负类定义和证据时，可计算：

- 最终候选层：`false_count`、`mean_false_per_frame`、`false_per_hour`；
- 候选或单元事件层：`background_frame_false_fraction`、`background_segment_false_fraction`；
- 单元层：`cell_false_fraction`。

单元越门限数由已有 ledger 中最终候选组和被后筛选拒绝的越门限组恢复；分母使用 ledger 的 `tested_bins`。这只评价已保存的原判决，不重跑 CFAR。若历史 ledger 没有这些字段，指标证据不足，不从最终候选数倒推单元概率。

## 输出包

成功执行的核心包生成：

- `evaluation-result.json`：严格的 `EvaluationResult`；
- `resolved-evaluation-config.json`：跨文档预检和实际输入摘要；
- `package-manifest.json`：文件摘要清单；

只在 `artifact_requests` 明确选择计算和保存时生成：

- `metrics.csv`：标量指标表；
- `report.md`：简短证据边界报告；
- `matches.json`：匹配审计产物；若没有实际匹配运行，明确记为未生成。

输出保留原 candidate_id 和 truth_id。上游检测包只读，评价输出不删除候选、不改历史门限、不回写质量结论。

## V1 边界

- 不做频率轨迹跟踪、事件合并、谐波族归并、声源归属或目标识别。
- 不自动制造真值、背景区域、验收阈值或“最好算法”。匹配门宽与重复规则可按标签不确定度、检测栅格和 SKILL.md 自主策略解析，并在 resolved config 中记录。
- 不实现统计置信区间、相关帧有效样本量估计或跨海况外推。
- 不从只有图片的结果生成精确数值，不把理论或标定概率冒充独立实测性能。
- 单个聚合标量所用的多个证据区域必须共享同一频带与时间参考；不同频带应拆成独立目标/指标，不用一个包围框掩盖未标注缺口。
- 不自动判定工程验收。`EvaluationResult.acceptance` 在没有独立标准请求时保持 `not_requested`。
