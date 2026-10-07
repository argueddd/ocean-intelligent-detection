# 交接包 → 统一输入适配（input_adapter 0.1.0）

本入口只提取和核对来源信息，不运行线谱检测，不要求先选择检测方法。先读 [统一输入](framework-input.md) 与 [旧交接规范](beamformed-input.md)；旁路另读同级波束 Skill 的 references/bypass-handoff.md。

## 输入与边界

支持明确指定的两类完整数据交接包：

- beamformed_handoff：主交接 handoff_version=0.1，由既有 receive 验证；不是主 result.json 或补图包。
- bypass_handoff：bypass_version=0.1，由既有 receive-bypass 验证，保留 single_sensor / beamformed 身份。

必须给出清单位置、已记录的 SHA256、包种类、一个明确的 signal_id，以及读取限制。不默认第一条、全部或最强波束。多条信号需分别适配，身份为清单 SHA256 + signal_id。只有谱或裸波形时回上游明确来源，不能在此猜身份。

使用既有接收器的独立进程，避免两个 Skill 同名 preflight 模块互相覆盖；只调用固定安装位置的代码，不加载交接包提供的代码。主路径需 NumPy、jsonschema/referencing；旁路还需同级 underwater-beamforming，缺失报告，不自动安装。此 POSIX 文件后端在 macOS 验证，不宣称 Windows 支持。

接收器验证整个包的产物摘要、来源副本、配置关联、波形形状/类型/有限值及已知掩码与区间的一致性，然后仅映射明确选择的信号。它不会重算 CBF/MVDR，不保证物理方向、同步、标定或实验说明真实，也不证明交接波形确实等于尚未打包的原始波束数组。

## 命令

以下是参数语法，所有尖括号内容需替换，不提供实测默认值：

~~~text
python3 <line-skill>/scripts/input_adapter.py adapt \
  --handoff <packet/handoff.json> --sha256 <pinned-sha256> \
  --kind <beamformed_handoff-or-bypass_handoff> --signal-id <explicit-signal-id> \
  --max-package-bytes <positive-integer> --max-block-samples <positive-integer> \
  [--out <new-SignalInput.json>]

python3 <line-skill>/scripts/input_adapter.py check <SignalInput.json> \
  --handoff <packet/handoff.json> \
  --max-package-bytes <positive-integer> --max-block-samples <positive-integer>
~~~

adapt 不给 --out 时只返回标准输出；给出时仅在包目录之外独占新建一份 SignalInput JSON，不创建父目录、不覆盖旧文件、不复制波形。完整核对报告仍在标准输出，是否另存由用户决定。check 始终只读，从输入文档取得绑定的包摘要、种类和 signal_id，重新验证来源并逐字段比较；不是只检查 JSON 格式。

返回 adapter_status=verified/mismatch/blocked；始终 can_execute=false、detection_status=not_run、authority_verified=false。退出码分别为 0/1/2。verified 是本适配范围一致，不是检测就绪、用户身份认证或工程验收。unknown_items 逐项说明未知信息和需询问的问题；其存在不阻止仅传递未知状态，后续依赖它的计算另作决定。

max_package_bytes 限制清单与全部登记产物的唯一文件字节总量；不是累计磁盘读取量或操作系统内存硬配额。max_block_samples 限制旧请求中接收器实际使用的分块长度，超限报错，不改写旧请求。JSON 解析上限32 MiB、接收器进程超时60秒是实现防护，不是声学参数。超时报告，不自动重试或扩大限制。

## 字段映射与保留策略

| SignalInput 字段 | 来源与规则 |
|---|---|
| source_package / signal_id | 原清单摘要、显式包种类、上游契约版本与原 signal_id；不重新编号 |
| data_role / waveform | 原角色与选定文件；float64 [N,1] 已由接收器核对；轴名改为公共语义 sample/signal，不变换数组 |
| sample_rate_hz | 原 provenance.sample_rate_hz，无默认值 |
| time_mapping | 原时间偏移；time_reference 以排序键紧凑 JSON 字符串无损保存原对象；source_sample_zero 仅从显式 original_source_sample_range 提取，缺失为 null，不用中间 source_sample_range 冒充 |
| validity | 主包继承原区间、掩码和 validity_limit；旁路保留 known/unknown 及原依据，未知掩码保持 null |
| units | 原 unknown → unknown/null，其他原单位照抄；幅值约定保留，不换算、不伪造声压单位 |
| frequency_coverage | 主包保留 requested_band_hz；active_frequency_ref 指向清单本身，精确活动频点位于 /provenance/frequency_coverage/actual_bin_centers_hz；不能把请求带宽当成理想连续通带。旁路保留原状态/频带，不伪造离散频点 |
| processing_history | upstream/this_run 分段逐条保存为带序号的规范 JSON 字符串；重复步骤不去重；完整来源配置另有摘要引用 |
| beam_source | 主包保留算法、beam_id、固定方向、坐标约定、保存列和扫描列、source_result 副本；完整方向基保留在原清单/结果引用中 |
| 旁路 beam_source | 单阵元 not_applicable；已有波束算法/方向按源状态继承，channel_id 不冒充 beam_id，缺失的 beam_id/scan_column/source_result 不编造；原通道身份与 original_source_channel_index 保留在完整清单引用中 |
| limitations / provenance | 原限制、验证状态、上游检查等原对象以带来源字段名的 JSON 保留；引用完整清单及包内 JSON 证据；不会读取原机器路径或声称外部原始文件已具备 |

所有 package_relative 引用都相对明确指定的交接包根目录，**不是**相对另存的 SignalInput 文件位置。移动完整包且保持文件名/内容不变不改变身份。预检仍通过上下文的 SHA256→显式路径绑定定位，不按文件名遍历查找。

check 对整个统一文档作确定性重建比较，包括 unknown 状态、证据引用、数组顺序、限制和信封。它检查本适配器的规范映射，不接受手工更改来源值或删除限制来“通过”；如需补充新的证据，应单独保留并明确扩展规范，不悄悄改源。

document_status=specified 表示结构完整，unresolved_items=[] 不意味着现实未知项已解决。unknown_items 在报告列出，未知状态和限制也保留在 SignalInput；后续预检按被选算法依赖要求处理。不能把仅传输未知的旧确认升级为未知条件下的计算授权。

## 接入预检

preflight 0.1.1 在 PreflightContext 0.1.0 中新增可选对象：

~~~text
"handoff_validation": {
  "max_package_bytes": <explicit-per-packet-limit>,
  "max_block_samples": <explicit-receiver-block-limit>
}
~~~

这是明确启用全包验证的选择，限额纳入方案摘要。缺省不调用适配器、不扩大读取范围，仍保留 upstream_adapter_semantics_not_verified。显式启用后要求完整交接包与清单绑定，来源差异报告为阻断问题；所有选中输入都验证成功才移除该阻断项。字段从未自动修复。

max_source_bytes 仍只约束原显式绑定来源读取；上述额外限额按包计算。接收器会读取包清单登记的全部产物，即使只选择一个 signal_id，也会验证包中其他已交接信号。根目录限定、预算和这个额外读取范围必须讲明；不自动读取包外原始路径。方案摘要纳入适配结果及适配版本，旧预检确认不可直接沿用。运行前仍应重新验证，检查不是文件锁或不可变快照。

即便适配通过，本适配器 can_execute 仍不变成 true。[runtime v1](runtime-v1.md) 另行核对算法、完整有效帧、参数/模型决定、资源、执行确认与结果。

## 验证范围

[适配测试](../tests/test_input_adapter.py) 用隔离临时目录中的合成 CBF/MVDR 主交接、单阵元旁路、已知/未知外部波束旁路覆盖实际接收器路径。固定合成参数及 MOCK 确认只用于测试，不是实测默认值或真实用户授权。测试依赖同级波束与读取检查 Skill 的测试/导出辅助程序。

验证显式选择与列重排、原始时间映射、未知状态、字段篡改、波形/掩码异常、来源变化、路径限制、预算限制、整包搬移、只读、不覆盖和预检接入。本组适配测试没有运行 S59 或检测；新增运行测试另见运行入口，同样不验证真实物理定位或海试检测效果。
