# 🚀 快速配置指南

## 📝 如何更新项目信息

### 1. 修改当前项目信息

编辑 `homepage/src/data/projectConfig.js`：

```javascript
export const projectConfig = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.05",                    // ← 修改启动时间
    title: "智能合同审查系统",                // ← 修改项目标题
    subtitle: "基于COT技术的文档智能分析",    // ← 修改副标题
    description: "利用Chain of Thought推理技术...", // ← 修改描述
    features: ["COT推理", "条款匹配", "风险识别", "合规检查"] // ← 修改特性
  },

  // 智能体性能指标
  performance: {
    accuracy: "95.2%",        // ← 修改准确率
    responseTime: "2.3s",     // ← 修改响应时间
    processingSpeed: "15页/分钟", // ← 修改处理速度
    stability: "99.8%"        // ← 修改稳定性
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "8/10", percentage: 80, color: "#ffa500" },
    { label: "复杂度", value: "10/10", percentage: 100, color: "#00aaff" },
    { label: "可扩展性", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "维护成本", value: "4/10", percentage: 40, color: "#ff6b6b" }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 40 },    // ← 修改技术栈占比
    { name: "Qwen", percentage: 35 },
    { name: "LangChain", percentage: 25 }
  ],

  // 功能模块
  modules: [
    {
      name: "文档解析",         // ← 修改模块名称
      status: "active",
      description: "支持PDF、Word等多种格式...", // ← 修改模块描述
      endpoints: ["/api/parse", "/api/upload"]  // ← 修改API端点
    }
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // ← 修改演示视频路径
    demoUrl: "/contract-review/app/" // ← 修改跳转链接
  }
};
```

### 2. 保存并重启

```bash
cd homepage
npm start
```

## 🏷️ 如何添加新项目到标签页2

### 步骤1：创建新项目配置

在 `homepage/src/data/projectConfig.js` 中添加新项目配置：

```javascript
export const projects = [
  // ... 现有项目
  {
    title: "智能客服 Agent",
    description: "基于RAG技术的智能客服系统，具备多轮对话能力，能够理解用户意图并提供准确的回答。",
    features: ["RAG检索", "多轮对话", "情感分析", "个性化服务"],
    videoUrl: "/data/customer_service_demo.mp4",
    progress: 88,
    achievements: [
      "客服效率提升 60%",
      "客户满意度 95%",
      "支持 24/7 服务",
      "多语言支持"
    ],
    techTags: ["OpenAI", "LangChain", "Python", "FastAPI", "Redis"],
    scenarioTags: ["在线客服", "技术支持", "产品咨询", "投诉处理"],
    featureTags: ["智能问答", "情感分析", "多轮对话", "知识库"],
    demoUrl: "/customer-service/demo/",
    
    // 智能体指标
    agentMetrics: {
      applicationType: "问答类应用",
      computingPower: "低",
      modelSize: "3B",
      responseTime: "1.2s",
      accuracy: "92%",
      processingSpeed: "100次/分钟"
    },
    
    // 功能模块
    modules: [
      {
        name: "对话管理",
        status: "运行中",
        description: "管理多轮对话流程和上下文",
        endpoints: ["/api/chat", "/api/context"]
      },
      {
        name: "情感分析",
        status: "运行中", 
        description: "实时分析用户情感和意图",
        endpoints: ["/api/sentiment", "/api/intent"]
      },
      {
        name: "知识库",
        status: "运行中",
        description: "智能检索和问答系统",
        endpoints: ["/api/search", "/api/qa"]
      }
    ],
    
    // 使用场景
    useCases: [
      {
        title: "在线客服",
        description: "7x24小时智能客服，处理常见问题"
      },
      {
        title: "技术支持",
        description: "提供技术问题解答和故障排除"
      },
      {
        title: "产品咨询",
        description: "产品功能介绍和购买建议"
      },
      {
        title: "投诉处理",
        description: "处理客户投诉和建议"
      }
    ]
  }
];
```

### 步骤2：添加媒体文件

```bash
# 复制架构图
cp your_customer_service_architecture.png homepage/public/data/customer_service_architecture.png

# 复制演示视频
cp your_customer_service_demo.mp4 homepage/public/data/customer_service_demo.mp4
```

## 📁 如何上传数据

### 1. 架构图上传

```bash
# 方法1：直接复制
cp /path/to/your/architecture.png homepage/public/data/architecture.png

# 方法2：重命名
mv your_image.png homepage/public/data/architecture.png

# 支持的格式：PNG, JPG, SVG
# 建议尺寸：800x400像素
```

### 2. 演示视频上传

```bash
# 复制视频文件
cp /path/to/your/demo.mp4 homepage/public/data/demo.mp4

# 支持的格式：MP4, WebM, OGV
# 建议时长：30-60秒
# 建议大小：< 10MB
```

### 3. 多项目文件管理

```bash
# 项目1文件
cp project1_arch.png homepage/public/data/architecture.png
cp project1_video.mp4 homepage/public/data/demo.mp4

# 项目2文件
cp project2_arch.png homepage/public/data/customer_service_architecture.png
cp project2_video.mp4 homepage/public/data/customer_service_demo.mp4
```

## 🐳 如何打包和部署

### 1. 开发环境测试

```bash
cd homepage
npm install
npm start
# 访问 http://localhost:3000
```

### 2. 生产环境构建

```bash
cd homepage
npm run build
# 生成 build/ 目录
```

### 3. Docker打包

```bash
# 创建Docker网络
docker network create proxy-tier

# 构建并运行
docker-compose up --build

# 或者只构建前端
docker build -t agent-showcase ./homepage
docker run -p 3000:80 agent-showcase
```

### 4. 部署到服务器

```bash
# 上传整个项目到服务器
scp -r agent_showcase_homepage/ user@server:/path/to/project/

# 在服务器上运行
ssh user@server
cd /path/to/project/agent_showcase_homepage
docker network create proxy-tier
docker-compose up -d --build
```

## 🔧 常用命令

### 开发命令

```bash
# 启动开发服务器
npm start

# 构建生产版本
npm run build

# 运行测试
npm test

# 代码检查
npm run lint
```

### Docker命令

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up

# 后台运行
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重新构建
docker-compose up --build
```

### 清理命令

```bash
# 清理Docker缓存
docker system prune -a

# 清理npm缓存
npm cache clean --force

# 删除node_modules重新安装
rm -rf node_modules package-lock.json
npm install
```

## ⚡ 快速修改清单

### 修改项目信息
- [ ] 编辑 `homepage/src/data/projectConfig.js`
- [ ] 修改 `basicInfo` 部分
- [ ] 修改 `performance` 数据
- [ ] 修改 `techStack` 占比
- [ ] 重启 `npm start`

### 添加新项目
- [ ] 创建 `projectConfig2` 配置
- [ ] 修改 `App.js` 中的 `projects` 数组
- [ ] 上传对应的媒体文件
- [ ] 测试新项目显示

### 上传媒体文件
- [ ] 准备架构图（PNG/JPG，800x400）
- [ ] 准备演示视频（MP4，30-60秒）
- [ ] 复制到 `homepage/public/data/` 目录
- [ ] 更新配置文件中的路径

### 部署到生产
- [ ] 运行 `npm run build`
- [ ] 创建Docker网络
- [ ] 运行 `docker-compose up --build`
- [ ] 检查 http://localhost 访问

## 🆘 故障排除

### 图片不显示
```bash
# 检查文件是否存在
ls -la homepage/public/data/

# 检查文件名是否正确
# 确保路径以 /data/ 开头
```

### 视频无法播放
```bash
# 检查文件格式
file homepage/public/data/demo.mp4

# 检查文件大小
ls -lh homepage/public/data/demo.mp4
```

### Docker构建失败
```bash
# 查看详细错误
docker-compose logs

# 清理并重建
docker-compose down
docker-compose build --no-cache
```

---

**提示**: 每次修改配置后记得重启开发服务器或重新构建Docker镜像！
