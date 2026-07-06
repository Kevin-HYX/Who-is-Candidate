# 评分维度与机制设计（Scoring Design）

> 面向对象：HR / 招聘负责人 + 研发。本文用大白话解释系统"怎么给候选人打分、凭什么排序"，并说明每个维度我们的数据能不能支撑。
>
> 相关文档：[SystemDesign.md](./SystemDesign.md)（总体设计）、[ImplementationPlan.md](./ImplementationPlan.md)（实现方案）。

---

## 0. 一个前提：这是泛行业候选库，不是技术人才库

我们的 1000 份简历来自各行各业（数据实测分布）：

- **职能**横跨 18 类：教育、工程技术、销售、运营、医疗、行政、C-Suite、客服、财务、研究、市场、技工、设计、法务、人力、咨询等，**没有任何一类超过 1/3**。
- **行业**横跨 24 类：教育、专业服务、制造、医疗、金融、零售、科技、政府、住宿餐饮、娱乐、建筑、物流等。科技/互联网只是其中一小块。
- 偏美国 LinkedIn 式画像，很多人**有多段跨行业经历**（人均 4.3 段工作经历，总经验中位数约 13.5 年）。

**因此设计原则是：不预设候选人是"技术人才"，所有维度必须对任意行业、任意职能都成立。** 用户搜"资深护士长""财务经理""销售总监""酒店运营"和搜"后端工程师"，走的是同一套机制。

---

## 1. HR 真实筛人时，到底看什么？

我们把 HR 的关注点归纳成 8 个大类。这也是本系统评分维度的来源。

| HR 关注的问题 | 通俗解释 | 本系统对应维度 |
|---|---|---|
| ① 是不是干这行的？ | 岗位/职能对不对口 | 岗位匹配 |
| ② 干了多久、够不够资深？ | 年限 + 职级 | 资历匹配 |
| ③ 会不会我要的技能？ | 技能、工具、专业能力 | 技能匹配 |
| ④ 有没有相关经验/项目？ | 做过类似的事 | 经验匹配 |
| ⑤ 行业背景对不对？ | 医疗/金融/制造等行业经验 | 行业匹配 |
| ⑥ 是执行还是负责？带不带人？ | 职责边界、是否管理/决策 | 职责与管理 |
| ⑦ 学历、证书够不够格？ | 学历门槛、证书偏好 | 教育与证书 |
| ⑧ 有没有硬伤/风险？ | 头衔与实际不符、纯理论、跳槽频繁等 | 风险提示（仅输出，不计分） |

---

## 2. 两种规则：硬规则 vs 软规则（先讲清区别）

这是整个机制最重要的一件事。

- **硬规则（Hard）= 门槛（第一轮）。** 明确不满足就**淘汰**（比如"必须硕士以上""必须是护理岗"）。只有证据**非常明确**时才敢淘汰人；证据不足时**不淘汰**，只标记"证据不足"如实告知（本期不因此扣分）。
- **软规则（Soft）= 打分（第二轮）。** 不淘汰任何人，只决定排名高低（比如"最好做过跨境电商""优先带过团队"）。越贴近需求，分越高；**"不要 X" 用负权重的软项表达**，越像越往下拉。

**怎么区分是硬还是软？看用户怎么说话：**
- 说"必须 / 只要 / 一定 / 排除某类" → 且落在 7 个够格字段上 → **硬规则（第一轮过滤）**。
- 说"最好 / 优先 / 倾向 / 熟悉 / 不要偏向…" → **软规则（第二轮打分，可正可负权重）**。

> 为什么要这么谨慎地淘汰人？因为我们的数据有缺失——很多简历没写职级、没写行业、没写工作描述。**"简历没写"不等于"他不会/没做过"。** 所以除非有明确证据，否则宁可交给第二轮软打分处理，也不在第一轮硬淘汰，避免误杀好候选人。

---

## 3. 评分维度总表（8 个维度）

下表说明每个维度**看什么、在两段式里怎么用（第一轮硬过滤 / 第二轮软打分 / 仅提示）、我们的数据撑不撑得住**。

| 维度 | 看什么 | 本期怎么用 | 数据支撑度 | 数据来源字段 |
|---|---|---|---|---|
| **1. 岗位匹配** | 职能/岗位对不对口 | 硬过滤（role_family）+ 软打分 | 强 | `role`、`title`、`headline`、`active_experience_title` |
| **2. 资历匹配** | 工作年限 + 职级 | 硬过滤（年限、职级）+ 软打分 | 强（年限）/ 中（职级） | `total_experience_duration_months`、`level`、`active_experience_management_level` |
| **3. 技能匹配** | 会不会目标技能/工具 | 仅软打分（不作硬过滤） | 中（噪声多） | `skills`、`experience.description` |
| **4. 经验匹配** | 做过没做过类似的事 | 仅软打分 | 中（描述仅 45% 覆盖） | `experience.description`、`title` |
| **5. 行业匹配** | 行业背景对不对 | 硬过滤（industries）+ 软打分 | 中 | `industry`、`company_tags`、`company_name` |
| **6. 职责与管理** | 执行 vs 负责、带不带人 | 硬过滤（management_scope）+ 软打分 | 中 | `management_level`、`is_decision_maker`、`level`、描述 |
| **7. 教育与证书** | 学历门槛、证书偏好 | 硬过滤（学历等级）+ 软打分（专业/证书） | 强（学历）/ 中（证书） | `education.degree_level`、`major`、`certifications` |
| **8. 风险提示** | 硬伤、头衔虚高、纯理论 | 仅输出提示，不计分 | 中 | 多字段交叉推断 |

> 说明：能进第一轮硬过滤的只有 7 个够格硬字段（§7）。技能、证书、经验因数据覆盖或噪声问题，本期**只进第二轮软打分**，不作硬淘汰。

---

## 4. 每个维度详解（含数据能力边界）

### 维度 1：岗位匹配（Role）
- **看什么**：候选人是不是干这个岗位的。用固定的 18 类职能族群做归类，再叠加职位名称的语义相似度。
- **硬规则用法**：用户说"必须是销售岗""必须是护理岗"时，职能族群不符→淘汰。
- **数据能力**：`role` 字段用的是 LinkedIn 标准 18 类（教育/工程技术/销售/运营/医疗/行政/财务/研究/市场/法务/HR/设计/咨询/技工/客服/C-Suite 等），可直接当枚举；缺失的段用 `title`/`headline` 语义补。
- **注意**：很多段没有 `role`，所以判断要综合当前职位 + 历史职位，不能只看一段。

### 维度 2：资历匹配（Seniority）
分两块：
- **工作年限**：`total_experience_duration_months ÷ 12`。94.5% 的人有这个字段，缺失的用各段 `duration_months` 汇总。→ **可做硬门槛**（如"≥5 年"）。
- **职级**：映射到统一 8 档 —— 实习 < 初级 < 资深(Senior) < 经理(Manager) < 总监(Director) < VP < C-Level < 创始人/Owner。来源 `active_experience_management_level` 和 `level`。→ 用户说"必须 Senior 以上""不要实习生"时可做硬门槛。
- **数据能力**：职级字段有缺失，缺失时从职位名关键词推断（置信度降一档），**推断出的职级不单独淘汰人**。

### 维度 3：技能匹配（Skill）
- **看什么**：会不会用户点名的技能/工具/专业词（如"CPA""焊接""儿科护理""Excel 建模""Python"）。
- **怎么算**：本期通过 `skills_search_text` 的语义相似度参与第二轮软打分（不作硬过滤）。
- **数据能力（重要）**：`skills` 字段噪声大——人均 11 个词，混杂大量不相关或空泛词。所以预处理时：
  - 技能只出现在 `skills` 列表里 → 记为**中等置信**。
  - 技能同时在 `experience.description` 里被印证过 → **高置信**（verified）。
  - 这个 verified 标记本期用于清洗检索文本、供解释；未来可支撑"语义+关键词双命中加分"（agreement_boost，暂不做）。
- 这样避免"简历堆了一堆技能词但其实没做过"的候选人被过度抬高（对应风险维度的"技能堆砌"提示）。

### 维度 4：经验匹配（Experience）
- **看什么**：有没有做过类似的项目/职责，而不只是头衔像。
- **数据能力（要坦白的短板）**：`experience.description` 只有 **45%** 的经历段有内容。所以：
  - 有描述 → 用描述做语义匹配，证据强。
  - 没描述 → 退化成用职位名 + 公司 + 行业推断，证据弱，**只影响排名不淘汰人**。
- 这条维度我们**不做硬淘汰**，因为缺描述太普遍，硬淘会误杀。

### 维度 5：行业匹配（Domain/Industry）
- **看什么**：有没有目标行业背景（医疗、金融、制造、教育、政府等）。
- **硬规则用法**：用户说"必须有医疗行业经验"时，可淘汰无任何医疗经历的人。
- **数据能力**：`industry` 字段有缺失（很多段为空），用 `company_tags`、`company_name` 补。用 LinkedIn 标准 24 类行业做枚举。跨行业经历会被全部保留，只要有一段命中即算有背景。

### 维度 6：职责与管理（Ownership & Management）
- **看什么**：是"执行者"还是"负责人"？带不带团队？是不是决策者？
- **为什么单列**：HR 常遇到"头衔像但其实只是助理/支持岗"的情况。这个维度专门区分 owned（负责）/ managed（带人）/ support（支持）。
- **硬规则用法**："必须带过团队""必须是决策者"→ 可硬判（`is_decision_maker`、管理层级）。
- **数据能力**：`active_experience_management_level`、`is_decision_maker`、`level` 有一部分人有；描述里的"led/managed/owned/responsible for"可补充证据。

### 维度 7：教育与证书（Education & Certification）
- **学历**：`degree_level` 编码 **0=大专及以下、1=本科、2=硕士、3=博士**，全员都有教育记录，取最高一段。→ **可做硬门槛**（"本科以上"=≥1，"硕士以上"=≥2）。
- **专业**：`major` 全员有，用于"要求相关专业"。
- **证书**：`certifications` 只有 22% 的人有。本期**不作为第一轮硬淘汰条件**：有明确证书要求（CPA/PMP/护士执照/AWS 等）时，命中者可提升软匹配排序，原始证书数组随 `raw_profile` 返回；缺失者保留，Agent 需要向用户说明：证书字段完备性不足，不能可靠用作硬筛。

### 维度 8：风险提示（Risk，仅输出不计分）
不是找优点，是找**硬伤**。本期**风险不进 final_score**，SearchResult 也不返回候选人级 `risk_flags`。Agent 如需提示风险，必须基于 `raw_profile` 中的原始字段自行判断，并说明证据：
- **头衔与实际不符**：职位名很唬人，但描述/职级显示只是执行或助理岗。
- **纯理论/纯研究**：只有论文、研究、无落地交付证据（如需排斥，用负权重软项表达）。
- **技能堆砌**：技能列表很长但描述里毫无印证。
- （可选）**频繁跳槽**：单段任职中位数仅约 2 年，若用户在意稳定性可开启此项，但**默认不开**，避免对正常换工作的人误伤。

> 注意：硬条件"证据不足"是**第一轮硬过滤**阶段的标记（保留进池、不淘汰、不扣分），在 `results[].hard_filter_status` 中体现，不属于风险提示。

---

## 5. 最终怎么合并成一个分（评分机制）

本系统采用**清爽的两段式**：第一轮纯硬过滤（只淘汰、不打分），第二轮纯软加权（只打分、不淘汰）。硬和软彻底解耦，各管一件事。

### 第一轮：硬过滤（pass / fail，不产生分数）

- Agent 指定硬条件，每条由 `field`、`op`、`value`、`rationale` 表达；包含、排除和比较语义由字段对应的 `op` 表达。
- 能挂硬条件的字段**有限**——只有那 7 个数据够充分、且值为**枚举或可比较数字**的够格字段（年限、学历等级、职能族群、职级、管理范围、行业、是否在职）。
- 明确违反任一硬条件 → **直接淘汰**，不进入打分。
- **证据不足的处理**：既不能确认满足、也不能确认违反的候选人 **不淘汰、保留进池**，打上 `insufficient_evidence` 标记如实告知，但**不在分数里扣**（保持第一轮纯 pass/fail，不掺分数）。

这一轮结束得到一个**幸存池**。所有幸存者对 must 条件都满足，所以"硬条件达成度"在池内几乎是常数——这正是我们不再让它进入总分的原因：它已经不区分人了。

### 第二轮：软加权打分（只在幸存池内比"多好"）

```
score_before_weight_i = percentile_i
score_after_weight_i = weight_i × score_before_weight_i
final_score = Σ score_after_weight_i
```

- 每个软项是一个三元组 `{ dimension, text, weight }`：
  - `dimension`：打到哪个 `*_search_text` 检索维度。
  - `text`：写成"具体做什么"的工作内容描述（见 EmbeddingFieldDesign）。
  - `weight`：相对权重，**可正可负**。
- `score_before_weight_i`：候选人在该维度上，`text` 与其检索文本的 embedding 余弦相似度，**在幸存池内换算成排名百分位**（0~1）。
- `score_after_weight_i`：该软项实际计入总分的加权后贡献。Tool 不暴露 raw cosine。
- 按 `final_score` 降序排名；同分候选人使用相同 rank，例如分数 `9.0, 8.5, 8.5, 8.0` 对应 rank `1, 2, 2, 4`。

**两个关键设计：**

1. **排名百分位做校准**：embedding 余弦分是压缩的（常挤在 0.4~0.7）、且跨维度基线不同，直接加权会让基线高的维度无理由主导。改用**池内排名百分位**后，每个维度都摊成可比的 0~1 分布，跨维度可加，且分数天然对应"在本次候选池里排多前"。

2. **负权重取代旧的 avoid 机制**：过去处理"不要纯审计"要单独改写负向画像、单独算 penalty。现在只需一个普通软项 `{ responsibilities, "以外部审计为主的工作", weight: -0.8 }`——和这段文本越像的人百分位越高，乘负权重就把总分往下拉。**"不要 X" = 负权重的偏好**，不再是独立机制。查询结构因此从四块缩到两块（hard_constraints + weighted_soft_preferences）。

### 暂不实现（未来工作）

以下"硬条件辅助软条件"的机制经讨论**本期不做**，从公式中移除，留待后续：

- `agreement_boost`：语义 + 关键词双命中的一致性加分。
- `conflict_penalty`：职责边界 / 资历冲突扣分。
- `insufficient_evidence_penalty`：证据不足的分数惩罚（本期只标记不扣分）。

风险维度（§4）本期不进入 `final_score` 计算，也不作为候选人级复杂输出字段返回；Agent 只可基于 `raw_profile` 原始字段自行提示。

---

## 6. Tool 最终返回什么

| 输出 | 含义 |
|---|---|
| `search_meta` | 本次检索元信息：候选池规模、幸存人数、返回数量、同分是否超过 top_k、分数公式 |
| `results[].rank` / `user_id` / `final_score` | 简单排序元信息 |
| `results[].hard_filter_status` | 结构化状态对象：`status` 为 `passed` 或 `kept_with_insufficient_evidence`，并带 `insufficient_evidence_fields` |
| `results[].soft_preference_scores` | 每条软偏好的加权前 percentile 分数和加权后贡献，与 QueryPlan 中的 `weighted_soft_preferences[]` 按序号对齐 |
| `results[].raw_profile` | 原始候选人 profile，格式与 JSONL 数据一致 |

Tool 不返回候选人级复杂解释字段，如 `soft_contributions`、`matched_evidence`、`risk_flags`。核心承诺改为：**排序由 Tool 确定，解释由 Agent 基于原始 profile 完成。** Agent 必须引用 `raw_profile` 中真实存在的字段，不能把缺失说成没有。

---

## 7. 一句话总结硬/软划分

- **第一轮硬过滤（明确才淘汰，不打分）**：工作年限、学历等级、职能族群、职级、管理范围、行业背景、是否在职——限这 7 个数据充分、可枚举或可比较的字段。证据不足者保留并标记，不淘汰、不扣分。
- **第二轮软打分（只在幸存池内比高低）**：所有偏好统一为带权重的软项，权重可正可负；每维用池内排名百分位校准后加权求和。"不要 X"用负权重表达。
- **暂不做**：agreement_boost、conflict_penalty、证据不足扣分等"硬辅助软"机制；风险仅作输出提示，不进总分。

---

## 附：需要固化的枚举表（实现时定稿）

- **职能族群（18 类）**：Education, Engineering and Technical, Sales, Operations, Medical, Administrative, C-Suite, Customer Service, Finance & Accounting, Research, Marketing, Trades, Design, Legal, Human Resources, Consulting, Project Management, Other。
- **职级（8+ 档，归一）**：Intern < Specialist(执行) < Senior < Manager < Director < President/VP < C-Level < Founder/Owner/Partner。
- **学历编码**：0=Associate及以下, 1=Bachelor, 2=Master, 3=Doctorate。
- **行业（24 类，LinkedIn 标准）**：Education, Professional Services, Manufacturing, Hospitals and Health Care, Financial Services, Retail, Technology/Information/Media, Government Administration, Consumer Services, Accommodation Services, Entertainment, Administrative and Support Services, Construction, Transportation/Logistics, Real Estate, Utilities, Oil/Gas/Mining, Wholesale, Farming/Ranching/Forestry 等。
