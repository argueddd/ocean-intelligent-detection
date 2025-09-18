// 项目配置文件 - 用户可以在这里修改所有展示内容

export const projectConfig = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.12",
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
    startTime: "2025.12",
    title: "智能客服系统",
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
    startTime: "21999.0",
    title: "智能客服系统",
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
