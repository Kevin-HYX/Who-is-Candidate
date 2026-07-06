# 预处理 LLM 判断标准（防幻觉规范）

> 本文是给**预处理 LLM** 的判断标准，逐字段、分点给出"凭什么下这个结论、什么时候必须说 unknown"，直接嵌入提示词，压制预处理阶段的幻觉。
>
> 相关：[SchemaDesign.md](./SchemaDesign.md)（输出契约）、[EmbeddingFieldDesign.md](./EmbeddingFieldDesign.md)（检索文本构建）。

---

## 0. 先分清：哪些不该问 LLM（公式字段 vs 推断字段）

**减少幻觉的第一原则是：能用代码算的，绝不让 LLM 判断。**

| 字段 | 处理方 | 说明 |
|---|---|---|
| `years_of_experience` | **代码公式** | `total_experience_duration_months ÷ 12`，缺失则汇总各段（去重叠） |
| `highest_degree_level` | **代码公式** | `max(education[].degree_level)` |
| `current_role_tenure_months` / `avg_tenure_months` | **代码公式** | 直接取/求均值 |
| `career_gap_flag` | **代码公式** | 相邻经历时间差阈值 |
| `domain_years` 的加总 | **代码公式** | 分组求和；但**分组用的 role_family 是推断字段** |
| —— 以下必须 LLM 推断 —— | | |
| `role_family`（缺 role 时） | LLM | 从 title/描述归类 |
| `seniority_level`（缺 level 时） | LLM | 从 title 关键词判级 |
| `management_scope` | LLM | 综合多字段判断带人/决策 |
| `industries`（缺 industry 时） | LLM | 从公司名/tags 推断 |
| `hard_skills` 的 verified 标记 | LLM | 判断技能是否被描述印证 |
| `regulated_industry_flag` | LLM | 判断是否受监管行业 |
| 7 个检索文本 / 3 个风险文本 | LLM | 职责内容转写 |
| `quantified_achievements` | LLM | 抽取量化成果 |
| `risk_flags` | LLM | 判断硬伤 |

下面只给**推断字段**的判断标准。公式字段交给代码，LLM 不碰。

---

## 1. 全局防幻觉铁律（所有推断字段通用）

1. **有据才判**：每个结论必须能指到原文字段（`source_field`）和原文片段（`evidence`）。指不出 → `unknown`。
2. **缺失 ≠ 否定**：字段没写，只能是 `unknown` / `not_provided`，**绝不能推成"不满足"，也不能推成"满足"**。例：没写证书 ≠ 没有证书；没写管理 ≠ 不带团队。
3. **不外推、不脑补**：不能因"这个 title 一般都会 X"就断定候选人 X。行业常识不是证据。
4. **区分"写了" vs "做了"**：`skills` 列出某技能，只证明"写了"；只有 `description` 印证才算"做了"（verified）。
5. **保守优先**：证据模糊时给低置信 + 保守值，把裁决权留给结构化字段和人工，而不是替用户拍板。
6. **只在枚举内取值**：枚举字段必须落在预定义集合；无法归类填 `Other` 并说明，禁止自造标签。
7. **不改写事实**：转写检索文本时可归纳，但不得新增未发生的项目、成果、职责。

---

## 2. 逐字段判断标准

### 2.1 `role_family`（18 类职能族群）
**判断顺序（从强到弱证据）：**
1. 该段有 `role` 字段 → 直接用，`confidence=high`。
2. 无 `role`，但 `title` 明确指向某族群 → 归类，`confidence=medium`。
3. `title` 模糊（如裸 "Manager""Associate""Consultant"）→ 结合 `description`/`department`/`company` 判断；仍无法确定 → `Other` + `low`，evidence 说明歧义。

**归类判据（点명到族群）：**
- 含教学/教授/教师/讲师/助教/学校 → Education
- 含 nurse/physician/clinical/medical/therapy/patient → Medical
- 含 sales/account executive/business development/retail associate → Sales
- 含 accountant/billing/audit/finance/bookkeep → Finance & Accounting
- 含 software/developer/engineer/network/data/IT → Engineering and Technical
- 含 admin/assistant/coordinator/clerk/office → Administrative
- 含 CEO/CFO/COO/owner/founder/president → C-Suite
- 含 research/scientist/lab/study → Research
- （其余按 ScoringDesign 18 类同理）

**禁止：** 仅凭公司行业反推职能（在医院工作 ≠ 医疗岗，可能是行政/IT）。

**歧义 title 强制消歧表：**
| 裸 title | 必须结合什么判断 |
|---|---|
| Manager | 看 description：管人？管项目？管店？→ 决定 Operations/Project/Retail-Sales |
| Analyst | 财务/系统/业务？→ Finance/Engineering/Consulting |
| Associate | 零售/律所/研究？→ Sales/Legal/Research |
| Coordinator | 市场/项目/后勤？|
| Director | 部门方向决定族群，不是一律 C-Suite |

### 2.2 `seniority_level`（8 档 rank）
**档位：** Intern=0 < Specialist=1 < Senior=2 < Manager=3 < Director=4 < President/VP=5 < C-Level=6 < Founder/Owner/Partner=7。

**判断顺序：**
1. 有 `active_experience_management_level` 或 `level` → 用，`high`。
2. 仅 title 关键词 → 推断，`medium`：
   - intern/trainee → Intern
   - senior/sr./lead/principal → Senior（lead 若明确带人升 Manager）
   - manager/supervisor/head of → Manager
   - director → Director；VP/vice president → VP；chief/C?O → C-Level；owner/founder/partner → 对应档
   - 无修饰的执行岗（specialist/associate/officer/representative）→ Specialist
3. 冲突时（title 说 Senior，level 说 Specialist）→ 取**结构化 level 字段**为准，evidence 记录冲突，`medium`。

**铁律：** 推断出的职级（medium/low）**不得用于第一轮硬淘汰**，只作为第二轮软打分/解释的参考。"Senior" 出现在公司名/产品名里（如 "Senior Care Inc"）不算职级——必须是修饰职位的词。

### 2.3 `management_scope`（none / lead_no_report / manage_team / decision_maker）
**判据（按证据强度）：**
- `is_decision_maker=true` 或 level ∈ {C-Level, VP, Owner, Director} → `decision_maker`，`high`。
- level=Manager 或 description 含 "managed a team of N""supervised N staff""led a department" → `manage_team`，`high`。
- description 含 "led"/"coordinated" 但无下属证据 → `lead_no_report`，`medium`（带项目不等于带人）。
- 无任何管理信号 → `none`（若字段齐全）或 `unknown`（若信息缺失）。

**禁止：** 把 "Manager" 头衔直接等于带人（Account Manager、Product Manager 常常不带人）。必须有下属/团队证据才算 manage_team。

### 2.4 `industries`（24 类，多值）
**判断顺序：**
1. 该段有 `industry` → 用，`high`。
2. 无，但 `company_tags`/`company_name` 明确 → 推断，`medium`。
3. 都模糊 → 该段不赋行业（`unknown`），不猜。

**铁律：** 只要有**一段**明确命中即算候选人"有该行业背景"（保留跨行业）；但不能因当前公司是医院就把全部经历标成医疗。逐段判断。

### 2.5 `regulated_industry_flag`
- industries 命中受监管集合（医疗、金融、政府、保险、制药、航空、能源）→ `true` + 指明哪段。
- 否则 `false`（若行业明确）或 `unknown`（行业缺失）。不凭 title 猜。

### 2.6 `hard_skills` 的 `verified` 标记
- 技能词同时出现在 `skills` **且**某段 `description` 用到 → `verified=true`，`high`，指出是哪段。
- 只在 `skills` 列表 → `verified=false`，`medium`。
- **清洗**：剔除泛词（management/responsible/less）、UI 残留、纯形容词后再纳入。
- **禁止：** 把 description 里未提及的技能标为 verified；把噪声词当技能。

### 2.7 `quantified_achievements`
- 只抽 `description`/`summary` 中**带明确数字或明确结果动词**的句子（增长 30%、省 $2M、上线 X、带 10 人）。
- 逐条给原文 evidence，`high`（因为是直接引用）。
- 无 → 空数组，**不编造，不把日常职责包装成成果**。

### 2.8 七个检索文本（详见 EmbeddingFieldDesign）
判断标准核心两条：
- **写职责内容不写头衔**，歧义 title 必须消歧展开。
- 描述缺失时可从 title/公司/行业**保守概括**，但**禁止编造具体项目、客户、数字**。不确定的降置信，留给结构化字段兜底。

### 2.9 三个风险文本 + `risk_flags`
只在**有证据支撑硬伤**时标记，宁可漏标不可错标：
- `title_role_mismatch`：头衔资深但 description/level 显示执行岗（如 title "Director" 但 level=Specialist 且无管理证据）。
- `research_heavy`：经历以研究/论文为主、缺生产交付证据。
- `skill_unverified`：技能列表长但描述几乎无印证。
- `insufficient_evidence:<字段>`：某关键字段既不能确认满足也不能确认违反。预处理期可作为字段级标记保留；SearchResult 中只通过 `results[].hard_filter_status` 体现，不作为候选人级 `risk_flags` 输出。
- **禁止：** 无证据地贴风险标签（如仅因换过几份工作就标不稳定——除非用户开启该项）。

---

## 3. 统一置信度评级（LLM 必须按此打分）

| 置信 | 什么时候用 |
|---|---|
| `high` | 直接来自原始结构化字段，或 description 明确文字印证。 |
| `medium` | 从 title/公司/tags 等间接信号合理推断，单一来源。 |
| `low` | 信号弱、多种解释、仅靠常识倾向。**low 字段不得用于硬淘汰。** |
| `unknown` | 无任何证据。禁止赋具体值。 |

---

## 4. LLM 输出前自检清单（写进提示词末尾）

生成每条候选人预处理结果后，LLM 必须自检：
1. 每个非 unknown 字段都填了 `source_field` 和 `evidence` 吗？
2. 有没有把"缺失"当成了"否定"或"满足"？
3. 枚举字段都在预定义集合内吗？
4. 有没有把 `skills` 列表的技能当成 verified？
5. 检索文本里有没有编造原文没有的项目/成果/数字？
6. 歧义 title（Manager/Analyst/Associate）都消歧了吗？
7. 推断出的（medium/low）硬字段有没有被误标成可淘汰的 high？

任一条不通过 → 该字段降级为 unknown 或降置信。

---

## 5. 示例：正确 vs 幻觉

**原始片段：** title="Billing Manager", role="Finance & Accounting", description 提到 "reduced denied claims, HIPAA compliance"，无 certifications 字段。

✅ **正确：**
- role_family = Finance & Accounting (high, 有 role 字段)
- management_scope = unknown 或 lead_no_report（"Manager" 头衔但无下属证据）（medium）
- industries = Hospitals and Health Care (medium, 由 HIPAA/claims 推断)
- certifications = insufficient_evidence（字段缺失）
- certifications 标为 insufficient_evidence（字段缺失不是风险，只是不确定）

❌ **幻觉（禁止）：**
- management_scope = manage_team（仅凭 "Manager" 头衔，无下属证据）
- certifications = ["none"] 当作"没有证书"（缺失被当否定）
- hard_skills 把 "HIPAA" 标 verified 却指不出原文
- achievement 编造 "reduced costs by 30%"（原文无数字）

---

## 6. 一句话总结

能算的用公式（零幻觉），要判的给 LLM 一套"有据才判、缺失不否定、歧义必消歧、推断不淘汰"的分点标准 + 输出自检清单。每个结论可回溯原文，才能让预处理既智能又可信。
