# 多智能体展示页面

## 快速启动

```bash
# 使用启动脚本
./start.sh

# 或直接使用docker-compose
docker-compose up --build
```

## 访问地址

- 🌐 **主页**: http://localhost

## 特性

- ✅ **代码热重载**: 修改 `homepage/src/` 下文件自动刷新
- ✅ **代码挂载**: 源码直接挂载到容器，无需重新构建
- ✅ **WebSocket支持**: 支持React热重载
- ✅ **统一代理**: 所有请求通过Nginx代理

## 文件结构

```
agent_showcase_homepage/
├── docker-compose.yml      # Docker配置
├── nginx.conf             # Nginx代理配置
├── start.sh               # 启动脚本
└── homepage/
    ├── Dockerfile         # 开发环境Dockerfile
    ├── src/               # React源码 (挂载)
    └── public/            # 静态资源 (挂载)
```

## 开发工作流

1. **启动服务**: `./start.sh`
2. **修改代码**: 编辑 `homepage/src/` 下文件
3. **查看效果**: 浏览器自动刷新
4. **停止服务**: `docker-compose down`

## 挂载目录

- `./homepage/src/` → `/app/src/`
- `./homepage/public/` → `/app/public/`
- `./homepage/package.json` → `/app/package.json`

修改这些目录下的文件会立即生效，无需重新构建Docker镜像。
