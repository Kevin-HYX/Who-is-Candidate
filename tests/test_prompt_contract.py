import re
import unittest
from pathlib import Path

from src.constants import INDUSTRY_VALUES, QUERY_GUIDE_FILE, ROLE_FAMILY_VALUES


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


def _table_values(text: str, start_marker: str, end_marker: str) -> set[str]:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    block = text[start:end]
    return set(re.findall(r"^\| `([^`]+)` \|", block, flags=re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
