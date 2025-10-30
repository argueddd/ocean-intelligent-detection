// 项目配置文件 - 用户可以在这里修改所有展示内容

export const projectConfig = {
  // 基础项目信息
  basicInfo: {
    startTime: "2024.12",
    projectTime: "30周",
    title: "合同稽核智能体",
    subtitle: "智能合同稽核与风险识别系统",
    description: "基于Chain of Thought推理与OCR语义融合技术，实现合同条款风险点自动识别、异常分析与稽核报告生成。",
    features: ["智能稽核", "风险识别", "条款匹配", "报告生成"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "76.33%",
    analyzedContracts: 3098,
    processingSpeed: "25.7秒/千字",
    responseTime: "18.6s",
    stability: "97.2%",
    auditPoints: 50
  },

  // 应用维度评估
  evaluation: [
    { "label": "算力依赖", "value": "9/10", "percentage": 90, "color": "#ffa500" },
    { "label": "复杂度", "value": "9/10", "percentage": 90, "color": "#00aaff" },
    { "label": "可扩展性", "value": "8/10", "percentage": 80, "color": "#00ff88" },
    { "label": "维护成本", "value": "5/10", "percentage": 50, "color": "#ff6b6b" }
  ],

  // Token 消耗
  tokenParse: {
    todayCount: "1.97M",
    inCount: "1.1M",
    outCount: "0.87M",
    avgTime: "21.3Min"
  },

  // 推荐运行配置
  "requirements": {
    "cpu": "32核心",
    "memory": "64G",
    "disk": "10T",
    "gpu": "A100*4 / Ascend 910B*4",
    "llmType": "qwen3-235B"
  },

  // 核心技能
  "skills": [
    {
      "frontTitle": "风险点识别",
      "frontDescription": "自动识别合同风险点并生成稽核报告，显著提升审核效率。",
      "backTitle": "语义异常检测",
      "backDescription": "融合OCR与语义匹配技术，精准定位条款异常与隐藏风险。"
    }
  ],

  // 调用趋势数据（折线图）
  "callTrendData": [
    { "hour": 0, "calls": 132 },
    { "hour": 1, "calls": 97 },
    { "hour": 2, "calls": 84 },
    { "hour": 3, "calls": 73 },
    { "hour": 4, "calls": 65 },
    { "hour": 5, "calls": 88 },
    { "hour": 6, "calls": 156 },
    { "hour": 7, "calls": 212 },
    { "hour": 8, "calls": 278 },
    { "hour": 9, "calls": 324 },
    { "hour": 10, "calls": 301 },
    { "hour": 11, "calls": 287 },
    { "hour": 12, "calls": 215 },
    { "hour": 13, "calls": 243 },
    { "hour": 14, "calls": 289 },
    { "hour": 15, "calls": 331 },
    { "hour": 16, "calls": 356 },
    { "hour": 17, "calls": 302 },
    { "hour": 18, "calls": 274 },
    { "hour": 19, "calls": 241 },
    { "hour": 20, "calls": 198 },
    { "hour": 21, "calls": 175 },
    { "hour": 22, "calls": 154 },
    { "hour": 23, "calls": 142 }
  ],

  // 使用场景
  "useCases": ["合同风险稽核", "合规性检测", "异常条款定位"],

  // 媒体文件路径
  "media": {
    "videoPath": "/data/demo.mp4",
    "demoUrl": "/contract-review/app/"
  }
};


export const projectConfig2 = {
  "basicInfo": {
    "startTime": "2025.01",
    "projectTime": "12周",
    "title": "设计方案稽核智能体",
    "subtitle": "基于大模型与规则知识库双引擎驱动的设计合规审查",
    "description": "面向通信设计文件，融合大语言模型、规则引擎与标准知识库，实现自动解析、标准匹配、问题识别与报告生成，提升审查效率与准确性。",
    "features": ["设计文档解析", "标准合规模型", "规则引擎校验", "自动生成报告"]
  },
  "performance": {
    "accuracy": "83.4%",
    "responseTime": "18.6s",
    "processingSpeed": "5页/分钟",
    "analyzedContracts": 221,
    "stability": "91.2%",
    "accCompare": "持平",
    "resCompare": "持平",
    "proCompare": "持平",
    "staCompare": "持平"
  },
  "evaluation": [
    { "label": "算力依赖", "value": "7/10", "percentage": 70, "color": "#ffa500" },
    { "label": "复杂度", "value": "7/10", "percentage": 70, "color": "#00aaff" },
    { "label": "可扩展性", "value": "6/10", "percentage": 60, "color": "#00ff88" },
    { "label": "维护成本", "value": "5/10", "percentage": 50, "color": "#ff6b6b" }
  ],
  "tokenParse": {
    "todayCount": "0.82M tokens",
    "inCount": "0.55M tokens",
    "outCount": "0.27M tokens",
    "avgTime": "18 秒"
  },
  "skills": [
    {
      "frontTitle": "设计合规COT推理",
      "frontDescription": "结合多步推理与上下文检索，定位设计方案中与标准不符的条款与参数。",
      "backTitle": "规则引擎与知识库融合",
      "backDescription": "将结构化规则与标准条文图谱化，支持快速更新与版本化比对，自动生成整改建议。"
    }
  ],
  "callTrendData": [
    { "hour": 0,  "calls": 60 },
    { "hour": 1,  "calls": 48 },
    { "hour": 2,  "calls": 42 },
    { "hour": 3,  "calls": 38 },
    { "hour": 4,  "calls": 35 },
    { "hour": 5,  "calls": 50 },
    { "hour": 6,  "calls": 95 },
    { "hour": 7,  "calls": 140 },
    { "hour": 8,  "calls": 220 },
    { "hour": 9,  "calls": 280 },
    { "hour": 10, "calls": 310 },
    { "hour": 11, "calls": 295 },
    { "hour": 12, "calls": 210 },
    { "hour": 13, "calls": 235 },
    { "hour": 14, "calls": 260 },
    { "hour": 15, "calls": 305 },
    { "hour": 16, "calls": 330 },
    { "hour": 17, "calls": 290 },
    { "hour": 18, "calls": 245 },
    { "hour": 19, "calls": 210 },
    { "hour": 20, "calls": 175 },
    { "hour": 21, "calls": 150 },
    { "hour": 22, "calls": 120 },
    { "hour": 23, "calls": 85 }
  ],
  "requirements": {
    "cpu": "16核心",
    "memory": "32G",
    "disk": "5T",
    "gpu": "A100*2 / Ascend 910B*2",
    "llmType": "qwen2.5-72B"
  },
  "useCases": [
    "通信设计方案合规性检查",
    "标准版本差异对比与追溯",
    "问题定位与整改建议生成",
    "批量方案快速稽核"
  ],
  "media": {
    "videoPath": "/data/demo_design_audit.mp4",
    "demoUrl": "/norms-review/app/"
  }
};

export const projectConfig3 = {
  "basicInfo": {
    "startTime": "2025.02",
    "projectTime": "14周",
    "title": "智源知识沉淀引擎",
    "subtitle": "文档语义切片与知识标签化的底层智能体",
    "description": "通过大语言模型驱动的文档解析、语义切片与知识标注机制，实现标准文档与行业规范的结构化沉淀、自动分类与智能报告生成，为上层稽核体系提供统一知识底座。",
    "features": ["语义切片", "标签标注", "知识聚合", "报告生成"]
  },

  "performance": {
    "accuracy": "94.7%",
    "responseTime": "16.8s",
    "processingSpeed": "8千字/分钟",
    "stability": "99.9%",
    "knowledgeExtraction": "540条知识片段/小时",
    "classificationPrecision": "92.3%",
    "reportGenerationRate": "97%",
    "resourceUsage": "GPU利用率 68%，内存占用 42%",
    "accCompare": "+0.4% 较昨日",
    "resCompare": "-0.6% 较昨日",
    "proCompare": "+0.2% 较昨日",
    "staCompare": "持平"
  },

  "evaluation": [
    { "label": "算力依赖", "value": "7/10", "percentage": 70, "color": "#ffa500" },
    { "label": "复杂度", "value": "8/10", "percentage": 80, "color": "#00aaff" },
    { "label": "可扩展性", "value": "10/10", "percentage": 100, "color": "#00ff88" },
    { "label": "维护成本", "value": "6/10", "percentage": 60, "color": "#ff6b6b" }
  ],

  "tokenParse": {
    "todayCount": "1.42M tokens",
    "inCount": "0.95M tokens",
    "outCount": "0.47M tokens",
    "avgTime": "24 秒"
  },


  "skills": [
    {
      "frontTitle": "语义知识切片",
      "frontDescription": "通过LLM自动拆分文档语义单元，构建高粒度知识块与上下文链路。",
      "backTitle": "智能标签与分类体系",
      "backDescription": "基于语义聚类与规则融合，实现知识自动打标、归类与结构化入库。"
    }
  ],

  "callTrendData": [
    { "hour": 0,  "calls": 85 },
    { "hour": 1,  "calls": 64 },
    { "hour": 2,  "calls": 58 },
    { "hour": 3,  "calls": 50 },
    { "hour": 4,  "calls": 48 },
    { "hour": 5,  "calls": 66 },
    { "hour": 6,  "calls": 130 },
    { "hour": 7,  "calls": 180 },
    { "hour": 8,  "calls": 250 },
    { "hour": 9,  "calls": 310 },
    { "hour": 10, "calls": 340 },
    { "hour": 11, "calls": 320 },
    { "hour": 12, "calls": 260 },
    { "hour": 13, "calls": 280 },
    { "hour": 14, "calls": 295 },
    { "hour": 15, "calls": 325 },
    { "hour": 16, "calls": 350 },
    { "hour": 17, "calls": 310 },
    { "hour": 18, "calls": 275 },
    { "hour": 19, "calls": 230 },
    { "hour": 20, "calls": 195 },
    { "hour": 21, "calls": 170 },
    { "hour": 22, "calls": 145 },
    { "hour": 23, "calls": 120 }
  ],

  "requirements": {
    "cpu": "32核心",
    "memory": "128G",
    "disk": "20T",
    "gpu": "A100*4 / Ascend 910B*4",
    "llmType": "qwen3-235B"
  },

  "useCases": [
    "多源文档知识沉淀",
    "行业规范语义解析",
    "知识分类与标签体系建设",
    "报告与知识摘要自动生成"
  ],

  "media": {
    "videoPath": "/data/demo_knowledgecore.mp4",
    "demoUrl": "/rag/app/"
  }
};

export const projectConfig4 = {
  "basicInfo": {
    "startTime": "2025.03",
    "projectTime": "16周",
    "title": "内审智能体能力库",
    "subtitle": "融合大模型的智能内审与风险洞察系统",
    "description": "集成投诉风险分类、往来金额异常诊断、OCR票据识别与照片合理性稽核等多项能力，基于大模型驱动实现数据审计、风险分析与可视化汇总，提升企业内控自动化水平。",
    "features": ["风险分类", "金额诊断", "OCR提取", "视觉稽核", "可视化分析"]
  },

  "performance": {
    "accuracy": "87.6%",
    "responseTime": "18.9s",
    "processingSpeed": "6千条/分钟",
    "stability": "97.8%",
    "riskDetectionRate": "84.3%",
    "imageAuditPrecision": "89.5%",
    "dataCoverage": "91.2%",
    "visualReportRate": "93.8%",
    "accCompare": "+0.2% 较昨日",
    "resCompare": "-0.3% 较昨日",
    "proCompare": "+0.1% 较昨日",
    "staCompare": "-0.1% 较昨日"
  },

  "evaluation": [
    { "label": "算力依赖", "value": "8/10", "percentage": 50, "color": "#ffa500" },
    { "label": "复杂度", "value": "5/10", "percentage": 50, "color": "#00aaff" },
    { "label": "可扩展性", "value": "4/10", "percentage": 40, "color": "#00ff88" },
    { "label": "维护成本", "value": "2/10", "percentage": 20, "color": "#ff6b6b" }
  ],

  "tokenParse": {
    "todayCount": "1.62M tokens",
    "inCount": "1.08M tokens",
    "outCount": "0.54M tokens",
    "avgTime": "20 秒"
  },

  "evaluation": [
    { "label": "算力依赖", "value": "8/10", "percentage": 50, "color": "#ffa500" },
    { "label": "复杂度", "value": "5/10", "percentage": 50, "color": "#00aaff" },
    { "label": "可扩展性", "value": "4/10", "percentage": 40, "color": "#00ff88" },
    { "label": "维护成本", "value": "2/10", "percentage": 20, "color": "#ff6b6b" }
  ],

  "skills": [
    {
      "frontTitle": "多源风险分析",
      "frontDescription": "结合结构化数据与自然语言输入，实现投诉事件与金额异常的智能分类与风险诊断。",
      "backTitle": "OCR与视觉稽核",
      "backDescription": "集成图像识别与文本提取模型，对票据与照片进行真实性与合理性稽核。"
    }
  ],

  "callTrendData": [
    { "hour": 0,  "calls": 105 },
    { "hour": 1,  "calls": 82 },
    { "hour": 2,  "calls": 70 },
    { "hour": 3,  "calls": 59 },
    { "hour": 4,  "calls": 54 },
    { "hour": 5,  "calls": 76 },
    { "hour": 6,  "calls": 142 },
    { "hour": 7,  "calls": 205 },
    { "hour": 8,  "calls": 278 },
    { "hour": 9,  "calls": 325 },
    { "hour": 10, "calls": 347 },
    { "hour": 11, "calls": 330 },
    { "hour": 12, "calls": 255 },
    { "hour": 13, "calls": 275 },
    { "hour": 14, "calls": 298 },
    { "hour": 15, "calls": 332 },
    { "hour": 16, "calls": 360 },
    { "hour": 17, "calls": 320 },
    { "hour": 18, "calls": 275 },
    { "hour": 19, "calls": 245 },
    { "hour": 20, "calls": 205 },
    { "hour": 21, "calls": 182 },
    { "hour": 22, "calls": 155 },
    { "hour": 23, "calls": 125 }
  ],

  "requirements": {
    "cpu": "32核心",
    "memory": "64G",
    "disk": "5T",
    "gpu": "A100*4 / Ascend 910B*4",
    "llmType": "qwen3-32B & qwen-vl-max"
  },

  "useCases": [
    "投诉事件风险分类",
    "往来金额异常诊断",
    "票据与照片内容稽核",
    "OCR文字提取与语义校验",
    "审计结果可视化与报告生成"
  ],

  "media": {
    "videoPath": "/data/demo_audit_engine.mp4",
    "demoUrl": "/intelligent-audit/app/"
  }
};



export const projectConfig5 = {
  "basicInfo": {
    "startTime": "2025.04",
    "projectTime": "10周",
    "title": "二手平台监控智能体",
    "subtitle": "基于多模态识别的违规物资监测系统",
    "description": "利用大模型结合图像识别与语义分析技术，对二手平台上涉嫌违规售卖的物资进行实时监控、比对与告警，支持自定义监测范围与合规标准。",
    "features": ["图像比对", "违规识别", "语义理解", "自定义监控", "告警报告生成"]
  },

  "performance": {
    "accuracy": "84.9%",
    "responseTime": "17.4s",
    "processingSpeed": "9个/分钟",
    "stability": "91.2%",
    "imageMatchPrecision": "88.1%",
    "violationDetectionRate": "82.7%",
    "customRuleCoverage": "91.5%",
    "alertPrecision": "89.3%",
    "accCompare": "+0.3% 较昨日",
    "resCompare": "-0.2% 较昨日",
    "proCompare": "+0.4% 较昨日",
    "staCompare": "-0.1% 较昨日"
  },

  "evaluation": [
    { "label": "算力依赖", "value": "5/10", "percentage": 50, "color": "#ffa500" },
    { "label": "复杂度", "value": "6/10", "percentage": 60, "color": "#00aaff" },
    { "label": "可扩展性", "value": "8/10", "percentage": 80, "color": "#00ff88" },
    { "label": "维护成本", "value": "6/10", "percentage": 60, "color": "#ff6b6b" }
  ],

  "tokenParse": {
    "todayCount": "1.28M tokens",
    "inCount": "0.85M tokens",
    "outCount": "0.43M tokens",
    "avgTime": "22 秒"
  },

  "skills": [
    {
      "frontTitle": "多模态违规检测",
      "frontDescription": "结合图像与文本双模态识别，对商品图片与标题描述进行一致性分析与违规判定。",
      "backTitle": "自定义监测策略",
      "backDescription": "用户可定义监控物资类型、规则模板与风险级别，实现灵活、高效的自动化巡检。"
    }
  ],

  "callTrendData": [
    { "hour": 0,  "calls": 70 },
    { "hour": 1,  "calls": 55 },
    { "hour": 2,  "calls": 50 },
    { "hour": 3,  "calls": 45 },
    { "hour": 4,  "calls": 42 },
    { "hour": 5,  "calls": 60 },
    { "hour": 6,  "calls": 120 },
    { "hour": 7,  "calls": 185 },
    { "hour": 8,  "calls": 260 },
    { "hour": 9,  "calls": 310 },
    { "hour": 10, "calls": 335 },
    { "hour": 11, "calls": 322 },
    { "hour": 12, "calls": 255 },
    { "hour": 13, "calls": 272 },
    { "hour": 14, "calls": 295 },
    { "hour": 15, "calls": 330 },
    { "hour": 16, "calls": 358 },
    { "hour": 17, "calls": 340 },
    { "hour": 18, "calls": 300 },
    { "hour": 19, "calls": 260 },
    { "hour": 20, "calls": 220 },
    { "hour": 21, "calls": 195 },
    { "hour": 22, "calls": 170 },
    { "hour": 23, "calls": 140 }
  ],

  "requirements": {
    "cpu": "16核心",
    "memory": "64G",
    "disk": "4T",
    "gpu": "A100*4 / Ascend 910B*4",
    "llmType": "qwen3-32B & qwen-vl-max"
  },

  "useCases": [
    "二手平台违规物资监测",
    "图像比对与风险识别",
    "物资流通合规分析",
    "自定义监控任务配置",
    "违规行为报告生成与告警"
  ],

  "media": {
    "videoPath": "/data/demo_resale_monitor.mp4",
    "demoUrl": "/goofish/monitor/app/"
  }
};

export const projectConfig6 = {
  "basicInfo": {
    "startTime": "2025.04",
    "projectTime": "15周",
    "title": "有线故障诊断智能体",
    "subtitle": "基于TOT框架与知识库驱动的智能运维专家",
    "description": "通过大模型结合RAG知识库、意图识别与流程编排，自动分析网络设备告警与性能波动，生成诊断方案并引导用户排障操作，实现从检测到解决的全流程闭环。",
    "features": ["故障识别", "推理诊断", "方案生成", "交互式排障", "反馈收集"]
  },

  "performance": {
    "accuracy": "86.8%",
    "responseTime": "20.5s",
    "processingSpeed": "45条/分钟",
    "stability": "99.9%",
    "diagnosisPrecision": "84.6%",
    "solutionSuccessRate": "82.9%",
    "feedbackIncorporation": "91.5%",
    "reportCompletionRate": "95.4%",
    "accCompare": "+0.2% 较昨日",
    "resCompare": "-0.3% 较昨日",
    "proCompare": "+0.1% 较昨日",
    "staCompare": "持平"
  },

  "evaluation": [
    { "label": "算力依赖", "value": "9/10", "percentage": 90, "color": "#ffa500" },
    { "label": "复杂度", "value": "10/10", "percentage": 100, "color": "#00aaff" },
    { "label": "可扩展性", "value": "8/10", "percentage": 80, "color": "#00ff88" },
    { "label": "维护成本", "value": "6/10", "percentage": 60, "color": "#ff6b6b" }
  ],

  "tokenParse": {
    "todayCount": "1.73M tokens",
    "inCount": "1.12M tokens",
    "outCount": "0.61M tokens",
    "avgTime": "23 秒"
  },
  "skills": [
    {
      "frontTitle": "RAG智能诊断",
      "frontDescription": "结合大模型推理与知识检索，快速定位设备告警根因并生成诊断路径。",
      "backTitle": "自适应排障编排",
      "backDescription": "融合意图识别与流程规划，动态生成排障步骤并引导用户完成操作。"
    }
  ],

  "callTrendData": [
    { "hour": 0,  "calls": 95 },
    { "hour": 1,  "calls": 70 },
    { "hour": 2,  "calls": 60 },
    { "hour": 3,  "calls": 55 },
    { "hour": 4,  "calls": 50 },
    { "hour": 5,  "calls": 72 },
    { "hour": 6,  "calls": 140 },
    { "hour": 7,  "calls": 200 },
    { "hour": 8,  "calls": 280 },
    { "hour": 9,  "calls": 330 },
    { "hour": 10, "calls": 355 },
    { "hour": 11, "calls": 340 },
    { "hour": 12, "calls": 260 },
    { "hour": 13, "calls": 275 },
    { "hour": 14, "calls": 295 },
    { "hour": 15, "calls": 330 },
    { "hour": 16, "calls": 365 },
    { "hour": 17, "calls": 345 },
    { "hour": 18, "calls": 310 },
    { "hour": 19, "calls": 270 },
    { "hour": 20, "calls": 230 },
    { "hour": 21, "calls": 200 },
    { "hour": 22, "calls": 165 },
    { "hour": 23, "calls": 135 }
  ],

  "requirements": {
    "cpu": "32核心",
    "memory": "64G",
    "disk": "1T",
    "gpu": "A100*2 / Ascend 910B*2",
    "llmType": "qwen2.5-72B"
  },

  "useCases": [
    "网络设备告警自动诊断",
    "性能波动根因分析",
    "交互式排障指导",
    "RAG知识库方案生成",
    "用户反馈学习与知识沉淀"
  ],

  "media": {
    "videoPath": "/data/demo_fault_diagnosis.mp4",
    "demoUrl": "/ai-diagnosis/app/"
  }
};

export const projectConfig7 = {
  // 基础项目信息
  basicInfo: {
    startTime: "2025.10",
    title: "语音识别与分析",
    projectTime: "10周",
    subtitle: "基于大模型的多语言语音处理系统",
    description: "借助先进的大模型能力实现语音文件到文字的精准转换，并支持多语言方言识别和深度文本分析。",
    features: ["多语言识别", "方言支持", "语音转写", "文本分析"]
  },

  // 智能体性能指标
  performance: {
    accuracy: "97.5%",
    responseTime: "1.8s", 
    processingSpeed: "实时处理",
    stability: "99.7%",
    accCompare: "+0.2% 较昨日",
    resCompare: "+0.3% 较昨日",
    proCompare: "+0.1% 较昨日",
    staCompare: "持平"
  },

  // 应用维度评估
  evaluation: [
    { label: "算力依赖", value: "9/10", percentage: 90, color: "#ffa500" },
    { label: "复杂度", value: "8/10", percentage: 80, color: "#00aaff" },
    { label: "可扩展性", value: "7/10", percentage: 70, color: "#00ff88" },
    { label: "维护成本", value: "5/10", percentage: 50, color: "#ff6b6b" }
  ],

  //Token 消耗
  tokenParse:{
    todayCount: "1.0M tokens",
    inCount: "0.7M tokens",
    outCount: "0.3M tokens",
    avgTime: "20 秒"
  },

  // 核心技能
  skills: [
    {
      frontTitle: "多语言语音识别",
      frontDescription: "支持普通话、粤语、维吾尔语及多种地区方言的高精度语音转文字，适应不同语言环境需求。",
      backTitle: "深度文本分析", 
      backDescription: "对转换后的文字内容进行语义分析、情感识别和关键信息提取，提供全面的语音内容洞察。"
    }
  ],

  //折线趋势图
  callTrendData: [
      { hour: 0, calls: 120 },
      { hour: 2, calls: 80 },
      { hour: 4, calls: 60 },
      { hour: 6, calls: 200 },
      { hour: 8, calls: 420 },
      { hour: 10, calls: 580 },
      { hour: 12, calls: 620 },
      { hour: 14, calls: 550 },
      { hour: 16, calls: 480 },
      { hour: 18, calls: 650 },
      { hour: 20, calls: 720 },
      { hour: 22, calls: 400 },
      { hour: 24, calls: 200 }
    ],

  //推荐配置
  requirements: {
    cpu: "32核心",
    memory: "64G",
    disk: "1T",
    gpu: "A100*2 / Ascend 910B*2",
    llmType: "qwen2.5-72B"
  },

  // 使用场景
  useCases: [
    "会议录音转写",
    "客服语音分析", 
    "多语言内容处理",
    "方言语音识别"
  ],

  // 媒体文件路径
  media: {
    videoPath: "/data/demo_voice.mp4", // 从public/data/文件夹读取
    demoUrl: "/voice/app/" // 跳转到demo页面
  }
};


// 项目数据模板 - 用户可以复制这个模板创建新项目
export const projectTemplate = {
  basicInfo: {
    startTime: "2024.XX",
    projectTime: "10周",
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
