from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "candidate-search.toml"

PREPROCESS_SCHEMA_VERSION = "2026-07-06.1"
EMBEDDING_INDEX_VERSION = "2026-07-06.1"

DEFAULT_TOP_K = 20
MAX_TOP_K = 75
DEFAULT_CONCURRENCY = 3

HARD_CONSTRAINT_FIELDS = {
    "years_of_experience",
    "highest_degree_level",
    "role_family",
    "seniority_level",
    "management_scope",
    "industries",
    "is_currently_working",
}

SEARCHABLE_DIMENSIONS = {
    "responsibilities_search_text",
    "skills_search_text",
    "experience_search_text",
    "domain_search_text",
    "ownership_search_text",
    "achievements_search_text",
    "education_search_text",
}

HARD_CONSTRAINT_OPERATORS = {
    "years_of_experience": {">=", "<=", ">", "<", "="},
    "highest_degree_level": {">=", "<=", "="},
    "seniority_level": {">=", "<=", "="},
    "role_family": {"in", "not_in"},
    "industries": {"in", "not_in"},
    "management_scope": {">=", "<=", "=", "in", "not_in"},
    "is_currently_working": {"="},
}

SENIORITY_RANK = {
    "Intern": 0,
    "Specialist": 1,
    "Senior": 2,
    "Manager": 3,
    "Director": 4,
    "President/VP": 5,
    "President/Vice President": 5,
    "C-Level": 6,
    "Founder/Owner/Partner": 7,
    "Founder": 7,
    "Owner": 7,
    "Partner": 7,
}

MANAGEMENT_SCOPE_RANK = {
    "none": 0,
    "lead_no_report": 1,
    "manage_team": 2,
    "decision_maker": 3,
}

CONFIG_REQUIRED_FIELDS = (
    ("openai", "api_key"),
    ("openai", "base_url"),
    ("models", "preprocess"),
    ("models", "embedding"),
    ("paths", "raw_profiles"),
    ("paths", "processed_dir"),
)

PROCESSED_PROFILES_FILE = "preprocessed_profiles.jsonl"
EMBEDDINGS_FILE = "embeddings.jsonl"
STATUS_FILE = "status.json"
PREPROCESS_ERRORS_FILE = "preprocess_errors.jsonl"
INDEX_ERRORS_FILE = "index_errors.jsonl"
PREPROCESS_PROMPT_FILE = PROJECT_ROOT / "prompts" / "preprosess.md"
MCP_GUIDE_FILE = PROJECT_ROOT / "prompts" / "mcp-guide.md"
QUERY_GUIDE_FILE = PROJECT_ROOT / "prompts" / "query-guide.md"
