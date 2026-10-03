---
name: harness-probe-data-health
description: 对 CSV 波形数据做数据体检，读取 YAML 元数据中的采样率，识别通道数、非有限值和恒定通道；采样率缺失时保留未知。
---

这是 Harness 执行链路的测试 Skill，不代表完整声纳数据体检方法。

使用本 Skill 资源目录下的 `scripts/check.py` 完成 CSV 数据体检。数据按行采样、按列通道，无表头。
脚本接受 `--input`、`--output`，以及可选的 `--sample-rate` 和 `--metadata`（YAML，字段为 sample_rate_hz），将结果写成 JSON。
用户给出采样率时传入；给出元数据文件时可读取它；均未给出时省略，让报告记录缺失参数，不把未知值编造成事实。
使用项目 Python 环境执行资源脚本；资源路径相对于本 Skill 的 base directory，输入和输出相对于项目工作目录。

输出文件保留脚本产生的解释器路径和检测指标，最后根据真实结果解释可继续哪些处理、哪些处理仍缺条件。
