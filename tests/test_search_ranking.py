import json
import math
import tempfile
import unittest
from pathlib import Path

from src.constants import (
    EMBEDDING_INDEX_VERSION,
    PROCESSED_PROFILES_FILE,
    PREPROCESS_SCHEMA_VERSION,
    SEARCHABLE_DIMENSIONS,
)
from src.retrieval import (
    _evaluate_hard_constraints,
    _score_candidates,
    canonical_hash,
    embedding_model_hash,
    preprocess_model_hash,
    search_candidates,
    search_text_hash,
    write_jsonl,
)
from src.schemas import RuntimeConfig


class FakeModelClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class SearchRankingTests(unittest.TestCase):
    def test_continuous_input_weights_are_normalized_before_scoring(self) -> None:
        scored = _score_candidates(
            [
                {
                    "user_id": 1,
                    "hard_filter_status": {"status": "passed"},
                    "embedding_record": {
                        "vectors": {
                            "domain_search_text": [1.0, 0.0],
                            "skills_search_text": [1.0, 0.0],
                        }
                    },
                }
            ],
            [
                {
                    "dimension": "domain_search_text",
                    "text": "hospital finance",
                    "weight": 2.0,
                },
                {
                    "dimension": "skills_search_text",
                    "text": "financial systems",
                    "weight": 1.0,
                },
            ],
            [[1.0, 0.0], [1.0, 0.0]],
        )

        scores = scored[0]["soft_preference_scores"]
        self.assertEqual([item["weight"] for item in scores], [0.666667, 0.333333])
        self.assertEqual(scored[0]["final_score"], 1.0)

    def test_missing_candidate_soft_dimension_scores_zero(self) -> None:
        candidates = [
            {
                "user_id": 1,
                "hard_filter_status": {"status": "passed"},
                "embedding_record": {"vectors": {}},
            },
            {
                "user_id": 2,
                "hard_filter_status": {"status": "passed"},
                "embedding_record": {
                    "vectors": {"domain_search_text": [1.0, 0.0]}
                },
            },
        ]

        scored = _score_candidates(
            candidates,
            [
                {
                    "dimension": "domain_search_text",
                    "text": "hospital finance",
                    "weight": 1.0,
                }
            ],
            [[1.0, 0.0]],
        )

        by_user_id = {item["user_id"]: item for item in scored}
        self.assertEqual(by_user_id[1]["final_score"], 0.0)
        self.assertEqual(by_user_id[2]["final_score"], 1.0)

    def test_medium_and_low_confidence_never_authorize_hard_filtering(self) -> None:
        constraint = {
            "field": "role_family",
            "op": "in",
            "value": ["Finance & Accounting"],
            "rationale": "The user requires a finance function.",
        }
        for confidence in ("medium", "low"):
            with self.subTest(confidence=confidence):
                result = _evaluate_hard_constraints(
                    {
                        "hard_fields": {
                            "role_family": {
                                "value": "Finance & Accounting",
                                "confidence": confidence,
                                "source_field": "experience[0].role",
                                "evidence": "Finance & Accounting",
                            }
                        }
                    },
                    [constraint],
                )
                self.assertEqual(
                    result,
                    {
                        "status": "kept_with_insufficient_evidence",
                        "insufficient_evidence_fields": ["role_family"],
                    },
                )

    def test_role_family_hard_filter_reads_canonical_value_field(self) -> None:
        result = _evaluate_hard_constraints(
            {
                "hard_fields": {
                    "role_family": {
                        "value": "Finance & Accounting",
                        "confidence": "high",
                        "source_field": "experience[0].role",
                        "evidence": "Finance & Accounting",
                    }
                }
            },
            [
                {
                    "field": "role_family",
                    "op": "in",
                    "value": ["Finance & Accounting"],
                    "rationale": "The user requires a finance function.",
                }
            ],
        )

        self.assertEqual(
            result,
            {"status": "passed", "insufficient_evidence_fields": []},
        )

    def test_same_score_uses_same_rank_and_top_k_boundary_is_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.jsonl"
            processed_dir = root / "processed"
            processed_dir.mkdir()
            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="qwen3.7-max",
                embedding_model="text-embedding-v4",
                raw_profiles_path=raw_path,
                processed_dir=processed_dir,
            )
            raw_profiles = [
                {"user_id": 1, "headline": "A"},
                {"user_id": 2, "headline": "B"},
                {"user_id": 3, "headline": "C"},
                {"user_id": 4, "headline": "D"},
            ]
            _write_raw(raw_path, raw_profiles)
            preprocessed_records = [
                _preprocessed_record(index, profile, config)
                for index, profile in enumerate(raw_profiles)
            ]
            write_jsonl(processed_dir / PROCESSED_PROFILES_FILE, preprocessed_records)

            vectors = {
                1: [1.0, 0.0],
                2: [0.9, math.sqrt(1 - 0.9**2)],
                3: [0.9, math.sqrt(1 - 0.9**2)],
                4: [0.0, 1.0],
            }
            embedding_records = [
                _embedding_record(
                    index,
                    profile["user_id"],
                    preprocessed_records[index],
                    vectors[profile["user_id"]],
                    config=config,
                )
                for index, profile in enumerate(raw_profiles)
            ]
            write_jsonl(processed_dir / "embeddings.jsonl", embedding_records)

            result = search_candidates(
                config,
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {
                            "dimension": "domain_search_text",
                            "text": "Healthcare finance, billing, and revenue management.",
                            "weight": 1.0,
                        }
                    ],
                },
                {"top_k": 2},
                model_client=FakeModelClient(),
            )

            self.assertEqual(result["search_meta"]["requested_top_k"], 2)
            self.assertEqual(result["search_meta"]["returned_count"], 3)
            self.assertIsNotNone(result["search_meta"]["returned_beyond_top_k_reason"])
            ranks = [(item["user_id"], item["rank"]) for item in result["results"]]
            self.assertEqual(ranks, [(1, 1), (2, 2), (3, 2)])
            for item in result["results"]:
                total = sum(
                    score["score_after_weight"]
                    for score in item["soft_preference_scores"]
                )
                self.assertAlmostEqual(item["final_score"], total)
                self.assertIn("raw_profile", item)

    def test_final_score_equals_sum_of_returned_rounded_contributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.jsonl"
            processed_dir = root / "processed"
            processed_dir.mkdir()
            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="qwen3.7-max",
                embedding_model="text-embedding-v4",
                raw_profiles_path=raw_path,
                processed_dir=processed_dir,
            )
            raw_profiles = [
                {"user_id": 1, "headline": "A"},
                {"user_id": 2, "headline": "B"},
                {"user_id": 3, "headline": "C"},
                {"user_id": 4, "headline": "D"},
            ]
            _write_raw(raw_path, raw_profiles)
            preprocessed_records = [
                _preprocessed_record(index, profile, config)
                for index, profile in enumerate(raw_profiles)
            ]
            write_jsonl(processed_dir / PROCESSED_PROFILES_FILE, preprocessed_records)
            vectors = {
                1: [1.0, 0.0],
                2: [0.9, math.sqrt(1 - 0.9**2)],
                3: [0.9, math.sqrt(1 - 0.9**2)],
                4: [0.0, 1.0],
            }
            ranked_dimensions = {
                "domain_search_text",
                "experience_search_text",
                "skills_search_text",
            }
            write_jsonl(
                processed_dir / "embeddings.jsonl",
                [
                    _embedding_record(
                        index,
                        profile["user_id"],
                        preprocessed_records[index],
                        vectors[profile["user_id"]],
                        config=config,
                        ranked_dimensions=ranked_dimensions,
                    )
                    for index, profile in enumerate(raw_profiles)
                ],
            )

            result = search_candidates(
                config,
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {
                            "dimension": dimension,
                            "text": "Healthcare finance operations and billing work.",
                            "weight": 1.0,
                        }
                        for dimension in sorted(ranked_dimensions)
                    ],
                },
                {"top_k": 4},
                model_client=FakeModelClient(),
            )

            candidate = next(item for item in result["results"] if item["user_id"] == 2)
            contribution_sum = sum(
                score["score_after_weight"]
                for score in candidate["soft_preference_scores"]
            )
            self.assertEqual(
                [score["weight"] for score in candidate["soft_preference_scores"]],
                [0.333333, 0.333333, 0.333333],
            )
            self.assertEqual(contribution_sum, 0.333333)
            self.assertEqual(candidate["final_score"], contribution_sum)


def _write_raw(path: Path, profiles: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for profile in profiles:
            handle.write(json.dumps(profile, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _preprocessed_record(
    index: int,
    profile: dict,
    config: RuntimeConfig,
) -> dict:
    preprocessed_profile = {
        "hard_fields": {},
        "embedding_search_texts": {
            dimension: f"{dimension} for {profile['user_id']}"
            for dimension in SEARCHABLE_DIMENSIONS
        },
        "derived_fields": {},
        "keyword_signals": {},
        "risk": {},
    }
    prompt_path = config.build_workspace().preprocess_prompt_path
    return {
        "user_id": profile["user_id"],
        "source_row_index": index,
        "raw_profile_hash": canonical_hash(profile),
        "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
        "preprocess_prompt_hash": canonical_hash(
            prompt_path.read_text(encoding="utf-8")
        ),
        "preprocess_model_hash": preprocess_model_hash(config),
        "preprocessed_profile": preprocessed_profile,
    }


def _embedding_record(
    index: int,
    user_id: int,
    preprocessed_record: dict,
    domain_vector: list[float],
    *,
    config: RuntimeConfig,
    ranked_dimensions: set[str] | None = None,
) -> dict:
    vectors = {
        dimension: [0.0, 1.0]
        for dimension in SEARCHABLE_DIMENSIONS
    }
    for dimension in ranked_dimensions or {"domain_search_text"}:
        vectors[dimension] = domain_vector
    return {
        "user_id": user_id,
        "source_row_index": index,
        "embedding_index_version": EMBEDDING_INDEX_VERSION,
        "embedding_model_hash": embedding_model_hash(config),
        "search_text_hash": search_text_hash(preprocessed_record["preprocessed_profile"]),
        "vectors": vectors,
    }


if __name__ == "__main__":
    unittest.main()
