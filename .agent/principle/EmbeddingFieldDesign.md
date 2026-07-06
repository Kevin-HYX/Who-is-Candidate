# Embedding 检索文本构建设计（怎么写 `*_search_text` 才好搜）

> 软条件全靠 embedding 相似度匹配。但 embedding 有一批固有缺陷会直接造成排序错误。本文说明这些缺陷，并规定 **LLM 在预处理阶段应如何构建各 `*_search_text` 检索文本**，让语义匹配真正对齐"工作内容"而非"字面"。字段名以 `_search_text` 结尾，就是要让预处理 LLM 和下游 Agent 都时刻清楚：**这是一段直接送去 embedding 的检索文本，字段名指到什么就写什么具体内容。**
>
> 相关：[SchemaDesign.md](./SchemaDesign.md)、[ScoringDesign.md](./ScoringDesign.md)、[ToolInterfaceDesign.md](./ToolInterfaceDesign.md)。

---

## 1. Embedding 的固有缺陷（用我们的真实数据说明）

### 缺陷 1：字面相近 ≠ 工作内容相近（最致命）
Embedding 对**词面/主题**敏感，对**职责实质**不敏感。实测：
- **"Manager" 有 377 种不同 title**：Store Manager（零售看店）、Project Manager（项目交付）、Office Manager（行政）、Account Manager（销售）。向量里都因 "manager" 高度相似，实际工作天差地别。
- **"Analyst" 112 种**：Business / Systems / Financial / Management Analyst，做的事完全不同。
- **"Associate"**：Sales Associate（零售店员）vs Associate Attorney（律师）vs Research Associate（研究）。

→ 如果 `responsibilities_search_text` 只放 title，搜"项目经理"会把"店长""办公室主任"一起捞上来。

### 缺陷 2：否定词被忽略
Embedding 几乎无视 "not / no / without"。"不要纯研究背景"和"纯研究背景"的向量高度相似。
→ `avoid` 绝不能直接 embedding。本系统用**负权重软项**表达"不要 X"（正面描述那类工作 + 负 weight），越像总分越低——绕开否定词失效（见 ScoringDesign §5）。

### 缺陷 3：噪声词稀释语义
`skills` 噪声极大，最高频词是 `management`、`sales`、`less`（简历 "Show less" 按钮被抓进来的垃圾）、`responsible`、`projects`——几乎不携带区分信息，却拉平所有人的向量。
→ 检索文本必须先清洗，去掉泛词、垃圾词、UI 残留。

### 缺陷 4：长文本语义被平均掉
把整段简历拼进一个 embedding，重点会被大量无关内容稀释，20 年老将和实习生的向量趋同。
→ 必须分维度（7 个检索文本）各自 embedding，而不是一个大向量。

### 缺陷 5：稀缺硬信号被淹没
"CPA""护士执照""FastAPI"这种关键精确信号，在语义空间里权重很低，容易被通用描述盖过。
→ 精确技能/证书理想上用**关键词命中**补，不单靠 embedding（对应 agreement_boost，本期暂不实现，见 §4）。

### 缺陷 6：领域词歧义 / 缩写
"PM"=Project Manager 还是 Product Manager 还是 Program Manager？"lead" 是动词还是职级？embedding 不消歧。
→ 检索文本里要写全称、消歧，不留裸缩写。

### 缺陷 7：表面相似的资历错配
"Senior X" 和 "Junior X" 语义高度相似，但资历天差。
→ 资历不靠 embedding，靠结构化 `seniority_level`（硬/软字段），检索文本里只描述职责不靠它定级。

---

## 2. 核心原则：检索文本要描述"做什么"，不是"叫什么"

一句话——**LLM 构建检索文本时，把"职位名"翻译成"职责与工作内容"。**

| 反例（只有字面） | 正例（描述工作内容） |
|---|---|
| "Store Manager" | "运营一家零售门店：管理店员排班、库存与销售目标、处理客户与日常运营" |
| "Project Manager" | "负责项目交付：制定计划与里程碑、协调跨职能团队、管控进度预算与风险" |
| "Analyst" | "分析业务数据、产出报表与洞察，支持某某决策"（并点明是财务/系统/运营分析） |
| "Associate" | 明确到"零售销售"或"律所初级律师"或"实验室研究助理" |

这样，两个都叫 "Manager" 但内容不同的人，向量会被工作内容拉开距离。

---

## 3. 各检索文本（`*_search_text`）的构建规范

**命名即契约**：字段名以 `_search_text` 结尾，就是在提醒——**这不是元数据标签，而是一段会被直接送去 embedding 的检索文本；字段名（responsibilities / skills / experience / domain / ownership / achievements）指到什么，AI 就写什么内容，用自然语句写清"这个人具体做了什么"。** 名字里没有 "title/role" 这种抽象词，就是不让 AI 去填职位名。

通用规则：
1. **写职责动作，不写头衔**：用"做了什么"的动词短语（负责/管理/交付/分析/服务/设计…）。
2. **消歧与全称**：缩写展开（PM→Project Management），行业/对象点明（给谁做、在什么场景）。
3. **清洗噪声**：剔除泛词（management/responsible/less）、UI 残留（"Show less"）、重复词。
4. **只放该维度信息**：skills_search_text 不混职责，achievements_search_text 不混技能，保持维度纯度。
5. **弱证据可写但要标**：描述缺失时可从 title/公司/行业保守推断，但不得编造具体项目。

| 检索文本字段 | 应包含（字段名指到什么就写什么） | 应排除 | 消歧要点 |
|---|---|---|---|
| `responsibilities_search_text` | 岗位职责实质、服务对象、岗位族群 | 纯 title、公司名 | Manager/Analyst/Associate 一律展开成职责 |
| `skills_search_text` | 清洗后的真实技能/工具/专业能力 | management、less、responsible 等泛词 | 通用词 → 具体化（"software"→ 具体栈或删除） |
| `experience_search_text` | 做过的项目/职责事实 | 空泛口号、形容词堆砌 | 从 description 抽事实，无描述则保守概括 |
| `domain_search_text` | 行业 + 业务场景 | 无关技能 | 行业全称（医疗细分：临床/账单/器械） |
| `ownership_search_text` | owned/managed/support 边界 | 头衔本身 | 区分"负责" vs "参与" vs "支持" |
| `achievements_search_text` | 结果产出（可量化优先） | 日常职责 | 动词开头：launched/reduced/grew/built |
| `education_search_text` | 学历、专业、证书文本 | 无 | 学位全称 + 专业 + 证书全称 |

---

## 3.5 两端对称：查询侧也要写"工作内容"，不是职位名

Embedding 匹配的是**两段文本之间的语义相似度**。候选人侧我们已经把职位名翻译成了工作内容描述，那么**查询侧必须同构**——否则一边是"做什么"、一边是"叫什么"，匹配不上。

**规则：Agent 把用户需求填进 `weighted_soft_preferences[].text` 时，也要写成"这个岗位具体做什么"的描述，而不是照抄用户说的职位名。**

| 用户原话 | ❌ 错误（照抄职位名） | ✅ 正确（写工作内容，与候选人侧同构） | 打到哪个字段 |
|---|---|---|---|
| "要个项目经理" | "项目经理" | "负责项目交付：制定计划与里程碑、协调跨职能团队、管控进度预算与风险" | responsibilities_search_text |
| "会 Python 后端" | "Python" | "用 Python 构建和维护后端服务与 API，处理数据与业务逻辑" | skills_search_text |
| "做过跨境电商" | "跨境电商" | "在跨境电商业务场景工作：面向海外市场的选品、履约、支付或运营" | domain_search_text |
| "带过团队的" | "带团队" | "带领并管理团队：负责下属绩效、任务分配与团队交付结果" | ownership_search_text |

**为什么这样更准**：候选人的 `responsibilities_search_text` 写的是"运营零售门店：管理店员排班……"，如果查询侧只写"店长"两个字，语义信息量太少、还带头衔歧义；写成同样粒度的职责描述，两段文本才在同一语义空间里可比。

**这条与预处理侧是一条规则的两面**：候选人侧"把叫什么翻译成做什么"，查询侧"把想要谁翻译成要谁做什么"。两端都落到工作内容，embedding 才对齐。`avoid` 同理——写成一个负权重软项（"以外部审计为主的工作"，weight 给负），不是"不要审计"。

---

## 4. 针对"字面近内容远"的专门机制

光靠检索文本清洗还不够，评分体系再加保险：

**本期已实现：**
1. **结构化闸门（第一轮硬过滤）**：用预处理生成的 `role_family`（18 类枚举）等硬字段先过滤。搜"项目管理"时把 `role_family=Sales` 的 "Account Manager" 直接排除或不作候选——**枚举硬字段兜住 embedding 的字面误判**，这是本系统对付"字面近内容远"的主力。
2. **负权重软项**：把不想要的画像（如"看起来像但实际是助理岗"的工作内容）写成负权重偏好，越像总分越低。

**暂不实现（未来工作）：**
- `conflict_penalty`：`ownership_search_text` 与需求 ownership 不符时的专门扣分。
- `agreement_boost`：语义 + 关键词双命中的一致性加分。

→ **embedding 负责召回，结构化硬字段负责纠偏（本期主力），负权重辅助压制不想要的画像。** 结合才对齐真实工作内容。

---

## 5. LLM 构建检索文本的输出约束（追加到预处理契约）

1. 检索文本是**职责/内容描述**，禁止直接照抄 title 或 skills 列表。
2. 缩写必须展开并消歧；歧义头衔（Manager/Analyst/Associate/PM/Lead）必须结合上下文点明实际职责。
3. 噪声词、UI 残留（"Show less"）、纯形容词必须清除。
4. 每个检索文本只承载本维度语义，不跨维度混入。
5. 描述缺失时可保守概括，但**不得编造未发生的项目或成果**；不确定的降置信、留待结构化字段兜底。
6. `avoid` 类需求不进候选人侧检索文本；在查询侧写成一个**负权重软项**（正面描述那类工作 + 负 weight）。

---

## 6. 一句话总结

Embedding 只认字面和主题，不认职责实质、否定和资历。所以 LLM 的检索文本必须**把"叫什么"翻译成"做什么"、消歧、去噪、分维度**；再用结构化枚举字段和负权重软项纠偏。embedding 管召回，结构化管精准——两层配合，才不会把"店长"当成"项目经理"。
