# 来源、参数与确认状态预检（preflight 0.1.1）

本层连接既有 SignalInput、AlgorithmDescriptor、DetectionRequest 文档，做只读预检、问题汇总和独立确认记录。它不选择算法、不接入旧检测命令、不计算谱或候选，也不执行波束补算。所有返回值均为 can_execute=false、检测未运行。

先遵守 [请求规范](framework-request.md) 与 [输入规范](framework-input.md)。仅做旧波束交接时仍使用 beamformed_input.py；不要为“只传输数据”提前索要检测方法或参数。本层只有用户明确推进检测方案准备/核对时才使用。

## 现在实际能做什么

- 用包摘要 + signal_id 精确匹配输入，用 detector_id + 版本 + 实现摘要精确匹配算法说明；不猜第一条、不按同名/最近方向/最新版替代。
- 将实际参数套入算法自带的 JSON Schema，检查类型、必填/条件必填、范围和互斥等已编码规则；检查参数出处覆盖，不补 default、不强制转型。
- 检查请求范围与声明的样本数、时钟、Nyquist、已知处理频带，检查已知有效区间是否与请求完全无交集；不自动截短或取交集。
- 核对已声明的处理步骤顺序与参数引用；核对计算/查看/保存的产物声明、显式依赖和循环依赖。看图所需新计算不能自动加入。
- 基础检查只读取显式文件绑定：流式核对 SHA256、普通文件属性、字节预算；核对波形 NPY 的 float64 [N,1]、掩码 NPY 的 bool [N] 及文件长度。不执行 pickle 或计算信号特征。
- 可显式启用 [交接适配核对](input-adapter.md)：调用既有接收器验证完整包、波形有限值和已知掩码，再与 SignalInput 逐字段比较；不检测、不静默修正。未启用不读取整包、不声称此项已核对。
- 按字段、任务、原因、问题和阻断状态汇总问题；同一位置的多个缺参问题不会丢失。plan_summary 展示实际请求、参数、输出选择与继承的来源限制，不能只给用户一个摘要要求同意。
- 生成版本化方案摘要；另存用户表述记录。以后重新预检，来源、文档、范围、参数、输出或预算变化会使旧绑定失效。

文件摘要一致说明“与给定摘要的字节相同”，不证明摘要来自真实可信实验。NPY 头检查不证明数值有限、掩码与区间一致、采样率正确或物理方向准确。input_adapter 0.1.0 已实现交接包自动适配及字段来源一致性验证；只有显式启用且成功才在报告中标为已核对。它不能证明来源声明的物理真实性。

## 指定读取范围

使用 [PreflightContext 草稿](../assets/templates/PreflightContext.draft.json)，其格式由 [PreflightContext Schema](../assets/schemas/PreflightContext.schema.json) 规定。这是工具配置，不是替代五类公共对象的新检测请求。

| 字段 | 含义 |
|---|---|
| context_version / document_status | 0.1.0；draft 保留待定项，specified 才可完整预检 |
| inputs | 明确选定的 SignalInput JSON 相对路径列表 |
| descriptors | 明确提供的 AlgorithmDescriptor JSON 相对路径列表 |
| source_files | 每项为 sha256 + path；显式绑定给定摘要与本地文件 |
| max_source_bytes | 基础绑定文件核对允许读取的来源字节总量；正整数，必须明确，不复用旧实验预算 |
| handoff_validation | 可选；显式开启适配核对，包含 max_package_bytes 与 max_block_samples 两个正整数限额；省略则不执行全包接收检查 |

开启 handoff_validation 会额外读取清单目录内全部登记产物（包括未选信号的包内波形），按每包 max_package_bytes 和旧请求实际块长核对；不是 max_source_bytes 的隐含扩容。具体限制、缺项与命令见 [输入适配器](input-adapter.md)。适配结果及版本纳入方案摘要，旧确认需重新核对；context/receipt/evidence 的字段版本仍是0.1.0。

上述路径相对命令行明确指定的 --source-root。只读根目录应限定为此次输入/说明/来源所在范围，不能用全盘目录来扩大查找。本版采用 POSIX 文件接口（已在 macOS 验证），未实现 Windows 路径后端；不支持目录/文件符号链接、上级越界、绝对路径或自动下载，不递归搜索缺失文件。

source_files 是明确的重定位表：按摘要映射，不使用文档中原机器绝对路径自动查找。原 location 仍保留作出处；重定位不代表该文件已重新打包。重复摘要绑定要求用户明确一个位置，不自动选取。未被引用的绑定不会被读取。

清单、波形、上游配置以及已提供的 mask/活动频率/波束结果引用为所选任务必须核对的来源。provenance 中仅作追溯且缺失的外部证据记录为非阻断警告，不假称已打包或已核验；后续操作若依赖它，必须升级为该操作的必需来源。

JSON 文件上限1 MiB，NPY 头上限64 KiB，流式读取块上限64 KiB。这些是解析器防护边界，不是声学处理参数。超过限制报告，不静默截断。max_source_bytes 是读取字节预算，不是算法内存/磁盘预算；本工具不估算算法资源；runtime v1 另做保守准入。

## 命令与状态

在本 Skill 目录运行，沿用 jsonschema / referencing 依赖，不新增数值处理依赖。

~~~bash
python3 scripts/preflight.py review /absolute/path/request.json \
  --context /absolute/path/context.json \
  --source-root /absolute/path/explicit-input-root
~~~

review 只向标准输出打印 JSON，不保存文件。它会读取上下文中的明确来源以核对摘要，区别于只检查一份 JSON 的 validate_contract.py。无算法说明或未定参数时输出问题，不执行、不建议替代算法，也不因为某些独立任务完整就开始部分计算。

| 状态 | 解释 |
|---|---|
| review_status=blocked | 本层存在未解决项，不能记录本轮完整方案确认 |
| review_complete_pending_confirmation | 本层已实现的有限检查无阻断，尚未记录用户表述；不是科学适用性或可运行证明 |
| review_complete_confirmation_recorded | 找到与当前方案匹配的独立记录；仍不能执行检测 |
| confirmation_status=unverified_request_claim | 请求自行写了 confirmed，但不能据此建立真实确认 |
| recorded_current | 独立记录、用户表述摘要与当前预检方案一致，不是用户身份认证 |
| stale / invalidated_by_review_blocker / invalid | 方案变化、核对受阻或记录损坏；旧记录保留，不能改写旧记录来继续使用 |

返回 issues 中 blocking=true 的项必须先解决；blocking=false 只说明非消费性追溯缺口，不代表对应证据真实可用。真正需要人工决定时按 question 汇总阻断项；可逆处理选择按主 Skill 的 Harness 执行策略由数据推导或采用保守基线，不把每个 question 都转成用户提问。

CLI 退出码：0 表示本次有限预检无阻断，或确认记录新建成功；1 表示 review 受阻/旧记录失效；2 表示读取、解析、记录操作等错误。0 永远不表示可以检测。若程序依赖缺失或平台不支持，也应报告，不自动安装、换算法或降级运行。

## 参数与未知项的明确解释规则

本层支持的嵌入参数 Schema 采用 Draft 2020-12，沿用结构检查器的本地引用限制。对象参数必须显式关闭额外键，或给额外键规定类型 Schema。未知关键字不忽略；本版未实现 format/content 断言的可靠支持，出现时明确阻断。default/examples 只是说明，不向请求注入值。依据：[jsonschema 校验说明](https://python-jsonschema.readthedocs.io/en/stable/validate/)与[默认值说明](https://python-jsonschema.readthedocs.io/en/stable/faq/)。

parameter_evidence.field 用相对 task 的 JSON Pointer，例如 /resolved_parameters/window_length，或覆盖整个已明确对象的 /resolved_parameters。每个实参都需有对应出处；evidence 是来源/用户决定的记录，文本引用本身并未被本工具认证。

processing_definition.parameter_paths 用相对 resolved_parameters 的 JSON Pointer。对应 processing_steps[].parameters 为“该指针 → 本次实际值”的映射；参数一致且顺序一致才通过。暂不支持依任务动态展开处理步骤，不能用省略或改名绕过核对。

input_requirements.required_metadata 使用相对 SignalInput.payload 的 JSON Pointer，指向实际所需属性；不要用笼统父对象替代某个具体必要属性。单位、方向等只有实际依赖时才阻断；无关未知随 plan_summary 保留，不伪造数值或多问无关阵列参数。

有效性与上游处理频带的未知必须明确处理。本层识别 unknown_metadata_policy 的两种明确声明：reject_unknown，或 allow_with_explicit_decision。后者还需要 request.unknown_decisions 中有唯一、对应 metadata 指针与 task_id、affected_actions 含 detection 的用户决定。交接时接受未知不能替代这次决定；not_applicable 不能冒充算法必需信息。策略不等于证明假设真实。

input_requirements.constraints 中只有自然语言的科学条件，本层不能证明已满足，会报告需要算法接入阶段的受控核对实现；不通过语言猜测来放行。资源模型描述同样不等于已完成资源估算，仍列为执行阻断项。

## 记录确认：必须绑定真实用户请求

只有用户明确要求对指定数据执行检测时才运行 record-confirmation，并绑定该请求的真实 statement/reference；“开始设计 Skill”、查看说明或只读审查不构成检测授权。当前会话已包含执行要求时无需再次询问。

拿到真实回复后，按 [ConfirmationEvidence 格式](../assets/schemas/ConfirmationEvidence.schema.json) 整理独立证据 JSON：

- actor=user、decision=confirm_reviewed_plan。
- request_id、plan_sha256 精确绑定刚展示的方案。
- statement 保存真实回复的内容，reference 标明对话消息或其他可回查出处。
- evidence_version=0.1.0。缺少真实回复就停在待确认，不造演示批准记录。

~~~bash
python3 scripts/preflight.py record-confirmation /absolute/path/request.json \
  --context /absolute/path/context.json \
  --source-root /absolute/path/explicit-input-root \
  --user-evidence /absolute/path/user-evidence.json \
  --out /absolute/path/new-confirmation.json
~~~

该命令重新做预检，核对证据中的请求/方案，才在指定位置独占新建 [ConfirmationReceipt](../assets/schemas/ConfirmationReceipt.schema.json)。不覆盖旧文件，不修改请求的 approval，不写入只读来源根目录，不自动创建父目录。写入中断留下的部分文件不能当有效确认，需使用另一个新位置；不能为了重试删除旧记录。

复核时：

~~~bash
python3 scripts/preflight.py review /absolute/path/request.json \
  --context /absolute/path/context.json \
  --source-root /absolute/path/explicit-input-root \
  --confirmation /absolute/path/new-confirmation.json
~~~

确认摘要采用本实现版本化的 UTF-8 JSON 序列化（排序键、紧凑分隔、不允许 NaN），不是 RFC 8785 的跨语言规范承诺。摘要包含请求（去除 approval 避免循环）、上下文、提供的输入/算法文档字节摘要、已核对来源身份/头部、已启用的适配核对结果与预检版本；上下文或说明文档字节变化也会触发重新核对，不悄悄迁移旧确认。

记录只保留“用户表述被记录且绑定到此方案”，authority_verified 始终 false。本地记录可被有文件写权限者伪造，工具不认证消息来源、用户身份或权限。调用方必须核对真实对话，不得仅凭 JSON 文件授予运行权。记录 scope 固定为 preflight_plan_only_not_execution，后续真正执行还需完整门禁，不自动继承成执行授权。

## 本工具不承担的职责

- 注册可信算法实现、其实现文件核对、实际执行器和算法专属科学约束。
- 检测算法有效帧规则与跨缺口处理核验。未启用适配器时，基础 NPY 头检查仍不检查数值/掩码；启用适配器复用接收器验证有限值、掩码/区间、主包内活动频点列表，但不验证物理通带效果。头部读取依据 [NumPy NPY 格式](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html)。
- 资源峰值估算、输出保存位置/最小追溯包验证、运行期间持续保护来源。
- 双向索引、联合显示、补算调度、检测质量与工程验收。

检查过程中会复核文件属性以发现常见并发修改，但不是锁定快照；来源在检查后仍可能变化。实际运行前、运行中与发布结果前必须重新核对，不能把本次 receipt 当作永久许可。


新增 [runtime v1](runtime-v1.md) 在基础预检之外实现登记/专属核验/确认执行与交付，[协作入口](association-runtime-v1.md) 实现索引/显示/受控补算；独立评价与工程验收仍不属于本层。这些新增能力不改变旧 scope 或 preflight 的 can_execute=false。

## 已做验证

原有40项结构测试、[50项预检与确认测试](../tests/test_preflight.py) 保持通过；新增 [29项适配与接入测试](../tests/test_input_adapter.py)，总计119项。使用临时目录中的合成包和明确标为假数据的 JSON，未读取或计算 S59 等实测数据，也未选择真实检测算法。

覆盖身份/版本错配、缺参/条件必填/默认值不填充、未知项处理、摘要和 NPY 头异常、越界/符号链接/预算、读取期间源变化、产物依赖与循环、只读不落盘、旧确认失效、确认不覆盖旧文件及 CLI 往返。通过这些测试不表示完整运行门禁或算法效果已验收。

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
~~~
