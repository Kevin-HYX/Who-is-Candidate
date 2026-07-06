# Return structured hard filter status

SearchResult rows return a structured `hard_filter_status` instead of a plain string. The status distinguishes fully passed candidates from candidates kept because one or more hard-constraint fields had insufficient evidence, and it includes the affected field names. This lets Agents avoid claiming uncertain hard constraints were satisfied while keeping the tool output simpler than a full explanation report.

