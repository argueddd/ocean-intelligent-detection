---
name: underwater-line-spectrum-tracking-evaluation
description: "只读评价已有、完整的 TrackingResultPackage：轨迹覆盖/连续性/短轨结构、真值频率误差、碎片化、身份交换、同源基线比较和显式阈值验收。适用于“已有轨迹表现如何”；不创建或重新关联轨迹。需要把 DetectionTrackingHandoff 候选连成轨迹时使用 underwater-line-spectrum-tracking。"
---

# 线谱轨迹跟踪评价

本 Skill 回答“已有频率轨迹表现怎样、证据能支持什么结论”。跟踪模块负责创建 `track_id`；本模块只读消费已完成的 `TrackingResultPackage 1.0.0`，生成独立评价包。

## 当前能力

- 核验跟踪结果包、manifest、文件摘要、候选覆盖和轨迹内部一致性。
- 无真值时描述轨迹数量、长短分布、单点/短轨比例、行跨度占用率、终止原因、间断和频率步进；这些是可观测结构，不是真实准确率。
- 有局部或完整轨迹真值时，按显式频率门宽做逐行一对一匹配，计算点级召回/精度、频率误差、轨迹级召回/精度、碎片数和身份交换。
- 对同一检测候选来源的两组轨迹结果做可比性核对和原始指标差值；不自动宣布哪组更好。
- 仅按用户提供的验收指标、运算符和阈值输出 pass/fail/insufficient_evidence。
- 生成 `evaluation-result.json`、`metrics.csv`、`report.md`、可选审计匹配和可选图形，拒绝覆盖旧目录。

## 证据等级

先完整阅读 [证据与指标](references/evidence-and-metrics.md)，再选择模式：

- `descriptive`：没有轨迹真值，只评价结构完整性和描述统计。
- `truth`：一个结果包加局部或完整轨迹真值。
- `comparison`：同源 primary/baseline 结果包，无真值时只比较描述指标。
- `truth_comparison`：同源 primary/baseline 使用同一份轨迹真值评价。

局部正标注不能把未匹配轨迹判作假轨迹；只有 `negative_labels_complete=true` 的覆盖区域才支持 point/track precision 和 false-track 结论。`confirmed` 只是上游工程状态，不能当真值。

## 自主评价策略

用户要求评价轨迹即授权本 Skill 自动选择证据允许的模式和指标：无真值用 `descriptive`，有真值用 `truth`，同源 baseline 存在时分别使用 `comparison` 或 `truth_comparison`。缺真值、完整负类、baseline 或验收阈值只限制对应指标，不阻断其余评价。

- 描述评价基线使用 `short_track_max_detections=2`、`continuity_basis=all_rows`；若上游存在 skipped 行且问题关注实际受检连续性，则改用与跟踪一致的 `tested_rows_only` 并说明。
- 真值匹配门宽优先来自标签不确定度；否则使用不小于一个检测频率栅格的可逆分析设置。未知负类完整性保持 unknown/false，不为计算 precision 而猜测。
- 用户未指定图表和审计表时保存核心指标，只有解释需要时保存匹配表和图；`plot_dpi=150`。输出使用新的唯一目录。
- 没有阈值时 `acceptance_checks=[]`，评价照常执行；不向用户索要临时阈值。review 通过后按原请求直接 execute。
- 多个 primary/baseline 同等合理或真值覆盖语义冲突时，先完成可独立的描述评价，再把全部阻断项、推荐选择和影响合并为一次“需要你确认”清单。

## 工作流

1. 解析 primary 结果包和评价问题，按证据自动选择模式、短轨定义、占用率分母及可用 baseline/真值；唯一对象直接使用。
2. 有真值时完整阅读 [真值与匹配](references/truth-and-matching.md)；有比较或验收时完整阅读 [比较与验收](references/comparison-and-acceptance.md)。门宽可按标签不确定度或频率栅格推导；覆盖、负类完整性和验收阈值属于证据事实，不得猜测。
3. 使用 `assets/templates/EvaluationRequest.draft.json` 整理请求，自主补齐可逆评价设置；只有真实证据冲突进入未决项。`document_status=specified` 且 `unresolved_items=[]` 后可以执行。
4. 先执行只读 review：

   ```text
   python3 scripts/evaluation_runtime.py review /absolute/EvaluationRequest.json
   ```

5. 原始请求已要求评价且 review 通过后直接执行：

   ```text
   python3 scripts/evaluation_runtime.py execute /absolute/EvaluationRequest.json \
     --review-sha256 <review_sha256>
   ```

   execute 会重新 review；请求、结果包、baseline 或真值变化都会使旧摘要失效。
6. 按 [运行与交付](references/runtime-v1.md) 和 [报告与下游](references/report-and-handoff.md) 汇报证据等级、指标分母、不可算项、验收状态和输出位置。

## 必须保留的边界

- 原检测包和轨迹包只读；不删除轨迹、不合并碎片、不改 `track_id`，不重新关联候选。
- 不试不同门限寻找更好结果，不自动修改频率门限、漏检容忍、预测模式或确认点数。
- 描述性短轨比例、间断比例和频率抖动只能提示需检查的现象；没有真值时不称为误轨、碎片化率或身份交换率。
- 轨迹真值只表示频率轨迹标签，不自动包含声源身份或现实目标身份。
- 不执行谐波族归并、多特征融合、声源/目标归属、目标身份识别或业务决策。
- 参数建议只能作为新的独立实验建议；评价结果不授权跟踪模块自动重跑。

## 资源

- [证据与指标](references/evidence-and-metrics.md)
- [真值与匹配](references/truth-and-matching.md)
- [比较与验收](references/comparison-and-acceptance.md)
- [运行与交付](references/runtime-v1.md)
- [报告与下游](references/report-and-handoff.md)
- `assets/schemas/`：请求、真值、上游结果快照和评价结果契约。
- `scripts/evaluation_runtime.py`：只读 review 与独立评价包执行器。
- `scripts/validate_contract.py`：请求、真值和结果的结构检查。

除非用户明确要求，不自动评价现有数据、不打包、不发给别人、不继续目标归属或身份识别。
