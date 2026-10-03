# 本地快速启动

## 独立 Harness（当前算法执行入口）

本机准备 Python ≥3.11、Node ≥22.19；在 `backend/.env` 填入 `LLM_*` 模型配置后：

```bash
./harness.sh --skills
./harness.sh --check
./harness.sh --smoke
./harness.sh "你的任务指令"
```

把标准 Skill 文件夹放进项目 `skills/` 即可自动发现；可附带根目录 `requirements.txt`，也支持 `scripts/requirements.txt`（根目录清单优先）。启动任务时自动创建 `.venv` 并准备依赖，无需逐个配置工具或手动 pip install。`./setup-python.sh` 可用于主动重检环境。

已安装 `underwater-data-inspection`，可直接请求“体检这个水声文件”自动选用，或用 `$underwater-data-inspection` 显式调用。请提供文件路径及已确认的字段、样本轴和采样率；缺失信息会在结果中保留为未知，不自动猜测。算法执行仍使用独立 Harness 入口。

频谱/时频图核对通过 `vision_inspect` 调用独立视觉模型，配置读取 `backend/.env` 的 `VLM_BASE_URL / VLM_API_KEY / VLM_MODEL`。当前已接入 `qwen3.8-omni-flash`，主任务仍用文本模型组织流程；视觉观察会与数值产物分开记录并交叉核对。

当前主模型为 `qwen3.8-flash`。默认 `LLM_THINKING=false`、`VLM_REASONING_EFFORT=none`，两类模型的长思考均显式关闭；数据分析仍能执行工具和说明方法依据。要开启时分别设置 `LLM_THINKING=true`、`VLM_REASONING_EFFORT=xhigh`，并重启入口。术语解释不重新分析原始数据；常规任务的结果优先复用，开发验收需明确请求。

浏览器试用独立 Harness：

```bash
./start.sh --harness  # 本机 Harness 3089 + 前端 5173，自动准备项目 .venv
```

打开 `http://127.0.0.1:5173/chat`。页面支持数据附件、Skill 调用和视觉复核，后端复用独立 Harness 运行时；会话与知识库模式分开保存。`./stop.sh` 停止本脚本启动的服务。已生成的试用问题在 `.run/harness-try-questions.md`；试用输入在 `.run/try-data/`。如果 5173 已被其他模式占用，先停止该前端再切换。

无需启动前端、LightRAG 或 MinerU。项目 `.venv` 负责 Python 依赖，SDK 沙箱负责执行限制，详见 [README.md](README.md#独立-harness-与-python-执行)。macOS 的本机执行路径已验证；当前 Docker 内核缺少可用的 Landlock，Docker 的代码执行问题需另行解决，不能复用宿主机虚拟环境。

## 已有知识库门户

一条命令拉起知识库智能体适配层与门户前端（首次运行会自动安装依赖并建立 profile 插件链接）：

```bash
./start.sh   # 适配层 3088 + 前端 5173，连接阿里云引擎，日志在 .run/
./stop.sh    # 停止
```

首次部署还需：

1. `cp backend/.env.example backend/.env`，填写模型地址/key、LightRAG 地址/key 与 MinerU 地址/key。
2. 确认阿里云的 LightRAG 与 MinerU 正常运行，使用工作空间的模型兼容地址。
3. 浏览器打开 `http://localhost:5173` → 「进入工作台」。

## Docker 一键启动（本地前后端）

先停掉宿主机上占用 3088 的开发后端，然后：

```bash
docker compose -f docker-compose.app.yml --env-file backend/.env up -d --build
```

启动后访问 `http://localhost:<WEB_PORT>/chat`（模板默认 8080，本机配置 8086）。前端 Nginx 把 `/api/` 代理到 backend:3088。默认只启动 backend/frontend；本地 LightRAG 的 `local-engines` profile 关闭，MinerU 使用阿里云服务。停止：`docker compose -f docker-compose.app.yml --env-file backend/.env down`。会话、知识账本与审批附件在 `rag-kb-runtime` / `rag-kb-spool` 卷中持久化；`backend/.env` 不进镜像，经 `env_file` 注入。

健康检查：`curl http://localhost:8080/api/integrations/health`。文档链路验证：`node backend/dev/smoke-documents.mjs`，会创建唯一命名的测试 PDF，验证解析、检索、替换与删除，结束时清理测试知识。

## 从 git 克隆到新机器（全新部署）

代码与 npm/Docker 依赖完全自包含，克隆后只需三步：

```bash
git clone <仓库地址> && cd rag-harness-sdk
cp backend/.env.example backend/.env   # 编辑填入自己的配置
docker compose -f docker-compose.app.yml --env-file backend/.env up -d --build
```

`backend/.env` 需要自备的内容（密钥与数据不入 git）：

| 配置 | 说明 |
| --- | --- |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 阿里百炼工作空间地址、文本模型密钥与型号 |
| `VLM_BASE_URL` / `VLM_API_KEY` / `VLM_MODEL` | 多模态模型地址、密钥与型号 |
| `LIGHTRAG_BASE_URL` / `LIGHTRAG_API_KEY` | 阿里云 LightRAG HTTPS 入口与服务鉴权 |
| `MINERU_BASE_URL` / `MINERU_API_KEY` | 阿里云 MinerU HTTPS 入口与服务鉴权 |
| `KB_RAG_STORAGE` / `KB_LIGHTRAG_INPUTS_DIR` | 远程模式留空；共享目录可用时才启用 GraphML 分析与原文图片回溯 |

非 Docker 方式需要本机 Node ≥22.19 + npm，以及可访问的阿里云知识服务：运行 `./start.sh`（自动安装依赖、建立插件链接、启动适配层 3088 与前端 5173）。macOS 脚本会在当前 Node 版本过低时尝试 Homebrew Node，也可以设置 `NODE_BIN`。

## 单点登录（手动分进程启动）

需要同时启动三个进程：CAS 认证服务、门户认证后端和门户前端。

### CAS 认证服务（项目内置）

```bash
cd backend/cas-server
.venv/bin/python app.py
```

监听端口：`9000`。演示账号：`wangqiyue / Wqy@2026#Secure!Cas`。

### 门户认证后端

```bash
cd backend/portal-auth
.venv/bin/python app.py
```

监听端口：`9010`。

### 门户前端

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 4173
```

打开 `http://127.0.0.1:4173`：

1. 选择“大客户内外数据比对智能体”。
2. 点击“登录并进入”。
3. 在 CAS 页面完成登录。
4. 门户建立登录态后，会自动继续跳转到该产品的 `/sso/login`。
5. 产品再次访问 CAS 时复用全局会话，无需重复输入密码。

要验证最后一步，需要同时启动对应智能体，或把
`VITE_KEY_ACCOUNT_COMPARISON_URL` 配置成可访问的 SSO 入口。

详细配置、Docker 运行和生产注意事项见 `README.md`。
