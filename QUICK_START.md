# 本地快速启动

一条命令拉起知识库智能体适配层与门户前端（首次运行会自动安装依赖并建立 profile 插件链接）：

```bash
./start.sh   # LightRAG 引擎（docker）+ 适配层 3088 + 前端 5173，日志在 .run/
./stop.sh    # 停止
```

首次部署还需：

1. `cp backend/.env.example backend/.env`，填入模型 key 与 LightRAG 路径（适配层端口、profile、模型路由同文件管理）。
2. 启动 LightRAG 引擎容器（`lightrag-docker-0.6B`）。
3. 浏览器打开 `http://localhost:5173` → 「进入工作台」。

## Docker 一键启动（三服务整体编排）

先停掉宿主机上的开发栈与本机已运行的 LightRAG 容器（端口冲突），然后：

```bash
docker compose -f docker-compose.app.yml --env-file backend/.env up -d --build
```

启动后访问 `http://localhost:8080`（前端 Nginx 已把 `/api/` 代理到 backend:3088，`/api/auth/` 代理到门户认证）。停止：`docker compose -f docker-compose.app.yml --env-file backend/.env down`。会话历史与审批附件在命名卷 `rag-kb-sessions` / `rag-kb-spool` 中持久化；`backend/.env` 不进镜像，模型 key 等经 `env_file` 注入。

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
| `QWEN_TOKEN_PLAN_API_KEY` | 阿里百炼 key（聊天模型）；对应 `dsh/home/settings.yaml` 的 provider 路由 |
| `KB_RAG_STORAGE` / `KB_LIGHTRAG_INPUTS_DIR` | LightRAG 数据卷与原料区路径；新机器可为空目录（空库启动，之后通过入库流程灌数据） |
| `LIGHTRAG_DOTENV` / `LIGHTRAG_PROMPTS_DIR` | LightRAG 引擎自身的 `.env`（含引擎抽取用模型 key）与 prompts 目录；缺失时 compose 启动即报错 |

非 Docker 方式（开发模式）需要本机 Node ≥ 22.19 或 24 + npm + 一个运行中的 LightRAG 引擎：`./start.sh` 即可（自动 `npm install`、建 profile 链接、起适配层 3088 与前端 5173）。

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
