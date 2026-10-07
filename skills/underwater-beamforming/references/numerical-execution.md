# 数值执行接口：v0.4.2（配置 v0.4，数值核沿用 v0.3.1）

先完整阅读 [结果输出与展示](output-products.md)：配置已升级为 execution_version=0.4、plan.schema_version=0.4，增加 analysis 与时域显式保留索引。本页算法公式不变，旧全方向时域策略已取消。0.4.1 允许 auxiliary_products 单选/组合，数值、图集和清单只交付所选项；已通过 v0.4.3 受限回归，见 [验证记录](acceptance-v043.md)。

实现修订 v0.3.1 保持本接口和数值语义不变。导向时延及波束加权使用显式 einsum 求和（optimize=False），规避部分 NumPy/macOS Accelerate 的错误浮点状态警告；不屏蔽警告、不升级全局依赖、不改变声速/权重/精度。4项新增兼容回归检查包含非连续数组、阵列规模、独立逐通道求和与失败报告。

## 范围与运行顺序

已实现 CBF、MVDR、STFT/WOLA 时域重建、指定方向及固定网格计算、仅指定方向 NPY 保存及输出谱/图。此版本是**受限的离线数值实现**，不是 SWellEx-96 验证完成版，也不是流式工程系统。

1. 阅读数据契约、自主参数规则、预检查及输出接口；整理完整 v0.4 plan。
2. 阅读本页，先由来源事实、确定性推导和 Skill 基线解决数值规则。不能把测试参数或模板固定字符串当作数据事实。
3. 把 plan 放入 v0.4 执行包装；填入 numerics、analysis 及显式时域保留列表，并记录每项来源。项目级自主授权可用于可逆处理选择；缺失物理事实仍不得伪造。
4. 先 check，再在用户授权范围内 run。run 会重新校验，不接受外部“通过报告”作为令牌。
5. 检查完成清单、时域文件、有效区间和校验摘要；报告限制。暂不自动调用下游检测。

环境：Python 3.10+、NumPy、SciPy；谱图生成另需 Matplotlib。开发验证环境为 Python 3.12 / NumPy 2.2.6 / SciPy 1.16.1；不自动安装或升级用户依赖。标准库 preflight.py 仍可单独运行。

```bash
python3 <skill-dir>/scripts/execute.py check <execution.json>
python3 <skill-dir>/scripts/execute.py digest <execution.json>
python3 <skill-dir>/scripts/execute.py run <execution.json>
python3 -B -W error::RuntimeWarning -m unittest discover -s <skill-dir>/tests
```

check 不读取波形，也不计算导向矢量、协方差或 FFT；仅检查配置、stat、确认、几何包围盒近似上限和资源估算。can_attempt_execution=true 只表示可尝试进入 run 阶段，实际文件、数值与存储检查仍可能失败。check/run 门禁阻断退出 2，I/O/数值失败退出 1，成功退出 0。digest 只产生摘要，不授权、不自动确认。

## 已实现轮廓与显式拒绝

| 项目 | v0.3 执行范围 |
|---|---|
| 输入 | 单个二维实数 NPY，float32/float64，轴固定 [sample,channel]；source.field 必须为 __array__ |
| 计算与输出精度 | float64；源 float32 在明确配置后提升精度，源文件不改写 |
| 数据身份 | 仅 sensor_array 在此执行；single_sensor/beamformed 不进入此执行器，经读取检查导出后另用 bypass_handoff.py 交接数据，不检测 |
| 几何与传播 | 右手坐标、显式 XYZ、已确认平面波和单一声速；不推断缺失横坐标 |
| 方向 | array_angle 或 azimuth_elevation；指定列表或固定笛卡尔网格，原顺序保留 |
| 窗/合成 | Hann/Hamming/boxcar，显式周期性、步长、FFT 长度；zeros/reflect/no_padding；dual_window/overlap_add |
| 预处理 | 明确列表中的 demean、linear_detrend，按列表顺序作用于本次整段；空列表表示已明确不预处理 |
| CBF | 显式实数阵元加权，单位响应归一化 |
| MVDR | 同源 processing_range 或 specified_range 训练；明确加载及离线滑窗更新；failure_policy 只实现 stop |
| 保存 | 仅指定方向 NPY 时域；全部实际权重、配置、方向/时间/频率坐标、有效样本掩码、诊断；请求谱时仅保存所选种类的全方向矩阵、PNG 和离线图集 |
| 不支持 | SIO/MAT/HDF5/NPZ 直读、复数基带、近场、流式/分块、float32 输出、mark_invalid、仅权重复现配方、二维角度切片图、自动检测交接 |

原 v0.2 检查器接受的配置范围比本执行器宽。不支持的选择必须明确报告，不能改成支持的值或无声忽略。不要为绕过门禁临时转码、改变精度或去掉用户请求的辅助产物；这些变化先征询处理方式。

## 执行包装与确认

原有顶层五个必需键（analysis 在纯时域任务显式 null，请求任意谱产物时必须完整）；0.4.2 另支持可选 inspection_handoff={path,sha256}，来自交接适配器时必须保留，详见 [交接接口](inspection-handoff.md)：

```json
{
  "execution_version": "0.4",
  "plan": {},
  "numerics": {},
  "analysis": null,
  "approval": null
}
```

plan 使用 0.4 输出结构及原逐组 parameter_records，详情见 preflight.md 和 output-products.md。其原有确认仍需通过；包装不会替代任何旧门禁。assets/execution-request.json 是**故意不完整、不可运行**的起始模板。

numerics 所有字段必填：

| 字段 | 含义 |
|---|---|
| reader | 固定 npy_real_2d；不是自动挑选读取器 |
| compute_precision | 固定 float64；plan.processing.precision 也须已确认 float64 |
| source_sha256 | 整个 NPY 文件的真实小写 SHA256；run 计算前后核对，不能用大小/mtime 冒充 |
| direction_mapping | look_vector_cos_sin_v1，下节定义 |
| direction_basis | 三个向量 [e0,e90,eup]；显式单位、正交、右手基，使用 geometry 同一坐标系 |
| stft_profile | unscaled_rfft_wola_v1，下节定义；包括分帧原点与有限段合成 |
| edge_bins | zero 或 require_real_steering；含义见下节，不能临时取实部解决冲突 |
| covariance_schedule | 有 MVDR 为 offline_trailing_bootstrap_v1；没有 MVDR 必须为 not_applicable |
| max_delay_to_window_ratio | 用户接受的窄带近似门槛 (0,1]；包围盒对角长度 / 声速 / 窗时长不得超过它 |
| response_tolerance | 单位响应、STFT 重建及端点实值检查容差，(0,1e-4]；必须明确值 |
| coverage_tolerance | 对偶窗与有限段分母正值门槛，(0,1e-4]；必须明确值 |
| max_working_bytes | 明确工作内存估算预算；超预算阻断，不截短或减波束 |
| max_artifact_bytes | 明确全部产物估算预算，除波形还包括权重/诊断/元数据；不替代 plan 中波形净数据预算 |

资源估算是带冗余系数的受管数组估计，不是操作系统硬内存配额，不保证 BLAS/操作系统峰值或磁盘配额。run 还检查实际可用磁盘；本版没有流式回退。

approval 格式：

```json
{
  "status": "confirmed",
  "scope_sha256": "<对整个包装除 approval 外的规范 JSON 求 SHA256>",
  "evidence": "<真实确认内容与范围>",
  "confirmation": {"method": "user", "reference": "<当前任务请求，或项目级 harness-autonomy-v1 授权引用>"}
}
```

digest 输出这个 scope_sha256。plan 中的逐组记录、数值选择或文件来源发生任何变化，包装确认随之失效。摘要只验证一致性，不验证来源是否真实；必须由智能体区分用户/文件提供的事实与 Harness 自主选择。禁止拷贝 tests 中 MOCK TEST 的确认记录进行实测。一般性的“开始吧”授权采用有依据的可逆设置，但不填补缺失的采样率、几何、映射或方向坐标等物理事实。

## 数值定义

### 方向、时延与 CBF

e0 是零角方向，e90 是正90度方向，eup 是正高角方向，均为**从阵列指向声源**的单位向量。array_angle 为选定平面内的角度，不自动等同水平航向；垂直阵不能凭该值声称辨识水平绝对方位。

- array_angle：u = cos(theta)e0 + sin(theta)e90。
- azimuth_elevation：u = cos(el)[cos(az)e0 + sin(az)e90] + sin(el)eup。
- 第 m 个阵元相对参考位置的时延 tau_m = -(r_m-r_ref)·u/c。
- x_m(t) = s_ref(t-tau_m)，a_m(f) = exp(-j 2 pi f tau_m)。
- CBF：w_m(f) = g_m a_m(f) / sum(g)，Y(f) = w(f)^H X(f)。

每个计算方向均在内存重建用于所请求的谱，仅指定保留方向保存波形；固定网格按 first_axis_slowest 展开；不寻峰、不选最大能量方向、不转动指向。CBF/MVDR 分别生成文件，不混成一个结果。

这是逐频点相移的窄带分箱近似，不是精确宽带分数延时。max_delay_to_window_ratio 只能限制近似条件，不证明实际误差小于某个值。阵列歧义、混叠、失配、未知同步/标定也不会因为单位响应成立而消失。

### STFT、频带和时域重建

分析窗 w 长 L、步长 H。填充模式的帧起点为 -floor((L-1)/H)H，之后每 H 个样本一帧，直到起点小于本段 N；no_padding 仅含起点 0,H,... 且完整位于区间内的帧。zeros 在本次选择区间外补零，reflect 做反射；**不偷偷从请求区间外借真实样本**。

每帧先乘 w，再不缩放 rFFT；频点 f=k*fs/nfft。按频点中心是否落在闭区间 band_hz 选择，不插值带边，不声称理想砖墙滤波。保留复数波束系数，irFFT 后取 L 个样本并加窗重叠合成：

- overlap_add：合成窗 g=w。
- dual_window：g[n]=w[n]/sum(w[k]^2，所有 k mod H=n mod H)。
- 有限段输出逐样本除以实际参与帧的 sum(w*g)，保留幅值尺度。
- 请求范围内任一样本覆盖分母不足，直接停止；不会填洞、偷偷增重叠或裁短波形。

run 对实际输入先做一次未波束加权的分析/合成往返检查，误差阈值为 response_tolerance * max(1,max(abs(x)))。这验证变换实现，不证明波束形成物理效果。

DC 及偶数 nfft 的 Nyquist 只容许实值频域端点：
- zero：明确移除这些端点；与 full_band 冲突，在门禁阶段拒绝。
- require_real_steering：活动端点导向响应虚部须在已确认容差内；仅将该数值残差投影为实数。否则停止，不能悄悄丢弃端点虚部。
- 奇数 nfft 没有 Nyquist 端点；最后一个正频点保留正常复数处理。
- 合成器额外拒绝含任何非零端点虚部的波束系数，避免 irfft 无声舍弃。

输出保留请求的全部样本和原采样率。valid_sample_mask 是所有波束共用的保守内部掩码：去掉参与填充帧覆盖的边缘，并额外将前后 L+ceil(max(abs(tau))*fs) 样本标为无效。不剪掉它们、不改变时间轴；没有有效内部样本则停止。掩码不证明采集连续性、同步、标定或相移近似的工程精度；下游还需明确接受范围。波束/带限 STFT 边界近似也须在实测验证中检查。

### MVDR 协方差与更新

训练与处理数据来自同一源文件，使用同一通道、窗和预处理列表。训练区间与处理区间不同时，各自独立进行整段去均值/趋势处理；不能把该行为解释成全文件统一去趋势。

训练仅用**完整、未填充帧**，从训练区间首样本开始每 H 个样本一帧。每 U=update_interval_frames 个输出 STFT 帧更新一次权重，更新后对接下来的最多 U 帧保持不变，不改变方向。

offline_trailing_bootstrap_v1 定义：
1. 本次更新锚点为第一个输出帧的绝对起点 + floor(L/2)。
2. 查找结束位置不晚于锚点的训练帧数量 E。
3. 令 right=min(T,max(K,E))，left=right-K；T 为完整训练帧总数，K=covariance_window_frames。
4. 使用训练帧 [left,right)。起始阶段可能使用未来帧，是**明确离线启动，不是因果实时系统**；训练结束后重复使用末尾 K 帧。

R=mean(x x^H)，center_snapshots=true 时先减去训练快拍均值，仍除以实际快拍数 K（不是 K-1）。加载为 none/absolute/trace_relative，后者 delta=value*trace(R)/M，加载矩阵 R+delta I。保存每次每频点实际 delta、条件数和单位响应残差。

求解 (R+delta I)v=a，再 w=v/(a^H v)，不显式求逆。非正定、快拍不足、条件数超标、数值溢出或单位响应不达标均停止全部本次发布。没有伪逆、自动加大加载、丢弃坏频点或 MVDR→CBF 替代。mark_invalid 尚未实现，不能选择后假装支持。

## 结果文件与完成判定

结果目录必须全新。算法在内存完成并再次验证源文件摘要/stat 后才创建它。写盘失败可能留下部分文件和 failure.json，不能用于下游；不会自动删除以掩盖失败。

主要文件：

- cbf_time.npy、mvdr_time.npy：只在有明确保留方向时为选择的算法生成，float64 [sample,retained_beam]；空列表不生成该文件。
- result.json：最后以同目录重命名发布的完成清单。必须存在、可解析、execution_status=completed，且引用文件摘要匹配，才视为保存完成。
- confirmed_config.json：本次完整配置与原始确认依据。
- directions_deg.npy、look_vectors.npy、frequencies_hz.npy、active_frequency_mask.npy、frame_start_sample.npy、valid_sample_mask.npy。
- cbf_weights.npy：[frequency,channel,beam]；非活动频点为 0，不能拿它们做单位响应判断。
- mvdr_weights.npy：[update,frequency,channel,beam]；mvdr_update_frame.npy 给输出帧更新索引。
- mvdr_training_frame_ranges.npy：[update,2]，训练帧索引半开范围；mvdr_training_frame_start_sample.npy 映射源绝对样本。
- mvdr_condition.npy、mvdr_loading.npy、mvdr_response_error.npy：[update,frequency]；非活动频点的 0 表示未计算。
- run_started.json：写入开始事件，不是成功标志；result.pending.json 若遗留也不是完成标志。

新增 scan_beams 是完整计算方向；beams 仅为已保存的时域列并记录 scan_column，未保存时 shape_per_algorithm=null。result.json 保留算法、稳定 beam_id/列、方向、源范围、样本时间映射、参考位置、实际频点、单位/幅值约定、有效区间、预处理、数值诊断、软件版本及实现文件摘要。源单位 unknown 就保留 unknown，不转成 Pa，不做逐波束峰值归一化。

通过交接导入时，执行器额外保留 upstream_inspection、原始样本/通道映射及 time_mapping。source_sample_range/帧起点仍是导出 NPY 索引；first_sample_offset_seconds 和谱时间包含原始导出起点。来源不匹配或证据变化会阻断；不改变波束数值核。

parameter_status=complete、execution_status=completed 与工程验收分别记录。handoff_status=blocked、downstream_integration=not_integrated 是主计算完成时的状态，不表示检测执行。独立交接/接收另发状态；v0.4.3 已验证数据链路，不含线谱检测。

## 验证证据与边界

自动测试覆盖：旧版配置/分流门禁；多种窗/填充/合成/非整数窗步长/奇数 FFT；端点、脉冲与幅值往返；不可逆情况拒绝；独立解析相位真值；合成平面波 CBF 时域输出；合成强干扰 MVDR 权重及单位响应；离线更新；两个算法端到端文件、配置与源摘要；未确认项阻断；不覆盖；数值失败与写入失败不发布完成结果。最新实际数量及环境见 SKILL.md。

所有模拟确认只存在于隔离测试。另已完成 S59 VLA 首60秒名义模型流程验证，详情见 [受限实测记录](real-data-validation.md)；没有宣称真实定位精度、SINR 增益、自动连续性/同步/标定判断或完整下游联调。通用执行器 result.real_data_validation 不替代独立实测验证报告。

实现公式核对参考（不授权使用其默认参数）：
- [SciPy ShortTimeFFT](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.ShortTimeFFT.html)：复数 STFT、对偶窗和逆变换。
- [SciPy check_NOLA](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.check_NOLA.html)：重叠分母非零的重建条件。
- [MathWorks MVDRBeamformer](https://www.mathworks.com/help/phased/ref/phased.mvdrbeamformer-system-object.html)：MVDR、训练数据和对角加载。
- [ARLpy beamforming](https://arlpy.readthedocs.io/en/latest/bf.html)：频域导向、复数输出与宽带分箱的区别。
