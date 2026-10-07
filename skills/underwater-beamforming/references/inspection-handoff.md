# 数据读取检查 → 波束形成交接 v0.1

实现位于 inspection_handoff.py，初始纳入波束形成 Skill 0.4.2，0.4.3 增加旁路专用草稿。只接收 underwater-data-inspection 的 schema_version=0.2 检查结果；不会运行 CBF/MVDR，也不会进入线谱检测。已完成 v0.4.3 合成与 S59 VLA 数据链路回归，见 [验证记录](acceptance-v043.md)；通过不解除新输入的确认门禁。

## 1. 三个阶段与授权边界

1. review：只读检查 JSON、核对源文件 stat，展示已有事实、21项检查状态及待确认问题。没有波形读取、复制或计算。
2. check / digest：核对导出配置、真实确认记录、原始范围、列身份、预算及来源。digest 只计算配置摘要，不授权。
3. prepare：仅在完整导出请求获确认后，重用上游读取器，分块导出 float64 NPY 和可追溯交接包，按明确身份生成尚不可执行的阵列配置或旁路请求草稿，以及对应问题清单。

导出准备好 ≠ 波束参数齐全 ≠ 波束计算获授权 ≠ 工程验收通过。填写草稿、确认参数和正式计算仍经过原执行器全部门禁，不自动填写 parameter_records 或执行 approval。不要删除草稿中的 inspection_handoff 字段绕过来源核对。

## 2. 命令与依赖

命令中的路径须替换为实际绝对路径：

```bash
python3 <beamforming-skill>/scripts/inspection_handoff.py review <inspection-result.json>
python3 <beamforming-skill>/scripts/inspection_handoff.py check <handoff-request.json>
python3 <beamforming-skill>/scripts/inspection_handoff.py digest <handoff-request.json>
python3 <beamforming-skill>/scripts/inspection_handoff.py prepare <handoff-request.json>
```

review/check/digest 只需标准库及本 Skill 的 preflight。prepare 需要同一个 skills 根目录下的 underwater-data-inspection，以及其 NumPy/SciPy/h5py 等读取依赖。没有依赖时报告，不安装、不切换解码器。只加载已安装同级 Skill 的读取器，报告内容不能指定可执行代码路径。普通 NPY 波束形成不要求安装读取检查 Skill。

源格式支持范围继承已安装的上游读取器：实数 NPY、NPZ、传统 MAT、HDF5、支持编码的 PCM WAV 和 SWellEx 风格 SIO。不复制解码逻辑，不宣称这些格式都完成本次联调。传统 MAT/NPZ 仍需满足整变量解码预算。

成功为退出码0；信息不足、不支持、来源变化或导出失败返回2，原因见 JSON。检查通过只是可以尝试导出，实际读取/转换仍可能失败。任何失败都不能伪造完成包。

## 3. 导出请求

从 [待确认模板](../assets/inspection-handoff-request.json) 开始。null 不是默认值，也不是授权。必填项：

| 字段 | 含义 |
|---|---|
| handoff_version | 0.1 |
| inspection_result | 已有 result.json 的 path 和实际 SHA256 |
| sample_range | 原始源样本的零基半开区间；必须位于上游实际读取范围内 |
| channel_indices | 原始列索引的非空唯一升序子集；只选上游已读取通道 |
| identity | data_role、与所选原始列一一对应的 channel_ids，以及 role_evidence / mapping_evidence |
| processing_history | values 与 evidence；未知用 ["unknown"]；[] 只用于明确已知无上游处理 |
| time_reference | kind=relative/utc 和 origin；指原始文件样本0的时间原点，不是导出片段的零点 |
| units_policy | preserve_report_value_or_unknown；不转换幅值，不伪造声压单位 |
| inspection_linkage | accept_size_mtime_link_not_historical_content_hash；明确接受旧检查仅有 stat 关联的证据边界 |
| limitations_acknowledgement | 对上游实际覆盖、未执行/未实现项目的确认说明；不是同步/标定正常声明 |
| output | 新 directory、dtype=float64、conversion=exact_numeric_no_scaling、block_samples、max_read_mib、max_artifact_bytes |
| approval | confirmed、scope_sha256、真实 evidence 和 confirmation.method=user/reference |

原始数据身份必须明确为 sensor_array、single_sensor 或 beamformed，不凭通道数决定。阵列至少两路，single_sensor 必须一路。单阵元/已有波束生成 bypass-request.json 旁路草稿，另经确认使用 [旁路交接](bypass-handoff.md)，不会二次当阵元波束形成，也不执行检测。

通道映射如果上游已确认，新列表必须与所选列对应一致；冲突先解决。上游只有 index:N 标签时，新的真实映射需由用户/可信来源明确说明并获确认，不能照抄位置标签冒充物理身份。上游采样率必须 confirmed 且有来源；缺失/冲突先解决上游记录，本接口不另设猜测覆盖值。

review 可以展示不完整事实。prepare 则要求读取选择、样本读取、标准视图、源稳定性几个前置子项已完成。上游顶层 partial 不一定阻断，例如只因谱分析不完整；但不能把失败、失效、probe-only 或未完成读取的结果拿来导出。是否做过质量/频谱检查及其范围逐项保留，不升级状态。

## 4. 导出与数据完整性

- 源文件只读；只做明确的字段/轴读取、范围/通道选择和精确 float64 数值转换。
- 不去均值、不滤波、不重采样、不标定、不归一化、不补零、不删样本或通道、不改变通道顺序。
- NaN/Inf 直接阻断；整数超过 ±2^53 阻断，不静默损失精度。合法的 float32/float64 和范围内整数按原数值导出，不把 PCM 整数自动归一化为音频幅值。
- 读取器 block_samples 可在明确内存预算内向下分块，但不会缩短总范围；读取预算不是操作系统硬内存保证。全部原始文件哈希在导出前后计算，可能需要额外磁盘读取时间。
- 检查报告 SHA256、源 stat、格式/字段形状/类型、读取器代码和导出前后源 SHA256 均核对。导出时取得的哈希不能追认旧检查时的文件内容；大小/mtime 一致也不是并发快照。
- 失败保留部分产物与 failure.json，不发布 handoff.json，不静默删除诊断目录；不得将残留 waveforms.npy 作为已完成交接使用。

完成包：

```text
handoff-directory/
  waveforms.npy                    # [导出样本数, 导出通道数]，float64
  inspection_result.json           # 上游 JSON 原样复制，保留全部检查记录
  confirmed_handoff_request.json   # 本次导出请求及真实确认
  handoff.json                     # 最后发布的完成清单、来源/映射/摘要
  execution-draft.json             # 仅sensor_array；可编辑，物理/处理参数待确认
  bypass-request.json              # 仅single_sensor/beamformed；选择/元数据/处理决定待确认
  questions.json                   # 待确认项，不是波束计算结果
```

两种草稿只生成与角色匹配的一种，handoff.json.editable_draft 指明文件；选择列表仍待明确，不默认全部。旧导出包无需重导，可从旁路模板手工建立新请求并绑定原清单摘要。

不可变数据产物有 SHA256 与大小记录；配置草稿和问题清单是可编辑内容，不进入源数据摘要链，避免“草稿引用清单、清单又散列草稿”的循环依赖。新目录不在原检查报告目录内部，不覆盖历史结果。

## 5. 波束形成接收与时间坐标

主执行包装仍为 execution_version=0.4；来自交接的数据新增可选顶层 inspection_handoff={path,sha256}。没有该字段的手工 NPY 输入保持原行为。字段存在但无效时阻断，不静默忽略。

主执行器会核对交接清单与配置的源路径、形状、类型、采样率、角色、列标识、单位、时间参考和处理历史；run 阶段仍验证实际 NPY 内容摘要。交接证据变化或来源不匹配时停止。允许明确确认后在已导出 NPY 内进一步选择样本区间/处理通道，不能借此读取导出范围以外的数据。

样本索引区分：
- input.sample_range 和波束 result.source_sample_range：导出 NPY 的局部索引。
- original_source_sample_range / original_source_channel_indices：回到原始录音的索引。
- 原始样本索引 = export_sample_zero_source_sample + NPY 局部样本索引。
- 输出 first_sample_offset_seconds = (导出起点 + 本次 NPY 起点) / fs；时频图沿用原始文件时间原点，不将中间片段误标为原文件第0秒。
- STFT 帧起点数组仍使用 NPY 源索引；time_mapping 明确其含义，不改变采样率或悄悄平移波形。

未知 UTC 保持相对时间；均匀采样坐标不证明采集连续性。波束输出和后续补图继续传递交接引用、上游检查状态/问题/未检查项、原始样本和通道映射。四项尚未实现的连续性、削波、同步、标定故障检查不能因交接而变成“已通过”。

草稿只继承有依据的输入事实。上游提供的米制坐标可作为待核对候选，但坐标系、参考位置、模型身份仍留空；不把旧分析频带、窗长、分析预算或几何一致性结论当作波束处理参数。

## 6. 当前边界

这一步只接通“读取检查 → 可追溯波形/配置草稿 → 波束执行入口”的代码路径。不是自动全流程，也没有新增线谱检测联调、水平阵列序结论、流式波束形成或性能验收。本次已验证非零片段起点、通道子集、未知事实阻断、来源变化、文件清单、同意范围失效及实际 VLA SIO 导出。检查通过不意味着覆盖所有编码/精度组合；新来源仍需按规则核对。
