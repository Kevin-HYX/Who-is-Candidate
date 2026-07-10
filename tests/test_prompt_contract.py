import re
import unittest
from pathlib import Path

from src.constants import (
    CONFIDENCE_VALUES,
    INDUSTRY_VALUES,
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
