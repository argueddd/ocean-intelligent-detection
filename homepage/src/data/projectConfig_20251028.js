// 项目配置文件 - 用户可以在这里修改所有展示内容

export const projectConfig = {
  // 基础项目信息
  basicInfo: {
    startTime: "2024.12",
    title: "智能合同审查系统",
    subtitle: "基于COT技术的文档智能分析",
    description: "利用Chain of Thought推理技术，实现合同条款的自动识别、风险分析和合规性检查。",
    features: ["COT推理", "条款匹配", "风险识别", "合规检查"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "95.2%",
    responseTime: "22.3s", 
    processingSpeed: "3页/分钟",
    stability: "99.8%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "8/10", percentage: 80, color: "#ffa500" },
    { label: "复杂度", value: "10/10", percentage: 100, color: "#00aaff" },
    { label: "可扩展性", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "维护成本", value: "4/10", percentage: 40, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "COT推理技术",
      frontDescription: "基于Chain of Thought的推理技术，通过分步骤思考解决复杂问题，提升智能体逻辑推理能力。",
      backTitle: "法律条款匹配", 
      backDescription: "自动分析合同条款，匹配相关法律法规，识别潜在风险点，提供专业的法律建议和合规指导。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 70 },
    { name: "JS", percentage: 25 },
    { name: "Others", percentage: 5 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture/网优智能体整体架构.png", // 从public/data/文件夹读取
  },

  // 功能模块
  modules: [
    {
      name: "文档解析",
      status: "active",
      description: "支持PDF、Word等多种格式的合同文档解析",
      endpoints: ["/api/parse", "/api/upload"]
    },
    {
      name: "智能分析", 
      status: "active",
      description: "基于COT技术的条款分析和风险识别",
      endpoints: ["/api/analyze", "/api/risk"]
    },
    {
      name: "报告生成",
      status: "active", 
      description: "自动生成专业的审查报告和建议",
      endpoints: ["/api/report", "/api/export"]
    }
  ],

  // 使用场景
  useCases: [
    "法律风险评估", 
    "合规性检查",
    "合同条款优化"
  ],


  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/contract-review/app/" // 跳转到demo页面
  }
};


export const projectConfig2 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.08",
    title: "文件检索智能体",
    subtitle: "基于RAG技术的智能客服助手",
    description: "利用Chain of Thought推理技术，实现合同条款的自动识别、风险分析和合规性检查。",
    features: ["COT推理", "条款匹配", "风险识别", "合规检查"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "95.2%",
    responseTime: "2.3s", 
    processingSpeed: "15页/分钟",
    stability: "99.8%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "8/10", percentage: 80, color: "#ffa500" },
    { label: "复杂度", value: "10/10", percentage: 100, color: "#00aaff" },
    { label: "可扩展性", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "维护成本", value: "4/10", percentage: 40, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "COT推理技术",
      frontDescription: "基于Chain of Thought的推理技术，通过分步骤思考解决复杂问题，提升智能体逻辑推理能力。",
      backTitle: "法律条款匹配", 
      backDescription: "自动分析合同条款，匹配相关法律法规，识别潜在风险点，提供专业的法律建议和合规指导。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 40 },
    { name: "Qwen", percentage: 35 },
    { name: "LangChain", percentage: 25 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "📄", label: "合同文档", type: "input" },
      { icon: "🧠", label: "COT推理", type: "process" },
      { icon: "📊", label: "审查报告", type: "output" }
    ],
    details: [
      { icon: "🔍", text: "条款匹配" },
      { icon: "⚖️", text: "风险识别" },
      { icon: "✅", text: "合规检查" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "文档解析",
      status: "active",
      description: "支持PDF、Word等多种格式的合同文档解析",
      endpoints: ["/api/parse", "/api/upload"]
    },
    {
      name: "智能分析", 
      status: "active",
      description: "基于COT技术的条款分析和风险识别",
      endpoints: ["/api/analyze", "/api/risk"]
    },
    {
      name: "报告生成",
      status: "active", 
      description: "自动生成专业的审查报告和建议",
      endpoints: ["/api/report", "/api/export"]
    }
  ],

  // 使用场景
  useCases: [
    "企业合同审查",
    "法律风险评估", 
    "合规性检查",
    "合同条款优化"
  ],


  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/contract-review/app/" // 跳转到demo页面
  }
};

export const projectConfig3 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.04",
    title: "内审智能体",
    subtitle: "基于RAG技术的智能客服助手",
    description: "利用Chain of Thought推理技术，实现合同条款的自动识别、风险分析和合规性检查。",
    features: ["COT推理", "条款匹配", "风险识别", "合规检查"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "95.2%",
    responseTime: "2.3s", 
    processingSpeed: "15页/分钟",
    stability: "99.8%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "8/10", percentage: 80, color: "#ffa500" },
    { label: "复杂度", value: "10/10", percentage: 100, color: "#00aaff" },
    { label: "可扩展性", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "维护成本", value: "4/10", percentage: 40, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "COT推理技术",
      frontDescription: "基于Chain of Thought的推理技术，通过分步骤思考解决复杂问题，提升智能体逻辑推理能力。",
      backTitle: "法律条款匹配", 
      backDescription: "自动分析合同条款，匹配相关法律法规，识别潜在风险点，提供专业的法律建议和合规指导。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 40 },
    { name: "Qwen", percentage: 35 },
    { name: "LangChain", percentage: 25 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "📄", label: "合同文档", type: "input" },
      { icon: "🧠", label: "COT推理", type: "process" },
      { icon: "📊", label: "审查报告", type: "output" }
    ],
    details: [
      { icon: "🔍", text: "条款匹配" },
      { icon: "⚖️", text: "风险识别" },
      { icon: "✅", text: "合规检查" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "文档解析",
      status: "active",
      description: "支持PDF、Word等多种格式的合同文档解析",
      endpoints: ["/api/parse", "/api/upload"]
    },
    {
      name: "智能分析", 
      status: "active",
      description: "基于COT技术的条款分析和风险识别",
      endpoints: ["/api/analyze", "/api/risk"]
    },
    {
      name: "报告生成",
      status: "active", 
      description: "自动生成专业的审查报告和建议",
      endpoints: ["/api/report", "/api/export"]
    }
  ],

  // 使用场景
  useCases: [
    "企业合同审查",
    "法律风险评估", 
    "合规性检查",
    "合同条款优化"
  ],


  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/contract-review/app/" // 跳转到demo页面
  }
};

export const projectConfig4 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.04",
    title: "规则稽核智能体",
    subtitle: "规则稽核智能体",
    description: "利用Chain of Thought推理技术，实现合同条款的自动识别、风险分析和合规性检查。",
    features: ["COT推理", "条款匹配", "风险识别", "合规检查"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "95.2%",
    responseTime: "2.3s", 
    processingSpeed: "15页/分钟",
    stability: "99.8%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "8/10", percentage: 80, color: "#ffa500" },
    { label: "复杂度", value: "10/10", percentage: 100, color: "#00aaff" },
    { label: "可扩展性", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "维护成本", value: "4/10", percentage: 40, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "COT推理技术",
      frontDescription: "基于Chain of Thought的推理技术，通过分步骤思考解决复杂问题，提升智能体逻辑推理能力。",
      backTitle: "法律条款匹配", 
      backDescription: "自动分析合同条款，匹配相关法律法规，识别潜在风险点，提供专业的法律建议和合规指导。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 40 },
    { name: "Qwen", percentage: 35 },
    { name: "LangChain", percentage: 25 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "📄", label: "合同文档", type: "input" },
      { icon: "🧠", label: "COT推理", type: "process" },
      { icon: "📊", label: "审查报告", type: "output" }
    ],
    details: [
      { icon: "🔍", text: "条款匹配" },
      { icon: "⚖️", text: "风险识别" },
      { icon: "✅", text: "合规检查" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "文档解析",
      status: "active",
      description: "支持PDF、Word等多种格式的合同文档解析",
      endpoints: ["/api/parse", "/api/upload"]
    },
    {
      name: "智能分析", 
      status: "active",
      description: "基于COT技术的条款分析和风险识别",
      endpoints: ["/api/analyze", "/api/risk"]
    },
    {
      name: "报告生成",
      status: "active", 
      description: "自动生成专业的审查报告和建议",
      endpoints: ["/api/report", "/api/export"]
    }
  ],

  // 使用场景
  useCases: [
    "企业合同审查",
    "法律风险评估", 
    "合规性检查",
    "合同条款优化"
  ],


  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/contract-review/app/" // 跳转到demo页面
  }
};



export const projectConfig5 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.04",
    title: "RAG知识库",
    subtitle: "基于智能文档处理的检索增强生成系统",
    description: "支持PDF文档的智能拆分与切片，构建高效可检索的知识库，提供精准的文档检索和知识查询服务。",
    features: ["PDF解析", "智能切片", "向量检索", "知识查询"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "96.8%",
    responseTime: "1.2s", 
    processingSpeed: "25页/分钟",
    stability: "99.9%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "6/10", percentage: 60, color: "#ffa500" },
    { label: "复杂度", value: "7/10", percentage: 70, color: "#00aaff" },
    { label: "可扩展性", value: "9/10", percentage: 90, color: "#00ff88" },
    { label: "维护成本", value: "3/10", percentage: 30, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "智能文档处理",
      frontDescription: "支持PDF文档的自动解析和智能拆分，实现文档内容的结构化处理和高效管理。",
      backTitle: "向量检索技术", 
      backDescription: "基于先进的向量化技术，实现文档内容的精准检索和相似度匹配，提升知识查询效率。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 45 },
    { name: "LangChain", percentage: 30 },
    { name: "向量数据库", percentage: 25 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "📄", label: "PDF文档", type: "input" },
      { icon: "✂️", label: "智能切片", type: "process" },
      { icon: "🔍", label: "知识检索", type: "output" }
    ],
    details: [
      { icon: "📊", text: "文档解析" },
      { icon: "🧩", text: "内容切片" },
      { icon: "🎯", text: "精准检索" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "文档上传",
      status: "active",
      description: "支持PDF格式文档上传和批量处理",
      endpoints: ["/api/upload", "/api/batch-upload"]
    },
    {
      name: "智能拆分", 
      status: "active",
      description: "基于内容的智能切片和段落划分",
      endpoints: ["/api/split", "/api/chunk"]
    },
    {
      name: "知识检索",
      status: "active", 
      description: "提供高效的文档检索和知识查询服务",
      endpoints: ["/api/search", "/api/query"]
    },
    {
      name: "配置管理",
      status: "active",
      description: "支持大模型参数配置和系统设置",
      endpoints: ["/api/config", "/api/settings"]
    }
  ],

  // 使用场景
  useCases: [
    "企业知识库构建",
    "文档内容检索", 
    "资料快速查询",
    "智能文档管理"
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/rag/app/" // 跳转到demo页面
  }
};

export const projectConfig6 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.10",
    title: "语音识别与分析",
    subtitle: "基于大模型的多语言语音处理系统",
    description: "借助先进的大模型能力实现语音文件到文字的精准转换，并支持多语言方言识别和深度文本分析。",
    features: ["多语言识别", "方言支持", "语音转写", "文本分析"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "97.5%",
    responseTime: "1.8s", 
    processingSpeed: "实时处理",
    stability: "99.7%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "9/10", percentage: 90, color: "#ffa500" },
    { label: "复杂度", value: "8/10", percentage: 80, color: "#00aaff" },
    { label: "可扩展性", value: "7/10", percentage: 70, color: "#00ff88" },
    { label: "维护成本", value: "5/10", percentage: 50, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "多语言语音识别",
      frontDescription: "支持普通话、粤语、维吾尔语及多种地区方言的高精度语音转文字，适应不同语言环境需求。",
      backTitle: "深度文本分析", 
      backDescription: "对转换后的文字内容进行语义分析、情感识别和关键信息提取，提供全面的语音内容洞察。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 50 },
    { name: "Whisper", percentage: 30 },
    { name: "大语言模型", percentage: 20 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "🎤", label: "语音输入", type: "input" },
      { icon: "🔊", label: "语音识别", type: "process" },
      { icon: "📝", label: "文本分析", type: "output" }
    ],
    details: [
      { icon: "🌐", text: "多语言支持" },
      { icon: "🗣️", text: "方言识别" },
      { icon: "📊", text: "内容分析" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "语音转写",
      status: "active",
      description: "支持多种音频格式的语音转文字功能",
      endpoints: ["/api/transcribe", "/api/upload-audio"]
    },
    {
      name: "方言识别", 
      status: "active",
      description: "识别粤语、维吾尔语及多种地区方言",
      endpoints: ["/api/dialect", "/api/detect-language"]
    },
    {
      name: "文本分析",
      status: "active", 
      description: "对转换文本进行语义分析和情感识别",
      endpoints: ["/api/analyze", "/api/sentiment"]
    },
    {
      name: "批量处理",
      status: "active",
      description: "支持批量语音文件的自动化处理",
      endpoints: ["/api/batch-process", "/api/queue"]
    }
  ],

  // 使用场景
  useCases: [
    "会议录音转写",
    "客服语音分析", 
    "多语言内容处理",
    "方言语音识别"
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/voice/app/" // 跳转到demo页面
  }
};

export const projectConfig7 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.04",
    title: "咸鱼智能监控机器人",
    subtitle: "基于智能推荐算法的商品监控系统",
    description: "通过创建监控任务自动扫描咸鱼平台商品，实时追踪价格变化并智能推荐符合要求的优质商品。",
    features: ["商品监控", "价格追踪", "智能推荐", "自动扫描"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "93.8%",
    responseTime: "1.5s", 
    processingSpeed: "1000+商品/分钟",
    stability: "99.5%"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "6/10", percentage: 60, color: "#ffa500" },
    { label: "复杂度", value: "7/10", percentage: 70, color: "#00aaff" },
    { label: "可扩展性", value: "9/10", percentage: 90, color: "#00ff88" },
    { label: "维护成本", value: "5/10", percentage: 50, color: "#ff6b6b" }
  ],

  // 核心技能
  skills: [
    {
      frontTitle: "智能商品监控",
      frontDescription: "基于商品描述信息自动创建监控任务，实时扫描咸鱼平台商品动态，精准捕捉目标商品。",
      backTitle: "个性化推荐算法", 
      backDescription: "运用智能推荐算法分析商品匹配度，自动筛选符合监控要求的优质商品，提升购物效率。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 45 },
    { name: "爬虫框架", percentage: 30 },
    { name: "推荐算法", percentage: 25 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png", // 从public/data/文件夹读取
    nodes: [
      { icon: "🛒", label: "商品监控", type: "input" },
      { icon: "🔍", label: "自动扫描", type: "process" },
      { icon: "📈", label: "智能推荐", type: "output" }
    ],
    details: [
      { icon: "🎯", text: "目标匹配" },
      { icon: "💰", text: "价格追踪" },
      { icon: "⭐", text: "优质筛选" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "任务创建",
      status: "active",
      description: "支持基于商品描述的监控任务创建和管理",
      endpoints: ["/api/task/create", "/api/task/manage"]
    },
    {
      name: "商品扫描", 
      status: "active",
      description: "自动扫描咸鱼平台商品信息并实时更新",
      endpoints: ["/api/scan", "/api/update"]
    },
    {
      name: "智能推荐",
      status: "active", 
      description: "基于监控要求智能推荐匹配商品",
      endpoints: ["/api/recommend", "/api/match"]
    }
  ],

  // 使用场景
  useCases: [
    "二手商品监控",
    "价格趋势追踪", 
    "优质商品发现"
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4", // 从public/data/文件夹读取
    demoUrl: "/goofish/monitor/app/" // 跳转到demo页面
  }
};


// 项目数据模板 - 用户可以复制这个模板创建新项目
export const projectTemplate = {
  basicInfo: {
    startTime: "2024.XX",
    title: "项目名称",
    subtitle: "项目副标题",
    description: "项目描述",
    features: ["特性1", "特性2", "特性3"]
  },
  performance: {
    accuracy: "XX%",
    responseTime: "X.Xs",
    processingSpeed: "XX页/分钟", 
    stability: "XX%"
  },
  evaluation: [
    { label: "维度1", value: "5/10", percentage: 50, color: "#00aaff" }
  ],
  skills: [
    {
      frontTitle: "技能标题",
      frontDescription: "技能描述"
    }
  ],
  techStack: [
    { name: "技术名称", percentage: 50 }
  ],
  architecture: {
    imagePath: "/data/project_architecture.png",
    nodes: [],
    details: []
  },
  modules: [],
  useCases: [],
  media: {
    videoPath: "/data/project_demo.mp4",
    demoUrl: "/project/demo/"
  }
};
