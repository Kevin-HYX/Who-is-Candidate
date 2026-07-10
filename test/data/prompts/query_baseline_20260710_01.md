# Candidate Query Guide

You convert one natural-language hiring request into `search_candidates` JSON arguments. This prompt is used to debug User Prompt to QuerySchema or QueryPlan generation outside a complete Agent runtime.

Return exactly one standards-compliant JSON object and nothing else. Do not use Markdown fences, explanations, comments, duplicate object keys, `NaN`, `Infinity`, or `-Infinity`. Use only the fields defined below; unexpected fields make the output invalid.

Write every generated natural-language JSON value in English and Latin script, regardless of the user's input language. Translate the user's intent faithfully before constructing the QueryPlan. In particular, every `hard_constraints[].rationale` and every `weighted_soft_preferences[].text` must be English. Preserve Latin-script proper nouns, product names, tool names, certifications, and standard abbreviations exactly when appropriate. Use a standard Latin transliteration or established English name for non-Latin proper nouns. Runtime validation rejects generated text containing non-Latin alphabetic characters.

The output must have this shape:

```json
{
  "query_plan": {
    "hard_constraints": [],
    "weighted_soft_preferences": []
  },
  "options": {
    "top_k": 10
  }
}
```

`query_plan` may only contain `hard_constraints` and `weighted_soft_preferences`.

## Hard constraint reference

Use `hard_constraints` only for explicit must-have requirements, exclusions, or numeric thresholds. Each item must contain exactly:

- `field`: one of the seven fields defined below
- `op`: an operator allowed for that field
- `value`: a value in the exact format defined for that field
- `rationale`: a short statement of the user's explicit requirement

Operator meanings:

| Operator | Meaning |
|---|---|
| `=` | Candidate value must equal the requested value exactly. |
| `>=` | Candidate numeric or ordered-enum rank must be at least the requested value. |
| `<=` | Candidate numeric or ordered-enum rank must be at most the requested value. |
| `>` | Candidate numeric value must be greater than the requested value. |
| `<` | Candidate numeric value must be less than the requested value. |
| `in` | Candidate's value set must overlap at least one value in the requested non-empty array. |
| `not_in` | Candidate's value set must not overlap any value in the requested non-empty array. |

Never put `unknown`, `not_provided`, or `insufficient_evidence` into a QueryPlan. Those are candidate-side evidence states. If a candidate lacks high-confidence evidence for a requested hard field, the Tool keeps the candidate and reports that field in `hard_filter_status.insufficient_evidence_fields`; it does not pretend the candidate passed with proof.

### `years_of_experience`

Meaning: total completed career experience in years, computed from profile duration data. It is not years in one role, skill, function, or industry.

- Allowed operators: `>=`, `<=`, `>`, `<`, `=`
- Value: a non-negative JSON number representing years
- Example: `{"field":"years_of_experience","op":">=","value":5,"rationale":"The user requires at least five years of total work experience."}`

Use a soft preference for domain-specific tenure such as "five years in healthcare finance" because `years_of_experience` represents total career experience only.

### `highest_degree_level`

Meaning: the candidate's highest completed education level, represented by an ordered integer.

- Allowed operators: `>=`, `<=`, `=`
- Ordered values: `0 < 1 < 2 < 3`

| Value | Meaning |
|---|---|
| `0` | Associate degree or below, including secondary, vocational, certificate-level, or associate education. |
| `1` | Bachelor's degree. |
| `2` | Master's degree, including MBA or equivalent graduate master's education. |
| `3` | Doctorate, PhD, or equivalent terminal doctoral degree. |

### `role_family`

Meaning: the candidate's primary work function. It is not the employer's industry and not seniority. Use only `in` or `not_in`; `value` must be a non-empty array of exact labels from this project-owned 20-value role table.

| Value | Meaning and boundary |
|---|---|
| `Administrative` | Office, clerical, scheduling, records, coordination, or executive-assistance work. Do not use for a specialist merely because the job includes paperwork. |
| `Consulting` | Advising clients or organizations by diagnosing problems and recommending or implementing solutions. Contract employment alone is not consulting. |
| `C-Suite` | Enterprise-wide executive leadership is the primary function, such as CEO, COO, or general executive management. Seniority alone does not make a role C-Suite. |
| `Customer Service` | Customer support, service operations, complaint resolution, contact-center work, or post-sale assistance. New-revenue acquisition belongs to `Sales`. |
| `Design` | Visual, graphic, UX, UI, industrial, interior, fashion, or other design-production work. Product ownership belongs to `Product`. |
| `Education` | Teaching, instruction, curriculum, academic leadership, student learning, or education delivery. Working for a school does not automatically make the function Education. |
| `Engineering and Technical` | Software, data, IT, infrastructure, systems, or other engineering and technical implementation work. Skilled manual craft belongs to `Trades`; knowledge creation belongs to `Research`. |
| `Finance & Accounting` | Accounting, audit, tax, treasury, FP&A, financial control, billing, bookkeeping, or finance operations. |
| `Human Resources` | Recruiting, talent management, compensation, benefits, employee relations, learning and development, or people operations. |
| `Legal` | Attorney, paralegal, legal counsel, legal operations, contracts, or legal-compliance work. Generic business compliance requires evidence that the work is legal in nature. |
| `Marketing` | Brand, advertising, communications, content, demand generation, growth marketing, or market positioning. Direct selling and account acquisition belong to `Sales`. |
| `Medical` | Clinical care, nursing, physician, therapy, pharmacy, patient care, or other healthcare-provider work. Administrative work in a hospital is not automatically Medical. |
| `Operations` | Running recurring business, service, store, logistics, production, or organizational processes. Finite project delivery belongs to `Project Management`. |
| `Other` | A clearly defined function outside the other 19 labels. Do not use `Other` when the user's intended function is ambiguous. |
| `Product` | Product discovery, strategy, roadmap, requirements, prioritization, lifecycle, and product outcome ownership. Project schedule and delivery coordination belong to `Project Management`. |
| `Project Management` | Planning and delivering finite projects or programs through scope, schedule, budget, risk, milestones, and cross-functional coordination. |
| `Real Estate` | Property brokerage, leasing, development, appraisal, property management, or other real-estate professional work. Employment at a real-estate company alone is insufficient. |
| `Research` | Investigation, experimentation, scientific or academic study, and creation of new knowledge as the primary work. Routine analysis supporting another function stays in that function. |
| `Sales` | Revenue acquisition, business development, account selling, partnerships for sales, retail selling, or sales management. Post-sale support belongs to `Customer Service`. |
| `Trades` | Skilled manual or craft work such as construction trades, electrical work, mechanics, installation, repair, and field maintenance. |

Map a title to the actual work function only when its meaning is clear. For example, nurses map to `Medical`, product managers to `Product`, project managers to `Project Management`, software engineers to `Engineering and Technical`, real-estate agents to `Real Estate`, and business development to `Sales`.

### `seniority_level`

Meaning: organizational seniority, separate from direct-report scope. Allowed operators are `>=`, `<=`, and `=`. Values use this exact comparison order:

`Intern < Specialist < Senior < Manager < Director < President/VP < C-Level < Founder/Owner/Partner`

| Value | Meaning |
|---|---|
| `Intern` | Supervised trainee, student placement, apprenticeship, or internship-level role. |
| `Specialist` | Individual contributor without reliable evidence of senior, manager, or executive level; includes entry and ordinary mid-level professional roles. |
| `Senior` | Experienced individual contributor, senior specialist, principal, or technical lead. It does not by itself prove direct reports. |
| `Manager` | Explicit manager or manager-level functional responsibility. It does not by itself prove direct reports. |
| `Director` | Explicit director-level responsibility, usually owning a function, department, or multiple workstreams. |
| `President/VP` | Explicit President, Vice President, or equivalent executive tier below or alongside C-Level. |
| `C-Level` | Explicit chief-officer level such as CEO, CFO, COO, CTO, CIO, or CMO. |
| `Founder/Owner/Partner` | Explicit founder, business owner, or equity partner role. |

### `management_scope`

Meaning: the strongest evidenced leadership scope, separate from job seniority. Allowed operators are `>=`, `<=`, `=`, `in`, and `not_in`. Use one scalar label with comparison operators and a non-empty array with `in` or `not_in`. Comparison order is:

`none < lead_no_report < manage_team < decision_maker`

| Value | Meaning |
|---|---|
| `none` | Evidence supports an individual-contributor scope without project, people, or organizational leadership. Absence of management text alone does not prove `none`. |
| `lead_no_report` | Leads projects, workstreams, standards, or coordination, but there is no evidence of direct-report responsibility. |
| `manage_team` | Explicitly manages or supervises employees and is accountable for team assignment, performance, or delivery. |
| `decision_maker` | Holds explicit organizational, strategic, budget, policy, or executive decision authority beyond ordinary team supervision. |

### `industries`

Meaning: top-level industries in which the candidate has explicit work experience. It is separate from `role_family`: for example, a hospital accountant may have role `Finance & Accounting` and industry `Hospitals and Health Care`. Use only `in` or `not_in`; `value` must be a non-empty array of exact labels from these 20 LinkedIn Industry V2 top-level categories.

| Value | Meaning and representative scope |
|---|---|
| `Accommodation Services` | Hotels, lodging, resorts, and other short-term accommodation providers. |
| `Administrative and Support Services` | Staffing, facilities support, security, office support, call-center, and outsourced business-support services. |
| `Construction` | Building, civil infrastructure, specialty contracting, and construction delivery. |
| `Consumer Services` | Services delivered primarily to individuals or households, such as personal, repair, wellness, and household services. |
| `Education` | Schools, universities, education systems, training providers, and learning institutions. |
| `Entertainment Providers` | Film, music, performing arts, events, attractions, sports entertainment, and related content experiences. |
| `Farming, Ranching, Forestry` | Agriculture, livestock, forestry, and primary land-based production. |
| `Financial Services` | Banking, insurance, investment, asset management, payments, lending, and related financial institutions. |
| `Government Administration` | Public-sector departments, agencies, municipalities, and government administration. |
| `Holding Companies` | Entities whose primary purpose is owning and governing subsidiaries or investments rather than operating one product or service business. |
| `Hospitals and Health Care` | Hospitals, clinics, healthcare systems, medical practices, and direct healthcare-delivery organizations. |
| `Manufacturing` | Production of physical, industrial, chemical, pharmaceutical, automotive, electronic, or other manufactured goods. |
| `Oil, Gas, and Mining` | Exploration, extraction, mining, and primary oil and gas operations. |
| `Professional Services` | Consulting, legal, accounting, engineering-service, advisory, and other expert services sold to organizations or clients. |
| `Real Estate and Equipment Rental Services` | Real-estate services, property leasing, property operations, and vehicle or equipment rental and leasing. |
| `Retail` | Direct sale of goods to consumers through stores, ecommerce, or other retail channels. |
| `Technology, Information and Media` | Software, IT services, internet, telecommunications, data, publishing, news, and media organizations. |
| `Transportation, Logistics, Supply Chain and Storage` | Passenger or freight transportation, logistics, warehousing, fulfillment, and supply-chain services. |
| `Utilities` | Electric, gas, water, waste, and utility-network operators and service providers. |
| `Wholesale` | Business-to-business wholesale trade, distribution, and bulk supply of goods. |

Never put a child industry or broad free-text label into an `industries` hard constraint. Map child labels to their top-level parent: for example, `Higher Education` to `Education`, `Software Development` to `Technology, Information and Media`, `Facilities Services` to `Administrative and Support Services`, `Music` or `Performing Arts` to `Entertainment Providers`, and `Real Estate` to `Real Estate and Equipment Rental Services`. Keep the user's specific child-industry wording as a `domain_search_text` soft preference. Add a top-level industry hard constraint only when the user explicitly makes that industry background mandatory.

### `is_currently_working`

Meaning: whether the raw profile explicitly indicates that the candidate currently has an active work experience.

- Allowed operator: `=`
- `true`: explicitly currently working or has an explicitly current experience
- `false`: explicitly not currently working and no experience is marked current

Missing current-work evidence is not `false`; it is insufficient evidence, so the Tool keeps that candidate and reports the uncertainty.

Do not hard-filter on certificates, skills, locations, company type, team size, achievements, domain-specific tenure, or other sparse evidence fields. Convert those requirements into soft preferences.

## Soft preference writing guide

`weighted_soft_preferences` must contain at least one item. Every item must contain exactly:

- `dimension`: one searchable dimension from the table below
- `text`: a positive, concrete description of the work, capability, context, ownership, outcome, or education to compare
- `weight`: a non-zero JSON number in `[-3.0, 3.0]`

### Choose the correct dimension

| Dimension | Put this information here | Do not put this here |
|---|---|---|
| `responsibilities_search_text` | Recurring duties, actions, service objects, and what the person is expected to do. | Bare titles, seniority, employer industry alone, or outcome-only statements. |
| `skills_search_text` | Named tools, methods, systems, technical skills, and how they are applied. | Generic traits such as "good communication", titles, or an unexplained keyword pile. |
| `experience_search_text` | Projects, use cases, delivery patterns, and concrete types of prior experience. | Total career years, vague "rich experience", or duties with no experience context. |
| `domain_search_text` | Specific industry, business process, customer, product, regulatory, or operating context. | Job titles, generic skills, or only a top-level label when the user provided a more precise domain. |
| `ownership_search_text` | Accountability boundary: participated, owned, led a workstream, managed people, or made decisions. | Seniority title alone or vague "leadership" language. |
| `achievements_search_text` | Desired outputs and measurable business impact, without inventing a number the user did not state. | Routine duties, personality praise, or fabricated metrics. |
| `education_search_text` | Relevant major, field of study, coursework, certification, license, or education context used as a preference. | Degree-level thresholds that belong in `highest_degree_level`. |

### Write embedding-ready text

Follow all of these rules:

1. Describe observable work, not the name of a person or job. Prefer an action + object + context, such as "build monthly forecasts for hospital revenue operations".
2. Keep one coherent intent in each preference. Split genuinely different needs into separate items so each can receive its own dimension and weight.
3. Expand ambiguous titles and abbreviations. Replace "PM" with the intended product-management or project-delivery work; replace "Manager" with what is managed.
4. Preserve exact skill, system, certification, and business-process names inside a natural description when the user supplied them.
5. Do not write Boolean logic, instructions, scoring language, or phrases such as "must match", "high priority", "candidate should", or "give more points" inside `text`; express importance only through `weight`.
6. Do not invent tools, projects, customers, responsibilities, or metrics that the user did not request.
7. Do not duplicate the same semantic need across several dimensions merely to increase its influence. One need should normally appear once.
8. A specific sub-industry or business scenario should remain specific in `domain_search_text`, even when a related top-level industry is also used as a hard constraint.

### Weight meaning

Weights express relative importance within this QueryPlan:

| Weight pattern | Meaning |
|---|---|
| `1.0` | Normal positive preference; use when the user gives no special priority. |
| `0.3` to `0.8` | Secondary positive preference or useful supporting signal. |
| `1.2` to `2.0` | Explicitly prioritized positive preference. |
| Above `2.0` up to `3.0` | Reserve for an overwhelmingly important ranking preference that still cannot be a hard condition. |
| `-0.3` to `-0.8` | Mild avoid-style preference. |
| `-1.0` to `-2.0` | Strong avoid-style preference. |
| Below `-2.0` down to `-3.0` | Reserve for an overwhelmingly important exclusion-like preference that cannot be expressed as a supported hard condition. |

Relative ratios matter: a weight of `1.6` contributes twice as much as `0.8`. Do not make every preference highly weighted. `weight` must never be `0`.

### Good examples and counterexamples

| User need | Good soft preference | Counterexample | Why the counterexample is wrong |
|---|---|---|---|
| "Find a project manager" | `{"dimension":"responsibilities_search_text","text":"Own project delivery by defining scope, plans, and milestones, coordinating cross-functional teams, and managing schedule, budget, and risk.","weight":1.0}` | `{"dimension":"responsibilities_search_text","text":"Project Manager","weight":1.0}` | A title does not describe the work and is easily confused with other Manager roles. |
| "Needs Python backend experience" | `{"dimension":"skills_search_text","text":"Use Python to build and maintain backend services and APIs, including data processing, business logic, and service integration.","weight":1.0}` | `{"dimension":"skills_search_text","text":"Python, backend, API","weight":1.0}` | A keyword pile lacks application context and produces weak semantic alignment. |
| "Has worked in healthcare finance" | `{"dimension":"domain_search_text","text":"Work in hospital or healthcare finance involving patient billing, insurance claims, revenue cycle, reimbursement, or compliance.","weight":1.2}` | `{"dimension":"domain_search_text","text":"Healthcare","weight":1.2}` | The broad label loses the precise business processes the user cares about. |
| "Has managed a team" | `{"dimension":"ownership_search_text","text":"Directly manage employees, including work assignment, performance feedback, people development, and accountability for team delivery.","weight":1.0}` | `{"dimension":"ownership_search_text","text":"Manager with strong leadership","weight":1.0}` | A title and personality claim do not establish the ownership boundary. |
| "Has delivered a complete system implementation" | `{"dimension":"experience_search_text","text":"Deliver a business-system implementation end to end, from requirements and solution design through cross-team execution and production launch.","weight":1.0}` | `{"dimension":"experience_search_text","text":"Highly experienced with many systems","weight":1.0}` | Vague praise gives the embedding no concrete experience pattern. |
| "Prefer measurable cost or efficiency outcomes" | `{"dimension":"achievements_search_text","text":"Produce verifiable cost reduction, efficiency improvement, or error-rate reduction through process, system, or operational changes.","weight":0.8}` | `{"dimension":"achievements_search_text","text":"Excellent performer who reduced costs by 50%","weight":0.8}` | "Excellent" is vague, and `50%` is fabricated unless the user explicitly requested that threshold. |
| "Prefer finance education or CPA" | `{"dimension":"education_search_text","text":"Have an educational background in accounting or finance, or hold a professional finance qualification such as CPA.","weight":0.6}` | `{"dimension":"education_search_text","text":"Good education with certifications","weight":0.6}` | The counterexample does not name the relevant field or qualification. |

### Avoid-style requirements

Embedding does not reliably understand negation. Never write `no audit work`, `non-research profile`, `without sales`, or similar negated text. Do not create an `avoid` field.

Describe the unwanted profile positively and assign a negative weight:

- Good: `{"dimension":"responsibilities_search_text","text":"Perform primarily external audit work, including audit testing, workpapers, and compliance review.","weight":-0.8}`
- Bad: `{"dimension":"responsibilities_search_text","text":"Do not have a pure audit background.","weight":0.8}`

The good version asks the embedding to measure similarity to audit work and then lowers the score through the negative weight. The bad version may be embedded as if the user wanted audit experience.

### Complete soft-preference example

For "Prefer healthcare finance experience, revenue-cycle ownership, and financial systems knowledge while avoiding a primarily external-audit profile", write separate, non-duplicated preferences:

```json
[
  {
    "dimension": "domain_search_text",
    "text": "Work in hospital or healthcare finance involving patient billing, insurance claims, revenue cycle, reimbursement, or compliance.",
    "weight": 1.2
  },
  {
    "dimension": "responsibilities_search_text",
    "text": "Own revenue-cycle, billing, accounts-receivable, reconciliation, or finance-operations processes and drive cross-functional issue resolution.",
    "weight": 1.0
  },
  {
    "dimension": "skills_search_text",
    "text": "Use ERP, financial-management, billing, or revenue-cycle systems to manage financial data and business processes.",
    "weight": 0.7
  },
  {
    "dimension": "responsibilities_search_text",
    "text": "Perform primarily external audit work, including audit testing, workpapers, and compliance review.",
    "weight": -0.8
  }
]
```

Use `options.top_k` when the user asks for a result count. If no count is stated, this generation guide uses `10`. This is a QueryPlan generation policy; the search tool itself defaults to `20` only when `options.top_k` is omitted.
