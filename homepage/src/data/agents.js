function applicationUrl(environmentName, fallback = "") {
  const configured = import.meta.env[environmentName];
  return typeof configured === "string" && configured.trim()
    ? configured.trim()
    : fallback;
}

export const agents = [
  {
    id: "audit-workbench",
    short: "稽核工作台",
    name: "稽核工作台",
    statement: "让稽核规则、问题定位和整改跟踪形成闭环。",
    description:
      "统一承接稽核任务与规则，自动发现异常线索，帮助团队快速下钻原因并跟踪整改结果。",
    role: "智能稽核",
    launchUrl: applicationUrl("VITE_AUDIT_WORKBENCH_URL"),
    shape: 0,
    capabilities: [
      ["合同稽核", "核验合同条款、计费规则与业务数据，识别履约、结算和风险异常。"],
      ["内外审计", "覆盖内部审计、外部审计及各类专项审计场景。"],
      ["规则驱动", "定位字段级差异、上下游数据链路和异常影响范围。"],
      ["灵活编排", "支持单个或多个审计任务，并可通过自然语言触发执行。"],
    ],
  },
  {
    id: "network-optimization",
    short: "网络优化",
    name: "网络优化智能体",
    statement: "从网络状态中发现问题，给出可验证的优化路径。",
    description:
      "结合性能指标、告警与区域特征识别网络瓶颈，辅助制定优化方案并观察执行效果。",
    role: "网络优化",
    launchUrl: applicationUrl("VITE_NETWORK_OPTIMIZATION_URL"),
    shape: 1,
    capabilities: [
      ["多源感知", "汇聚性能指标、告警、工参、路测和用户投诉数据。"],
      ["异常诊断", "识别弱覆盖、干扰、高负荷、切换失败等小区级问题。"],
      ["方案生成", "给出功率、频点、天线、邻区参数和扩容建议。"],
      ["闭环评估", "对比优化前后指标，自动判断效果并沉淀优化经验。"],
    ],
  },
  {
    id: "key-account-comparison",
    short: "大客户数据比对",
    name: "大客户内外数据比对智能体",
    statement: "把内外部客户数据放到同一套口径中核验。",
    description:
      "连接内部经营数据与外部客户信息，完成实体匹配、差异识别和关键线索整理。",
    role: "客户数据核验",
    launchUrl: applicationUrl(
      "VITE_KEY_ACCOUNT_COMPARISON_URL",
      "http://127.0.0.1:9100/vip_139/report/api/auth/sso/login",
    ),
    shape: 2,
    capabilities: [
      ["内部解读", "清洗企业名称、统一信用代码、地址和联系方式。"],
      ["协同比对", "通过精确匹配、模糊匹配和关联关系识别同一客户。"],
      ["差异报告", "发现内外部数据中的缺失、冲突、异常和过期信息。"],
      ["根因溯源", "形成差异证据、风险标签和商机线索，并推送业务系统。"],
    ],
  },
  {
    id: "smart-store-selection",
    short: "智慧选店",
    name: "智慧选店智能体",
    statement: "综合位置、客群和经营条件，辅助判断开店机会。",
    description:
      "围绕候选区域分析客流、竞争、消费与覆盖能力，形成可比较的选址判断。",
    role: "选址决策",
    launchUrl: applicationUrl("VITE_SMART_STORE_SELECTION_URL"),
    shape: 3,
    capabilities: [
      ["商圈画像", "分析客流、人口、消费、交通、POI 和区域发展情况。"],
      ["竞争格局", "识别竞品门店、商圈饱和度和门店覆盖重叠范围。"],
      ["潜力预测", "估算候选位置的客流、营收、租金压力和投资回报。"],
      ["地址评估", "支持地图圈选、多点比较、综合评分和选址排序。"],
    ],
  },
  {
    id: "live-script",
    short: "直播话术",
    name: "直播话术生成智能体",
    statement: "围绕商品和直播节奏，生成自然、可讲的话术。",
    description:
      "理解商品卖点、目标人群与直播阶段，组织开场、讲解、互动和转化话术。",
    role: "直播内容生成",
    launchUrl: applicationUrl("VITE_LIVE_SCRIPT_URL"),
    shape: 4,
    capabilities: [
      ["商品建模", "从商品资料中提取卖点、参数、适用人群和常见异议。"],
      ["话术编排", "生成开场、留人、讲解、互动、促单和收尾话术。"],
      ["实时续写", "根据观众评论和临场问题生成即时回应与过渡内容。"],
      ["合规复盘", "识别敏感词、夸大宣传和风险表达，并结合直播效果优化话术。"],
    ],
  },
  {
    id: "news-gathering",
    short: "要闻慧聚",
    name: "要闻慧聚智能体",
    statement: "从海量资讯中聚合真正需要关注的要闻。",
    description:
      "持续跟踪重点领域，对信息进行筛选、归类与摘要，帮助团队快速掌握重要变化。",
    role: "要闻聚合",
    launchUrl: applicationUrl("VITE_NEWS_GATHERING_URL"),
    shape: 5,
    capabilities: [
      ["多源采集", "接入新闻、网站、公众号和内部信息源并自动去重。"],
      ["事件聚合", "识别人、企业、区域和事件，将同类报道合并为事件专题。"],
      ["影响分析", "提炼关键事实、观点差异、事件脉络和业务影响。"],
      ["订阅预警", "支持重点主题持续跟踪、重大事件提醒和日报周报生成。"],
    ],
  },
  {
    id: "knowledge-harness",
    short: "知识问答 Harness",
    name: "知识问答 Harness 智能体",
    statement: "让组织知识能够被准确找到，并保留回答依据。",
    description:
      "接入制度、文档和项目经验，理解问题上下文，输出有来源、可追溯的知识回答。",
    role: "知识问答",
    launchUrl: applicationUrl("VITE_KNOWLEDGE_HARNESS_URL"),
    shape: 6,
    capabilities: [
      ["知识运营", "完成知识接入、切分、标签、版本、权限和有效期管理。"],
      ["多模问答", "支持文档、表格、图片和音视频内容问答，并提供来源依据。"],
      ["实体图谱", "进行实体与关系抽取、实体关系图谱建模和关联知识检索。"],
      ["自我进化", "将问答结果自动沉淀，并进行低质量检测、冲突检测和知识更新。"],
    ],
  },
  {
    id: "data-harness",
    short: "数据问答 Harness",
    name: "数据问答 Harness 智能体",
    statement: "用自然语言提问，直接获得数据结果和解释。",
    description:
      "理解业务问题并转换为数据查询，返回指标结果、变化对比和可继续追问的分析线索。",
    role: "数据问答",
    launchUrl: applicationUrl("VITE_DATA_HARNESS_URL"),
    shape: 7,
    capabilities: [
      ["指标建模", "统一指标、维度、统计粒度、业务口径和数据权限。"],
      ["自然取数", "把业务问题转换为多表查询并安全执行。"],
      ["可视回答", "自动生成指标卡、表格、趋势图、对比图和数据解读。"],
      ["多轮钻取", "保留上下文，支持连续追问、归因拆解和查询结果校验。"],
    ],
  },
  {
    id: "agent-hub",
    short: "超级路由",
    name: "Agent-hub 超级路由智能体",
    statement: "识别任务意图，把请求交给最合适的智能体。",
    description:
      "作为九个产品的统一入口，理解复杂任务、选择专业智能体并协调多智能体协作。",
    role: "智能体路由",
    launchUrl: applicationUrl(
      "VITE_AGENT_HUB_URL",
      "http://127.0.0.1:9888/agent_hub/api/auth/sso/login",
    ),
    shape: 8,
    capabilities: [
      ["注册管理", "管理智能体能力、接口、版本、权限和可用状态。"],
      ["意图路由", "判断任务类型并动态选择最合适的专业智能体。"],
      ["协同编排", "支持任务拆解、串并行执行、重试、交接和结果依赖。"],
      ["运行治理", "完成上下文共享、结果汇总、运行日志、成本和质量监控。"],
    ],
  },
];
