---
name: harness-probe-spectrum
description: 对采样率已知的单通道 CSV 波形执行功率谱与谱峰分析，根据分辨率和平均需求选择 periodogram 或 Welch，并从数据推导分段长度。
---

这是 Harness 执行链路的测试 Skill，不代表高性能弱线谱检测算法。

使用本 Skill 资源目录下的 `scripts/analyze.py`，参数为 `--input`、`--output`、`--sample-rate`、`--method periodogram|welch`，以及可选 `--resolution`（Hz，默认 1）。CSV 无表头、单列波形。
采样率未知时，不运行频率分析；可先用可用的数据体检 Skill 记录已知特征和缺失条件。
用户要求多段平均以提高噪声背景下稳定性时选 Welch；要求整个短记录的谱分辨能力时可选 periodogram。
Welch 的分段长度由 `ceil(采样率 / 目标分辨率)` 推导，并受真实样本数限制。脚本会报告实际分辨率，不声称超过记录长度支持的能力。
使用项目 Python 环境执行，脚本路径相对于本 Skill 的 base directory。若输入文件不存在，报告实际错误，检查用户提供目录中的真实文件后再修正路径重试，不合成替代数据。

保留脚本生成的原始指标，最后用实际结果说明选择依据、推导参数与后续调整条件。重叠点数和平均段数直接使用报告中的 noverlap、segment_count；补充数值推导时先用工具计算，不靠口算猜指标。
