# 智能体产品门户

蓝白视觉的九智能体产品门户，包含 Vite + React 前端、轻量门户认证适配和 Nginx 静态服务。

## 目录结构

```text
agent_showcase_homepage/
├── homepage/              # React 门户与首页 Nginx
├── portal-auth/           # CAS 客户端与门户会话服务
├── nginx.conf             # 服务器总入口，TLS 与多应用路由
└── docker-compose.yml     # 服务器总入口 Nginx
```

首页服务自己的 Compose 位于 `homepage/docker-compose.yml`，包含：

- `homepagev2`：构建并提供 React 静态页面。
- `portal-auth`：发起 CAS 登录、校验 Ticket，并通过签名 Cookie 保存最小用户身份。

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

## 本地联调

### 1. 启动 mock CAS

```bash
git clone git@github.com:MindForge-Harvey/mock-cas-server.git
cd mock-cas-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

默认地址为 `http://127.0.0.1:9000/cas/login`。

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

如需验证门户到业务系统的完整跳转，切换到“大客户内外数据比对智能体”，
点击“登录并进入”。其默认入口为：

```text
http://127.0.0.1:9100/vip_139/report/api/auth/sso/login
```

各产品入口通过 `homepage/.env` 中的 `VITE_*_URL` 配置。没有配置入口的产品
在登录后显示“应用接入中”，不会跳转到虚构地址。

## 自动化检查

```bash
cd portal-auth
.venv/bin/python -m unittest discover -s tests -v

cd ../homepage
npm run build
docker compose config --quiet
```

## Docker 运行

```bash
docker network inspect proxy-tier >/dev/null 2>&1 || docker network create proxy-tier
cd homepage
cp .env.example .env
docker compose up -d --build
```

Docker 中的 `portal-auth` 不依赖数据库或 Redis，只保存经过签名的最小身份 Cookie。

## 生产配置

生产环境至少需要设置：

```ini
APP_ENV=production
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

可以用 `openssl rand -hex 32` 生成 `PORTAL_AUTH_SECRET_KEY`。
门户 Cookie 默认有效一小时；过期后会通过 CAS 全局会话静默恢复登录。

当前根级 Nginx 的首页仍指向原服务。正式切换到 `homepagev2:80` 前，需要先部署并验证 CAS、门户认证后端和首页容器。

## 当前范围

- 已完成门户自身的 CAS 登录闭环。
- 已完成登录、用户状态查询和本地会话退出。
- 尚未把九个业务系统逐个接成 CAS 客户端。
- `mock-cas-server` 仅用于开发联调，不能作为生产认证中心直接上线。
