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
from src.retrieval import canonical_hash, search_candidates, search_text_hash, write_jsonl, write_status
from src.schemas import RuntimeConfig


class FakeModelClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class SearchRankingTests(unittest.TestCase):
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
                _preprocessed_record(index, profile)
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
                _embedding_record(index, profile["user_id"], preprocessed_records[index], vectors[profile["user_id"]])
                for index, profile in enumerate(raw_profiles)
            ]
            write_jsonl(processed_dir / "embeddings.jsonl", embedding_records)
            write_status(config)

            result = search_candidates(
                config,
                {
                    "hard_constraints": [],
                    "weighted_soft_preferences": [
                        {
                            "dimension": "domain_search_text",
                            "text": "医疗财务账单收入管理",
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


def _write_raw(path: Path, profiles: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for profile in profiles:
            handle.write(json.dumps(profile, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _preprocessed_record(index: int, profile: dict) -> dict:
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
    return {
        "user_id": profile["user_id"],
        "source_row_index": index,
        "raw_profile_hash": canonical_hash(profile),
        "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
        "preprocessed_profile": preprocessed_profile,
    }


def _embedding_record(index: int, user_id: int, preprocessed_record: dict, domain_vector: list[float]) -> dict:
    vectors = {
        dimension: [0.0, 1.0]
        for dimension in SEARCHABLE_DIMENSIONS
    }
    vectors["domain_search_text"] = domain_vector
    return {
        "user_id": user_id,
        "source_row_index": index,
        "embedding_index_version": EMBEDDING_INDEX_VERSION,
        "search_text_hash": search_text_hash(preprocessed_record["preprocessed_profile"]),
        "vectors": vectors,
    }


if __name__ == "__main__":
    unittest.main()
