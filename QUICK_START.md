# 本地单点登录快速启动

需要同时启动三个进程：mock CAS、门户认证后端和门户前端。

## mock CAS

```bash
cd mock-cas-server
.venv/bin/python app.py
```

监听端口：`9000`。

## 门户认证后端

```bash
cd agent_showcase_homepage/portal-auth
.venv/bin/python app.py
```

监听端口：`9010`。

## 门户前端

```bash
cd agent_showcase_homepage/homepage
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
