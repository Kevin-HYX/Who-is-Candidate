# Desensitization Profiles 数据结构分析

- 原始文件：`data/desensitization_profiles/1000_Desensitization_profiles.jsonl`
- 记录数：1000
- 解析错误：0
- 文件大小：5,436,709 bytes
- 格式：JSON Lines，每行一个候选人 profile 对象

## 顶层结构

顶层对象主要由候选人基础信息、当前经历摘要、技能列表、经历数组、教育数组以及成果类数组组成。

- 全量出现字段：`awards`, `certifications`, `courses`, `education`, `experience`, `patents`, `publications`, `skills`, `user_id`
- 非全量字段：`active_experience_company_id`, `active_experience_department`, `active_experience_description`, `active_experience_management_level`, `active_experience_title`, `headline`, `is_decision_maker`, `is_working`, `summary`, `total_experience_duration_months`

| 字段 | 出现 | 类型 | 空数组/空值 | 说明 |
| --- | ---: | --- | ---: | --- |
| `active_experience_company_id` | 630/1000 | integer:630 | 0 | 当前经历公司 ID |
| `active_experience_department` | 771/1000 | string:771 | 0 | 当前经历部门或职能 |
| `active_experience_description` | 234/1000 | string:234 | 0 | 当前经历描述 |
| `active_experience_management_level` | 771/1000 | string:771 | 0 | 当前经历管理层级 |
| `active_experience_title` | 874/1000 | string:874 | 0 | 当前经历标题 |
| `awards` | 1000/1000 | array:1000 | 910 | 奖项数组，当前样本中多为空 |
| `certifications` | 1000/1000 | array:1000 | 779 | 证书数组，元素为字符串 |
| `courses` | 1000/1000 | array:1000 | 937 | 课程数组，元素为字符串 |
| `education` | 1000/1000 | array:1000 | 0 | 教育经历数组 |
| `experience` | 1000/1000 | array:1000 | 0 | 工作经历数组 |
| `headline` | 944/1000 | string:944 | 0 | 职业标题或一句话简介 |
| `is_decision_maker` | 771/1000 | boolean:771 | 0 | 是否决策者 |
| `is_working` | 874/1000 | boolean:874 | 0 | 是否当前在职 |
| `patents` | 1000/1000 | array:1000 | 996 | 专利数组，当前样本中几乎为空 |
| `publications` | 1000/1000 | array:1000 | 975 | 出版物数组，当前样本中多为空 |
| `skills` | 1000/1000 | array:1000 | 148 | 技能关键词数组，元素为字符串 |
| `summary` | 441/1000 | string:441 | 0 | 个人摘要 |
| `total_experience_duration_months` | 945/1000 | integer:945 | 0 | 总工作月数 |
| `user_id` | 1000/1000 | integer:1000 | 0 | 候选人 ID |

## 嵌套数组

| 数组字段 | 有数据的 profile | 总元素数 | 每人元素数 min/avg/max | 元素类型 |
| --- | ---: | ---: | --- | --- |
| `skills` | 852/1000 | 11448 | 0/11.45/124 | string:11448 |
| `experience` | 1000/1000 | 4286 | 1/4.29/25 | object:4286 |
| `education` | 1000/1000 | 1751 | 1/1.75/15 | object:1751 |
| `awards` | 90/1000 | 225 | 0/0.23/10 | string:225 |
| `courses` | 63/1000 | 431 | 0/0.43/30 | string:431 |
| `certifications` | 221/1000 | 612 | 0/0.61/10 | string:612 |
| `publications` | 25/1000 | 72 | 0/0.07/10 | string:72 |
| `patents` | 4/1000 | 6 | 0/0.01/2 | string:6 |

## experience 元素字段

`experience` 是工作经历明细数组，共 4286 条 object。

| 字段 | 出现 | 类型 | 说明 |
| --- | ---: | --- | --- |
| `address_city` | 3656/4286 | string:3656 | 城市 |
| `address_country` | 3656/4286 | string:3656 | 国家 |
| `address_state` | 3656/4286 | string:3656 | 州或省 |
| `company_employees_count` | 2930/4286 | integer:2930 | 公司员工数 |
| `company_founded_year` | 1731/4286 | integer:1731 | 公司成立年份 |
| `company_id` | 2974/4286 | integer:2974 | 公司 ID |
| `company_name` | 4283/4286 | string:4283 | 公司名 |
| `company_size_range` | 4286/4286 | integer:4286 | 公司规模区间编码，-1 表示未知 |
| `company_tags` | 4286/4286 | array:4286 | 公司标签数组 |
| `company_type` | 2772/4286 | string:2772 | 公司类型 |
| `date_from_month` | 3847/4286 | integer:3847 | 开始月 |
| `date_from_year` | 4200/4286 | integer:4200 | 开始年 |
| `date_to_month` | 2878/4286 | integer:2878 | 结束月 |
| `date_to_year` | 3164/4286 | integer:3164 | 结束年 |
| `description` | 1950/4286 | string:1950 | 经历描述 |
| `duration_months` | 4200/4286 | integer:4200 | 该段经历月数 |
| `end_time` | 3164/4286 | string:3164 | 结束日期，格式通常为 YYYY-MM-DD |
| `full_address` | 3656/4286 | string:3656 | 完整地址 |
| `industry` | 2898/4286 | string:2898 | 行业 |
| `is_current` | 4286/4286 | boolean:4286 | 是否当前经历 |
| `level` | 3425/4286 | string:3425 | 职位层级 |
| `order_in_profile` | 4286/4286 | integer:4286 | 在 profile 中的排序 |
| `role` | 3425/4286 | string:3425 | 职能分类 |
| `start_time` | 4200/4286 | string:4200 | 开始日期，格式通常为 YYYY-MM-DD |
| `title` | 4286/4286 | string:4286 | 职位标题 |

## education 元素字段

`education` 是教育经历明细数组，共 1751 条 object。

| 字段 | 出现 | 类型 | 说明 |
| --- | ---: | --- | --- |
| `begin_year` | 1376/1751 | integer:1376 | 开始年份 |
| `degree_level` | 1751/1751 | integer:1751 | 学历等级编码 |
| `degree_str` | 1582/1751 | string:1582 | 学历原始文本 |
| `end_year` | 1346/1751 | integer:1346 | 结束年份 |
| `gpa` | 97/1751 | number:97 | GPA |
| `institution_city` | 1223/1751 | string:1223 | 学校城市 |
| `institution_country` | 1319/1751 | string:1319 | 学校国家 |
| `institution_full_address` | 1368/1751 | string:1368 | 学校完整地址 |
| `institution_name` | 1749/1751 | string:1749 | 学校或机构名 |
| `institution_state` | 1220/1751 | string:1220 | 学校州或省 |
| `is_current` | 1751/1751 | boolean:1751 | 是否当前教育经历 |
| `major` | 1751/1751 | string:1751 | 专业 |
| `order_in_profile` | 1751/1751 | integer:1751 | 在 profile 中的排序 |

## 文件清单

- `1000_Desensitization_profiles.jsonl`：复制后的原始 JSONL
- `schema_summary.json`：完整字段统计、类型统计、样例值
- `sample_profiles.json`：前 5 条样例，便于查看嵌套结构
- `structure_report.md`：当前报告
