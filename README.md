# 水下探测 Harness 与产品门户

## 独立 Harness 与 Python 执行

当前优先建设通用 Harness。`harness` profile 使用 DeepSeek Harness SDK 的任务循环、Skills、文件工具、沙箱 Shell、后台任务和会话持久化，不加载知识库助手插件。入口与已有 `rag-kb` 门户独立：

```bash
./harness.sh "分析数据，先检查采样率、通道数和异常，再给出处理方案"
./harness.sh --skills          # 离线列出项目内实际可用的 Skills
./harness.sh --check           # 准备环境后验证解释器、依赖与沙箱权限
./harness.sh --smoke           # 模型实际生成并执行频谱分析，验证 JSON 和 PNG 产物
./setup-python.sh             # 可选：主动重新检查 Python 依赖
./start.sh --harness          # 前端试用：http://127.0.0.1:5173/chat，后端为本机 3089
```

需要 Python ≥3.11、Node ≥22.19；模型配置读取 `backend/.env` 的 `LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`。独立入口固定选择 `harness` profile，无需 LightRAG、MinerU 或前端。CLI 在启动任务前自动创建项目 `.venv`、准备基础和 Skill 依赖、预热绘图缓存；执行环境将 `python / python3` 指向项目 `.venv/bin`，同时提供绝对路径 `HARNESS_PYTHON`。基础依赖由 `requirements-harness.txt` 管理。

`./start.sh --harness` 提供浏览器试用入口，复用同一 Harness 运行时与项目 `.venv`，支持数据文件附件和执行过程展示。它在本机 3089 运行，前端 5173 将请求代理到该服务；会话存储与旧知识库门户隔离。启动脚本会检查前端代理确实连接 `harness` profile。旧模式仍用 `./start.sh`，切换前需停止占用 5173 的前端；`./stop.sh` 停止脚本管理的两种本机服务。

默认 `LLM_THINKING=false`：主 Qwen 模型通过原生 SDK 明确发送 `enable_thinking:false`。`VLM_REASONING_EFFORT=none` 为 Qwen3.8 Omni 明确发送 `reasoning_effort:none`。仅声明 SDK 的 `reasoningEfforts:false` 无法关闭服务端默认思考。需要时可用 `LLM_THINKING=true` 或 `VLM_REASONING_EFFORT=xhigh` 开启；`LLM_REASONING_EFFORT=off/low` 可覆盖主模型档位。变更模型配置后重启相应入口。关闭隐藏思考后，仍会调用工具、选择方法并简洁说明参数依据。

问候和术语解释直接回答；对已有结果的追问优先复用数值产物。常规分析不运行 Skill 开发验收、不重新写读取器作独立对照，不为每张图追加视觉调用；出现具体冲突时才做针对性核对。dtype、字节序与填充等仍保存在机器结果中，报告正文只突出结论、关键指标、覆盖及必要限制。真实模型响应回归可运行 `node backend/dev/smoke-harness-responsiveness.mjs`，包含问候、术语解释、既有结果总结、视觉请求及前 60 秒 SIO 分析；结果保存在 `.run/harness-responsiveness/`。

### Skill 放入即可使用

推荐将标准 Skill 包直接放入项目 `skills/`，也兼容项目 `.agents/skills/` 与 `.dsh/skills/`，按这个顺序选择同名 Skill。项目入口不扫描用户全局 Skills：

```text
skills/
└── your-skill/
    ├── SKILL.md           # YAML frontmatter 至少含 name、description
    ├── requirements.txt   # 可选：这个 Skill 的 Python 依赖
    ├── scripts/           # 可选：已有函数/算法的执行脚本
    └── references/        # 可选：按需读取的方法说明
```

`name` 使用小写字母、数字和连字符，`description` 说明何时适用。正文中的资源路径相对于 Skill 所在目录；输入、输出路径按用户任务约定。用 `./harness.sh --skills` 检查发现结果，随后直接提交任务，不需要修改 profile、注册工具或手动切换虚拟环境。

启动时会把基础和各 Skill 的依赖一起求解并安装到项目 `.venv`：优先使用 Skill 根目录 `requirements.txt`，没有时使用 `scripts/requirements.txt`，每个 Skill 只选择一份，支持本地嵌套 `-r/-c` 文件。清单和已安装版本均未变化时跳过安装；新增 Skill、修改依赖、手动改变包版本或上次初始化失败时自动重检。依赖冲突会在求解阶段明确报错，并保留原环境；不同 Skill 的不可兼容依赖需要先协调版本。初始化使用文件锁，多个启动不会同时修改依赖。Skill 删除后不自动卸载额外包。

SDK 支持同一运行实例在后续步骤发现 Skill 新增、元数据修改与删除；正文再次加载时重读。正在运行的任务若需要新安装的依赖，应结束后重新启动入口完成依赖准备；热更新不会后台修改正在执行的 Python 环境。Skills 的 Python 包依赖可以自动准备；需要 MATLAB、CUDA 或外部服务的 Skill 仍需对应系统能力。

### 验证

```bash
node backend/dev/run-tests.mjs                 # 契约回归；Python/沙箱检查包含真实本机执行
node backend/dev/smoke-harness-skills.mjs        # 4 个真实模型场景，临时复制 Skill 后执行并核验
node backend/dev/smoke-underwater-inspection.mjs # 正式水声 Skill 的 4 个真实模型场景
node backend/dev/smoke-harness-vision.mjs        # 主模型实际调用独立视觉模型核对频谱图
node backend/dev/smoke-harness-delivery.mjs      # 复用已有真实结果：对话呈现，再按请求生成可预览报告（需启动3089）
node backend/dev/smoke-harness-efficiency.mjs    # 真实SIO：全量体检、限定范围分析、目录候选；检查少步骤与中文目的（需启动3089）
```

真实模型场景覆盖隐式选用、YAML 依赖与元数据读取、采样率缺失、Welch 分段参数推导、路径错误重试；事件记录和原始结果在 `.run/harness-skills-smoke/<运行编号>/`。测试用 Skill 完成后自动从项目 `skills/` 移除，固定夹具保存在 `backend/dev/fixtures/harness-skills/`，不作为正式声纳算法发布。离线依赖测试使用临时虚拟环境、本地 wheel 和禁网求解；macOS 执行测试检查实际超时、取消、进程清理和拒写。

### 已接入的水声数据体检 Skill

`skills/underwater-data-inspection/` 包含数据探查、只读读取、完整性/通道质量指标、Welch PSD 和时频分析，支持 NPY、NPZ、传统 MAT、HDF5、PCM WAV 与文档指定的 SIO 变体。常规任务优先调用 `scripts/inspect_data.py execute`，传入已确认事实的内联配置，一次完成探查、运行和返回摘要；原 `probe/run` 入口保留。目录输入一次返回实际候选与结构，多份记录时需明确选择；挂载路径只在唯一匹配时解析并记录映射。字段/轴不明时交付探查，采样率缺失或冲突时保留样本检查并暂停秒/Hz 分析；不会自动填补异常或替用户解决数据事实冲突。

执行卡片与时间线优先显示工具提供的中文目的，例如“检查非有限值与恒值段”或“计算功率谱与时频特征”。原始命令、参数与结果在展开详情中保留；相邻已完成的文件定位与状态查询可合并查看，失败、部分完成和审批状态单独展示。只要求体检时不追加频谱分析，成功摘要足够回答时不再反复探查结果字段或搬动产物。

例如：

```bash
./harness.sh '体检 /绝对路径/recordings.npy，已确认轴0是样本，采样率2000Hz。检查全部数据，基础频谱只分析前65536样本和前4路，保存新结果目录。'
```

普通分析默认在对话中呈现结论、指标表及必要图像，`summary.md` 作为内部内容来源，无需追加计算或视觉验收。只有明确要求报告时，才从现有结果整理新的正式报告，并提供可点击链接。前端支持本地报告、图片与目录预览，报告内的相对链接按报告目录解析；文件入口只读取工作区的 `.run/`、`tasks/`、`output/` 产物。`report.md` 保留技术明细，`result.json`、`feature_status.csv`、质量指标与适用的图像/NPZ 保留可复现证据。顶层 `completed` 只表示本次支持的流程结束，须结合子项清单、实际样本/通道覆盖和未知条件理解。当前 Skill 提供基础分析证据，后续波束形成和线谱检测需要各自的 Skill。正式 Skill 的独立 CLI 测试在 `backend/dev/contract-underwater-inspection.py`；`contract-underwater-sandbox.mjs` 用 SDK 的真实文件沙箱执行随包测试和独立测试。真实模型集成证据存放在 `.run/underwater-inspection-smoke/<运行编号>/`，四类任务为隐式选用与部分谱覆盖、显式调用且缺采样率、字段/轴歧义、WAV 采样率冲突。测试输入为生成的已知信号，用于核验行为和数值，不代替真实海试数据验证。

### 独立视觉模型

`ocean-harness-vision` 插件提供 `vision_inspect`。主模型继续使用 `LLM_*` 配置；图像核对单独使用 `VLM_BASE_URL / VLM_API_KEY / VLM_MODEL`（当前模型 `qwen3.8-omni-flash`），这些值在被 Git 忽略的 `backend/.env` 管理。工具通过 SDK 文件服务和图像附件服务读取 PNG/JPEG/WebP/GIF，继承文件策略、调用取消和 120 秒超时；默认输出预算 2048 tokens，截断明确标记 `partial`。源码在 `backend/dsh/harness-vision/`，不依赖知识库门户。

浏览器聊天可上传一张 PNG/JPEG/WebP/GIF 图片，或在输入框直接按 ⌘V / Ctrl+V 粘贴剪贴板截图，同时填写问题。默认每张图片最多 5 MiB；发送前可预览、移除。普通文字粘贴保持原有行为；粘贴图片保留已输入的问题，并复用上传的同一视觉解读流程。后端自动把图片像素与问题一起交给视觉模型，再将视觉观察与用户原文传给主模型回答，无需手动指定 `vision_inspect`。坏图、格式不符及超限会明确报错，解读截断会标记。`contract-image-input.mjs` 覆盖真实 HTTP 请求、文本与图片共同输入及中止时断开视觉请求。

“停止回答”会取消本轮后台执行，等待取消确认后可在同一个会话继续提问。每轮独立 `requestId` 防止迟到的停止操作影响下一轮，断开聊天流也会触发取消。SDK 当前没有 JSON-RPC 单轮取消接口，浏览器适配层通过 `ocean-harness-control` 本机桥调用公开的 `Agent.cancel`，并等待相关工具、子任务与后台 jobs 收敛；不会关闭其他会话共用的 Harness 子进程。桥只监听回环地址，令牌由服务启动时临时生成，不需要额外配置；独立 CLI 默认不启用该桥。取消无法确认时界面保留停止状态并提示重试。`contract-control.mjs` 与聊天契约覆盖取消与同会话复用。

工具把图像直接交给独立视觉模型，主任务收到带图像路径、原始字节 SHA256、实际模型、回答和可得用量的纯文本 JSON。SDK 附件服务可能把 PNG 优化为 WebP；哈希对应原始读取文件，附件类型对应实际提交的图像。读图可核对曲线、坐标、谱峰近似位置与明显异常，精确数值仍引用 JSON/NPZ。`contract-vision.mjs` 用真实 SDK 文件/图像服务和模拟模型验证读取、格式与预算、错误、取消及超时；真实模型证据保存在 `.run/harness-vision-smoke/<运行编号>/`。

虚拟环境管理 Python 依赖；执行限制由 SDK 的 `workspace-write` 沙箱提供。macOS 使用 Seatbelt（`sandbox-exec`），Linux 需要可用的 Bubblewrap 或 Landlock，沙箱不可用时拒绝执行。当前本机 Docker 内核的 Landlock 不可用且未安装 Bubblewrap，因此算法执行先走宿主机入口；这里没有关闭 Docker 沙箱来绕过错误。此沙箱限制文件访问，不提供网络隔离；`.venv` 也不是安全隔离边界。

核心代码：`backend/harness/runtime.mjs` 统一创建 SDK 和 Python 环境，`backend/dsh/home/profiles/harness/cordis.patch.yml` 管理通用行为与执行策略。真实执行验证产物保存在 `.run/harness-smoke/<运行编号>/`，含脚本、结果、频谱图与工具事件。虚拟环境和运行数据不入 Git，宿主机 `.venv` 不复制到 Docker 镜像。

DeepSeek 提供 [TypeScript SDK](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/sdk/client) 和 [Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)。Python SDK 用来驱动 Harness 会话，与算法脚本的 Python 解释器是两个层次；本项目保留已有 TypeScript SDK，由其沙箱 Shell 调用项目 `.venv`。官方另有 [实验性 Python PTC runtime](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/experimental/ptc-runtime-python/README.md)，它自身不提供文件沙箱，目前不接入。

## 已有知识库门户

基于 DeepSeek Harness SDK（npm 包 `@deepseek-ai/dsh-sdk-client`）的知识库智能体适配层，外加蓝白视觉的产品门户（Vite + React 前端、轻量门户认证适配和 Nginx 静态服务）。自包含仓库：不依赖 DeepSeek Harness 源码仓。

## 阿里云知识服务模式（当前默认）

本地问答智能体连接阿里云上的 LightRAG 与 MinerU。配置集中在 `backend/.env`：文本模型 `qwen3.8-flash`、图片模型 `qwen3.8-omni-flash`、模型兼容地址和密钥、LightRAG 地址与 `X-API-Key`、MinerU 地址与 Bearer key。密钥文件不进 Git 或镜像。首次配置见 `backend/.env.example` 与 [QUICK_START.md](QUICK_START.md)。

```bash
docker compose -f docker-compose.app.yml --env-file backend/.env up -d --build
```

访问 `http://localhost:<WEB_PORT>/chat`（模板默认 8080，本机配置 8086）。默认只启动前后端；本地 LightRAG 放入关闭的 `local-engines` profile，MinerU 由阿里云运行。PDF 上传经过「本地后端 → LightRAG → MinerU 适配器 → MinerU」解析入库；聊天图片附件调用多模态模型后交给问答模型。集成状态可查看 `/api/integrations/health`。

会话、知识注册表、意图与审计账本保存在 `rag-kb-runtime` 卷，附件保存在 `rag-kb-spool` 卷。SDK 的运行配置由 `.env` 在启动时生成到 `.runtime/dsh-home`，`dsh/home` 继续作为插件模板。

远程 REST 模式支持知识检索、文档管理与图谱增删改查。`KB_RAG_STORAGE` 和 `KB_LIGHTRAG_INPUTS_DIR` 留空时，依赖共享文件的 GraphML 重复实体分析和原文图片回溯自动降级；PDF 解析与图片附件识别仍可用。

## 目录结构

```text
rag-harness-sdk/
├── backend/                    # 后端
│   ├── index.js                #   适配层：浏览器 ↔ dsh 子进程桥（SSE 聊天/审批/kb REST，3088）
│   ├── package.json            #   适配层依赖：@deepseek-ai/dsh-sdk-client（含版本 overrides）
│   ├── cas-server/             #   独立 CAS 认证中心（前后端一体，仅负责认证）
│   ├── portal-auth/            #   门户的 CAS 客户端与门户会话服务
│   └── dsh/                    # dsh 运行时与插件
│       ├── home/               #     DSH_HOME：settings、profiles/rag-kb、.env（模板 .env.example）
│       ├── dsh-knowledge/      #     知识库插件（LightRAG 适配、/kb/* REST、kb_* 模型工具）
│       └── plugin-approval-bridge/ # 审批桥接插件（/approvals/* HTTP 面）
├── frontend/                   # 前端：React 门户与首页 Nginx
├── gateway/                    # 网关 Nginx 路由
├── nginx.conf                  # 服务器总入口，TLS 与多应用路由
└── docker-compose.yml          # 服务器总入口 Nginx
```

门户 SSO 由三部分组成（`docker-compose.gateway.yml` 统一编排）：

- `cas-server`：独立 CAS 认证系统，登录成功 302 回跳 service（门户/业务系统）。
- `portal-auth`：门户的 CAS 客户端，发起登录、校验 Ticket，通过签名 Cookie 保存最小用户身份。
- `homepagev2`：React 门户前端（静态页）。

## 认证流程

```text
浏览器
  -> 点击产品的“登录并进入”
  -> /api/auth/login
  -> CAS /login
  -> /api/auth/callback?ticket=ST-xxx
  -> portal-auth 服务端校验 Ticket
  -> 浏览器获得签名的 HttpOnly 会话 Cookie
  -> 门户 /api/auth/me 返回当前用户
  -> 自动继续访问产品 /sso/login
  -> CAS 复用全局登录会话，无需再次输入密码
  -> 产品获得并校验自己的 Service Ticket
```

前端不会读取或保存 CAS Ticket，也不会把用户名当作可信身份。

## 业务系统单点登录接入

任何业务系统都可以通过 CAS 协议接入本门户，实现「门户登录一次，各系统免密进入」。
下面以「大客户内外数据比对智能体」（139 工程，即 tri-source-agent）为例，
说明接入步骤并给出后端示例代码。

### 接入原理

```text
业务系统后端(未登录)
  -> 302 到 CAS /cas/login?service=<业务系统回跳地址>
  -> CAS 展示登录页 / 免密发放 ticket
  -> 302 回跳 <业务系统回跳地址>?ticket=ST-xxx
  -> 业务系统后端拿 ticket 调 CAS /cas/serviceValidate 校验
  -> CAS 返回 XML(含 user/uid)
  -> 校验通过，业务系统建立自己的登录态(如签发 JWT)
```

业务系统只需实现两个动作：**引导登录**（跳 CAS）和 **校验回跳**（验 ticket）。

### 关键配置（139 工程 `.env` 实例）

```ini
# 浏览器跳转的 CAS 登录地址
CAS_SERVER_URL=http://127.0.0.1:9000/cas

# 本系统对外回跳地址，必须与登录时传给 CAS 的 service 完全一致
CAS_SERVICE_URL=http://127.0.0.1:9100/vip_139/report/api/auth/sso/login

# 后端校验 ticket 接口（可留空，自动推导为 {CAS_SERVER_URL}/serviceValidate）
SSO_VALIDATE_URL=http://127.0.0.1:9000/cas/serviceValidate

# 从 CAS 返回 attributes 中取用户标识的属性名
SSO_UID_ATTRIBUTE=uid
```

> 重要协议约束（CAS 官方规范，必须遵守）：
> - 登录传给 CAS 的 `service` 与校验时用的 `service` **必须严格一致**。
> - `service` 参数不得含转义符号 / `#` / 多个 `?`。
> - ticket 一次性使用，30 秒过期。

### 后端示例代码（以 139 工程为准，可复制到任意 Python 后端）

```python
"""CAS 单点登录客户端接入示例（路由适配任意 Web 框架）。"""
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import requests

CAS_SERVER = "http://127.0.0.1:9000/cas"
CAS_SERVICE_URL = "http://127.0.0.1:9100/vip_139/report/api/auth/sso/login"  # 本系统回跳地址


def build_login_url() -> str:
    """构造引导用户跳转到 CAS 登录页的 URL。"""
    query = urlencode({"service": CAS_SERVICE_URL})
    return f"{CAS_SERVER}/login?{query}"


def sso_login(request) -> "Response":
    """GET /sso/login：未登录就跳 CAS，带 ticket 回跳则校验。"""
    ticket = request.args.get("ticket", "")
    if not ticket:
        # 未登录：跳转到 CAS 登录页
        return redirect_302(build_login_url())
    # 已从 CAS 回跳：校验 ticket
    result = validate_ticket(ticket)
    if not result["success"]:
        return render_error("登录失败: " + result["error"])
    # 建立本系统登录态，例如签发 JWT / 写入会话
    return issue_local_session(result["uid"])


def validate_ticket(ticket: str) -> dict:
    """向 CAS 校验 ticket，返回 {"success": bool, "uid": str, "attributes": dict}。"""
    url = f"{CAS_SERVER}/serviceValidate?{urlencode({'service': CAS_SERVICE_URL, 'ticket': ticket})}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"success": False, "error": f"CAS 不可达: {exc}"}
    return parse_cas_xml(resp.text)


def parse_cas_xml(xml_text: str) -> dict:
    """解析 CAS /serviceValidate 返回的 XML。"""
    ns = {"cas": "http://www.yale.edu/tp/cas"}
    root = ET.fromstring(xml_text)
    failure = root.find(".//cas:authenticationFailure", ns)
    if failure is not None:
        return {"success": False, "error": (failure.text or "").strip()}
    uid = root.findtext(".//cas:authenticationSuccess/cas:user", namespaces=ns)
    attrs = {}
    node = root.find(".//cas:authenticationSuccess/cas:attributes", ns)
    if node is not None:
        for child in node:
            key = child.tag.rsplit("}", 1)[-1]
            attrs[key] = (child.text or "").strip()
    if not uid:
        return {"success": False, "error": "CAS 未返回 uid"}
    return {"success": True, "uid": attrs.get("uid", uid), "attributes": attrs}
```

接入后，在门户 `frontend/.env` 中把该产品入口指向本系统 `/sso/login`，例如：

```ini
VITE_KEY_ACCOUNT_COMPARISON_URL=http://127.0.0.1:9100/vip_139/report/api/auth/sso/login
```

门户前端「登录并进入」即可触发上述 SSO 流程，进入 139 工程时不需再输入密码。

## 本地联调

### 1. 启动项目内置 CAS 认证服务

CAS 已收入本项目 `cas-server/`，为独立认证系统（不再依赖外部 mock-cas-server 项目）。

```bash
cd cas-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

默认地址为 `http://127.0.0.1:9000/cas/login`。演示账号：`wangqiyue / Wqy@2026#Secure!Cas`。

### 2. 启动门户认证后端

```bash
cd portal-auth
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

门户认证适配监听 `http://127.0.0.1:9010`。

### 3. 启动前端

```bash
cd homepage
npm ci
npm run dev -- --host 127.0.0.1 --port 4173
```

访问 `http://127.0.0.1:4173`，点击右上角“统一登录”。

对话工作台原型位于 `http://127.0.0.1:4173/chat?agent=agent-hub`，也可以从
门户产品详情中的“对话原型”进入。当前版本用于界面与交互联调，回复内容为前端演示数据，
后续再接入真实智能体会话接口。

如需验证门户到业务系统的完整跳转，切换到“大客户内外数据比对智能体”，
点击“登录并进入”。其默认入口为：

```text
http://127.0.0.1:9100/vip_139/report/api/auth/sso/login
```

各产品入口通过 `frontend/.env` 中的 `VITE_*_URL` 配置。没有配置入口的产品
在登录后显示“应用接入中”，不会跳转到虚构地址。

## 自动化检查

```bash
cd cas-server
.venv/bin/python -m py_compile app.py

cd ../portal-auth
.venv/bin/python -m unittest discover -s tests -v

cd ../homepage
npm run build

cd ..
docker compose -f docker-compose.gateway.yml config --quiet
```

## Docker 运行

推荐用根目录的 `docker-compose.gateway.yml` 将 CAS、门户认证后端、门户前端统一编排启动：

```bash
docker compose -f docker-compose.gateway.yml up -d --build
```

拓扑（网关 `:8080` 为唯一对外入口）：

- `/` → `homepagev2`：门户前端静态页
- `/api/auth/*` → `portal-auth`：门户认证后端
- `/cas/*` → `cas-server`：项目内置 CAS 认证中心

Docker 中的 `portal-auth` 不依赖数据库或 Redis，只保存经过签名的最小身份 Cookie。
`cas-server` 的演示账号仅用于联调，生产请替换为真实账号数据源。

## 生产配置

生产环境至少需要设置：

```ini
# cas-server（项目内置 CAS）
APP_ENV=production
SECRET_KEY=<强随机值>

# portal-auth（门户认证后端）
PORTAL_AUTH_SECRET_KEY=<强随机值>
CAS_PUBLIC_URL=https://sso.example.com/cas
CAS_INTERNAL_URL=http://cas-server:9000/cas
CAS_SERVICE_URL=https://www.example.com/api/auth/callback
PORTAL_PUBLIC_URL=https://www.example.com
SESSION_COOKIE_SECURE=true
SESSION_TTL_SECONDS=3600

VITE_KEY_ACCOUNT_COMPARISON_URL=https://www.example.com/report/api/auth/sso/login
VITE_AGENT_HUB_URL=https://www.example.com/agent_hub/api/auth/sso/login
```

- `CAS_PUBLIC_URL`：浏览器（用户）可访问的 CAS 登录地址。
- `CAS_INTERNAL_URL`：portal-auth 后端校验 ticket 时访问的 CAS 内网地址（指向 cas-server 容器）。
- `SECRET_KEY` / `PORTAL_AUTH_SECRET_KEY`：分别用 `openssl rand -hex 32` 生成。

门户 Cookie 默认有效一小时；过期后会通过 CAS 全局会话静默恢复登录。
生产请把 `cas-server` 的演示账号替换为真实账号数据源（LDAP / 数据库等）。

> 说明：当前根级 `nginx.conf`（`docker-compose.yml`）仍指向生产多业务路由。
> 若仅部署门户 SSO，请使用 `docker-compose.gateway.yml`（网关单入口，:8080）。

## 当前范围

- 已完成门户自身的 CAS 登录闭环。
- 已完成登录、用户状态查询和本地会话退出。
- 尚未把九个业务系统逐个接成 CAS 客户端。
- `cas-server` 内置的演示账号仅用于开发联调，生产应替换为真实账号数据源（LDAP/数据库等）。
