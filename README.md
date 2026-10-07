# 深海智探

面向水下弱目标探测的自主分析 Harness。系统接收水声数据、图片或已有算法结果，先识别数据特征与证据边界，再选择数据体检、波束形成、线谱结果评价或轨迹处理能力，并把参数来源、执行过程、指标和图像呈现在同一对话中。

当前默认入口是独立 Harness。旧知识库门户仍保留，但不参与水下算法任务。

## 从零启动

以下步骤按全新仓库环境设计。支持 macOS 和 Linux，Windows 请使用 WSL。

### 1. 安装基础环境

- Git
- Node.js 22.19 或更高版本
- Python 3.11 或更高版本
- npm（随 Node.js 安装）

先确认版本：

```bash
git --version
```

```bash
node --version
```

```bash
python3 --version
```

### 2. 克隆项目

```bash
git clone git@github.com:argueddd/ocean--intelligent-detection.git
```

```bash
cd ocean--intelligent-detection
```

### 3. 创建本机配置

```bash
cp backend/.env.example backend/.env
```

用任意文本编辑器打开配置：

```bash
nano backend/.env
```

至少填写下面三项：

```dotenv
LLM_BASE_URL=https://你的模型服务地址/compatible-mode/v1
LLM_API_KEY=你的文本模型密钥
LLM_MODEL=qwen3.8-flash
```

如需在对话框中粘贴或上传图片，再填写：

```dotenv
VLM_BASE_URL=https://你的模型服务地址/compatible-mode/v1
VLM_API_KEY=你的视觉模型密钥
VLM_MODEL=qwen3.8-omni-flash
```

`backend/.env` 已被 `.gitignore` 排除。不要把真实密钥写入 `.env.example`、源码或提交记录。

### 4. 启动

```bash
./start.sh --harness
```

首次启动会自动完成以下工作：

- 安装前后端 npm 依赖；
- 在项目根目录创建独立 `.venv`；
- 安装基础依赖和各 Skill 自带的 Python 依赖；
- 启动 Harness API `127.0.0.1:3089`；
- 启动前端 `127.0.0.1:5173`。

浏览器打开：

<http://127.0.0.1:5173/chat>

检查服务状态：

```bash
curl http://127.0.0.1:3089/api/health
```

正常结果中的 `profile` 应为 `harness`。

### 5. 停止

```bash
./stop.sh
```

## 使用方式

网页端支持：

- 直接描述任务并提供本机数据绝对路径；
- 点击输入框左侧的 `+` 上传数据、结果文件或图片；
- 把剪切板图片直接粘贴到输入框，与文字问题一起发送；
- 在右侧“过程”面板查看每一步的目的和状态；
- 在回答中直接查看结果图，点击报告或结果链接打开预览。

也可以不启动前端，直接使用命令行：

```bash
./harness.sh "体检 /绝对路径/recordings.npy，并给出进入波束形成前的判断"
```

查看自动发现的 Skills：

```bash
./harness.sh --skills
```

检查 Python、依赖和沙箱执行环境：

```bash
./harness.sh --check
```

所有 Python 代码都通过项目根目录的 `.venv` 执行，不使用系统 Python 环境。运行产物保存在 `.run/`，前后端日志也在 `.run/`。

## 配置说明

运行配置统一放在 `backend/.env`。常用变量如下：

| 变量 | 是否必需 | 用途 |
| --- | --- | --- |
| `LLM_BASE_URL` | 是 | 文本模型的 OpenAI 兼容接口 |
| `LLM_API_KEY` | 是 | 文本模型密钥 |
| `LLM_MODEL` | 是 | 主模型名称 |
| `LLM_THINKING` | 否 | 是否开启服务端长思考，默认 `false` |
| `VLM_BASE_URL` | 图片任务必需 | 视觉模型接口 |
| `VLM_API_KEY` | 图片任务必需 | 视觉模型密钥 |
| `VLM_MODEL` | 图片任务必需 | 视觉模型名称 |
| `VLM_REASONING_EFFORT` | 否 | 视觉模型思考档位，默认 `none` |
| `VLM_MAX_IMAGE_BYTES` | 否 | 单张图片上限，默认 5 MiB |

`LIGHTRAG_*`、`MINERU_*` 和 `KB_*` 只用于旧知识库门户。运行 `./start.sh --harness` 时不需要配置。

修改模型配置后，依次执行：

```bash
./stop.sh
```

```bash
./start.sh --harness
```

## 已接入能力

| Skill | 输入 | 职责 |
| --- | --- | --- |
| `underwater-data-inspection` | 原始波形、阵元文件 | 接入、结构识别、完整性、通道质量、PSD 与时频分析 |
| `underwater-beamforming` | 阵元时域数据及阵列事实 | CBF/MVDR 形成、扫描与波束产物生成 |
| `underwater-beamforming-evaluation` | 已保存的波束结果 | 空间谱、DOA、BTR、输出质量和算法对比评价 |
| `underwater-line-spectrum-detection` | 完整波束或旁路时域交接 | CA/OS-CFAR 检测、门限、线谱候选与逐帧覆盖账本 |
| `underwater-line-spectrum-evaluation` | 完整检测结果包 | 候选统计、真值匹配和检测指标评价 |
| `underwater-line-spectrum-tracking` | 完整检测交接包 | 把逐窗线谱候选关联为轨迹 |
| `underwater-line-spectrum-tracking-evaluation` | 完整轨迹结果包 | 连续性、碎片、短轨和误差评价 |

Harness 按输入契约和动作区分检测、评价与跟踪：检测从合规时域交接生成候选，评价只读取已有检测结果，跟踪只关联完整逐窗候选。单独的 PSD 或图片可以用于定性观察，不能伪装成可执行检测输入。

### 增加 Skill

把标准 Skill 目录放到项目 `skills/` 即可被 Harness 自动发现：

```text
skills/
└── your-skill/
    ├── SKILL.md
    ├── requirements.txt
    ├── scripts/
    └── references/
```

`SKILL.md` 的 YAML frontmatter 至少需要 `name` 和 `description`。Python 依赖可以放在 Skill 根目录的 `requirements.txt`；如根目录没有，也会读取 `scripts/requirements.txt`。新增 Skill 后重新启动，依赖会自动安装到项目 `.venv`。

Harness 根据任务动作和输入产物契约路由 Skill。缺少单位、真值、基线或验收阈值时，它会先完成仍可计算的部分并降低结论等级；只有核心物理事实或输入对象确实无法判断时，才会把全部阻断项合并成一次提问。

## 项目结构

```text
.
├── backend/
│   ├── harness/                 # 独立 Harness 启动与 Python 环境编排
│   ├── dsh/                     # DeepSeek Harness profile 与本地插件
│   ├── dev/                     # 契约和真实模型回归
│   ├── .env.example             # 唯一运行配置模板
│   └── index.js                 # Web API 与流式会话适配层
├── frontend/
│   └── src/                     # React 对话界面
├── skills/                      # 水声算法与评价 Skills
├── requirements-harness.txt     # Harness 基础 Python 依赖
├── setup-python.sh              # 项目 .venv 管理
├── harness.sh                   # 命令行入口
├── start.sh                     # 本机一键启动
└── stop.sh                      # 本机停止
```

## 开发验证

前端构建：

```bash
cd frontend
```

```bash
npm run build
```

返回项目根目录：

```bash
cd ..
```

运行离线契约回归：

```bash
node backend/dev/run-tests.mjs
```

真实模型和真实数据 smoke 脚本位于 `backend/dev/smoke-*.mjs`。它们会消耗模型额度，并且部分脚本需要本机数据路径，所以不会在普通启动时自动运行。

## 常见问题

**端口已被占用**

先执行：

```bash
./stop.sh
```

再检查 `3089` 和 `5173` 是否被其他程序占用。

**启动失败**

查看日志：

```bash
ls -la .run
```

```bash
tail -n 100 .run/harness-server.log
```

```bash
tail -n 100 .run/harness-web.log
```

**需要重建 Python 环境**

`.venv` 只属于当前项目，可以删除后重建：

```bash
rm -rf .venv
```

```bash
./setup-python.sh
```

## 旧知识库门户

知识库模式使用 `rag-kb` profile，并依赖 LightRAG 和 MinerU 服务。在 `backend/.env` 填好对应配置后启动：

```bash
./start.sh
```

它与 Harness 共用前端端口，切换模式前请先运行 `./stop.sh`。
