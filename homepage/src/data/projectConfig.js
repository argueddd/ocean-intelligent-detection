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
    startTime: "2025.09",
    title: "规则学习智能体",
    subtitle: "稽核点生成与匹配助手",
    description:
      "该智能体能够自动学习和解析规则文档，生成标准化的稽核点，并在实际业务场景中快速匹配最相关的稽核点，帮助用户理解规则要点和应用范围。",
    features: [
      "稽核点生成",
      "规则标准化",
      "稽核点理解",
      "场景匹配",
      "结果输出"
    ]
  },

  // 智能体性能指标（更贴近“稽核点”应用）
  performance: {
    pointCoverage: "支持生成 95%+ 规则稽核点",
    responseTime: "秒级响应",
    matchingAccuracy: "稽核点匹配准确率 92%",
    stability: "全年稳定率 99.9%"
  },

  // 应用维度评估
  evaluation: [
    { label: "准确性", value: "9/10", percentage: 90, color: "#00aaff" },
    { label: "覆盖度", value: "8/10", percentage: 80, color: "#00ff88" },
    { label: "可解释性", value: "9/10", percentage: 90, color: "#ffa500" },
    { label: "维护成本", value: "5/10", percentage: 50, color: "#ff6b6b" }
  ],

  // 核心能力
  skills: [
    {
      frontTitle: "稽核点生成",
      frontDescription:
        "从规则、条文、制度等文档中抽取关键信息，生成可管理的稽核点。",
      backTitle: "规则标准化",
      backDescription:
        "将零散条文转化为结构化的稽核点集合，便于存储和调用。"
    },
    {
      frontTitle: "稽核点理解",
      frontDescription:
        "对用户输入的需求或描述进行解析，识别对应的稽核点。",
      backTitle: "多维度解释",
      backDescription:
        "结合语义理解，输出稽核点的适用范围、限制条件和说明。"
    },
    {
      frontTitle: "场景匹配",
      frontDescription:
        "在具体场景中调用最相关的稽核点，形成针对性的匹配结果。",
      backTitle: "结果输出",
      backDescription:
        "以清晰直观的方式展示适用的稽核点，支持导出或二次应用。"
    }
  ],

  // 技术栈占比
  techStack: [
    { name: "Python", percentage: 35 },
    { name: "大语言模型", percentage: 30 },
    { name: "知识库/数据库", percentage: 25 },
    { name: "前端可视化", percentage: 10 }
  ],

  // 系统架构图
  architecture: {
    imagePath: "/data/architecture.png",
    nodes: [
      { icon: "📄", label: "规则文档", type: "input" },
      { icon: "🤖", label: "规则学习智能体", type: "process" },
      { icon: "📌", label: "稽核点生成", type: "process" },
      { icon: "📚", label: "稽核点库", type: "storage" },
      { icon: "📊", label: "匹配结果", type: "output" }
    ],
    details: [
      { icon: "📝", text: "稽核点生成" },
      { icon: "🔍", text: "稽核点理解" },
      { icon: "📌", text: "场景匹配" },
      { icon: "📑", text: "结果输出" }
    ]
  },

  // 功能模块
  modules: [
    {
      name: "规则解析",
      status: "active",
      description: "支持多种文档格式，自动解析并提取稽核点",
      endpoints: ["/api/parse", "/api/upload"]
    },
    {
      name: "稽核点生成",
      status: "active",
      description: "将条文转化为结构化稽核点，并入库管理",
      endpoints: ["/api/generate", "/api/store"]
    },
    {
      name: "稽核点匹配",
      status: "active",
      description: "根据输入场景或需求，匹配最相关的稽核点",
      endpoints: ["/api/match", "/api/query"]
    },
    {
      name: "结果输出",
      status: "active",
      description: "以直观的方式展示匹配稽核点，支持导出或接口调用",
      endpoints: ["/api/result", "/api/export"]
    }
  ],

  // 使用场景
  useCases: [
    "合同条款稽核点生成",
    "政策法规稽核点提炼",
    "营销活动合规要点抽取",
    "内部制度稽核点管理",
    "场景化稽核点匹配与输出"
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo.mp4",
    demoUrl: "/rule-learning/app/"
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
