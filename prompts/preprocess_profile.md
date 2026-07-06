# Candidate Preprocess Prompt

You convert one raw candidate JSON profile into one preprocessed profile JSON object.

Return only JSON. Do not wrap it in Markdown.

The JSON object must contain:

- `hard_fields`
- `embedding_search_texts`
- `derived_fields`
- `keyword_signals`
- `risk`

The caller computes formula fields such as total years, highest degree, current role tenure, average tenure, and currently-working status in code. Do not invent those values.

For every non-formula inferred field, include `confidence`, `source_field`, and `evidence`. If evidence is missing, use `unknown`, `not_provided`, or `insufficient_evidence`; never treat a missing field as a negative fact.

`embedding_search_texts` must include all of:

- `responsibilities_search_text`
- `skills_search_text`
- `experience_search_text`
- `domain_search_text`
- `ownership_search_text`
- `achievements_search_text`
- `education_search_text`

Write search texts as concrete work content and business context, not just titles or keywords. Expand ambiguous titles such as Manager, Analyst, Associate, PM, and Lead into what the candidate actually did when evidence allows. Do not invent projects, clients, numbers, or certifications.

