import re
import unittest
from pathlib import Path

from src.constants import (
    CONFIDENCE_VALUES,
    INDUSTRY_VALUES,
    MCP_GUIDE_FILE,
    QUERY_GUIDE_FILE,
    ROLE_FAMILY_VALUES,
    SENIORITY_RANK,
)


PREPROCESS_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "preprosess.md"


class PromptContractTests(unittest.TestCase):
    def test_prompts_use_the_same_role_and_industry_enums_as_code(self) -> None:
        preprocess_text = PREPROCESS_PROMPT.read_text(encoding="utf-8")
        query_text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        preprocess_roles = _table_values(
            preprocess_text,
            "20 project-canonical labels:",
            "Use the exact English",
        )
        query_roles = _table_values(
            query_text,
            "project-owned 20-value role table.",
            "Map a title",
        )
        preprocess_industries = _table_values(
            preprocess_text,
            "20 LinkedIn Industry V2 top-level labels:",
            "Use the exact English",
        )
        query_industries = _table_values(
            query_text,
            "20 LinkedIn Industry V2 top-level categories.",
            "Never put a child industry",
        )

        self.assertEqual(preprocess_roles, set(ROLE_FAMILY_VALUES))
        self.assertEqual(query_roles, set(ROLE_FAMILY_VALUES))
        self.assertEqual(preprocess_industries, set(INDUSTRY_VALUES))
        self.assertEqual(query_industries, set(INDUSTRY_VALUES))

    def test_runtime_prompts_contain_no_han_characters(self) -> None:
        for path in (PREPROCESS_PROMPT, QUERY_GUIDE_FILE):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\u4e00-\u9fff]", text))

    def test_preprocess_prompt_defines_hard_filter_confidence_contract(self) -> None:
        text = PREPROCESS_PROMPT.read_text(encoding="utf-8")
        match = re.search(
            r"Use `confidence` as exactly one of: ([^.]*)\.",
            text,
        )
        self.assertIsNotNone(match)
        assert match is not None
        prompt_values = set(re.findall(r"`([^`]+)`", match.group(1)))

        self.assertEqual(prompt_values, CONFIDENCE_VALUES)
        self.assertIn("Only `high` authorizes hard elimination.", text)
        self.assertIn("An `unknown` value can never use `high`.", text)
        for field in ("role_family", "seniority_level", "management_scope", "industries"):
            self.assertIn(f"- `{field}`:", text)

    def test_prompts_define_the_same_six_position_levels_as_code(self) -> None:
        expected = (
            "Internship",
            "Entry level",
            "Associate",
            "Mid-Senior level",
            "Director",
            "Executive",
        )
        preprocess_text = PREPROCESS_PROMPT.read_text(encoding="utf-8")
        query_text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        self.assertEqual(tuple(SENIORITY_RANK), expected)
        self.assertEqual(
            _ordered_table_values(
                preprocess_text,
                "`seniority_level.value` must use exactly one value below.",
                "`management_scope.value` must use exactly one value below.",
            ),
            expected,
        )
        self.assertEqual(
            _ordered_table_values(
                query_text,
                "Values use this exact comparison order:",
                "### `management_scope`",
            ),
            expected,
        )

    def test_prompts_define_executable_position_level_boundaries(self) -> None:
        preprocess_text = PREPROCESS_PROMPT.read_text(encoding="utf-8")
        query_text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        for phrase in (
            "Primary Current Position",
            "`active_experience_title`",
            "If no current position exists",
            "`Retired`, `Unemployed`, `Career Break`, `Seeking Work`",
            "Historical positions cannot determine `seniority_level`",
            "Career length and professional credentials cannot determine `seniority_level`",
            "`Specialist` maps to `Associate`",
            "`Senior` and `Manager` map to `Mid-Senior level`",
            "Founder, Owner, Partner, and Head do not determine a level by themselves",
        ):
            self.assertIn(phrase, preprocess_text)

        for level in SENIORITY_RANK:
            self.assertIn(f"| `{level}` |", preprocess_text)
            self.assertIn(f"| `{level}` |", query_text)

        self.assertIn("professional capability", query_text)
        self.assertIn("Manager maps to `Mid-Senior level`", query_text)
        self.assertIn("Founder, Owner, and Partner", query_text)

    def test_role_family_means_primary_current_work_function_on_both_sides(self) -> None:
        preprocess_text = PREPROCESS_PROMPT.read_text(encoding="utf-8")
        query_text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        for text in (preprocess_text, query_text):
            self.assertIn(
                "role_family` represents the primary work function of the Primary Current Position",
                text,
            )
            self.assertIn(
            "Historical positions cannot establish a `high` current `role_family`",
            text,
            )

        self.assertIn(
            "Words such as `current`, `professional`, `specialist`, `leader`, or `experienced`",
            query_text,
        )
        self.assertIn("current primary role is Sales", query_text)
        self.assertIn("audit every `role_family` hard constraint separately", query_text)
        self.assertIn("current finance manager", query_text)
        self.assertIn("Find an operations leader for an analytical laboratory", query_text)
        self.assertIn('not `role_family in ["Operations"]`', query_text)
        self.assertIn("never preserves a narrower occupation, specialty, or title", query_text)
        self.assertIn("application architect", query_text)
        self.assertIn("coarse raw-data signal", query_text)
        self.assertIn("do not pretend this field enforces that guarantee", query_text)
        self.assertIn("bare `Manager` may establish a seniority requirement", query_text)
        self.assertIn("Preserve the user's abstraction level", query_text)
        self.assertIn("Manufacturing finance` does not authorize cost accounting", query_text)
        self.assertIn("Finance Manager` does not authorize an `ownership_search_text`", query_text)
        self.assertIn("User-source traceability gate", query_text)
        self.assertIn("every content-bearing word or phrase", query_text)
        self.assertIn("A parent concept never authorizes guessed children", query_text)
        self.assertIn("Finance work in a manufacturing environment", query_text)
        self.assertIn("Run this deletion audit after drafting", query_text)
        self.assertIn("User-requirement coverage gate", query_text)
        self.assertIn("represented exactly once", query_text)
        self.assertIn("Engineering and Technical` does not cover `application or technical architecture", query_text)
        self.assertIn("`Leader`, `Lead`, and `Head` are not stable organizational bands", query_text)
        self.assertIn("operations leader who has managed technicians", query_text)
        self.assertIn("does not authorize any `seniority_level` constraint", query_text)

    def test_query_examples_obey_user_source_traceability_gate(self) -> None:
        text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        for phrase in (
            "Perform project management and project delivery work",
            "Use Python for backend software development",
            "Work in healthcare finance",
            "Directly manage a team of employees",
            "Deliver a complete system implementation end to end",
            "Produce measurable cost reduction or efficiency improvement",
            "Own revenue-cycle processes in healthcare finance",
            "Perform primarily external audit work",
        ):
            self.assertIn(phrase, text)

        for invented_template in (
            "Work in hospital or healthcare finance involving patient billing, insurance claims",
            "Directly manage employees, including work assignment, performance feedback",
            "Perform primarily external audit work, including audit testing, workpapers",
            "Own revenue-cycle, billing, accounts-receivable",
            "Produce verifiable cost reduction, efficiency improvement, or error-rate reduction",
        ):
            self.assertNotIn(invented_template, text)

        self.assertIn("Identify the user's explicit priority phrase", text)
        self.assertIn("does not count as priority language", text)
        self.assertNotIn('"text":"Work in healthcare finance.","weight":1.2', text)

    def test_runtime_warning_stays_in_mcp_guide(self) -> None:
        query_text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")
        mcp_text = MCP_GUIDE_FILE.read_text(encoding="utf-8")

        self.assertNotIn("inspect returned `raw_profile` before presenting", query_text)
        self.assertIn("coarse raw-data signal", mcp_text)
        self.assertIn("cannot enforce the requirement perfectly", mcp_text)
        self.assertIn("inspect each returned `raw_profile`", mcp_text)

    def test_query_guide_matches_current_work_formula_priority(self) -> None:
        text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")

        self.assertIn("raw `is_working` is a Boolean", text)
        self.assertIn("resolved in favor of the Boolean `is_working` field", text)
        self.assertIn("displayed absolute weights may differ from `1.0`", text)

    def test_preprocess_prompt_defines_controlled_retrieval_enrichment(self) -> None:
        text = PREPROCESS_PROMPT.read_text(encoding="utf-8")

        for phrase in (
            "canonical occupational concept",
            "not as an action the candidate performed",
            "return exactly `not_provided`",
            "Achievements and ownership require explicit candidate evidence",
            "An explicit `experience[].industry` value",
            "Do not combine unrelated fields into a new biographical claim",
        ):
            self.assertIn(phrase, text)

    def test_preprocess_prompt_uses_source_first_embedding_rewrites(self) -> None:
        text = PREPROCESS_PROMPT.read_text(encoding="utf-8")

        for phrase in (
            "A valid omission is always better than an unsupported enrichment",
            "the source boundary always wins",
            "A summary is not automatically work evidence",
            "Aspirations, interests, goals, desired future roles, ideal workplaces",
            "If no Primary Current Position remains, `role_family.value` must be `unknown`",
            "no contradictory current-function evidence",
            "Sales And Purchasing Administrator",
            "non-occupational self-labels",
            "Hardworker",
            "bare `Professional`",
            "Sales Professional",
            "source level attached to an excluded status or self-label cannot resurrect",
            "bare `Professional` plus source level `Specialist`",
            "strongest explicitly evidenced leadership scope anywhere",
            "supervised a group of Service Team Members",
            "if ownership says the candidate supervised or managed a team",
            "A raw skill token is not automatically valid",
            "Start with a source-gating pass",
            "Do not stop after reading `skills[]`",
            "Never use `education`, `courses`, `certifications`, or licenses as a source for `skills_search_text`",
            "DataCamp courses named",
            "Apply this consistency rule",
            "Teacher` may yield `Teaching and instruction` in both dimensions",
            "A number alone also establishes nothing",
            "Responsible for leasing and renewals for over 600 apartment units",
            "run a cross-dimension title audit",
            "Receptionist` producing `Reception and front desk administration`",
            "Self-description such as `effective leader`",
            "There is no minimum length",
            "Never convert `skills[]` into experience or responsibilities",
            "Do not copy raw `skills[]` as a keyword list",
            "Do not begin domain text with a shared boilerplate prefix",
            "Preserve exact high-value names",
            "Experience may state that the candidate held an explicit role",
            "Controlled occupational expansion is allowed only in",
            "A generic hierarchy title provides no occupational content",
            "DOMAIN DECISION",
            "OWNERSHIP DECISION",
            "RESPONSIBILITIES DECISION",
            "EXPERIENCE DECISION",
            "ACHIEVEMENTS DECISION",
            "FINAL DELETION AUDIT",
            "do not replace it with evidence from another field",
            "do not make it more generic to hide the unsupported inference",
        ):
            self.assertIn(phrase, text)

        self.assertNotIn("target 12 to 60 English words", text)


def _table_values(text: str, start_marker: str, end_marker: str) -> set[str]:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    block = text[start:end]
    return set(re.findall(r"^\| `([^`]+)` \|", block, flags=re.MULTILINE))


def _ordered_table_values(
    text: str,
    start_marker: str,
    end_marker: str,
) -> tuple[str, ...]:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    block = text[start:end]
    return tuple(re.findall(r"^\| `([^`]+)` \|", block, flags=re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
