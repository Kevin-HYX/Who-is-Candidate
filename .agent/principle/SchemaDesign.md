# AI 预处理输出 Schema 设计（第一轮预处理契约）

> 本文定义预处理阶段 **AI 第一轮预处理** 的输出结构，重点是**造出可用于硬筛选的结构化字段**。
>
> 相关：[ScoringDesign.md](./ScoringDesign.md)（评分维度）、[SystemDesign.md](./SystemDesign.md)、[ImplementationPlan.md](./ImplementationPlan.md)。

---

## 1. 为什么要 AI 预处理：原始数据不够硬

硬筛选（明确不满足就淘汰）要求字段满足两个条件：

1. **数据支撑足**：缺失率低——因为"简历没写"不能当"不满足"，缺失一多就误杀。
2. **可判定**：能收敛成**少数几个枚举值**或**可比较的整数**——否则没法做布尔/阈值判断。

但原始数据结构性不强：`role` 有 861 段缺失、`level` 缺失、`industry` 缺失 1388 段、`management_level` 3 成人没有。直接拿原始字段做硬筛选会大面积误杀。

**所以硬筛选字段不是"从原始字段里挑现成的"，而是由 AI 第一轮预处理专门归一。** AI 的任务是：从接近满覆盖的锚点字段出发，把散乱信息归一成干净的枚举 / 整数硬字段，并为每个结论附证据。

**AI 可依赖的高覆盖锚点字段（实测）：**

| 锚点字段 | 覆盖 | 能造出的硬字段 |
|---|---|---|
| `experience[].title` | **4286/4286 = 100%** | role_family、seniority_level |
| `education[].degree_level` | 每条教育记录都有，全员有教育 | highest_degree_level |
| `duration_months` + `total_experience_duration_months` | 4200/4286 + 945/1000 | years_of_experience |
| `company_name` / `company_tags` | 4283 / 4286 | industries |
| `active_experience_management_level` / `is_decision_maker` / `level` | 部分 + title 补 | seniority、management |

---

## 2. 硬筛选字段资格判定（预处理后是否够格）

对每个候选硬字段，按"预处理后缺失率"和"是否可枚举/可比较"两关判定：

| 预处理后字段 | 目标类型 | 预处理后覆盖预期 | 可枚举/可比较 | **是否够格硬筛选** |
|---|---|---|---|---|
| `years_of_experience` | 整数（年） | 高（title+duration 几乎全可算） | 可比较整数 | ✅ 够格 |
| `highest_degree_level` | 枚举 0/1/2/3 | 高（全员有教育） | 可比较整数 | ✅ 够格 |
| `role_family` | 18 类枚举 | 高（title 100% 可推） | 枚举 | ✅ 够格 |
| `seniority_level` | 8 档枚举 | 中高（title+level 推断） | 可比较枚举 | ✅ 够格（推断段降置信） |
| `management_scope` | 枚举 none/lead/manage/decision | 中（部分锚点+描述） | 枚举 | ✅ 够格 |
| `industries` | 24 类枚举（多值） | 中高（title/公司/tags 补） | 枚举集合 | ✅ 够格 |
| `is_currently_working` | 布尔 | 高（is_current 可推） | 布尔 | ✅ 够格（仅用户明确要求时启用） |
| `certifications_normalized` | 归一枚举 | **低（原始仅 22%）** | 枚举 | ⚠️ **默认不够格**：AI 造不出没有的证书；缺失只标 insufficient_evidence，仅当用户明确点名证书时作为软信号（满足即写进检索文本/解释，缺失不淘汰） |
| `licenses` | 归一枚举 | 低 | 枚举 | ⚠️ 同上 |
| `hard_skills` | 归一技能集合 | 中（噪声大） | 枚举集合 | ⚠️ **不作硬筛**：仅列表出现记 medium，被描述印证才 high；只进第二轮软打分，不淘汰 |

**结论**：够格默认硬筛选的只有 7 个 —— `years_of_experience`、`highest_degree_level`、`role_family`、`seniority_level`、`management_scope`、`industries`、`is_currently_working`。其余（证书、执照、技能）**即使预处理后也停留在软规则/证据不足**层面。

---

## 3. 硬筛选字段规范（AI 输出契约）

每个字段是一个对象，除值外必须带 `confidence` / `source_field` / `evidence`。缺证据只能给 `unknown`，**不得猜成满足**。

### 3.1 `years_of_experience`
```json
{ "value": 12, "unit": "years",
  "derivation": "total_experience_duration_months",   // 或 "summed_from_experience"
  "confidence": "high", "source_field": "total_experience_duration_months",
  "evidence": "162 months" }
```
- 规则：优先用 `total_experience_duration_months ÷ 12`；缺失时汇总各段 `duration_months`（去重叠），置信降为 medium。都没有 → `unknown`。

### 3.2 `highest_degree_level`
```json
{ "value": 2, "label": "Master",
  "confidence": "high", "source_field": "education[0].degree_level",
  "evidence": "Master of Business Administration (MBA)" }
```
- 编码：`0=Associate及以下, 1=Bachelor, 2=Master, 3=Doctorate`。取所有教育段最大值。全员有教育记录，覆盖高。

### 3.3 `role_family`（18 类枚举，可多值取主）
```json
{ "primary": "Finance & Accounting",
  "all": ["Finance & Accounting", "Administrative"],
  "confidence": "high", "source_field": "experience[0].role",
  "evidence": "role=Finance & Accounting; title=Billing Manager" }
```
- 枚举：Education, Engineering and Technical, Sales, Operations, Medical, Administrative, C-Suite, Customer Service, Finance & Accounting, Research, Marketing, Trades, Design, Legal, Human Resources, Consulting, Project Management, Other。
- 规则：有 `role` 字段 → high；只能从 `title` 推 → medium。primary 取当前/最近一段的族群，`all` 汇总全部经历（支持跨行业/跨职能）。

### 3.4 `seniority_level`（8 档，可比较）
```json
{ "value": "Manager", "rank": 4,
  "confidence": "medium", "source_field": "experience[0].title",
  "evidence": "title contains 'Manager'; no explicit level field" }
```
- 归一档位（rank 便于比较）：`Intern=0 < Specialist=1 < Senior=2 < Manager=3 < Director=4 < President/VP=5 < C-Level=6 < Founder/Owner/Partner=7`。
- 规则：有 `management_level`/`level` → high；仅 title 关键词推断 → medium（**推断出的职级不用于第一轮硬淘汰**，只作第二轮软打分/解释参考）。

### 3.5 `management_scope`（枚举）
```json
{ "value": "manage_team",   // none | lead_no_report | manage_team | decision_maker
  "confidence": "high", "source_field": "is_decision_maker + level",
  "evidence": "is_decision_maker=true; level=Director" }
```
- 规则：`is_decision_maker=true` 或 C-Level/VP/Owner → decision_maker；level=Manager/Director 或描述含 "managed a team of" → manage_team；描述含 "led" 无下属证据 → lead_no_report；否则 none/unknown。

### 3.6 `industries`（24 类枚举，多值）
```json
{ "all": ["Hospitals and Health Care", "Financial Services"],
  "primary": "Hospitals and Health Care",
  "confidence": "medium", "source_field": "experience[].industry + company_tags",
  "evidence": "industry=Hospitals and Health Care; tags include 'medical'" }
```
- 枚举：LinkedIn 标准 24 类（见 ScoringDesign 附录）。
- 规则：有 `industry` → high；用 `company_tags`/`company_name` 推断 → medium。**只要有一段命中即算有该行业背景**（跨行业保留）。

### 3.7 `is_currently_working`（布尔）
```json
{ "value": true, "confidence": "high",
  "source_field": "is_working", "evidence": "is_working=true" }
```
- 规则：优先读 `is_working`；缺失时看是否存在 `experience.is_current=true` 段。仅当用户明确要求"在职"时才作硬条件。

---

## 4. 同一轮里顺带产出的非硬字段（软打分 & 风险用）

AI 预处理一次成型，除 `hard_fields` 外同时产出（详见 ScoringDesign、EmbeddingFieldDesign）：

- **`embedding_search_texts`（7 个检索文本）**：`responsibilities_search_text`、`skills_search_text`、`experience_search_text`、`domain_search_text`、`ownership_search_text`、`achievements_search_text`、`education_search_text` —— 供 embedding 语义匹配（第二轮软打分），允许弱证据。
- **`risk`（3 个风险文本 + risk_flags）**：`role_boundary_risk_text`、`research_only_risk_text`、`skill_stuffing_risk_text`；离散标记如 `title_role_mismatch`、`research_heavy`、`skill_unverified`。这是预处理结构内部标记，本期不计分，也不作为 SearchResult 的候选人级复杂字段返回。
- **`keyword_signals`（关键词信号）**：`hard_skills`（含 verified 标记）、`title_keywords`、`description_facts`、`sparse_bonus`（awards/publications/patents）。

---

## 4.5 LLM 可派生的预处理字段（原始数据里没有，但能算出来）

除了归一原有字段，LLM 在预处理阶段还应**计算 / 推断出原始 JSON 里不存在、但 HR 精准匹配时真正需要的派生指标**。这些字段是本系统相对"关键词搜简历"的核心增值。每个仍须带证据，缺证据标 `unknown`。

下表按数据支撑度和用途分级（覆盖度均为实测）：

| 派生字段 | 含义 / HR 为什么要 | 怎么算 | 数据支撑 | 用途（本期） |
|---|---|---|---|---|
| `domain_years`（分领域年限） | "总经验 20 年，但财务只有 2 年" —— 总年限骗人，领域年限才准 | 按 `role_family`/`industry` 分组累加 `duration_months` | 强（title+duration 全覆盖） | 软/解释 |
| `current_role_tenure_months`（现岗时长） | 判断稳定性 / 是否刚上手 | 当前经历段 `duration_months` | 强 | 软 |
| `avg_tenure_months`（平均任职时长） | 跳槽频率、稳定性 | 各段 duration 均值 | 强 | 软（可选风险，默认关闭） |
| `career_gap_flag`（职业空窗） | 有无长时间空档 | 相邻经历时间差 > 阈值 | 中（依赖起止年月） | 软/风险提示 |
| `locations`（工作地点） | "必须在某城市 / 某国 / 远程" | `experience.address_*` / `full_address` 归一 | **强（908/1000 有）** | 软/解释 |
| `company_size_tier`（公司规模档） | "来自大厂 / 初创经验" | `company_size_range`（1=最小…7=最大，-1未知）归档 | 中（约 2/3 段有） | 软 |
| `company_types`（公司性质） | "政府 / 非营利 / 上市公司背景" | `company_type` 归一（私企/上市/教育/非营利/政府/合伙/自雇） | 中高 | 软 |
| `industry_focus`（领域专注度） | 通才 vs 深耕某行 | 不同 `industry` 数（中位 1、最多 7） | 强 | 软（解释用） |
| `career_progression`（晋升轨迹） | 是否有成长、从执行到管理 | seniority rank 随时间是否上升 | 中（依赖职级+时间） | 软/解释 |
| `regulated_industry_flag`（受监管行业经验） | 医疗/金融/政府等合规敏感岗看重 | industries 命中受监管集合 | 中 | 软 |
| `quantified_achievements`（量化成果） | "增长 30%""省 $2M""带 10 人团队" | 从 description 抽数字化成果 | **弱（仅 437/1950 描述有）** | 软/解释（稀疏） |
| `explicit_team_size`（明确带团队规模） | "带过多大团队" | description 里 "team of N" 等 | **很弱（仅 51 人）** | 软/解释（稀疏） |
| `languages` / `keywords_extra` | 语言能力、其他可搜特征 | summary/description 抽取 | 弱 | 软/解释（稀疏） |

**用途说明（对齐两段式）**：本期**硬筛选字段锁定为 §2 认定的 7 个**，派生字段**一律不作硬条件**——它们全部服务于第二轮软打分与结果解释。派生字段之所以有价值，是它们能被写进检索文本、或供 Agent 生成解释；`domain_years`、`locations`、`company_types` 数据覆盖虽好，但本期也只作软用途，是否未来升级为硬字段留待后续（需先补相应过滤算子）。稀疏字段（量化成果、团队规模）本就只在有数据时锦上添花，无数据不影响候选人。

派生字段输出规范同 §3，每个带 `value` + `confidence` + `source_field` + `evidence`。示例：

```json
"domain_years": [
  { "domain": "Finance & Accounting", "years": 11, "confidence": "high",
    "source_field": "experience[].role+duration_months",
    "evidence": "Billing Manager 60m + Independent Contractor 233m in finance roles" },
  { "domain": "Administrative", "years": 1, "confidence": "medium",
    "source_field": "experience[1].role", "evidence": "Club Administrator 12m" }
]
```

## 5. 预处理输出顶层结构（一条候选人）

```json
{
  "user_id": 218051274,
  "hard_fields": {
    "years_of_experience": { ... },
    "highest_degree_level": { ... },
    "role_family": { ... },
    "seniority_level": { ... },
    "management_scope": { ... },
    "industries": { ... },
    "is_currently_working": { ... }
  },
  "embedding_search_texts": {
    "responsibilities_search_text": "…", "skills_search_text": "…", "experience_search_text": "…",
    "domain_search_text": "…", "ownership_search_text": "…", "achievements_search_text": "…",
    "education_search_text": "…"
  },
  "derived_fields": {
    "domain_years": [ {"domain": "Finance & Accounting", "years": 11, "confidence": "high", "source_field": "...", "evidence": "..."} ],
    "current_role_tenure_months": { "value": 233, "confidence": "high", "source_field": "experience[is_current].duration_months", "evidence": "233 months" },
    "avg_tenure_months": { "value": 102, "confidence": "medium", "source_field": "experience[].duration_months", "evidence": "3 jobs" },
    "locations": { "value": ["United States"], "confidence": "medium", "source_field": "experience[].full_address", "evidence": "no address on current role" },
    "company_size_tier": { "value": "unknown", "confidence": "low", "source_field": "company_size_range", "evidence": "all -1" },
    "company_types": { "value": [], "confidence": "unknown", "source_field": "company_type", "evidence": "not_provided" },
    "regulated_industry_flag": { "value": true, "confidence": "high", "source_field": "industries", "evidence": "Hospitals and Health Care" },
    "quantified_achievements": [ {"text": "98% billing accuracy", "confidence": "high", "source_field": "active_experience_description", "evidence": "ninety-eight percent accuracy"} ],
    "explicit_team_size": { "value": null, "confidence": "unknown", "source_field": "description", "evidence": "not_provided" }
  },
  "keyword_signals": {
    "hard_skills": [ {"skill": "medical billing", "verified": true, "source_field": "experience[0].description"} ],
    "title_keywords": ["billing manager", "independent contractor"],
    "description_facts": ["managed billing and collections", "HIPAA compliance"],
    "sparse_bonus": {"awards": 0, "publications": 0, "patents": 0}
  },
  "risk": {
    "role_boundary_risk_text": "…",
    "research_only_risk_text": "…",
    "skill_stuffing_risk_text": "…",
    "risk_flags": []
  },
  "raw_profile_ref": "保留指向原始 JSONL 行的引用，最终解释可回溯"
}
```

---

## 6. AI 预处理的硬约束（不可违反）

1. 每个推断字段必须带 `confidence` / `source_field` / `evidence`。
2. 无证据只能标 `unknown` / `not_provided` / `insufficient_evidence`；**缺失不得当负面证据，也不得猜成满足**。
3. 硬字段只在**明确字段或 high 置信 evidence** 下才允许后续用于淘汰；medium/low 置信不用于淘汰，标 insufficient_evidence 或留给软打分层。
4. 枚举字段必须落在预定义枚举内；无法归类填 `Other` 并在 evidence 说明。
5. 原始 profile 必须保留，任何结论可回溯原文。

---

## 7. 一句话总结

AI 第一轮预处理的核心产出是 **7 个够格硬字段**（年限、学历等级、职能族群、职级、管理范围、行业、在职）——它们缺失率低、可枚举或可比较，是唯一允许用于淘汰的字段；证书、执照、具体技能因原始覆盖太低或噪声大，预处理后仍只进第二轮软打分或标证据不足，不参与硬淘汰。
