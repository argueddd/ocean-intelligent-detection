# 线谱评价入口（兼容定位）

评价职责已独立到 [underwater-line-spectrum-evaluation](../../underwater-line-spectrum-evaluation/SKILL.md)。本文件不再维护第二份指标公式或执行流程。

开展指标设计、结果评价、效果比较或验收时，确认该 Skill 可用，完整阅读其入口及 [证据与指标规则](../../underwater-line-spectrum-evaluation/references/evidence-and-metrics.md)。缺失时报出依赖，不自动安装或调用旧工具替代。

- 有真值的性能评价与无真值的结果分析分开；部分标注不把未标记区域变成负样本。
- 候选数不是误报数；背景统计量不是背景真值；未定义/不可算的指标不填 0。
- 平均误报数、候选误报占比与单元/帧/整段误报概率是不同量。
- line_spectrum_metrics.py 是保留的历史工具，不是新评价执行器。psd/lofar 包含检测，旧 psd 无真值时会把候选计入误报；禁止直接用于新评价流程。复用需明确适配与测试。

CFAR 控制目标与门限设计仍见本检测 Skill 的 [门限设计](cfar-threshold-design.md)，不因职责拆分而自动确认未决参数。
