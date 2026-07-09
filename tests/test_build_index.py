import json
import tempfile
import unittest
from pathlib import Path

from src.constants import (
    EMBEDDINGS_FILE,
    PREPROCESS_SCHEMA_VERSION,
    PROCESSED_PROFILES_FILE,
    SEARCHABLE_DIMENSIONS,
    STATUS_FILE,
)
from src.retrieval import build_index, canonical_hash, write_jsonl
from src.schemas import BuildWorkspace, CandidateSearchError, RuntimeConfig


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


class BuildIndexTests(unittest.TestCase):
    def test_build_index_writes_embeddings_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])

            result = build_index(config, model_client=FakeEmbeddingClient())

            self.assertEqual(result["indexed_count"], 1)
            embeddings = [
                json.loads(line)
                for line in (config.processed_dir / EMBEDDINGS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(embeddings), 1)
            self.assertEqual(set(embeddings[0]["vectors"]), SEARCHABLE_DIMENSIONS)
            status = json.loads((config.processed_dir / STATUS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(status["index_status"], "full")

    def test_build_index_requires_preprocessed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = _setup_config_with_raw(tmp)
            with self.assertRaises(CandidateSearchError) as ctx:
                build_index(config, model_client=FakeEmbeddingClient())
            self.assertEqual(ctx.exception.code, "PREPROCESS_AND_INDEX_NOT_BUILT")

    def test_build_index_can_target_explicit_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = _setup_config_with_raw(tmp)
            root = Path(tmp)
            workspace_raw = root / "raw_profiles.jsonl"
            workspace_processed = root / "sample_artifacts"
            workspace_processed.mkdir()
            raw_profile = {"user_id": 9, "headline": "Sample Candidate"}
            workspace_raw.write_text(json.dumps(raw_profile) + "\n", encoding="utf-8")
            workspace = BuildWorkspace(
                raw_profiles_path=workspace_raw,
                processed_dir=workspace_processed,
            )
            preprocessed = _preprocessed_record(0, raw_profile)
            write_jsonl(workspace_processed / PROCESSED_PROFILES_FILE, [preprocessed])

            result = build_index(config, workspace=workspace, model_client=FakeEmbeddingClient())

            self.assertEqual(result["indexed_count"], 1)
            self.assertTrue((workspace_processed / EMBEDDINGS_FILE).exists())
            self.assertTrue((workspace_processed / STATUS_FILE).exists())
            self.assertFalse((config.processed_dir / EMBEDDINGS_FILE).exists())
            self.assertFalse((config.processed_dir / STATUS_FILE).exists())


def _setup_config_with_raw(tmp: str) -> tuple[RuntimeConfig, dict]:
    root = Path(tmp)
    processed_dir = root / "processed"
    processed_dir.mkdir()
    raw_path = root / "raw.jsonl"
    raw_profile = {"user_id": 1, "headline": "A"}
    raw_path.write_text(json.dumps(raw_profile) + "\n", encoding="utf-8")
    return (
        RuntimeConfig(
            config_path=root / "candidate-search.toml",
            api_key="sk-test",
            base_url="https://example.test/compatible-mode/v1",
            preprocess_model="qwen3.7-max",
            embedding_model="text-embedding-v4",
            raw_profiles_path=raw_path,
            processed_dir=processed_dir,
        ),
        raw_profile,
    )


def _preprocessed_record(index: int, raw_profile: dict) -> dict:
    preprocessed_profile = {
        "hard_fields": {},
        "embedding_search_texts": {
            dimension: f"text for {dimension}"
            for dimension in SEARCHABLE_DIMENSIONS
        },
        "derived_fields": {},
        "keyword_signals": {},
        "risk": {},
    }
    return {
        "user_id": raw_profile["user_id"],
        "source_row_index": index,
        "raw_profile_hash": canonical_hash(raw_profile),
        "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
        "preprocessed_profile": preprocessed_profile,
    }


if __name__ == "__main__":
    unittest.main()
