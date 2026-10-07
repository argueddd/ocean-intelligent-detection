---
name: underwater-line-spectrum-tracking
description: "只接收完整 DetectionTrackingHandoff，把已有逐窗线谱候选跨时间关联成新的可追溯频率轨迹和候选—轨迹映射。适用于“把候选连成轨迹/执行跟踪”；不从波形或谱图检测候选，也不评价已有轨迹效果。评价 TrackingResultPackage 时使用 underwater-line-spectrum-tracking-evaluation。"
---

# 线谱轨迹跟踪

本 Skill 回答“不同时间窗中的候选是否属于同一条频率轨迹”。输入必须是一个已完成逐窗检测任务生成的 `DetectionTrackingHandoff 1.0.0`；输出创建新的 `track_id`，同时保留每个原始 `run_id + task_id + candidate_id`。

## 能力与边界

- 核验交接文件及其绑定的候选表、帧账本和来源摘要，绝不回写检测包。
- 按检测行的原生时间顺序，以明确门限进行一对一候选关联；支持上一频率或常速预测。
- 显式处理零候选行、跳过行、短时漏检、轨迹初始化、确认和终止。
- 生成完整轨迹、候选—轨迹映射、逐行关联账本和可选频率—时间图。
- `confirmation_status` 只是满足最少检测点数的工程状态，不是目标概率、真实性或评价结论。
- 不重新计算 PSD/CFAR，不补候选，不做无界寻优；允许按本 Skill 自主策略设置跟踪参数并做有界敏感性检查。
- 不做谐波族归并、DEMON、多特征融合、声源/目标归属、目标身份识别、真实性判断或性能验收。

## 自主参数策略

用户要求把合规逐窗候选形成轨迹，即授权本 Skill 根据交接中的时间栅格、频率栅格、跳过行和功率可比性自主填写 TrackingRequest，并在 review 通过后直接 execute；无需逐个确认门限、gap、预测模式、绘图或输出目录。

按以下顺序选值：用户给定/绑定配置 → 可由数据确定性推导 → 场景特征 → 基线预设。没有外部运动模型和真值时使用可复现基线：

- `prediction_mode=last_frequency`；只有连续点已显示稳定单向漂移且时间步长有效时才选 `constant_velocity`。
- `frequency_gate_hz` 至少覆盖一个检测频率栅格；结合相邻行候选的稳健局部步进放宽，但不能仅为得到更长轨迹无限放宽。
- `frequency_rate_gate_hz_per_s=null`，除非请求或来源给出可信变化率边界；有边界时由该边界与时间步长推导。
- `power_change_gate_db=null`、`power_cost_weight=0`；只有全部候选 power 定义一致、正有限且任务需要功率消歧时才启用。默认 `frequency_cost_weight=1`。
- `max_missed_rows=1`，`gap_count_basis=tested_rows_only`，`min_confirmed_detections=3`。若时间栅格或任务明确要求其他容忍度，再按覆盖推导调整。
- 默认保存轨迹图，`plot_dpi=150`；绘图库不可用时关闭图形，不阻断核心 JSON。

这些值是可逆工程基线，不是物理真值。允许做少量有界敏感性检查来显示结论对门限的依赖；无真值时不得以轨迹更长、更少或更平滑宣布某组参数更准确。确有多个输入交接或物理运动约束存在冲突时，先 review 可用证据，再把全部当前阻断项和推荐方案合并成一次“需要你确认”清单。

## 工作流

1. 完整读取 [输入输出契约](references/input-output-contract.md)，确认交接版本、证据和候选粒度满足要求。
2. 对任何新任务完整读取 [跟踪方法](references/tracking-method.md)。按上方自主策略确定频率门限、变化率门限、功率门限、漏检容忍、跳过行策略、预测模式和确认点数，并记录依据；不得从数据试到“看起来最好”后声称为真实最优。
3. 从 `assets/templates/TrackingRequest.draft.json` 建立请求，自主解决处理设置；只有真实输入歧义或冲突进入 `unresolved_items`。`document_status=specified`、`unresolved_items=[]` 后可以执行。
4. 先运行只读 review：

   ```text
   python3 scripts/tracking_runtime.py review /absolute/TrackingRequest.json
   ```

   review 会重新读取全部绑定证据并输出 `review_sha256`，但不会创建轨迹或目录。
5. 原始请求已要求形成轨迹且 review 通过后，直接运行：

   ```text
   python3 scripts/tracking_runtime.py execute /absolute/TrackingRequest.json \
     --review-sha256 <review_sha256>
   ```

   execute 必须重新 review；请求、交接或证据变化都会使旧摘要失效。输出目录必须不存在，运行不会覆盖旧结果。
6. 按 [结果解释与交接](references/result-and-handoff.md) 报告实际参数、轨迹数量、已确认/暂定轨迹、覆盖、限制和输出位置。需要评价时移交独立的轨迹评价模块，不能在本 Skill 内宣布“跟踪准确”或“达到验收标准”。

## 实现约束

- 当前运行实现为 `global-frequency-assignment-v1` 1.0.0：每行先对现有活动轨迹与候选做最大匹配数、最小总代价的一对一全局分配，再由未匹配候选建立新轨迹。
- 频率和时间只使用交接中的原生候选点、样本区间、采样率及时间映射；不从谱图读数，不插值生成观测点。
- `tested_rows_only` 与 `all_rows` 的漏检计数语义不同，请求中必须显式记录选择；未给定时按自主基线使用前者。前者不把上游跳过行记为跟踪漏检，后者会计入。
- 启用功率变化门限或功率代价时，每个候选都必须有正有限 `power` 测量；缺失时阻断，不静默退化为仅频率匹配。
- 所有输入 JSON 拒绝重复键和非有限数。来源文件路径必须是普通非符号链接文件，大小和 SHA-256 必须与交接一致。
- 图形仅用于展示已有轨迹，不改变关联；缺少绘图库时，核心 JSON 仍可在 `save_plot=false` 下运行。

## 参考与资源

- [输入输出契约](references/input-output-contract.md)：正式输入、请求字段和证据验证。
- [跟踪方法](references/tracking-method.md)：预测、门控、全局分配、轨迹生命周期和冲突规则。
- [结果解释与交接](references/result-and-handoff.md)：输出语义、限制和下游边界。
- [场景与参数决策](references/scenarios.md)：稳定线、漂移线、交叉、间断和跳过行的处理选择。
- `assets/schemas/`：交接快照、请求及结果 Schema。
- `scripts/tracking_runtime.py`：只读 review 与新目录 execute。
- `scripts/validate_contract.py`：请求、交接或结果 JSON 的结构检查。

交付时说明本次实际执行与验证范围。除非用户明确要求，不自动运行真实数据、不打包、不评价、不继续目标归属或身份识别。
