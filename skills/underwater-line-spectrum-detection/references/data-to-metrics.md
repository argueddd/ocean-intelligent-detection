# 数据到评价信息入口（兼容定位）

本轮将评价的数据要求统一到独立评价 Skill，避免两边维护不同规则：

- 先读 [线谱评价 Skill](../../underwater-line-spectrum-evaluation/SKILL.md)。
- 判断数据和标签支持什么指标：读 [证据与指标规则](../../underwater-line-spectrum-evaluation/references/evidence-and-metrics.md)。
- 检测结果、真值、波束索引及保存的交接语义：读 [评价交接设计](../../underwater-line-spectrum-evaluation/references/evaluation-handoff.md)。

不知道矩阵轴、时间映射、真值覆盖、匹配门宽或统计分母时，报告或询问后再算；不根据矩阵形状自动转置，不从已有候选时间推断全部帧/时长。无真值数值描述与仅图定性审查分别处理。

如果收到的是待检测的波束时域，而非已有检测结果，仍走本检测 Skill 的 [输入接入](beamformed-input.md)；不把“评价”当成运行谱估计或检测的许可。已有 DetectionResult 0.1.0 也不保证所有评价所需证据均已保存。
