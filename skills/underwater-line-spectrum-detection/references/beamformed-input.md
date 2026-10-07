# 波束时域 → 下游数据与信息交接（主契约 v0.1，实现 v0.1.2）

本适配器只传递已成功保存的 CBF/MVDR 时域数据及下游需要的相关信息；不重新波束形成、不选择目标、不计算谱或检测线谱，也不生成或确认检测参数。实现位于 scripts/beamformed_input.py。已通过同级波束 Skill v0.4.3 的合成、命令行和 S59 VLA 数据交接回归，见其 references/acceptance-v043.md。该结论仅指波形与元数据链路，不包含检测。

## 范围与阻断条件

- 仅接收主 execute.py 结果；补图包的来源和幅值记录不同，本版明确拒绝，不自动追链或猜测。接受波束模块 execution_version=0.4、execution_status=completed、parameter_status=complete、data_role=beamformed 的结果包，实际波形须为 float64、轴 [sample, retained_beam]。不猜旧版本、裸 NPY、多阵元、复数或图像的身份。
- source_result 指向完成 result.json 并绑定 SHA256。所有路径相对请求文件解释；产物必须位于结果包内。源文件只读，输出必须是源结果目录之外的全新目录。
- 从用户明确选择的 algorithm + beam_id 定位已保存的 column；scan_column 是原计算方向索引，两者不能混用。不按最大功率、第一列、最近角度或“默认全部”选束。角度请求先依据方向定义精确映射为 beam_id 并确认。
- 只有谱/图、未保存所选方向时报告不能交接。功率无法恢复时域相位；需要用户另行授权波束时域生成，不回读其他目录偷偷补齐。
- 当前只复制所选波束的**完整输出样本轴**，不提供交接时裁剪、重采样、滤波、归一化或量化。有效掩码逐样本保留，不能用 y[mask] 拼接有效区间再作 FFT。
- 缺少采样率、方向映射、单位状态、频带、时间映射、有效区间或处理历史时阻断。unknown 单位原样保留，交接不意味着允许输出声压级。
- 本页主结果接口不接管单阵元裸文件或匿名既有波束；经读取检查和明确身份导出的旁路包使用下述独立入口。原始多阵元不得旁路；检测算法选择、自动跟踪或工程评价不属于交接。

## 命令与交接范围确认

这里确认的是数据来源、所选波束、保留策略、限制和输出资源，不是检测方法、检测窗长、阈值或检测搜索频带。可靠的上游采样率/方向等记录直接继承，不要求重复填写；下游检测参数未确定不阻断交接。

先阅读来源；此步只读 JSON 和文件尺寸，不读波形、不计算 FFT：

```bash
python3 <line-skill-dir>/scripts/beamformed_input.py review <beamforming-result.json>
```

使用 [请求模板](../assets/beamformed-handoff-request.json)。模板故意不完整，固定字符串只描述实现支持的策略，不替代真实确认：

| 字段 | 需明确的内容 |
|---|---|
| source_result | 实际完成清单的路径和小写 SHA256 |
| selection | 非空唯一列表，每项 {algorithm, beam_id}；算法为 cbf/mvdr，波束须实际保存 |
| sample_policy | preserve_full_output_and_mask：完整时间轴和原掩码 |
| units_policy | preserve_no_scaling：无幅值变换 |
| limitations_acknowledgement | 用户对上游频带、边界及未知同步/标定等限制的接受记录 |
| output | 新目录、正整数 block_samples、max_working_bytes、max_artifact_bytes |
| approval | status=confirmed、scope_sha256、evidence、confirmation={method:user,reference} |

```bash
python3 <line-skill-dir>/scripts/beamformed_input.py digest <request.json>
python3 <line-skill-dir>/scripts/beamformed_input.py check <request.json>
python3 <line-skill-dir>/scripts/beamformed_input.py prepare <request.json>
python3 <line-skill-dir>/scripts/beamformed_input.py receive <handoff.json> --sha256 <交接时记录的摘要>
```

digest 只计算除 approval 外的规范 JSON 摘要，不生成授权。用户在明确范围上确认后才填写 approval；修改来源、选束、范围或预算需重新核对确认。check 验证配置、来源 JSON、文件尺寸和估算，不读波形；can_attempt_preparation 不代表内容已通过。prepare 才核对消费文件的内容摘要、NPY 类型/形状、所选波形有限值、有效掩码与区间的一致性，分块复制并再次核对来源。无需原始阵列文件仍在本机，不重复索要无关阵元参数。

资源估算是受管数组和元数据的保守估算，不是操作系统峰值/硬配额。磁盘不足、预算超限、来源改变或波形异常则停止，不自动减波束、缩短数据或覆盖输出。失败目录保留 failure.json 及部分文件，但不发布 handoff.json；这些文件不能作为完成交接。

## 产物与追溯

全新目录包含：

- signal_000000.npy 等：按 selection 顺序，一算法一波束一文件，float64 [N,1]；不是把多个算法混成多阵元。
- valid_sample_mask.npy：bool [N]，所有信号共用上游掩码，完整时间轴不变。
- source_result.json、source_config.json：上游清单和确认配置的字节副本；旧清单内的其他路径只是追溯信息，不表示那些权重、图片或原始数据也已打包。
- confirmed_handoff_request.json：交接选择、限制接受和确认记录。
- handoff-report.json：交接说明，列出信号身份、已保留字段、元数据位置、完整上游配置引用、原单位、有效性限制、上游问题及用户接受记录；不会替未知项作决定。未提供的可选来源字段单独列出，不补成“正常”或“已验证”。
- handoff.json：最后写入的完成清单、各文件摘要、来源与时间/方向映射。prepare 返回它的 SHA256，应随包保留供 receive 校验。

清单保留算法、稳定 beam_id、source_column、scan_column、方向定义/基向量、采样率、单位、幅值约定、频带及实际活动频点、处理历史、原始样本/时间/阵元来源和上游检查限制。可移植输入包不要求源路径仍可访问，但也不声称包含上游全部证据文件。

时间采用上游 first_sample_offset_seconds + i / sample_rate_hz，i 是完整输出数组索引。若有 original_source_sample_range，其起点 + i 对应原始录音样本；source_sample_range 可能只是中间导出 NPY 索引，不能混同。相对时间不伪造为 UTC。掩码只继承上游数值边界含义，不证明采集连续性、同步、标定或物理模型准确。

## 接收端与后续检测的边界

receive 验证便携包摘要、来源副本、交接确认范围、单束映射、NPY 形状/精度/有限值及掩码；同时核对新版交接说明是否与来源记录一致。返回信号身份、provenance、有效掩码路径、已核对的上游配置路径及摘要、交接清单引用。它不运行 FFT 或检测，也不改原清单。

代码调用可用 load_beam(handoff_path, expected_sha256, signal_id)，返回只读二维 waveform、valid_sample_mask、signal 身份、provenance 及 source_configuration={path,sha256}。后者指向包内完整上游配置，保留波束模型、变换设置、同步/标定记录与参数确认依据，不把这些记录当作已通过工程验证。调用者必须明确 signal_id，不能展平多束，也不能丢弃掩码。底层采用只读内存映射而非锁定快照；在后续计算期间也应保护并再次核对来源，不能把只读视图当作其他进程无法改源的保证。

现有 line_spectrum_methods.py 的 welch-detect 是通用数组入口，不识别完整交接元数据及掩码；**不能直接把此包的 NPY 传给旧命令并称为完整联调**。本轮阻止其 NPY 多列静默展平，保留其原单列用法，但没有将旧命令升级为完整的受控检测执行器。

本模块职责到数据和信息传递为止。检测方法、检测窗参数、阈值、后续有效帧处理、检测计算与结果解释，由下游在另一个明确任务中负责；本交接任务不开发或调用它们。

实现 v0.1.1 不再生成 detection-draft.json 和检测参数 questions.json。契约仍为0.1，旧交接包可按原字段接收；旧草稿原样保留且不读取执行，也不删除历史文件。新包用 purpose=waveform_and_metadata_transfer_only 明示用途；handoff-report.json 受产物摘要和来源一致性核对约束。

上游波束 result.json 中 handoff_status=blocked / downstream_integration=not_integrated 是生成时的历史状态，不被交接器改写。新包 handoff_status=prepared 只表示输入已准备；receive 的 input_status=accepted 仅表示结构和内容检查通过，can_detect 始终 false、detection_status=not_run。检测参数确认、数值运行、结果质量及工程验收必须分别报告。


## 单阵元 / 外部已有波束的旁路接收（实现 v0.1.2）

这是另一种显式包格式，不扩张原 receive/load_beam 的主结果契约。先完整阅读同级 underwater-beamforming 的 references/bypass-handoff.md；输入需经读取检查适配器导出并明确角色，再用 scripts/bypass_handoff.py 生成 bypass_version=0.1 包。裸数组、角色不明或原始多阵元不能靠本入口自动解释。

```bash
python3 <line-skill-dir>/scripts/beamformed_input.py receive-bypass <bypass-handoff.json> --sha256 <记录的清单摘要>
```

代码入口 load_bypass_signal(path, sha256, signal_id) 返回只读 [N,1] waveform、signal/data_role、provenance、包内已确认旁路配置的 source_configuration，以及 valid_sample_mask（可为 None）。明确选择 signal_id，不展平多列。方向/算法未知可经真实确认保持 unknown；单阵元是 not_applicable，不伪装成某种波束。

receive-bypass 调用固定同级 Skill 的旁路校验器，不从交接包内加载代码。只有旁路接收需要此依赖；普通主结果交接的依赖保持不变。缺少适配器或同名模块来自其他位置即停止，不自动下载安装。接收后不需要源机器原始录音路径仍存在。

未知有效性保持 null，禁止生成全 true 掩码；未知频带不填全频带。只读传输可以在用户明确接受未知项后进行，但不能据 accepted 在未知条件下开始参数相关计算。采样率、真实身份、样本/列映射、单位状态与时间参考仍必须有明确记录。

主结果包保留完整波束执行配置；旁路包保留完整旁路请求与上游读取/导出证据。旁路没有在本模块执行 CBF/MVDR，因此不能伪造它不存在的权重或阵列配置。本次不选择检测方法、窗长、阈值，不调用任何检测命令。新增旁路已通过合成导出/接收、未知字段保留和命令行回归；未开展外部实测波束来源的物理验收。
