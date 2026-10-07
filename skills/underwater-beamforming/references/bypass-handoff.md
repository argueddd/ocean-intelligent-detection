# 单阵元 / 已有波束旁路交接 v0.1

实现 scripts/bypass_handoff.py，纳入 Skill 0.4.3。只交接波形、身份、来源及限制；不做阵列计算、频谱分析或线谱检测。已通过 v0.4.3 合成数据与命令行回归（含未知有效性、缺口掩码和便携接收），见 [验证记录](acceptance-v043.md)；没有宣称所有外部实测来源均已验证。

## 输入与分流

- 只接受 [读取检查交接适配器](inspection-handoff.md) 已完成的 handoff_version=0.1 包：waveforms.npy 为实数 float64 [sample,channel]，有已确认的采样率、原始样本/列映射、角色及来源证据。
- single_sensor 必须一路；beamformed 可以一条或多条已形成的波束。sensor_array 拒绝旁路，不能凭“一列”把原始阵元改称波束。
- 不直接解释裸 NPY、旧 result.json 或任意 WAV/SIO。先按上游读取检查和明确导出流程接入；已有本模块主执行结果则继续使用原波束交接接口，不绕回旁路改身份。
- 按当前任务选择导出包中的 channel_ids 及顺序；唯一信号直接选择，多信号按用户指定或下游范围选择，不把第一列或最强波束当作隐含物理目标。每条保存为 [N,1]，完整导出样本轴不变，不在交接时另行裁剪。
- 不要求声速、阵列坐标、CBF 权重或 MVDR 设置等无关参数，不伪造来源波束的算法。

## 请求与未知信息

从 [待确认请求模板](../assets/bypass-request.json) 开始。模板未填写的 null 不能直接运行；优先从交接证据和任务自主解析。纯传递允许按契约保留 unknown 并记录项目级授权，只有下游必需事实仍有歧义时才一次性询问。

| 字段 | 契约 |
|---|---|
| bypass_version | 0.1 |
| source_handoff | 上游完成 handoff.json 的 path / sha256 |
| selected_channel_ids | 实际已导出 ID 的非空唯一列表，按希望交付顺序 |
| signal_metadata | 与选择一一对应，包含 channel_id、algorithm、direction、evidence |
| frequency_coverage | status=known/unknown、band_hz、evidence；描述既有信号已处理频带，不是检测搜索频带 |
| validity | status=known/unknown、sample_intervals、evidence |
| unknown_metadata_policy | preserve_unknown_for_transfer_only，仅数据传递，不授权未知条件下计算 |
| limitations_acknowledgement | 接受上游限制和未知项处理方式的真实说明 |
| output | 全新 directory、block_samples、max_working_bytes、max_artifact_bytes |
| approval | confirmed、scope_sha256、evidence、confirmation={method:user,reference} |

signal_metadata 规则：

- 单阵元 algorithm=null、direction=null，状态为 not_applicable，不称“匿名波束”。
- 已有波束 algorithm 为有依据的非空名称或明确 null（unknown）；不限制外部已有波束必须来自 CBF/MVDR，也不在此运行其他算法。
- 已有波束 direction=null 只在明确接受未知方向交接时使用；已知方向必须完整提供 parameterization=array_angle/azimuth_elevation、angles_deg（对应一或两个角度）、angle_unit=deg、coordinate_frame、zero_direction、positive_direction、fixed_direction=true。只有角度数值、没有参考定义仍不足；本版不支持变指向轨迹，不把它静默简化成固定角。
- 每项 evidence 必须说明来源或用户决定。程序只核对其存在和一致性，不能证明文档或人类确认的真实性。

频带 known 时 band_hz=[lo,hi]，0<=lo<hi<=fs/2；unknown 时 band_hz=null，不猜成全频带。

有效性 known 时 sample_intervals 是输出相对、非空、有序不重叠半开区间的列表，所有所选信号共用；按明确区间生成 bool [N] 掩码。unknown 时 sample_intervals=null，**不写掩码，valid_sample_mask=null**，绝不填成全 true 或全 false。不同信号有不同有效区间时应分开交接，不能偷偷求交集。单纯结构/有限值检查不证明采集连续性、同步或标定正常。

## 命令与批准范围

```bash
python3 <beam-skill-dir>/scripts/bypass_handoff.py review <upstream-handoff.json> --sha256 <上游清单摘要>
python3 <beam-skill-dir>/scripts/bypass_handoff.py digest <bypass-request.json>
python3 <beam-skill-dir>/scripts/bypass_handoff.py check <bypass-request.json>
python3 <beam-skill-dir>/scripts/bypass_handoff.py prepare <bypass-request.json>
python3 <beam-skill-dir>/scripts/bypass_handoff.py receive <new-handoff.json> --sha256 <新交接清单摘要>
```

路径相对请求所在目录解释。review/check 只核对 JSON、证据 JSON 摘要与源文件 stat，不读波形或做 FFT；check 不表示实际内容已验证。digest 不授权，改变选择、未知项决定、范围、输出或预算必须重新确认。上游导出授权不能代替旁路授权。

prepare 才读真实数组、核对源产物内容摘要/形状/编码/有限值，分块无幅值变换复制所选列；前后复核来源不变。只使用 NumPy，不调用 CBF、MVDR 或检测器。超预算、源变化、异常数据直接停止，不缩范围、不修复数据。估算包含证据副本与受管工作数组，但不是操作系统硬内存配额。输出目录必须在源包外且不存在；失败保留 failure.json 和部分文件，不能当完成包。

## 新交接包

- signal_000000.npy 等：按明确选择顺序保存 float64 [N,1]。
- valid_sample_mask.npy：仅有效区间明确时存在。
- upstream_handoff.json、upstream_inspection_result.json、upstream_export_request.json：上游清单、检查报告和导出请求的字节副本；不复制整个原始录音。
- confirmed_bypass_request.json：本次选择、未知项决策及授权；作为 source_configuration 引用。
- handoff.json：最后发布，包含 signal_id、channel_id、source_column、原始列索引、算法/方向及各自状态、单位、频带、时间映射、上游检查与未检查项、处理历史和文件摘要。prepare 返回该清单 SHA256，随包记录。
- purpose=waveform_and_metadata_transfer_only、beamforming_performed=false、detection_status=not_run、can_detect=false。

原始样本索引 = export_sample_zero_source_sample + 输出索引；时间 = first_sample_offset_seconds + i/fs，相对原始文件样本0的 time_reference。不拼接有效区间，不伪造 UTC。幅值保持已导出 float64 数值，不代表上游未处理或物理标定合格。

## 接收端

receive 核对包内文件摘要、来源证据、请求范围、角色/列/时间元数据、实际 [N,1]、有限值和已知掩码；可移植接收不要求源机器的路径仍存在。load_signal(path, sha256, signal_id) 返回只读 waveform、可为 None 的 valid_sample_mask、signal、data_role、provenance 和包内 source_configuration 路径/摘要。必须明确 signal_id；只读内存映射不是锁定快照，后续消费仍需保护和复核来源。

下游的 scripts/beamformed_input.py 提供 receive-bypass 和 load_bypass_signal；仅该旁路入口需要安装同级 underwater-beamforming。正常主结果交接仍用原 receive/load_beam，两种契约不混猜。

accepted 只表示交接接收检查通过，不表示可在未知有效性/频带下直接计算。后续参数和未知信息若影响计算，必须在独立下游任务先明确处理；本模块不生成检测草稿、不询问检测阈值，也不调用旧 welch-detect。
