# 评价字段格式与只读检查

状态：主字段契约 0.1.0，TruthLabels 契约 1.0.0，评价运行时 1.0.0。已实现单文档结构/局部一致性检查、跨文档预检、无真值描述统计、真值匹配与可信背景误报统计。不认证真值真实性，不自动索引任意历史结果，不自动做工程验收。

## 1. 三类主记录与标签记录

| 记录 | 回答的问题 | 定义与模板 |
|---|---|---|
| EvaluationRequest | 评价哪些结果、哪些指标，哪些参数/保存选择已明确 | [Schema](../assets/schemas/EvaluationRequest.schema.json) · [草稿](../assets/templates/EvaluationRequest.draft.json) |
| TruthCoverage | 某一检测目标的哪些时频范围有何种标签/背景证据 | [Schema](../assets/schemas/TruthCoverage.schema.json) · [草稿](../assets/templates/TruthCoverage.draft.json) |
| EvaluationResult | 每个所选指标算了没有、值与分母是什么、证据支持到哪里 | [Schema](../assets/schemas/EvaluationResult.schema.json) · [草稿](../assets/templates/EvaluationResult.draft.json) |
| TruthLabels | `complete`/`partial_positive` 区域的具体频率标签与时间定位 | [Schema](../assets/schemas/TruthLabels.schema.json) |

三种主对象使用独立命名空间 urn:underwater-line-spectrum-evaluation:contracts:0.1.0，共享 [common.schema.json](../assets/schemas/common.schema.json) 的定义。TruthLabels 1.0.0 是 TruthCoverage `labels_ref` 指向的严格独立记录。它们都不是 DetectionRequest/DetectionResult，不传入检测或波束执行入口；原有检测契约不改变。

## 2. 通用封装与填写

三种主文档包含 schema_version、record_type、document_status、payload、unresolved_items，拒绝未定义字段。TruthLabels 使用更窄的顶层标签结构，不具有草稿状态。两类都不自动添加库默认值或未知“扩展”对象。

- draft：顶层业务字段可为 null，必须列出 unresolved_items。模板全部业务字段留空，未选信号、算法、指标、门宽或输出策略。草稿仅检查形状/类型，不保证局部业务一致性。
- specified：使用完整业务结构，顶层 unresolved_items 为空；这是“声明已按完整格式记录”，不是“所有参数已解决”。业务内仍可明确写 unknown、pending 或 unavailable，其 reason 说明限制；不能把这些状态变成默认值。
- 明确没有与未知不同：例如 truth binding 的 none 是已知没有真值，unknown 是真值状态尚未查清；pending 匹配规则没有选好参数。空数组只表示明确没有条目。
- 文件引用声明 locator 和 SHA-256；会话引用用 session 定位，不冒充已保存文件；unavailable 必须说明原因。引用里的 SHA-256 目前仅校验格式，不实际核对文件。
- 每次填写保留最小来源/配置；引用不可用时不得另找同名文件替换。单文档检查器不跟随引用；跨文档预检只打开请求显式引用的评价、检测与标签文件，并实际核对摘要。
- 时间使用原来源对应的秒坐标、明确 reference 和半开区间 [start, stop)；频带为闭区间 [low, high] Hz。时间未知不填区间，已有原点说明可保留；单谱确实不适用时间时用 not_applicable 并解释。不能根据候选首末时间反推观测区间。
- known 输入身份保留 input_package_sha256 + signal_id；known 波束保留 result_sha256 + beamformer + beam_id 与元数据引用。unknown 身份可保留已知的部分事实并说明缺口；单阵元用 not_applicable，不造波束。

先复用可靠上游信息，再列需要用户决定的项。要进入 specified，按相应结构补齐声明，而不是简单改状态字段。声明为 recorded 的确认必须带真实表述与证据引用；工具既不生成确认，也不认证表述或用户身份。

## 3. EvaluationRequest

targets 是明确选定的评价对象，每个 target_id 限定检测 result_ref、run_id、task_id、来源身份、实际配置引用、task_kind 与范围。相同来源的不同子范围可用不同 target_id，但不以此宣称独立试验。task_kind 为 framewise 或 averaged_spectrum。

若只有外部图或旧表而没有可核对的 run/task 身份，不造运行记录来填满 Schema；保留 draft 并报告适配缺口，仍可按 Skill 规则开展明确受限的定性审查。当前没有外部格式自动适配器。

truth_bindings 对每个 target 恰好一项，分别为 provided、none 或 unknown。provided 引用独立 TruthCoverage；另外两种写原因，不造“空负样本表”。当前不打开该覆盖记录，身份与范围匹配留给后续跨文档预检。

metric_requests 按 metric_id + target_id 选择指标，compute 为本次是否请求计算；只是记录选择，不是许可。definition_version 当前为 0.1.0。count_stage 区分 final_candidate 和 cell_threshold_crossing；denominator_rule、aggregation_rule、coverage_rule 必须写明，不套用统一分母。没有选择的指标无需列满。

matching_rules 记录频率门宽、时间规则、分配方法、平局和重复候选处理。specified 时逐项明确；pending 时参数为空并写原因。时间规则 frame_identity 不填时间容差，tolerance 才填 time_gate_s，确实无需时间匹配用 not_applicable。依赖匹配且请求计算的指标至少引用一个已明确或待确认的规则；不可借空引用暗用默认门宽。字段检查器不实施匹配；V1 执行器只支持 `maximum_cardinality_minimum_frequency_error` 与 `candidate_id_then_truth_id`，其他声明在预检阶段被拒绝。

output_plan 分别列出显示、保存的 metric_id；artifact_requests 明确额外产物是否计算/显示/保存，不自动全选。选择保存时才填写 save_destination。compute=false 且需要展示已有值时，未来还须确认该值实际存在；目前检查器不查文件，也不偷偷补算。accepted_limitations 记录已接受的限制，不将假设提升为事实。

## 4. TruthCoverage

一个文档描述一个 target 的证据覆盖。availability=available 需要证据来源和区域；none/unknown 不得填入已标注区域，evidence_origin 与状态对应。已有证据的 origin 区分人工/实测标注、仿真、注入、模型和预期参照，不混称海试真值。

regions 在目标范围内分别声明：

| label_status | 必须保留的含义 |
|---|---|
| complete | 该区域标签完整；正负类别和标注粒度明确，提供标签与依据；未标记按声明的负类解释 |
| partial_positive | 只知道部分正例；未标记仍未知，不能计为误报 |
| verified_background | 有证据支持明确 H0；提供零假设、负类定义与依据，不从“安静”或空表推断 |
| unlabeled | 未标注；无标签引用，说明原因，未标记仍未知 |
| excluded | 明确不参与评价，说明原因 |
| disputed | 标签有争议；未标记不当负类，先解决或限制评价范围 |

label_grain 区分 cfar_cell、candidate_peak、frame、segment 等，不能用峰表冒充全单元判决。超出已声明 regions 的范围一律 unknown，不要求用户伪造全域标注。

0.1.0 不接受同一时频位置的重叠区域声明；应先明确取用哪份证据或分区，不能由程序默默取优先级。闭频带共享端点也算重叠；时间半开区间共享边界不算重叠。时间未知而无法区分的重叠风险会被报告。地区标签结构合格不证明标注真实、完整或与检测数据对应。

independence 明确相对于哪些来源声明独立以及依据；unknown 不补独立。expected_reference 不能声明完整真值或纯背景。仿真/注入/模型条件只支持相应条件的结论。

## 5. EvaluationResult

evaluation_id 独立于检测 run_id；保留请求、实际评价配置和目标引用。execution_status 描述评价过程，不覆盖逐指标状态。completed 可表示“审查完成且有指标证据不足”，不等于全部指标已算出；仍有待确认、未运行或计算失败的项目不能隐藏为全完成。

每项 metrics 保留 metric_id、target_id、metric_kind、定义/版本、status、value、unit、实际范围、匹配规则引用、计数层级、basis 和 accounting。

- computed：有数值、实际覆盖、可用来源/配置/判据引用，并满足本指标的声明要求。
- 其他状态：not_requested、not_run、pending_confirmation、insufficient_evidence、not_applicable、undefined、not_implemented、failed。value 必须为 null 并说明 reason，不填 0。
- computed 且数值 0 可以是真正的零候选/零观测；不能用它表示缺证据。比值分母为 0 时不允许标 computed，可报告 undefined。
- numerator / denominator 带数值、单位、定义和证据引用。比值/率需要二者；当前只核对基本范围和分母规则，不重算公式或原始指标。
- basis 区分描述、标签匹配、可信背景、标定观测、独立验证等。性能指标需相应 truth_status、coverage_ref 和 region_ids；局部标注只支持已匹配项的频率误差，不自动支持总体精确率或误报。理论/预期/图片结论不伪装成实测标量。
- accounting 描述实际所选范围的试验单位、候选完整性、零检出单位是否包含、请求/处理/排除数与理由。不是逐帧明细的替代证明。逐帧均值分母必须对应处理过的有效帧数，且包含成功零候选帧；单元概率必须用单元级判决。
- actual_scope 应位于目标请求范围内；跨缺口不拼接，不改变原时间参考。不同算法范围不同须报告，不能默认为公平可比。
- findings 分开记录 observation、interpretation、assumption、recommendation；建议不触发新计算。
- artifacts 区分未请求、未生成、临时可用、已保存、不可用与失败；saved 需要文件定位和摘要声明。
- acceptance 的关键 metric_ids、标准与证据另列。未请求则不捏造验收计划；明确效果结论需要标准引用和已算出的所选关键性能指标。此处只检查声明配套，不读取标准或判断实际通过。

本版每条 metric 记录一个标量；曲线、分组表和图片通过按需 artifact 引用表达，不在 value 中塞列表或未定义字典。跨目标比较可写入有依据的 findings；尚未实现比较调度或统一评分。未列出的新指标需先定义并版本化扩展，不借改名称绕过约束。

## 6. 内置指标名称与单位

下表既是字段词表，也是 V1 执行器的内置标量指标集。计算定义与证据要求见 [证据与指标规则](evidence-and-metrics.md)，执行约束见 [评价执行器 V1](runtime-v1.md)。

| metric_kind | unit | 说明 |
|---|---|---|
| candidate_count | candidate | 所选实际范围内的最终候选数 |
| mean_candidates_per_frame | candidate/frame | 候选数 / 有效完成帧数 |
| candidate_frame_fraction | 1 | 有候选有效帧数 / 全部有效完成帧数 |
| false_count | candidate 或 cfar_cell | 依明确计数层级统计误报 |
| mean_false_per_frame | candidate/frame 或 cfar_cell/frame | 对应层级的误报数 / 可评价帧数 |
| false_per_hour | candidate/hour | 候选误报数 / 有效观测小时，不自动合并成报警事件 |
| cell_false_fraction | 1 | 合格 H0 单元过门限数 / 全部合格 H0 单元数 |
| background_frame_false_fraction | 1 | 有误报的背景帧数 / 合格背景帧数；事件层级另由 count_stage 指明 |
| background_segment_false_fraction | 1 | 有误报的背景段数 / 合格背景段数；统计可靠性另行评价 |
| recall / precision / f1 | 1 | 完整标签定义范围内的匹配统计，各自分母不同 |
| frequency_mae_hz / frequency_rmse_hz / frequency_bias_hz | Hz | 只针对已匹配项；同时报告匹配覆盖与漏检限制 |
| mean_threshold_margin_db / mean_background_contrast_db | dB | 已有同尺度判据的明确平均方式，不等于物理 SNR 或正确概率 |

这些量是有证据时的观测统计，不把相关帧当独立样本，也不表示已确认 CFAR 应控制哪个量。按帧/整段风险目标仍需用户选择。必要的置信区间、跨帧跟踪、事件合并和新谱计算均未包含在本轮执行能力中。

## 7. 使用检查工具

需要 Python 3、jsonschema 和 referencing。本次验证环境为 jsonschema 4.25.1、referencing 0.36.2；缺依赖时报告，不未经确认自动安装。

在 Skill 目录下，只检查一份明确文档：

```bash
python3 -B scripts/validate_contract.py assets/templates/EvaluationRequest.draft.json --kind EvaluationRequest
python3 -B scripts/validate_contract.py assets/templates/TruthCoverage.draft.json --kind TruthCoverage
python3 -B scripts/validate_contract.py assets/templates/EvaluationResult.draft.json --kind EvaluationResult
python3 -B scripts/validate_truth_labels.py /explicit/path/to/truth-labels.json
```

实际使用把文档路径换成用户指定文件。程序只向标准输出返回 JSON，不写报告文件、不修正输入。退出码：0 为本次声明检查通过；1 为结构/局部一致性不合格；2 为文件读取/JSON 解析失败。这些只读单文档检查结果始终 can_execute=false。实际执行前再运行 `python3 -B scripts/evaluation_runtime.py request.json --preflight-only`。

检查范围：

- 字段、版本、类型、枚举、基本范围；不认识的字段拒绝，不默默忽略。
- 重复 ID、悬空的文档内 target/metric/rule 引用、时间区间、区域重叠及范围包含关系。
- 真值与未知声明、指标状态/空值、必要证据引用声明、单位、分母与基本覆盖计数的一致性。
- 重复 JSON 键、NaN/Infinity、指数溢出、非 JSON Python 对象被拒绝；只加载随包 Schema，不下载或运行文档指定的外部 Schema。

明确不检查：被引用文件内容与摘要、跨文档身份与版本、标签真实完整性、真实试验分母、指标公式重算、参数科学适用性、真实用户确认与工程效果。因此“provided/complete/recorded”都只是本文件声称的状态，不能当作已核验事实。有人在结果里谎称完整真值，此工具不会凭一个引用识别出来；后续必须做跨文档和实际证据核验。

## 8. 测试与运行时边界

运行：

```bash
python3 -B -m unittest discover -s tests -v
```

当前 94 项测试包含 86 项原契约/只读 CLI 测试和 8 项运行时测试。运行时测试覆盖无真值指标、完整真值一对一匹配、可信背景候选/单元指标、缺真值空值状态、波束身份矛盾、摘要篡改阻断和拒绝覆盖输出。此外已对 SWellEx-96 S59 完成检测包做无真值集成验证。

这些测试证明执行器的字段、证据门禁和数值公式在覆盖场景下按预期工作，不证明任何检测算法在未验证海况下达标，也不认证外部标签为真。单文档检查器始终 `can_execute=false`；只有独立跨文档预检才能返回可执行状态。

实现采用 [JSON Schema 条件结构](https://json-schema.org/understanding-json-schema/reference/conditionals) 和 [jsonschema 本地引用注册机制](https://python-jsonschema.readthedocs.io/en/stable/referencing/)；这些技术机制只支持格式检查，不认证数据事实。
