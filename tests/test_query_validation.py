import unittest

from src.schemas import (
    CandidateSearchError,
    validate_generated_search_arguments,
    validate_search_arguments,
    validate_search_request,
)


VALID_SOFT = [
    {
        "dimension": "domain_search_text",
        "text": "Work in healthcare finance, billing, and revenue-cycle operations.",
        "weight": 1.2,
    }
]


def valid_plan(*, hard_constraints: list[dict] | None = None) -> dict:
    return {
        "hard_constraints": hard_constraints or [],
        "weighted_soft_preferences": VALID_SOFT,
    }


class QueryValidationTests(unittest.TestCase):
    def test_rejects_empty_soft_preferences(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {"hard_constraints": [], "weighted_soft_preferences": []}
            )
        self.assertEqual(ctx.exception.code, "EMPTY_SOFT_PREFERENCES")

    def test_rejects_invalid_hard_field(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [
                        {
                            "field": "certifications",
                            "op": "in",
                            "value": ["CPA"],
                            "rationale": "The user requires CPA certification.",
                        }
                    ],
                    "weighted_soft_preferences": VALID_SOFT,
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_FIELD")

    def test_rejects_top_k_above_limit(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                valid_plan(),
                {"top_k": 76},
            )
        self.assertEqual(ctx.exception.code, "TOP_K_TOO_LARGE")

    def test_rejects_invalid_hard_value(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [
                        {
                            "field": "seniority_level",
                            "op": ">=",
                            "value": "Wizard",
                            "rationale": "The user requires a senior candidate.",
                        }
                    ],
                    "weighted_soft_preferences": VALID_SOFT,
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_VALUE")

    def test_accepts_six_position_levels_and_rejects_legacy_levels(self) -> None:
        levels = (
            "Internship",
            "Entry level",
            "Associate",
            "Mid-Senior level",
            "Director",
            "Executive",
        )
        for level in levels:
            with self.subTest(level=level):
                validate_search_request(
                    valid_plan(
                        hard_constraints=[
                            {
                                "field": "seniority_level",
                                "op": "=",
                                "value": level,
                                "rationale": "The user explicitly requires this position level.",
                            }
                        ]
                    )
                )

        for legacy_level in ("Intern", "Specialist", "Senior", "Manager", "President/VP", "C-Level", "Founder/Owner/Partner"):
            with self.subTest(legacy_level=legacy_level):
                with self.assertRaises(CandidateSearchError) as ctx:
                    validate_search_request(
                        valid_plan(
                            hard_constraints=[
                                {
                                    "field": "seniority_level",
                                    "op": "=",
                                    "value": legacy_level,
                                    "rationale": "The user explicitly requires this position level.",
                                }
                            ]
                        )
                    )
                self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_VALUE")

    def test_rejects_zero_weight(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {
                            "dimension": "domain_search_text",
                            "text": "Work in healthcare finance and billing operations.",
                            "weight": 0,
                        }
                    ]
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_WEIGHT")

    def test_accepts_continuous_weight_within_bounded_range(self) -> None:
        request = validate_search_request(
            {
                "hard_constraints": [],
                "weighted_soft_preferences": [
                    {
                        "dimension": "domain_search_text",
                        "text": "Work in healthcare finance and billing operations.",
                        "weight": 1.37,
                    }
                ],
            }
        )

        self.assertEqual(
            request.query_plan["weighted_soft_preferences"][0]["weight"],
            1.37,
        )

    def test_rejects_weight_outside_range_or_below_minimum_magnitude(self) -> None:
        for weight in (-2.01, -0.09, 0.09, 2.01):
            with self.subTest(weight=weight):
                with self.assertRaises(CandidateSearchError) as ctx:
                    validate_search_request(
                        {
                            "hard_constraints": [],
                            "weighted_soft_preferences": [
                                {
                                    "dimension": "domain_search_text",
                                    "text": "Work in healthcare finance operations.",
                                    "weight": weight,
                                }
                            ],
                        }
                    )
                self.assertEqual(ctx.exception.code, "INVALID_WEIGHT")

    def test_rejects_noncanonical_role_and_industry_values(self) -> None:
        invalid_constraints = [
            {
                "field": "role_family",
                "op": "in",
                "value": ["Finance"],
                "rationale": "The user requires a finance function.",
            },
            {
                "field": "industries",
                "op": "in",
                "value": ["Higher Education"],
                "rationale": "The user requires higher-education experience.",
            },
        ]
        for constraint in invalid_constraints:
            with self.subTest(field=constraint["field"]):
                with self.assertRaises(CandidateSearchError) as ctx:
                    validate_search_request(valid_plan(hard_constraints=[constraint]))
                self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_VALUE")

    def test_rejects_scalar_value_for_set_operator(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                valid_plan(
                    hard_constraints=[
                        {
                            "field": "role_family",
                            "op": "in",
                            "value": "Finance & Accounting",
                            "rationale": "The user requires a finance function.",
                        }
                    ]
                )
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT_VALUE")

    def test_rejects_missing_rationale_and_extra_preference_fields(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                valid_plan(
                    hard_constraints=[
                        {
                            "field": "role_family",
                            "op": "in",
                            "value": ["Finance & Accounting"],
                        }
                    ]
                )
            )
        self.assertEqual(ctx.exception.code, "INVALID_HARD_CONSTRAINT")

        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {**VALID_SOFT[0], "notes": "unsupported"}
                    ],
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_SOFT_PREFERENCE")

    def test_rejects_unknown_options_and_noninteger_top_k(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(valid_plan(), {"normalization": "percentile"})
        self.assertEqual(ctx.exception.code, "INVALID_OPTIONS_FIELD")

        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(valid_plan(), {"top_k": "10"})
        self.assertEqual(ctx.exception.code, "INVALID_TOP_K")

    def test_rejects_duplicate_and_negated_soft_preferences(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [VALID_SOFT[0], VALID_SOFT[0]],
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_SOFT_PREFERENCE")

        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_request(
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {
                            "dimension": "responsibilities_search_text",
                            "text": "Do not perform external audit work.",
                            "weight": 0.8,
                        }
                    ],
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_SOFT_PREFERENCE_TEXT")

    def test_rejects_non_english_generated_query_text(self) -> None:
        chinese_rationale = valid_plan(
            hard_constraints=[
                {
                    "field": "years_of_experience",
                    "op": ">=",
                    "value": 5,
                    "rationale": "用户要求至少五年经验。",
                }
            ]
        )
        chinese_soft_text = {
            "hard_constraints": [],
            "weighted_soft_preferences": [
                {
                    "dimension": "domain_search_text",
                    "text": "医疗财务与收入周期管理经验",
                    "weight": 1.0,
                }
            ],
        }

        for query_plan in (chinese_rationale, chinese_soft_text):
            with self.subTest(query_plan=query_plan):
                with self.assertRaises(CandidateSearchError) as ctx:
                    validate_search_request(query_plan)
                self.assertEqual(ctx.exception.code, "NON_ENGLISH_GENERATED_TEXT")

    def test_generated_arguments_require_exact_top_level_shape(self) -> None:
        valid_output = {
            "query_plan": valid_plan(),
            "options": {"top_k": 10},
        }
        request = validate_generated_search_arguments(valid_output)
        self.assertEqual(request.top_k, 10)

        for invalid_output in (
            {"query_plan": valid_plan()},
            {**valid_output, "explanation": "extra"},
        ):
            with self.subTest(output=invalid_output):
                with self.assertRaises(CandidateSearchError) as ctx:
                    validate_generated_search_arguments(invalid_output)
                self.assertEqual(ctx.exception.code, "INVALID_QUERY_SCHEMA_OUTPUT")

    def test_search_arguments_reject_unsupported_top_level_fields(self) -> None:
        with self.assertRaises(CandidateSearchError) as ctx:
            validate_search_arguments(
                {
                    "query_plan": valid_plan(),
                    "options": {"top_k": 10},
                    "explanation": "unsupported",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_SEARCH_ARGUMENTS")


if __name__ == "__main__":
    unittest.main()
