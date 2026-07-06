# Candidate Search Agent

本项目用于基于 1000 条脱敏候选人 profile 构建候选人搜索 Agent：Agent 将用户自然语言需求写成 QueryPlan，Search Tool 返回排序候选人的简单元信息和原始 profile，最终匹配解释由 Agent 基于原始字段完成。

## 关键目录

- `.agent/principle/SystemDesign.md`：系统目标、核心设计思想和实现路径。
- `.agent/principle/ImplementationPlan.md`：核心检索工具的实现方案（技术选型、目录结构、落地策略）。
- `.agent/principle/ScoringDesign.md`：评分维度与机制设计（HR 视角、硬/软规则划分、数据支撑度）。
- `.agent/principle/SchemaDesign.md`：AI 第一轮预处理的输出契约（硬筛选字段的归一与资格判定）。
- `.agent/principle/EmbeddingFieldDesign.md`：embedding 的缺陷与 view 字段构建规范（让语义匹配对齐工作内容而非字面）。
- `.agent/principle/PreprocessJudgmentStandards.md`：预处理 LLM 的分点判断标准与防幻觉规范（公式字段 vs 推断字段）。
- `.agent/principle/ToolInterfaceDesign.md`：检索工具对下游 Agent 的输入/输出接口设计（Agent 写 QueryPlan，Tool 只检索）。
- `.agent/principle/AgentSystemPromptDesign.md`：未来交互 Agent 的系统提示词设计（如何合理使用 Tool、如何向用户解释数据完备性）。
- `data/desensitization_profiles/`：原始 JSONL、结构分析报告和样例。
- `data/desensitization_profiles/structure_report.md`：原始数据字段结构、类型和嵌套数组统计。
- `data/desensitization_profiles/schema_summary.json`：机器可读的数据结构统计。
- `data/desensitization_profiles/sample_profiles.json`：前 5 条样例 profile。
