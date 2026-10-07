# H0 门限标定与独立验证 v1

`cfar_calibration.py` 标定的是 CFAR 门限系数，不是声压/传感器标定。先读 [门限设计](cfar-threshold-design.md) 与 [运行门禁](runtime-v1.md)。选择这条路线不自动授权生成噪声、挑“安静片段”、重做波束或标定。

## 输入与方案

配置的键严格为：calibration_version=`1.0.0`、target_request、context、trials、independence_statement、background_evidence_reference、confidence_level、minimum_calibration_events、minimum_validation_events、quantile_rule、validation_rule。

- target_request 是指定唯一 target task 的合法 DetectionRequest。route=calibration，calibration_ref=null、theory_assumption=null；products 三项均 []，display=null，表示这次只校准，不同时检测/绘图。其 resources 是本次标定的显式资源/保存计划。
- context 与普通检测相同，显式包含目标及所有 H0 试验的 SignalInput 和来源文件，强制完整上游适配核验。背景输入也必须按相同交接契约接入；不接无来源的比值表冒充完整标定。
- 每个 trial 都明确 trial_id、split（calibration/validation）、input_ref、scope、background_statement、processing_equivalence_statement。H0 真值/独立性/处理等价是有出处的显式声明，不是软件从无标签录音推断出的事实。
- independence_statement 和 background_evidence_reference 说明重复试验的来源、独立依据；不能把重叠帧当独立重复。程序拒绝同一波形摘要上目标检测片段、标定试验、验证试验之间重叠的样本支持，并在消费记录时重新检查目标与试验的重叠；但这不能证明不同文件/不同来源就统计独立。
- confidence_level 与两类 minimum_*_events 必须逐次确认，没有隐藏的 95% 或样本数默认值。默认库置信度不会代替本次选择。
- quantile_rule 显式选择 `conservative_order_statistic`；validation_rule 显式选择 `one_sided_clopper_pearson_upper_le_q`。它们是本版支持的可审计实现，不自动代选。

帧控制：一个 H0 trial 恰好一个完整有效帧，每个 trial 最大值覆盖全部合格 CUT。整段控制：一个 trial 覆盖与目标相同的完整帧数量/相对起点/间隙结构。平均谱还匹配算术平均支持。不能拿短段、不同帧数或单频点标定结果套到整段。

目标与试验核对采样率、单位状态、数据角色、波束算法/方向、窗/步长/FFT/去均值、任务类型、参考/保护/OS 秩、频带、频点集、事件范围和 q。来源配置不同必须保留逐试验的显式处理等价声明；相同元数据不证明真实背景匹配。记录绑定目标来源配置摘要，消费时不会仅凭名字、算法类型或接近的参数复用。

## 固定的统计计算

对每次完整 H0 重复，运行同一 PSD/背景核心，记录该事件范围的 `max(P/Z)`。任何零/非有限背景会阻断标定，不删除异常试验后凑样本数。候选过滤不用于调系数，控制对象是原始过门限事件，因此最终候选事件不会多于它。

对 n 个 calibration 最大值，使用升序第 `ceil((n+1)*(1-q))` 个值作为 alpha。若秩超过 n，尾部支持不足，必须报告；不把样本最大值自动当作达标。这个有限样本顺序统计量选择与交换性下的秩校准有关，背景同分布/代表性仍须成立；不把它说成海况无关的条件保证。相关思路参见 [Angelopoulos 与 Bates 的原始教程](https://arxiv.org/abs/2107.07511)。

validation 集从不参与选 alpha。记录超出 alpha 的事件数 k、总数 n、观测比例，以及声明置信度 c 的单侧 Clopper–Pearson 上界：k=n 时为 1，否则 `Beta.ppf(c,k+1,n-k)`。只有上界不大于 q，记录才为 qualified_for_declared_scope；否则为 not_qualified，不可供检测消费。此验证要求试验独立且 H0 声明可信。精确二项区间定义见 [SciPy Clopper–Pearson 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)，代码与单侧 binomtest 区间交叉测试。

不因验证未通过而自动改 q、提高 alpha、增加试验或在验证集反复优化后声称独立通过。下一步方案必须重新确认。验证统计只属于本次门限标定的 H0 证据，不代替实测线谱评价 Skill。

## 执行与复用

```text
python3 scripts/cfar_calibration.py review /absolute/calibration.json --source-root /absolute/readonly-inputs
python3 scripts/cfar_calibration.py confirm /absolute/calibration.json --source-root /absolute/readonly-inputs --evidence /absolute/user-evidence.json --receipt-output /absolute/new-calibration-receipt.json
python3 scripts/cfar_calibration.py run /absolute/calibration.json --source-root /absolute/readonly-inputs --receipt /absolute/new-calibration-receipt.json
```

execution receipt 的 scope=calibration，与普通检测 receipt 不能混用。按资源选择临时返回或新目录保存 calibration-record.json、calibration-request.json、calibration-review.json、最后写入的 package-manifest.json。

复用时把 calibration-record.json 的真实 SHA256/显式位置加入 context.source_files 和 threshold.calibration_ref。记录保留 h0_assertions（独立性声明与背景依据引用）。执行门禁检查状态、精确 signature、alpha/order、最大值与试验划分审计、H0 声明、独立验证统计及确认范围；不会自动修订系数或重跑标定。

标定不自动生成 H0 波形。若用户选噪声模型，先由已确认的独立试验准备流程生成并保存模型、种子和参数来源，再按统一输入交接。若用户只有无标签实测数据且无法说明背景来源，应报告暂缺标定依据，而非伪造纯背景标签。
