export const projects = [
  {
    title: "合同审查 Agent",
    description: "基于COT技术的智能合同审查系统，学习了多种企业规范与法律法规，能够自动分析合同、匹配规范条款并逐项排查，最终产出专业结论。",
    features: ["COT推理", "法律条款匹配", "自动排查", "结论生成"],
    videoUrl: "https://sample-videos.com/zip/10/mp4/SampleVideo_1280x720_1mb.mp4",
    progress: 92,
    achievements: [
      "审查准确率 95%",
      "处理速度提升 80%", 
      "支持 50+ 合同类型",
      "节省人力成本 70%"
    ],
    techTags: ["Qwen", "DeepSeek", "Python", "FastAPI", "LangChain", "VectorDB"],
    scenarioTags: ["合同审查", "法律分析", "合规检查", "风险评估"],
    featureTags: ["COT推理", "条款匹配", "自动排查", "智能结论"],
    demoUrl: "/contract-review/app/chatbot",
    
    // 智能体特有指标
    agentMetrics: {
      applicationType: "流程类应用",
      computingPower: "中等",
      modelSize: "7B",
      trainingData: "50GB",
      responseTime: "2.3s",
      accuracy: "95%",
      processingSpeed: "15页/分钟"
    },
    
    // 技能评分 (0-100)
    skills: {
      "COT推理": 95,
      "法律条款匹配": 90,
      "自动排查": 88,
      "结论生成": 92,
      "合规检查": 85,
      "风险评估": 80
    },
    
    // 软件/技术熟练度
    techProficiency: {
      "Qwen": 90,
      "DeepSeek": 85,
      "Python": 88,
      "LangChain": 82,
      "FastAPI": 85,
      "VectorDB": 75
    },
    
    // 项目发展历程
    developmentTimeline: [
      {
        year: "2024.01",
        title: "项目启动",
        description: "开始研究COT技术在合同审查中的应用"
      },
      {
        year: "2024.03", 
        title: "模型训练",
        description: "完成50GB法律文本数据的模型训练"
      },
      {
        year: "2024.06",
        title: "系统集成",
        description: "集成向量数据库和API接口"
      },
      {
        year: "2024.09",
        title: "上线测试",
        description: "在真实业务场景中进行测试验证"
      },
      {
        year: "2024.12",
        title: "正式发布",
        description: "达到95%准确率，正式投入生产使用"
      }
    ],
    
    // 个人标签
    personalTags: [
      "AI工程师", "法律科技", "COT专家", "Python开发", 
      "机器学习", "合规专家", "系统架构", "产品设计",
      "团队协作", "持续学习", "技术创新", "业务理解"
    ],
    
    // 技术选型详情
    techStack: {
      primaryModel: "Qwen2.5-7B",
      reasoningEngine: "COT",
      vectorDatabase: "Chroma",
      framework: "LangChain",
      deployment: "FastAPI + Docker"
    },
    
    // 应用场景
    useCases: [
      {
        title: "合同审查",
        description: "自动分析各类合同，匹配法律条款，识别风险点，生成专业审查报告"
      },
      {
        title: "合规检查", 
        description: "基于企业规范和法律法规，逐项排查合同合规性，确保业务合规"
      },
      {
        title: "风险评估",
        description: "识别合同中的潜在风险，提供风险等级评估和改善建议"
      }
    ],
    // 新增：系统功能模块
    modules: [
      {
        name: "对话管理",
        status: "运行中",
        description: "多轮对话上下文管理",
        endpoints: ["/chat", "/context", "/history"]
      },
      {
        name: "知识库检索",
        status: "运行中", 
        description: "RAG向量检索系统",
        endpoints: ["/search", "/embed", "/index"]
      },
      {
        name: "情感分析",
        status: "运行中",
        description: "实时情感识别与响应",
        endpoints: ["/sentiment", "/emotion", "/tone"]
      },
      {
        name: "多语言支持",
        status: "运行中",
        description: "50+语言实时翻译",
        endpoints: ["/translate", "/detect", "/localize"]
      }
    ],
    // 新增：系统架构信息
    architecture: {
      frontend: "React + TypeScript + Ant Design",
      backend: "FastAPI + Python 3.11",
      database: "PostgreSQL + Redis",
      ai: "OpenAI GPT-4 + Embeddings",
      infrastructure: "Docker + Kubernetes"
    },
    // 新增：API统计
    apiStats: {
      totalEndpoints: 24,
      activeConnections: 156,
      avgResponseTime: "120ms",
      successRate: "99.2%",
      dailyRequests: 15420
    },
    // 新增：使用场景详情
    useCases: [
      {
        title: "在线客服",
        description: "7x24小时智能客服，处理常见问题",
        usage: "日均处理5000+咨询"
      },
      {
        title: "知识问答",
        description: "基于企业知识库的智能问答",
        usage: "覆盖产品、政策、流程等"
      },
      {
        title: "情感支持",
        description: "识别客户情绪，提供个性化服务",
        usage: "情感识别准确率94%"
      }
    ]
  },
  {
    title: "智能客服 Agent",
    description: "基于RAG技术的智能客服系统，具备多轮对话能力，能够理解用户意图并提供准确的回答，支持情感分析和个性化服务。",
    features: ["RAG检索", "多轮对话", "情感分析", "个性化服务"],
    videoUrl: "https://sample-videos.com/zip/10/mp4/SampleVideo_1280x720_2mb.mp4",
    progress: 88,
    
    // 智能体特有指标
    agentMetrics: {
      applicationType: "问答类应用",
      computingPower: "低",
      modelSize: "3B",
      trainingData: "20GB",
      responseTime: "1.2s",
      accuracy: "92%",
      processingSpeed: "100次/分钟"
    },
    
    // 技术选型详情
    techStack: {
      primaryModel: "Qwen2.5-3B",
      reasoningEngine: "RAG",
      vectorDatabase: "Milvus",
      framework: "LangChain",
      deployment: "FastAPI + Redis"
    },
    achievements: [
      "文档解析准确率 95%",
      "支持 10+ 文件格式",
      "批量处理效率提升 50%",
      "智能摘要生成"
    ],
    techTags: ["OCR", "NLP", "Vue.js", "Node.js", "MongoDB", "Docker"],
    scenarioTags: ["文档处理", "信息提取", "智能摘要", "知识管理"],
    featureTags: ["批量处理", "多格式", "高精度", "云部署"],
    demoUrl: "/contract-review/app/document",
    modules: [
      {
        name: "文档解析",
        status: "运行中",
        description: "支持PDF、Word、Excel等格式解析",
        endpoints: ["/parse", "/extract", "/convert"]
      },
      {
        name: "OCR识别",
        status: "运行中",
        description: "图像文字识别与转换",
        endpoints: ["/ocr", "/recognize", "/preprocess"]
      },
      {
        name: "智能摘要",
        status: "运行中",
        description: "自动生成文档摘要",
        endpoints: ["/summarize", "/abstract", "/keypoints"]
      },
      {
        name: "知识提取",
        status: "运行中",
        description: "结构化信息提取",
        endpoints: ["/extract", "/entities", "/relations"]
      }
    ],
    architecture: {
      frontend: "Vue.js + Element UI + TypeScript",
      backend: "Node.js + Express + Python",
      database: "MongoDB + Redis + Elasticsearch",
      ai: "Tesseract OCR + spaCy NLP",
      infrastructure: "Docker + Kubernetes + MinIO"
    },
    apiStats: {
      totalEndpoints: 18,
      activeConnections: 89,
      avgResponseTime: "850ms",
      successRate: "96.8%",
      dailyRequests: 8750
    },
    useCases: [
      {
        title: "合同审查",
        description: "自动解析合同条款，提取关键信息",
        usage: "处理1000+合同/天"
      },
      {
        title: "文档归档",
        description: "批量处理历史文档，建立知识库",
        usage: "支持10+文档格式"
      },
      {
        title: "智能问答",
        description: "基于文档内容的智能问答系统",
        usage: "准确率95%"
      }
    ]
  },
  {
    title: "数据分析 Agent",
    description: "智能数据分析平台，提供实时数据处理、可视化展示和预测建模功能，支持自动化报告生成和业务洞察发现。",
    features: ["实时分析", "数据可视化", "预测建模", "自动化报告"],
    progress: 90,
    achievements: [
      "数据可视化效率提升 40%",
      "支持实时数据流",
      "自动化报告生成",
      "预测准确率 85%"
    ],
    techTags: ["Python", "Pandas", "D3.js", "TensorFlow", "Redis", "Kafka"],
    scenarioTags: ["数据分析", "可视化", "预测建模", "实时监控"],
    featureTags: ["实时分析", "可视化", "自动化", "预测"],
    demoUrl: "/contract-review/app/analytics"
  },
  {
    title: "代码助手 Agent",
    description: "智能代码助手系统，支持多种编程语言的代码生成、Bug检测和重构建议，提供代码质量评估和版本控制集成功能。",
    features: ["代码生成", "Bug检测", "重构建议", "质量评估"],
    progress: 80,
    achievements: [
      "代码生成效率提升 60%",
      "支持 20+ 编程语言",
      "Bug 检测准确率 90%",
      "代码质量评估"
    ],
    techTags: ["CodeT5", "AST", "VS Code", "TypeScript", "GitHub API", "Docker"],
    scenarioTags: ["代码生成", "Bug 检测", "重构建议", "代码审查"],
    featureTags: ["多语言", "智能提示", "质量检测", "版本控制"],
    demoUrl: "/contract-review/app/code-assistant"
  },
  {
    title: "翻译助手 Agent",
    description: "智能翻译助手系统，支持50+种语言的实时翻译，具备语音识别、专业术语识别和高精度翻译功能。",
    features: ["多语言翻译", "语音识别", "实时翻译", "专业术语"],
    progress: 95,
    achievements: [
      "支持 50+ 语言翻译",
      "翻译准确率 98%",
      "实时翻译延迟 < 200ms",
      "上下文理解增强"
    ],
    techTags: ["Transformer", "BERT", "React", "Express", "PostgreSQL", "Redis"],
    scenarioTags: ["实时翻译", "文档翻译", "语音翻译", "专业术语"],
    featureTags: ["多语言", "高精度", "实时性", "上下文"],
    demoUrl: "/contract-review/app/translator"
  },
  {
    title: "图像识别 Agent",
    progress: 70,
    achievements: [
      "图像识别准确率 96%",
      "支持多种图像格式",
      "实时处理能力",
      "物体检测与分类"
    ],
    techTags: ["YOLO", "OpenCV", "Flask", "TensorFlow", "MySQL", "Nginx"],
    scenarioTags: ["物体检测", "图像分类", "OCR识别", "人脸识别"],
    featureTags: ["高精度", "实时处理", "多格式", "可扩展"],
    demoUrl: "/contract-review/app/image-recognition"
  },
  {
    title: "语音助手 Agent",
    progress: 65,
    achievements: [
      "语音识别准确率 94%",
      "支持多语言语音",
      "实时语音转换",
      "情感语音合成"
    ],
    techTags: ["Whisper", "TTS", "WebRTC", "Node.js", "Socket.io", "FFmpeg"],
    scenarioTags: ["语音识别", "语音合成", "实时对话", "语音控制"],
    featureTags: ["多语言", "实时性", "情感表达", "噪声抑制"],
    demoUrl: "/contract-review/app/voice-assistant"
  },
  {
    title: "推荐系统 Agent",
    progress: 88,
    achievements: [
      "推荐准确率 87%",
      "用户点击率提升 35%",
      "实时推荐更新",
      "多维度推荐"
    ],
    techTags: ["Collaborative Filtering", "Deep Learning", "Spark", "Kafka", "Cassandra", "Redis"],
    scenarioTags: ["个性化推荐", "内容推荐", "商品推荐", "社交推荐"],
    featureTags: ["实时推荐", "个性化", "多维度", "可扩展"],
    demoUrl: "/contract-review/app/recommendation"
  },
  {
    title: "监控告警 Agent",
    progress: 92,
    achievements: [
      "系统监控覆盖率 99%",
      "告警响应时间 < 1分钟",
      "误报率降低 80%",
      "自动化故障处理"
    ],
    techTags: ["Prometheus", "Grafana", "AlertManager", "Python", "InfluxDB", "Kubernetes"],
    scenarioTags: ["系统监控", "性能监控", "日志分析", "故障预警"],
    featureTags: ["实时监控", "智能告警", "自动化", "可视化"],
    demoUrl: "/contract-review/app/monitoring"
  },
  {
    title: "自动化测试 Agent",
    progress: 78,
    achievements: [
      "测试覆盖率提升 60%",
      "测试执行效率提升 45%",
      "Bug 发现率提升 30%",
      "自动化测试报告"
    ],
    techTags: ["Selenium", "Jest", "Cypress", "Jenkins", "Docker", "Allure"],
    scenarioTags: ["UI测试", "API测试", "性能测试", "回归测试"],
    featureTags: ["自动化", "全覆盖", "持续集成", "智能报告"],
    demoUrl: "/contract-review/app/testing"
  }
];
