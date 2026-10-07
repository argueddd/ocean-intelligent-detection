# 波束形成评价交接

## 上游波束形成 → 本 Skill

优先交付数值与机读元数据，图片仅用于展示。一个可审计输入至少保留：

- 完成清单/result.json 及摘要；
- 算法名、稳定 beam ID、方向参数化、角度坐标系和列序；
- 输入来源、处理时段、通道、阵列几何/模型、声速和预处理；
- 数组的轴、shape、dtype、单位和尺度（线性功率、幅度或 dB）；
- 时间/频率/方向坐标文件；
- 有效样本/帧范围、缺口和失败范围；
- 对于 MVDR：快拍、协方差来源/更新、对角加载、条件数与导向失配信息；
- 用户明确提供的真值、基线、验收阈值及其覆盖。

波束形成模块不应预先写“评价通过”。本 Skill 也不回写上游 result.json。

### 现有 `underwater-beamforming` 0.4.x 包

可直接用：

- `*_scan_power.npy` + `directions_deg.npy` → `spectrum`；
- `*_psd.npy` + `analysis_frequency_hz.npy` + `directions_deg.npy` → `freq-bearing`；
- `*_btr_power.npy` + `analysis_time_seconds.npy` + `directions_deg.npy` → `btr`；
- `*_time.npy` + 采样率/明确片段 → `signal`；
- `*_psd.npy` 的某个已明确波束列 + 频率轴 → `spectrum-output`；
- `*_time_frequency_psd.npy` 的某个已明确波束切片 + 时频轴 → `time-frequency`。

三维时频数组不得自动选最强列；必须先按用户指定的 algorithm + beam ID 做可追溯切片。

## 本 Skill → 调优/上游新任务

评价包交付 `evaluation-result.json`、完整 job 结果、报告和清单。若要迭代，另外生成“建议实验”，每项包含：

1. 观测证据及其覆盖；
2. 待验证原因，不写成已证明故障；
3. 只改变的因素与保持不变的对照条件；
4. 预期改善和防退化指标；
5. 需要的新波束形成请求、参数确认和执行授权。

不直接修改历史参数或在评价目录里重跑上游。

## 本 Skill → 线谱检测/其他下游

如果问题是“哪些频率是线谱候选”，交给线谱检测；本 Skill 不在评价中密寻频带或调 CFAR 阈值。如果问题是“线谱检测得怎么样”，交给线谱评价。如果问题是跨帧连线、声源关联或目标识别，分别交给跟踪、融合和识别模块。
