# 计算前检查器：历史 v0.2 与新 v0.4

v0.4 使用相同物理参数组与确认机制，但 output 改为显式选择时域保存方向。新版差异见 [结果输出 v0.4](output-products.md)，下文固定 save_time_domain=true/all_requested 仅描述历史 0.2 配置。0.2 可检查但不能由新版执行器直接执行，必须询问保留方向后形成新版配置。

本页仅定义 preflight.py 的 v0.2 清单 CLI。它不读取波形、不加载 NumPy/SciPy、不生成导向矢量、协方差、波束或频谱。Skill v0.3 另有 [独立数值执行入口](numerical-execution.md)，包装本页 plan 并要求额外确认；不能把旧报告当数值执行令牌。

## 命令与退出码

Python 3.10+，仅依赖标准库。命令中的路径需替换成实际绝对路径：

```bash
python3 <skill-dir>/scripts/preflight.py check <plan.json> --out <new-preflight-report-dir>
python3 <skill-dir>/scripts/preflight.py digests <plan.json>
python3 -B -m unittest discover -s <skill-dir>/tests -v
```

- `check` 向标准输出返回 JSON；提供 `--out` 时仅创建 `preflight.json` 和 `report.md`。
- 输出报告目录必须全新，且不能占用未来算法结果目录或其子目录。不修改配置或源文件。
- `digests` 只返回配置摘要，不确认参数，不运行门禁或算法，不生成确认记录。
- 退出码 0：本检查器覆盖的配置与确认记录检查通过；2：需要补充/确认；1：无效、冲突、不支持或 I/O 错误。
- 退出码 0 不代表可以运行算法，也不代表数据质量合格。`can_execute` 始终为 false，`execution_status` 始终为 `not_run`。不存在 `run` 子命令。

配置最多 2 MiB；严格拒绝重复 JSON 键、非标准 NaN/Infinity、未知字段和拼写错误。数值字段不接受布尔值，不将 null 视为默认值。相对源路径和未来输出路径相对于配置文件目录解析；`--out` 相对于调用时工作目录解析。

## 检查边界

本版读取清单并只读 stat 源文件，对比大小/mtime_ns，不读取或散列波形内容。`shape`、`dtype`、通道身份和时间参考仍是外部提供的声明；需上游证据支撑。文件真实编码/内容、同步、标定、声速真实性、窗函数可逆性、数值稳定性及实际磁盘空间/权限不在已验证范围内。

确认记录的内容及摘要一致性可检查，但工具不能鉴别人类是否真的作出该确认，也不能验证来源文档的真实性。智能体仍必须遵守 [参数确认规则](parameter-policy.md)，不能伪造记录让检查“通过”。

本版具体可检查的算法配置轮廓是实数时域输入、平面波模型和 STFT 配置。只声明这些配置可检查，不代表它们是来源事实。时域延时实现、复数基带、近场传播、外部训练文件和开放式自动调参暂未纳入机器校验；用户明确要求不支持能力时合并询问是否接受受支持的近似方案，一般探索任务可按自主基线选择已实现模型并标明限制。

## 顶层结构与分流

历史 `schema_version` 为字符串 `0.2`；当前执行所需 plan 为 `0.4`，其输出新增显式列表。原始阵列分支要求：

```text
schema_version
input
algorithms
geometry
propagation
synchronization
calibration
direction_plan
processing
transform
cbf                 仅选择 CBF 时必需
mvdr                仅选择 MVDR 时必需
output
parameter_records
```

单阵元或已有波束旁路仅要求 `schema_version`、`input`、`handoff`、`parameter_records`，不要求阵列几何和算法参数；混入阵列配置会报冲突，不会静默忽略。

各组字段除明确标注“条件字段”外均必需。空数组只在明确允许处表示“没有该处理/产物”；不是未知。建议分支明确后再整理该分支配置，不将测试夹具当实测模板。

## input

| 字段 | 类型与内容 |
|---|---|
| `source` | `{path, field, size_bytes, mtime_ns}`；path/field 为非空字符串；大小/时间为非负整数；path 必须指向已有普通文件 |
| `representation` | `time_waveform_real` |
| `data_role` | `sensor_array` / `single_sensor` / `beamformed` / `unknown`；unknown 必须询问 |
| `axes` | 必须为 `["sample", "channel"]`，指已建立的访问视图，不会修改源文件轴 |
| `shape` | 两个正整数 `[源视图样本总数, 源视图通道总数]`；不把请求片段长度当源总长度 |
| `dtype` | int8/uint8/int16/uint16/int32/uint32/int64/uint64/float32/float64 之一；不支持复数 |
| `sample_rate_hz` | 有限正数 |
| `sample_range` | 本次请求的零基半开样本区间 `[start, stop]`；非空、不越界 |
| `channels` | 完整输入视图的唯一通道 ID 列表，顺序对应列；数量与 shape 一致 |
| `units` | 非空字符串；未知写 `unknown`，自主限制为原始单位相对分析，不输出校准声级 |
| `time_reference` | `{kind: relative或utc, origin: 非空说明}`；本版检查声明存在，不解析和验证时间戳真实性 |
| `processing_history` | 非空说明字符串的数组；有来源证明无处理才可 `[]`；未知写 `["unknown"]`，自主限制为不宣称原始未处理 |

单阵元要求一列；原始阵列要求至少两列。已有多波束可有多列，但仍分流至 `beamformed_handoff`。输入身份及记录未获确认时，正式 route 为 `unresolved`；检查器可以根据声明列出该候选分支还缺什么，但不运行它。

## 原始阵列的公共组

| 组 | 字段 |
|---|---|
| `algorithms` | 唯一非空数组，成员仅 `cbf`、`mvdr`；不能配置未选择算法的参数组 |
| `geometry` | `channel_ids`、`coordinates_m`、`coordinate_system`、`reference_m`、`model_kind`、`model_description` |
| `propagation` | `model=plane_wave`、正数 `sound_speed_m_s`、非空 `source_or_rationale` |
| `synchronization` | `status=verified/assumed/unknown`、非空 `details`；unknown 阻断 |
| `calibration` | `status=calibrated/uncalibrated/assumed/unknown`、`handling=applied_upstream/none`、`details`；unknown 阻断；applied_upstream 要求 calibrated |
| `processing` | 选定 ID 顺序 `channels`、`band_hz=[lo,hi]`、`preprocessing`、`precision=float32/float64` |

几何坐标每行三个有限数，行顺序与选定通道完全对应；ID 与坐标都不允许重复。`coordinate_system` 包含非空的 `name/origin/x_positive/y_positive/z_positive` 和 `handedness=right/left`。`reference_m` 为三元向量；`model_kind=measured/nominal`。名义模型通过确认后可用于后续实验，但不能写成实测模型。

选定通道必须保持源顺序，不能自动重排。`preprocessing` 当前接受 `demean`、`linear_detrend` 的唯一列表，明确不做则为 `[]`；本检查器并不执行这些处理。频带须满足 `0 ≤ lo < hi ≤ fs/2`。

本页枚举不是默认选项；缺失值会被报告。

## direction_plan

公共字段：`mode=specified/grid`、`parameterization=array_angle/azimuth_elevation`、`angle_unit=deg`、`coordinate_frame`、`zero_direction`、`positive_direction`。后三者为非空字符串；coordinate_frame 必须等于几何 coordinate_system.name，本版不自动变换坐标。

- `specified` 条件字段 `directions_deg`：方向二维列表；array_angle 每行一个角度，azimuth_elevation 每行两个角度，顺序为方位、俯仰。不同时接受 grid_axes/grid_order。
- `grid` 条件字段 `grid_axes`、`grid_order=first_axis_slowest`；单轴或双轴与参数化一致。双轴按方位、俯仰排列。不同时接受 directions_deg。
- 每个网格轴有 `start_deg`、`stop_deg`、正数 `step_deg`、布尔 `include_stop`。升序非空；包含终点时，终点必须准确落在网格上。使用十进制数值关系检查，不静默舍入。
- 俯仰范围限定 [-90,90]。指定方向拒绝重复和按 360 度周期重复的方位；方位网格不接受覆盖重复周期的定义。
- 本版只估计波束数，不展开巨大网格数组，不生成波束或选择目标。

## transform

所有字段均需确认：

| 字段 | 本版可检查的值 |
|---|---|
| `domain` | `stft` |
| `window` / `window_periodic` | hann/hamming/boxcar；布尔值 |
| `window_samples` / `hop_samples` / `nfft` | 正整数；nfft 不小于窗长，步长不超过窗长；窗长不超过请求数据长度 |
| `boundary` | zeros/reflect/no_padding |
| `synthesis` | dual_window/overlap_add；本版不证明可逆性 |
| `normalization` | amplitude_preserving |
| `out_of_band` | zero/full_band；full_band 要求 band_hz 为 [0,fs/2] |
| `time_alignment` | reference_position |

设置这些字符串不证明变换、边界或尺度正确。v0.3 对其支持子集实现了数值检查和合成测试，具体限制仍须查阅数值执行接口；不能把本页的接受范围等同于全部已可执行。

## cbf 与 mvdr

CBF 字段：`element_weights` 为对应选定阵元的有限实数列表，数量匹配且和有限非零；`normalization=unit_response`。不自动生成均匀权重。

MVDR 字段：

| 字段 | 内容 |
|---|---|
| `training` | `mode=processing_range` 时使用已明确的 input.sample_range，不再提供区间；`mode=specified_range` 时另给 `sample_range`，须在同一源视图范围内 |
| `covariance_window_frames` | 协方差估计窗口帧数，正整数；本版仅按没有边界填充的完整帧检查总训练长度是否足够 |
| `update_interval_frames` | 正整数 |
| `center_snapshots` | 布尔值 |
| `diagonal_loading` | `{mode, value}`；none 必须 value=0；absolute/trace_relative 必须为有限正值 |
| `min_snapshots` | 正整数，不大于 covariance_window_frames |
| `max_condition_number` | 有限数，必须大于 1；并非通用可靠性标准，也不代表本次已计算条件数 |
| `failure_policy` | stop/mark_invalid；不会在此阶段执行任何回退策略 |
| `normalization` | unit_response |

本预检查轮廓中，每个 STFT 帧作为一个频点协方差的样本，min_snapshots 是帧数下限，不是独立快拍保证。本配置轮廓约定 trace_relative 表示加载量为 value × trace(R) / 阵元数，absolute 表示加载量直接为 value；R 使用各频点当前窗口内指定是否中心化的数据，按窗口内实际快拍数平均外积。unit_response 要求对所选导向向量满足单位响应。它们是明确的实现约定而非默认数值；计算正确性和逐块数值行为仍需在算法实现阶段审查和测试，本版不据配置完整性证明这些公式已得到正确实现。任意自定义自适应规则不可由字符串绕过校验，需后续扩展明确的规则解析器。

## output 与 handoff

原始阵列 `output` 必需字段：

- `directory`：未来算法结果的新目录，本检查器不创建它。
- `format=npy`、`save_time_domain=true`、`beam_selection=all_requested`。
- `auxiliary_products`：唯一列表，可选 psd/time_frequency/spatial_spectrum/frequency_angle/btr；明确无辅助结果为 `[]`。
- `weights=save_all/reproducible_recipe`：后续权重保存或复现策略。
- `max_waveform_bytes`：用户确认的正整数数组净数据量预算；按请求样本数×波束数×算法数×每元素字节数估算。估计不含文件头、权重、辅助产物、内存和临时空间；不等同于磁盘容量验证。

旁路 `handoff` 必需字段为选定 ID 列表 `selected_channels` 和 `unknown_direction_policy=allow_anonymous/require_known`。已有波束且 require_known 时，还需与选定 ID 一一对应的 `beam_directions` 非空说明列表。这里检查说明存在，不证明方向元数据准确。

本旧 plan 预检查的旁路通过只报告 `handoff_manifest_ready=true`，实际文件未在此验证，故报告中 `handoff_status=blocked`。实际数据交接另用 [bypass_handoff.py 的独立请求与门禁](bypass-handoff.md)，不把旧 plan 检查报告当授权；两者都不执行检测。

## parameter_records：将确认绑定到配置

确认以配置组为单位。每条记录字段如下：

```text
key                  组名，例如 input 或 direction_plan
kind                 fact / model_assumption / processing_choice
status               unknown / proposed / confirmed / conflict / not_applicable
value_sha256         当前配置组的规范 JSON 摘要
scope_sha256         整个配置（不含 parameter_records）的规范 JSON 摘要
evidence             非空证据说明
confirmation.method  user / source
confirmation.reference  非空的当前请求、项目级自主授权或来源引用
```

只有 confirmed 可满足必需组。重复记录、冲突记录、不匹配的摘要或缺失记录都不能通过。`source` 方法仅允许 input 事实组，且不能用来允许 unknown 单位或 unknown 处理历史。模型和处理选择可引用当前用户任务与项目级 `harness-autonomy-v1` 授权，evidence 必须同时记录实际推导、基线或限制；不能写成用户逐项提供数值。

摘要算法为 UTF-8 JSON（键排序、无多余空白、不转义中文、禁止 NaN/Inf）取 SHA-256。`digests` 会提供摘要。来源事实须有真实来源；可逆处理选择可在项目级授权下由智能体确定并补记录。严禁因拿到摘要就把未知事实标成 confirmed。

本版保守地绑定整个计划：任何配置组变化都会使旧 scope_sha256 失效，需要重新核对确认。这不是密码学签名，也不是身份验证。源文件的实际大小/修改时间变化即使配置摘要没变也会单独阻断；相同大小/mtime 不保证内容相同。

## 报告与测试

报告分开记录 preflight_status、parameter_status、route、实现状态、未运行状态、问题、摘要、确认组、源文件 stat 对比、估计波束数与净数据量。实际数值覆盖为零，artifacts 不列出任何波束产物。questions 是 needs_input 项；invalid/unsupported 问题仍应查看完整 issues。

`passed` 不是对证据真实性、信号质量或未来算法可运行性的担保。不得将本报告当执行令牌；`require_executable` 在本版对任何报告都拒绝运行。

测试使用隔离临时目录和明确标记的合成清单，包含故意不是波形的元数据夹具，以验证检查器没有偷偷读取样本。测试中的参数和模拟确认不能复制为实测授权。测试命令以实际运行结果为准，不以文档列举代替测试。
