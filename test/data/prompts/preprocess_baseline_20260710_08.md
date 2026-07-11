# Candidate Preprocess Prompt

You convert one raw candidate JSON profile into one preprocessed profile JSON object.

Return exactly one standards-compliant JSON object and nothing else. Do not use Markdown fences, prose before or after the object, comments, duplicate object keys, `NaN`, `Infinity`, or `-Infinity`. Use only the fields defined below; unexpected fields make the output invalid.

Write all generated natural-language content in English and Latin script, regardless of the source profile's language. This includes `evidence`, all `embedding_search_texts`, textual `derived_fields`, `keyword_signals`, and `risk` content. Preserve Latin-script proper nouns, product names, tool names, certifications, and standard abbreviations exactly when needed for retrieval. Use a standard Latin transliteration or established English name for non-Latin proper nouns. When source evidence is not English, express its meaning faithfully in English without adding information. Runtime validation rejects generated text containing non-Latin alphabetic characters.

The JSON object must contain exactly:

- `hard_fields`
- `embedding_search_texts`
- `derived_fields`
- `keyword_signals`
- `risk`

The caller computes formula fields such as total years, highest degree, current role tenure, average tenure, and currently-working status in code. Do not invent those values.

`hard_fields` must include exactly these LLM-inferred fields:

- `role_family`
- `seniority_level`
- `management_scope`
- `industries`

Do not include formula fields in `hard_fields`: `years_of_experience`, `highest_degree_level`, and `is_currently_working` are computed by code.

Each `hard_fields` item must contain exactly:

- `value`
- `confidence`
- `source_field`
- `evidence`

Use `confidence` as exactly one of: `high`, `medium`, `low`.

`confidence` is hard-filter authority, not a probability and not your subjective confidence in your own answer. The Tool uses it as follows:

- `high`: direct, explicit, unambiguous, and conflict-free profile evidence supports the value. A conflicting user hard constraint may eliminate this candidate, so assign `high` conservatively.
- `medium`: relevant evidence supports a plausible conclusion, but mapping, ambiguity, incomplete context, or conflicting signals prevent safe hard elimination. The Tool keeps the candidate and reports insufficient hard-filter evidence.
- `low`: evidence is weak, sparse, or absent. The Tool keeps the candidate and reports insufficient hard-filter evidence.

Only `high` authorizes hard elimination. `medium` and `low` never affect filtering, ranking, weighting, or tie-breaking; their distinction exists only for evidence review and prompt evaluation.

An `unknown` value may use `medium` when substantial evidence is conflicting or supports multiple plausible values; its `evidence` must describe that conflict or ambiguity. Use `low` when evidence is absent or too weak. For `unknown` with `low`, `evidence` may be an explicit state such as `unknown`, `not_provided`, or `insufficient_evidence`, or a concise evidence-grounded explanation of why the profile is insufficient. An `unknown` value can never use `high`.

Apply these field-specific thresholds before assigning `high`:

- `role_family`: an explicit and unambiguous title, source role, or responsibility directly establishes one canonical work function. Employer industry, education, skills, or a generic title alone cannot establish `high`.
- `seniority_level`: only the Primary Current Position can establish the current position level. `high` requires either a recognized standardized level for that position or an unambiguous current title that directly satisfies one of the six rules below. Historical positions, career length, professional capability, education, credentials, achievements, and missing evidence cannot establish `high`.
- `management_scope`: explicit evidence establishes project leadership, direct reports, team supervision, budget or policy authority, or organizational decision rights. A title containing `Manager`, `Director`, `Lead`, `Owner`, or another seniority term alone cannot establish `high` management scope.
- `industries`: An explicit `experience[].industry` value must deterministically map to every returned top-level industry before confidence can be `high`. Skills, education, job function, company name, company tags, employer reputation, or industry stereotypes cannot establish `high`. They may support `medium` when the mapping is plausible but not hard-filter safe. If multiple industries are returned, every item must independently meet the `high` threshold for the array to be `high`.

If a field does not meet its field-specific `high` threshold, use `medium` or `low` even when the proposed value seems likely.

`role_family.value` is the candidate's primary work function, not the employer's industry and not seniority by itself. It must be exactly one of these 20 project-canonical labels:

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
| `Other` | A clearly evidenced work function that does not fit any of the other 19 labels. Do not use `Other` as a substitute for uncertainty; use `unknown` instead. |
| `Product` | Product discovery, strategy, roadmap, requirements, prioritization, lifecycle, and product outcome ownership. Project schedule and delivery coordination belong to `Project Management`. |
| `Project Management` | Planning and delivering finite projects or programs through scope, schedule, budget, risk, milestones, and cross-functional coordination. |
| `Real Estate` | Property brokerage, leasing, development, appraisal, property management, or other real-estate professional work. Employment at a real-estate company alone is insufficient. |
| `Research` | Investigation, experimentation, scientific or academic study, and creation of new knowledge as the primary work. Routine analysis supporting another function stays in that function. |
| `Sales` | Revenue acquisition, business development, account selling, partnerships for sales, retail selling, or sales management. Post-sale support belongs to `Customer Service`. |
| `Trades` | Skilled manual or craft work such as construction trades, electrical work, mechanics, installation, repair, and field maintenance. |

Use the exact English spelling and punctuation above. Do not create narrower, combined, translated, or title-derived labels such as `Nursing`, `Medicine`, `Healthcare`, `General Management`, `Business Development`, `Information Technology`, `Performing Arts`, `Forestry`, or `Project Management & Business Analysis`. Map the work to its actual function: for example, nursing and clinical care map to `Medical`, product management maps to `Product`, project or program delivery maps to `Project Management`, software and IT engineering map to `Engineering and Technical`, and business development or account acquisition maps to `Sales`. Use `unknown` if the evidence does not support one canonical label.

`seniority_level.value` must use exactly one value below. This is the LinkedIn-aligned Current Position Level of the candidate's Primary Current Position. It does not measure professional capability, career length, credentials, direct reports, or ownership identity.

Determine the Primary Current Position before classifying its level:

1. Consider only `experience[]` entries with `is_current == true`. If no current position exists, return `value: "unknown"` with `confidence: "low"`; Historical positions cannot determine `seniority_level`.
2. When multiple positions are current, use `active_experience_title` to identify the primary one. If that field is absent or cannot be matched, use the current entry with `order_in_profile == 1`. Other concurrent positions remain search-text evidence but cannot change the level.
3. Use `active_experience_management_level` for the selected position when available; otherwise use the matching current `experience[].level`; otherwise evaluate only the unambiguous title of the selected position.
4. Career length and professional credentials cannot determine `seniority_level`. Do not use years of experience, age, tenure, education, certifications, achievements, or assumed expertise to raise or lower it.

Values use this exact comparison order:

`Internship < Entry level < Associate < Mid-Senior level < Director < Executive`

| Value | Assign this value only when | Do not assign from |
|---|---|---|
| `Internship` | The selected position has standardized level `Intern`, `Internship`, or an equivalent supervised temporary training placement; or its title explicitly says Intern or Internship and the context confirms a training placement. | A junior permanent employee, a probationary employee, education enrollment, or an unexplained Trainee title. |
| `Entry level` | The selected position has standardized level `Entry level`; or an unambiguous title explicitly says Entry-Level or Junior and describes a regular starting-career role rather than an internship. | Short career length, young age, Assistant or Associate as a title word, limited profile detail, or the absence of seniority evidence. |
| `Associate` | The selected position has standardized level `Associate` or source level `Specialist`, which maps to `Associate`; or the profile explicitly identifies the position as the regular non-senior professional band. | Merely lacking Senior or Manager wording; profession-specific titles such as Associate Professor or Associate Attorney without a standardized level; years, skills, or credentials. |
| `Mid-Senior level` | The selected position has standardized source level `Senior` or `Manager`; `Senior` and `Manager` map to `Mid-Senior level`. An unambiguous title may also qualify when Senior, Sr., or a formal Manager level clearly describes organizational position level. | Account Manager, Case Manager, Community Manager, Product Manager, Project Manager, Lead, Staff, or Principal as a title word alone; professional expertise, long tenure, or a senior credential. |
| `Director` | The selected position has standardized level `Director`; or an unambiguous title such as Director of Finance clearly denotes formal organizational Director level. | Film Director, Funeral Director, Assistant Director, Associate Director, Head, or other uses where Director or leadership wording does not unambiguously identify the organizational band. |
| `Executive` | The selected position has standardized source level `President/Vice President` or `C-Level`; or an unambiguous title explicitly states President, Vice President, CEO, CFO, COO, CTO, CIO, CMO, or another Chief X Officer position. | Executive Assistant, Account Executive, Sales Executive, Chief of Staff, Head, Founder, Owner, or Partner without a separate explicit executive-level position. Founder, Owner, Partner, and Head do not determine a level by themselves. |

Source-to-project mapping is exact: `Intern` maps to `Internship`; `Specialist` maps to `Associate`; `Senior` and `Manager` map to `Mid-Senior level`; `Director` maps to `Director`; and `President/Vice President` plus `C-Level` map to `Executive`. A source value outside those mappings requires an independently unambiguous current title or produces `unknown`.

Use `high` only when the selected current position and the rule for the returned value are both explicit and conflict-free. Use `medium` when current-position evidence is substantial but conflicting or ambiguous. Use `low` with `unknown` when the current position or its level evidence is absent. Never use a historical title to fill a missing current level.

`management_scope.value` must use exactly one value below. This field describes leadership scope separately from seniority:

| Value | Meaning |
|---|---|
| `none` | Evidence supports an individual-contributor scope without project, people, or organizational leadership. Do not infer `none` merely because management evidence is absent. |
| `lead_no_report` | Leads projects, workstreams, standards, or coordination, but there is no evidence of direct-report responsibility. |
| `manage_team` | Explicitly manages or supervises employees and is accountable for team assignment, performance, or delivery. |
| `decision_maker` | Holds explicit organizational, strategic, budget, policy, or executive decision authority beyond ordinary team supervision. |
| `unknown` | Available evidence cannot reliably determine leadership scope. |

`industries.value` must be a non-empty array containing only these 20 LinkedIn Industry V2 top-level labels:

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

Use the exact English spelling and punctuation above. Map raw child industries and source-specific labels to their top-level parent instead of copying them. Examples: `Higher Education` maps to `Education`; `Software Development` maps to `Technology, Information and Media`; `Facilities Services` maps to `Administrative and Support Services`; `Music` or `Performing Arts` maps to `Entertainment Providers`; and `Real Estate` maps to `Real Estate and Equipment Rental Services`. Do not output free labels such as `Healthcare`, `Technology`, `Medical Services`, `Equipment Rental`, `Non-profit`, `Automotive`, or `Environmental Consulting`. Preserve multiple top-level industries only when separate experience evidence supports each one. Use `["unknown"]` if there is not enough evidence for any canonical industry.

For every non-formula inferred field, include `confidence`, `source_field`, and non-empty `evidence`. If evidence is missing, use an `unknown` value with `low` confidence. Its evidence may use an explicit absence state or briefly explain which required evidence the profile does not provide; exact absence wording is not required. Never treat a missing field as a negative fact.

`embedding_search_texts` must include all of:

- `responsibilities_search_text`
- `skills_search_text`
- `experience_search_text`
- `domain_search_text`
- `ownership_search_text`
- `achievements_search_text`
- `education_search_text`

Build each candidate-side search text for the matching query-side soft-preference dimension. The goal is precise retrieval enrichment, not biography rewriting and not maximum field completion.

SOFT-TEXT PRIORITY ORDER:

1. Source boundary.
2. Factual accuracy.
3. Dimension separation.
4. Retrieval usefulness.
5. Completeness.
6. Text richness.

A valid omission is always better than an unsupported enrichment. When completeness conflicts with a source boundary, the source boundary always wins. Use `not_provided` whenever useful text would require a forbidden source. Do not borrow evidence from another dimension to avoid `not_provided`, and do not treat inspection of every permitted source as a requirement to fill every dimension.

A summary is not automatically work evidence. Distinguish completed or current work from self-presentation and future intent. Aspirations, interests, goals, desired future roles, ideal workplaces, motivational statements, and generic traits do not establish experience, responsibilities, domain, ownership, or achievements. A stated interest such as dentistry or exotic-animal practice is not evidence that the candidate worked in that area. A goal to grow a team or business is not evidence that the candidate already led that team or growth. An explicitly stated current skill may remain skills evidence, but wanting to learn, seeking exposure, or describing oneself as motivated does not establish proficiency.

Use as few words as the permitted evidence supports. A precise two-word phrase is better than a padded sentence. Each non-missing dimension must contain no more than 60 English words. There is no minimum length. Write focused phrases or one or two coherent clauses; do not add generic praise, unsupported adjectives, or repeated boilerplate. Do not begin domain text with a shared boilerplate prefix such as `Employment context:`.

Preserve exact high-value names of tools, systems, certifications, licenses, works, publications, awards, employers, and all meaningful ranks, quantities, percentages, and dates. Add only direct synonyms, standard abbreviations, and immediate parent concepts. Do not strengthen verbs, scope, certainty, or impact. Do not combine unrelated fields into a new biographical claim.

Controlled occupational expansion is allowed only in `responsibilities_search_text` and `skills_search_text`. It is never allowed in experience, domain, ownership, achievements, or education. A title-derived canonical occupational concept must be a neutral noun phrase, not as an action the candidate performed. It must not add tools, customers, projects, outcomes, authority, scale, population, or specialized domain.

A generic hierarchy title provides no occupational content. Generic titles include `Manager`, `Director`, `President`, `Owner`, `Founder`, `Executive`, `Associate`, `Specialist`, `Lead`, and `Supervisor` when no specific function is named. Preserve such a title as role history in experience when useful, but do not derive responsibilities, skills, ownership, or achievements from hierarchy wording alone.

RESPONSIBILITIES DECISION:

1. First use explicit duties from `summary` and `experience[].description`.
2. If no explicit duty exists, a specific occupational title may contribute one concise neutral occupational concept. For example, `Program Coordinator` may yield `Program coordination`; `Speech Language Pathologist` may yield `Speech-language pathology`.
3. A generic hierarchy title or employer identity contributes nothing.
4. A title-derived concept must not use an action verb or imply performed work, authority, tools, customers, outcomes, or scope.
5. If no valid content remains, return exactly `not_provided`.

SKILLS DECISION:

1. Use explicit tools, systems, methods, and skills from `skills[]`, `summary`, and `experience[].description`.
2. Filter generic terms, hierarchy words, UI residue, duplicates, and context-free fragments. Do not copy raw `skills[]` as a keyword list.
3. Preserve discriminating names such as `Oomnitza`, `Microsoft Excel`, `Google Sheets`, `Salesforce Commerce Cloud`, `HubSpot`, or other exact source systems.
4. Courses may contribute only wording explicitly marked as `coursework`; study or exam preparation is not proficiency or a completed credential.
5. A specific occupational title may contribute one concise neutral skill concept, but a generic hierarchy title contributes nothing.
6. Never convert `skills[]` into experience or responsibilities, and never claim that a listed skill was applied without work evidence.
7. If no valid content remains, return exactly `not_provided`.

EXPERIENCE DECISION:

1. Experience may state that the candidate held an explicit role and may preserve the exact employer identity.
2. When a role has no supporting description or summary, use only role-history wording such as `Current role: <title> at <company>.` or `Past role: <title> at <company>.`
3. Actions, projects, use cases, delivery patterns, and applied tools require explicit support from `summary` or `experience[].description`.
4. Never convert a title, skill, course, employer tag, industry, or company reputation into an action or project.
5. Never include total career years, vague experience claims, or invented continuity between unrelated roles.
6. If no explicit role, employer, description, or summary provides useful content, return exactly `not_provided`.

DOMAIN DECISION:

1. Use explicit operating contexts stated in `summary` or `experience[].description`.
2. You may also use the exact canonical meaning of an explicit `experience[].industry`.
3. If only explicit industries are available, output only their canonical meanings without adding a specialization, customer type, regulation, product, or business process.
4. Always ignore company name, company tags, company description, employer reputation, title, source role, skills, education, courses, and certifications, even when the inferred domain appears obvious or is common knowledge.
5. If neither summary, descriptions, nor explicit industries provide domain evidence, return exactly `not_provided`.

OWNERSHIP DECISION:

1. Use only explicit ownership, workstream leadership, people management, budget authority, policy authority, or organizational decision statements from `summary` or `experience[].description`.
2. If `is_decision_maker == true` is the only qualifying evidence, output exactly `Explicit decision-maker status.`
3. A title alone never establishes an ownership action, team, budget, decision scope, or operating scope. Owner, Founder, President, Director, Manager, and Lead titles may remain role history in experience but cannot supply ownership text by themselves.
4. Ordinary duties remain responsibilities even when performed by a leader. Do not move coordination, administration, technical review, customer service, marketing execution, or tool administration into ownership unless the source explicitly describes leadership or authority.
5. Achievements and ownership require explicit candidate evidence. If no qualifying evidence exists, return exactly `not_provided`.

ACHIEVEMENTS DECISION:

1. Use only explicit awards, rankings, publications, works, launches, quantified outcomes, improvements, savings, growth, quality changes, or other evidenced impact from dedicated fields, `summary`, or `experience[].description`.
2. A client name, employer, title, responsibility, credential, or area of work is not an achievement by itself.
3. Preserve exact work names, award names, ranks, quantities, percentages, and measured results.
4. Never turn routine duties, prestigious employers, notable clients, or generic praise into achievements.
5. If no qualifying evidence exists, return exactly `not_provided`.

EDUCATION DECISION:

1. Use explicit degrees, majors, fields of study, coursework, certifications, licenses, and education context.
2. Preserve whether an item is completed, held, in progress, studied, or being prepared for.
3. Never present coursework as applied work, study as proficiency, exam preparation as a completed license, or an absent credential as a negative fact.
4. Keep full education and credential detail here; do not duplicate it across other dimensions unless another dimension has independently permitted evidence.
5. If no qualifying evidence exists, return exactly `not_provided`.

Critical examples:

- `Manager at Jim's Happy Bee Honey` with no description: responsibilities and skills must be `not_provided`, not office coordination, clerical support, or administrative management.
- `Program Coordinator` with no description may yield the neutral concept `Program coordination`, but not cross-functional delivery, stakeholder management, or project outcomes.
- `Seeking a small and exotic animal practice` and listing dentistry or surgery as interests do not establish veterinary domain experience or performed clinical responsibilities.
- `My goal is to grow a collective` does not establish that the candidate currently leads a team, owns a workstream, or performs organizational growth responsibilities.
- `Process Engineer at Intel`, a Chemical Engineering degree, Intel company tags, and explicit industry `Manufacturing`: domain may say `Manufacturing`, but not semiconductor design, chemical engineering processes, artificial intelligence, or other company- or education-derived specializations.
- `Managing Director - Reinsurance` with only `is_decision_maker == true`: ownership must be exactly `Explicit decision-maker status.`, not `Oversaw reinsurance operations`.
- `NCI Community Oncology Research Program Director` with no description: experience may say `Current role: NCI Community Oncology Research Program Director.`, but not `Directed an oncology research program.`
- A list of prestigious clients is experience context, not an achievement, unless the source states a result, award, launch, or measurable impact.
- `Studying Spanish and preparing for a real-estate license examination` belongs in education and does not establish Spanish proficiency or a completed real-estate credential.

Before returning, verify that `role_family.value` and every item in `industries.value` belong to the exact allowed lists above, except for the explicit `unknown` absence state. Any other classification label makes the output invalid.

Before returning JSON, audit every `high` value as if it could eliminate the candidate. For `role_family`, reject `high` when the classification depends on skills, education, employer industry, company name, or company tags rather than an explicit work-function source. For `industries`, verify that every returned label maps from an explicit `experience[].industry`; otherwise confidence cannot be `high`. For `seniority_level`, verify that the evidence names the Primary Current Position and satisfies exactly one six-level rule without using historical roles, years, credentials, or professional reputation. For `management_scope=none`, require explicit evidence of no project, people, or organizational leadership; no management description, a Specialist or individual-contributor title, and the absence of direct-report evidence do not authorize `high`.

FINAL DELETION AUDIT:

Before returning, silently identify one permitted source for every generated clause; do not output this audit. Delete a clause if its source is forbidden for that dimension, if it depends on company knowledge or company tags, if it contains an action unsupported by `summary` or `experience[].description`, if it adds authority or scope from a title, if it turns study or preparation into proficiency, or if it repeats ordinary responsibilities as ownership or achievements.

After deleting an invalid clause, do not replace it with evidence from another field, do not make it more generic to hide the unsupported inference, and do not pad the remaining text. Use `not_provided` if no valid clause remains. Before retaining any `not_provided`, verify only that all permitted sources for that dimension were inspected; completeness never authorizes a forbidden source.

Return a JSON object shaped like this:

```json
{
  "hard_fields": {
    "role_family": {
      "value": "Finance & Accounting",
      "confidence": "high",
      "source_field": "experience[].title",
      "evidence": "Controller"
    },
    "seniority_level": {
      "value": "Mid-Senior level",
      "confidence": "high",
      "source_field": "active_experience_management_level",
      "evidence": "Manager maps to Mid-Senior level"
    },
    "management_scope": {
      "value": "unknown",
      "confidence": "low",
      "source_field": "experience[].description",
      "evidence": "insufficient_evidence"
    },
    "industries": {
      "value": ["Financial Services"],
      "confidence": "medium",
      "source_field": "company_name",
      "evidence": "banking employer"
    }
  },
  "embedding_search_texts": {
    "responsibilities_search_text": "...",
    "skills_search_text": "...",
    "experience_search_text": "...",
    "domain_search_text": "...",
    "ownership_search_text": "...",
    "achievements_search_text": "not_provided",
    "education_search_text": "..."
  },
  "derived_fields": {},
  "keyword_signals": {},
  "risk": {}
}
```
