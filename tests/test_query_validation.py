import unittest

from src.schemas import CandidateSearchError, validate_search_request


VALID_SOFT = [
    {
        "dimension": "domain_search_text",
        "text": "在医疗财务账单和收入管理场景中工作",
        "weight": 1.2,
    }
]


class QueryValidationTests(unittest.TestCase):
    def test_rejects_empty_soft_preferences(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request({"weighted_soft_preferences": []})
        self.assertEqual(ctx.exception.code, "EMPTY_SOFT_PREFERENCES")

    def test_rejects_invalid_hard_field(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [
                        {"field": "certifications", "op": "in", "value": ["CPA"]}
                    ],
                    "weighted_soft_preferences": VALID_SOFT,
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_FIELD")

    def test_rejects_top_k_above_limit(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {"weighted_soft_preferences": VALID_SOFT},
                {"top_k": 76},
            )
        self.assertEqual(ctx.exception.code, "TOP_K_TOO_LARGE")

    def test_rejects_invalid_hard_value(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [
                        {"field": "seniority_level", "op": ">=", "value": "Wizard"}
                    ],
                    "weighted_soft_preferences": VALID_SOFT,
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_VALUE")

    def test_rejects_zero_weight(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "weighted_soft_preferences": [
                        {
                            "dimension": "domain_search_text",
                            "text": "在医疗财务账单和收入管理场景中工作",
                            "weight": 0,
                        }
                    ]
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_WEIGHT")


if __name__ == "__main__":
    unittest.main()
