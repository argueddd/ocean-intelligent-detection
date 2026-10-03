# 数据契约 v0.2

## 运行配置

JSON 根对象只允许下列键；拼写错误/未知键报错。

| 字段 | 约定 |
|---|---|
| mode | read/check/analyze，默认 check |
| field | MAT/NPZ/HDF5 必填，从 probe 原样选择；NPY/WAV/SIO 为 data |
| sample_axis | 非 WAV/SIO 必填，0 或 1；一维只能 0；WAV/SIO 按格式固定为 0 |
| sample_rate_hz | 用户或可信文档确认的有限正数，可缺失；来源需随配置记录 |
| sample_rate_field | 明确指定 MAT/NPZ/HDF5 中单位为 Hz 的标量字段，不自动发现 |
| sample_rate_resolution | 可选 {"use":"user"或"file","reason":"用户明确解释"}；只用于冲突 |
| units | 已确认的原始样本单位；未知时省略此键，不填 unknown/null，不换算 |
| channel_ids | 原始通道轴顺序的完整唯一字符串列表，可缺失 |
| array_geometry_m | 原始通道顺序的 [channels,3] 有限米制坐标，填写代表确认映射 |
| start_sample, stop_sample | 零基半开区间，默认整个存储范围，越界报错 |
| channels | 原始通道位置，唯一升序零基列表；默认全部，不重排 |
| max_read_mib | 解码/工作预算，默认 512；传统 MAT 按所有变量估算，NPZ 按成员估算 |
| block_samples | 每块样本上限，默认 65536，仍受内存预算限制 |
| analysis_max_samples | 分析请求起点后最多多少样本，默认 262144 |
| analysis_max_channels | 分析请求列表前几路，默认 4，最多 16 |
| nperseg | 至少 8，不超过分析样本数；默认 min(4096,样本数) |
| overlap_fraction | 默认 0.5，范围 [0,1) |
| band_hz | 可选 [lo,hi]，0 ≤ lo < hi ≤ fs/2；只截取结果，不滤波 |

缺 fs 不阻断 read/check；analyze 返回已完成检查及待补充信息。冲突未解决不生成 Hz/秒坐标。

用户已明确确认的值以当前指令为来源，直接写最小配置，不另查外部来源或复制历史配置。合法示例见 [Skill 执行入口](../SKILL.md)。字段从 probe 原样选择，轴需用户确认或格式规定；未知的 fs/units/channel_ids/array_geometry_m 省略，不用示例值、unknown 字符串或 null 代替事实。

时间区间由已确认 fs 推导成整数样本索引，记录实际半开范围。网格间距 Δf 对应 nperseg=fs/Δf；不能表示为合法整数窗长或范围太短时明确说明限制。start/stop/channels 定义请求，analysis_max_samples/analysis_max_channels 定义计算预算；预算未覆盖请求时报告实际部分覆盖，不悄悄扩大或改写用户范围。

## 输出

每次新建结果目录，拒绝覆盖；源文件只读。result.json 记录完成/阻断/错误，无法计算用 null，不写 NaN/Inf。

- schema_version: 0.2。
- status: completed/partial/needs_input/failed，表示执行状态，不是质量合格。
- source: 绝对路径、字节数、mtime_ns，不是内容哈希。
- probe: 格式、字段、形状、类型、估计字节数和限制。
- config: 实际配置及路径。
- dataset: 标准轴、源映射、范围、单位/fs 来源、结构转换；不默认复制完整数据。
- request: 本次是 probe 还是 run。
- selection: 已确认的字段与样本轴，仅在成功建立读取视图后出现。
- stages: status 保留基础流程调度状态；assessment_status 汇总该阶段所有清单子项，check_counts 给出各状态数量。
- checks: 21 个子项的 id、stage、title、implementation、status、reason；有证据时附 evidence，有待补充信息时附 required_input，有数值范围时附 coverage。
- coverage_summary: 子项状态计数及 all_listed_checks_complete；不是质量评分或验收通过标记。
- issues: 代码、说明、需补充信息。
- quality: 逐通道指标、覆盖和分母。
- analysis: 设置、独立覆盖、成功/跳过通道和产物。
- readiness: 各用途的条件与限制。
- not_checked: 未执行或缺少参考的项目。
- software: Python/依赖版本。

每次报告包含 feature_status.csv，与 result.json 的 checks 对应。其他产物可能有 channel_quality.csv、analysis_products.npz、波形/PSD/时频图及 report.md，以实际返回为准，不生成伪结果。

正常任务成功后以这些产物为主要证据。同一源文件指纹（路径/大小/mtime）、配置和范围未变化、results_valid 未标为 false、相关子项已有执行证据时，可复用对应结果；不得把失败、失效或未运行子项当作已完成。只解释术语或已有结果时，无需再次检查源文件或运行分析，必要时只读取现有产物的相关项。源变化、用户新增范围或配置改变只使受影响结果需要重算；未变化的大小/mtime 不构成内容哈希保证。

面向用户的摘要按结论、关键指标、覆盖限制和必要下一步组织，不逐项复制机器清单。dtype、字节序、头部偏移及存储填充放入机器结果或技术附录，只有影响结论或用户问到时展开。分析完整窗口之外的未用尾样本与文件存储填充分别报告，不混淆两者。

子项 implementation 为 implemented/not_implemented，status 为 completed/partial/blocked/not_implemented/not_run/not_applicable/failed/invalidated。具体含义与验收规则见 [六项清单](acceptance-checklist.md)。顶层 completed 与退出码 0 只表示本次已支持的基础流程执行结束；不能代替子项清单。

coverage 同时记录实际区间和通道、请求区间和通道、源数据总样本数和总通道数。complete_requested_range 不等于 complete_source_range。频谱覆盖只计完整窗口及实际成功通道；通道对指标列期望对数、完成对数及成功通道对。

标准视图 [samples,channels]，索引保留源位置。fs 推导的均匀轴不能证明无采集缺口。记录大小/mtime 变化，不等价于哈希。NPY/HDF5/WAV/SIO 分块；传统 MAT/压缩 NPZ 有解码预算。对象、复数、稀疏、结构化数组、嵌套 MAT struct、高维波形不支持，不静默压平、取实部或 squeeze。

PCM WAV 在读取前检查 RIFF/chunk 声明边界与帧对齐，只支持一个 fmt/data chunk；多 data chunk、不完整 PCM 帧及截断声明会明确阻断，不忽略末尾字节。
