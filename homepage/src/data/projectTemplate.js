// 新项目配置模板
// 将此模板添加到 homepage/src/data/projects.js 的 projects 数组中

export const newProjectTemplate = {
  title: "新项目名称",
  description: "详细的项目描述，介绍项目的核心功能和价值...",
  features: ["特性1", "特性2", "特性3", "特性4"],
  videoUrl: "/data/new_project_demo.mp4",
  progress: XX, // 进度百分比 (0-100)
  achievements: [
    "成就描述1",
    "成就描述2", 
    "成就描述3",
    "成就描述4"
  ],
  techTags: ["技术1", "技术2", "技术3", "技术4", "技术5"],
  scenarioTags: ["场景1", "场景2", "场景3", "场景4"],
  featureTags: ["功能1", "功能2", "功能3", "功能4"],
  demoUrl: "/new-project/demo/",
  
  // 智能体特有指标
  agentMetrics: {
    applicationType: "应用类型", // 如：流程类应用、问答类应用等
    computingPower: "算力等级", // 如：低、中等、高
    modelSize: "XXB", // 模型大小，如：3B、7B、13B
    trainingData: "XXGB", // 训练数据大小
    responseTime: "X.Xs", // 响应时间
    accuracy: "XX%", // 准确率
    processingSpeed: "XX次/分钟" // 处理速度
  },
  
  // 技能评分 (0-100)
  skills: {
    "技能1": XX,
    "技能2": XX,
    "技能3": XX,
    "技能4": XX,
    "技能5": XX,
    "技能6": XX
  },
  
  // 软件/技术熟练度
  techProficiency: {
    "技术1": XX,
    "技术2": XX,
    "技术3": XX,
    "技术4": XX,
    "技术5": XX,
    "技术6": XX
  },
  
  // 项目发展历程
  developmentTimeline: [
    {
      year: "2024.XX",
      title: "里程碑1",
      description: "里程碑描述"
    },
    {
      year: "2024.XX", 
      title: "里程碑2",
      description: "里程碑描述"
    },
    {
      year: "2024.XX",
      title: "里程碑3",
      description: "里程碑描述"
    }
  ],
  
  // 个人标签
  personalTags: [
    "标签1", "标签2", "标签3", "标签4", 
    "标签5", "标签6", "标签7", "标签8",
    "标签9", "标签10", "标签11", "标签12"
  ],
  
  // 技术选型详情
  techStack: {
    primaryModel: "主要模型",
    reasoningEngine: "推理引擎",
    vectorDatabase: "向量数据库",
    framework: "框架",
    deployment: "部署方式"
  },
  
  // 系统功能模块
  modules: [
    {
      name: "模块名称1",
      status: "运行中",
      description: "模块功能描述",
      endpoints: ["/api/endpoint1", "/api/endpoint2"]
    },
    {
      name: "模块名称2",
      status: "运行中", 
      description: "模块功能描述",
      endpoints: ["/api/endpoint3", "/api/endpoint4"]
    },
    {
      name: "模块名称3",
      status: "运行中",
      description: "模块功能描述",
      endpoints: ["/api/endpoint5", "/api/endpoint6"]
    }
  ],
  
  // 系统架构信息
  architecture: {
    frontend: "前端技术栈",
    backend: "后端技术栈",
    database: "数据库技术",
    ai: "AI技术",
    infrastructure: "基础设施"
  },
  
  // API统计
  apiStats: {
    totalEndpoints: XX,
    activeConnections: XX,
    avgResponseTime: "XXms",
    successRate: "XX%",
    dailyRequests: XXXXX
  },
  
  // 使用场景详情
  useCases: [
    {
      title: "使用场景1",
      description: "场景详细描述",
      usage: "使用情况说明"
    },
    {
      title: "使用场景2",
      description: "场景详细描述",
      usage: "使用情况说明"
    },
    {
      title: "使用场景3",
      description: "场景详细描述",
      usage: "使用情况说明"
    }
  ]
};

// 使用说明：
// 1. 复制此模板到 homepage/src/data/projects.js
// 2. 修改所有 XX 占位符为实际值
// 3. 更新所有中文描述为实际内容
// 4. 准备对应的媒体文件（架构图和演示视频）
// 5. 将新项目添加到 projects 数组中
