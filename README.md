# 智能体产品门户

蓝白视觉的九智能体产品门户，包含 Vite + React 前端、轻量门户认证适配和 Nginx 静态服务。

## 目录结构

```text
agent_showcase_homepage/
├── homepage/              # React 门户与首页 Nginx
├── portal-auth/           # CAS 客户端与门户会话服务
├── cas-server/            # 项目内置独立 CAS 认证中心（前后端一体，仅负责认证）
├── nginx.conf             # 服务器总入口，TLS 与多应用路由
└── docker-compose.yml     # 服务器总入口 Nginx
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

接入后，在门户 `homepage/.env` 中把该产品入口指向本系统 `/sso/login`，例如：

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

各产品入口通过 `homepage/.env` 中的 `VITE_*_URL` 配置。没有配置入口的产品
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
