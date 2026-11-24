# 商业模式画布 JSON 规范

本规范定义了商业模式画布的**严格**输出格式。该数据将直接用于 `businessmodelcraft.com` 网站生成页面，格式错误会导致网站崩溃。

## 关键格式规则
1.  **禁止 Markdown**: 不要使用 ` ```json ` 或 ` ``` ` 代码块。
2.  **禁止废话**: 不要写"这是 JSON："或"希望能帮到你"。
3.  **纯净 JSON**: 输出必须以 `{` 开始，以 `}` 结束。
4.  **列表项**: 使用圆点字符 `•` (U+2022) 后跟一个空格来表示列表项。
5.  **双语要求**: 核心内容必须同时提供中文 (`_zh`) 和英文 (`_en`) 版本。
6.  **Slug 规范**: 使用小写英文，如果必须是单词词组，则单词间用连字符连接（例如 `berkshire-hathaway`）。
7.  **中文字段引号规范**：所有 `_zh` 字段（`intro_zh`、`canvas_zh` 各子字段、`description_zh`、`displayTitle_zh` 等）中，如需引用词语或强调短语，必须使用中文弯引号 `"…"` / `'…'`（单层嵌套用 `'…'`），**严禁使用 ASCII 直引号 `"..."` 或 `'...'`**。ASCII 直引号在中文语境下排版错误，且会与 JSON 语法的字符串界定符视觉混淆。
   - ✅ `"把\"迁移到云\"和\"离开 Oracle\"这两件事拆分"` → 正文渲染为：把"迁移到云"和"离开 Oracle"这两件事拆分
   - ❌ `"把\"迁移到云\"和\"离开 Oracle\"这两件事拆分"`（同样是转义引号，但应在写入 JSON 前确认源内容用的是 `"` 而非 `"`）
   - 实操：直接在源字符串中写 `"迁移到云"` 弯引号字符，无需转义（它们是普通 Unicode 字符，不是 JSON 特殊字符）。

## JSON Schema (模式)

```json
{
  "slug": "string (kebab-case, e.g., 'apple')",
  "name_en": "string (Common Brand Name, NO 'Inc'/'Ltd')",
  "name_zh": "string (通用中文品牌名，如'美团'而非'三快科技'；若有公允中文名则必须使用，如'英伟达'而非'NVIDIA'；若无官方或业界通行中文名，则直接保留英文原名，严禁自行音译或意译，例如 Venture Global 没有官方中文名，应写 'Venture Global' 而非'万途全球')",
  "symbol": "string (Stock Symbol, e.g., 'AAPL')",
  "industry_en": "string (Industry/Sector)",
  "industry_zh": "string (行业/板块)",
  "publishDate": "string (YYYY-MM-DD, use today's date)",
  "weight": "integer (0-100, company prominence score)",
  "displayTitle_en": "string (MUST MATCH Markdown Title: Company + Metaphor)",
  "displayTitle_zh": "string (必须与 Markdown 文档标题完全一致)",
  "seo": {
    "title_en": "string (SEO Title for English page)",
    "title_zh": "string (SEO 标题)",
    "description_en": "string (Meta Description ~160 chars)",
    "description_zh": "string (元描述 ~160 字符)"
  },
  "content": {
    "intro_en": "string (Deep strategic summary in English)",
    "intro_zh": "string (深度战略总结中文版)",
    "canvas_en": {
      "keyPartners": "string (Bulleted list • ...)",
      "keyActivities": "string (Bulleted list • ...)",
      "keyResources": "string (Bulleted list • ...)",
      "valuePropositions": "string (Bulleted list • ...)",
      "customerRelationships": "string (Bulleted list • ...)",
      "channels": "string (Bulleted list • ...)",
      "customerSegments": "string (Bulleted list • ...)",
      "costStructure": "string (Bulleted list • ...)",
      "revenueStreams": "string (Bulleted list • ...)"
    },
    "canvas_zh": {
      "keyPartners": "string (带圆点的列表 • ...)",
      "keyActivities": "string (带圆点的列表 • ...)",
      "keyResources": "string (带圆点的列表 • ...)",
      "valuePropositions": "string (带圆点的列表 • ...)",
      "customerRelationships": "string (带圆点的列表 • ...)",
      "channels": "string (带圆点的列表 • ...)",
      "customerSegments": "string (带圆点的列表 • ...)",
      "costStructure": "string (带圆点的列表 • ...)",
      "revenueStreams": "string (带圆点的列表 • ...)"
    }
  }
}
```

## 字段生成指南

### SEO 与 元数据
- **slug**: 使用公司英文全名，去掉 "Inc", "Corp" 等后缀，转小写并用 `-` 连接。
- **symbol**: 美股 ticker（如 `AAPL`、`TSLA`）。该字段用于网站股价行情展示和关联数据抓取。若分析对象不是美股上市公司（港股、A 股、非上市公司），可留空字符串 `""`；若为港股，可填入格式为 `"00700.HK"` 的代码，以支持未来扩展。
- **displayTitle**: 即文章在网站上展示的标题。Markdown 文件中不出现 H1 标题，因此 `displayTitle` 就是文章标题，二者是同一事物——不需要"一致性检查"，只需要在 JSON 里写好。标题必须有钩子，见 `bmc-analysis-guide.md` 七、标题写法。
  - *Good*: "Netflix Business Model: The Engine of Scale"
  - *Bad*: "Netflix BMC"
- **intro**: 类似于 Markdown 报告中的“执行摘要”，但更精炼。解释它是如何赚钱的，以及它的护城河是什么。

### 公司权重 (Weight)

`weight` 字段用于表示目标公司的行业地位和知名度，数据类型为整数，范围 0-100。评分规则：

| 分值范围 | 含义 | 示例 |
|---------|------|------|
| 90–100 | 时代级巨头或绝对流量密码。全球家喻户晓，引领科技或商业风向（尽量不要打满分，打分要审慎克制） | OpenAI, Apple, Nvidia, Tesla |
| 70–89 | 经典商业模式标杆或行业绝对霸主。商学院经典研究案例 | Berkshire Hathaway, Costco, Meta, Walmart |
| 40–69 | 特定赛道（如 SaaS、消费品）的知名巨头或区域市场龙头企业 | Oracle, Salesforce, Ambev, 泡泡玛特 |
| 10–39 | 细分领域的创新型公司、垂类赛道新星或具有特定商业模式的早期科技企业 | 北森, Hims & Hers |
| 0 | 极其冷门的 B2B 企业、不知名长尾公司或仅用于凑数的边缘案例 | — |

### 画布内容 (Canvas Content)
- **翻译一致性**: 确保 `_zh` 和 `_en` 表达的意思一致，但符合各自的语言习惯。
- **深度**: 即使在 JSON 中，也要保持深度。
  - *Bad*: "• Sell cars"
  - *Good*: "• Direct-to-Consumer Sales (bypassing dealerships to control experience and margin)"

## 示例输出 (Berkshire Hathaway)

```json
{
  "slug": "berkshire-hathaway",
  "name_en": "Berkshire Hathaway",
  "name_zh": "伯克希尔·哈撒韦",
  "industry_en": "Conglomerate / Investment",
  "industry_zh": "综合企业 / 投资",
  "publishDate": "2026-01-11",
  "weight": 78,
  "displayTitle_en": "Berkshire Hathaway Business Model: The Fortress of Capital & Float",
  "displayTitle_zh": "伯克希尔·哈撒韦商业模式：资本堡垒与浮存金飞轮",
  "seo": {
    "title_en": "Berkshire Hathaway Business Model Canvas Analysis",
    "title_zh": "伯克希尔·哈撒韦商业模式画布深度解析",
    "description_en": "Deconstruct Warren Buffett's empire: How Insurance Float and Capital Allocation create the world's most robust compounding machine.",
    "description_zh": "深度拆解巴菲特的商业帝国：保险浮存金与极致的资本配置如何构建出全球最稳固的复利机器。"
  },
  "content": {
    "intro_en": "Berkshire Hathaway is not just a holding company; it is a meticulously designed 'compounding machine'. Its core engine utilizes zero-cost insurance float to fund acquisitions of high-quality businesses and stocks, managed through extreme decentralization.",
    "intro_zh": "伯克希尔·哈撒韦不仅仅是一家控股公司，它是一台精密设计的“复利机器”。其核心引擎是利用零成本的保险浮存金，去收购优质的实体企业和股票，并通过极致的分权管理模式进行运营。",
    "canvas_en": {
      "keyPartners": "• Subsidiary Managers: The actual operators of the businesses. Buffett trusts them implicitly.\n• Reinsurance Brokers: Essential partners for distributing catastrophic risks.",
      "keyActivities": "• Capital Allocation: The only core task of HQ.\n• Risk Management: Ensuring no single deal can destroy the company.",
      "keyResources": "• The Float (~$170B): Zero-cost leverage.\n• The Cash Pile: Hundreds of billions in cash.",
      "valuePropositions": "• For Sellers: 'Permanent Home & Complete Autonomy'.\n• For Shareholders: 'Risk-free Compounding Machine'.",
      "customerRelationships": "• Extreme Decentralization: 'Don't call me unless you're sending a check'.",
      "channels": "• Reputation: Buffett's name is the biggest channel.\n• Annual Meeting: Woodstock for Capitalists.",
      "customerSegments": "• Founders Seeking Safe Haven\n• Long-term Shareholders",
      "costStructure": "• Near-Zero HQ Cost: Only ~25 employees.\n• Insurance Claims: The primary variable cost.",
      "revenueStreams": "• Insurance Float: Collecting premiums first.\n• Operating Earnings: Cash flow from real industries."
    },
    "canvas_zh": {
      "keyPartners": "• 子公司经理人：实际经营者，享有完全经营权。\n• 再保险经纪人：分担超级灾难风险。",
      "keyActivities": "• 资本配置：总部唯一核心业务。\n• 风险控制：确保公司不被摧毁。",
      "keyResources": "• 浮存金：约1700亿美元零成本杠杆。\n• 现金堡垒：拥有定价权的王牌。",
      "valuePropositions": "• 对于卖家：永恒的资本与完全自治。\n• 对于股东：零风险复利机器。",
      "customerRelationships": "• 极端分权：除了寄支票别来烦我。",
      "channels": "• 信誉与口碑：巴菲特的名声。\n• 股东大会：资本家的伍德斯托克。",
      "customerSegments": "• 寻求避风港的创始人\n• 长期主义股东",
      "costStructure": "• 总部成本近乎零：仅25名员工。\n• 保险赔付：主要变动成本。",
      "revenueStreams": "• 保险浮存金：先收保费后赔付。\n• 经营性利润：实体产业现金流。"
    }
  }
}
```
