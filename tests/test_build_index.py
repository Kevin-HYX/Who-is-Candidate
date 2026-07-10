import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.constants import (
    EMBEDDING_INDEX_VERSION,
    EMBEDDINGS_FILE,
    PREPROCESS_SCHEMA_VERSION,
    PROCESSED_PROFILES_FILE,
    SEARCHABLE_DIMENSIONS,
)
from src.retrieval import build_index, canonical_hash, get_index_status, write_jsonl
from src.schemas import BuildWorkspace, CandidateSearchError, RuntimeConfig


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


class InvalidEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding request failed")


class NonFiniteEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float("nan"), 1.0] for _ in texts]


class BuildIndexTests(unittest.TestCase):
    def test_build_index_writes_embeddings_and_computes_live_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])

            result = build_index(config, model_client=FakeEmbeddingClient())

            self.assertEqual(result["indexed_count"], 1)
            embeddings = [
                json.loads(line)
                for line in (config.processed_dir / EMBEDDINGS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(embeddings), 1)
            self.assertEqual(set(embeddings[0]["vectors"]), SEARCHABLE_DIMENSIONS)
            status = get_index_status(config)
            self.assertEqual(status["index_status"], "full")
            self.assertFalse((config.processed_dir / "status.json").exists())

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
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(workspace_processed / PROCESSED_PROFILES_FILE, [preprocessed])

            result = build_index(config, workspace=workspace, model_client=FakeEmbeddingClient())

            self.assertEqual(result["indexed_count"], 1)
            self.assertTrue((workspace_processed / EMBEDDINGS_FILE).exists())
            self.assertFalse((workspace_processed / "status.json").exists())
            self.assertFalse((config.processed_dir / EMBEDDINGS_FILE).exists())

    def test_missing_artifacts_are_reported_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = _setup_config_with_raw(tmp)

            status = get_index_status(config)

            self.assertEqual(status["preprocess_schema_version"], PREPROCESS_SCHEMA_VERSION)
            self.assertEqual(status["embedding_index_version"], EMBEDDING_INDEX_VERSION)
            self.assertEqual(status["preprocess_status"], "missing")
            self.assertEqual(status["index_status"], "missing")
            self.assertEqual(status["preprocessed_candidates"], 0)
            self.assertEqual(status["indexed_candidates"], 0)
            self.assertEqual(status["source_ranges"], [])
            self.assertEqual(status["next_actions"], ["preprocess", "build-index"])

    def test_discard_cache_failure_removes_previous_embedding_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])
            build_index(config, model_client=FakeEmbeddingClient())

            with self.assertRaises(CandidateSearchError) as ctx:
                build_index(
                    config,
                    model_client=InvalidEmbeddingClient(),
                    discard_cache=True,
                )

            self.assertEqual(ctx.exception.code, "BUILD_INDEX_FAILED")
            self.assertEqual(
                (config.processed_dir / EMBEDDINGS_FILE).read_text(encoding="utf-8"),
                "",
            )
            status = get_index_status(config)
            self.assertEqual(status["index_status"], "missing")

    def test_embedding_model_change_invalidates_only_index_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])
            client = FakeEmbeddingClient()
            build_index(config, model_client=client)
            changed_config = replace(config, embedding_model="text-embedding-v5")

            stale_status = get_index_status(changed_config)

            self.assertEqual(stale_status["preprocess_status"], "full")
            self.assertEqual(stale_status["index_status"], "missing")
            rebuilt = build_index(changed_config, model_client=client)
            self.assertEqual(rebuilt["indexed_count"], 1)
            self.assertEqual(client.calls, 2)

    def test_non_finite_embedding_is_retried_then_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])

            with self.assertRaises(CandidateSearchError) as ctx:
                build_index(config, model_client=NonFiniteEmbeddingClient())

            self.assertEqual(ctx.exception.code, "BUILD_INDEX_FAILED")
            self.assertEqual(
                (config.processed_dir / EMBEDDINGS_FILE).read_text(encoding="utf-8"),
                "",
            )

    def test_status_validates_actual_artifacts_instead_of_trusting_cached_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, raw_profile = _setup_config_with_raw(tmp)
            preprocessed = _preprocessed_record(0, raw_profile, config=config)
            write_jsonl(config.processed_dir / PROCESSED_PROFILES_FILE, [preprocessed])
            build_index(config, model_client=FakeEmbeddingClient())
            self.assertEqual(get_index_status(config)["index_status"], "full")

            (config.processed_dir / EMBEDDINGS_FILE).write_text("", encoding="utf-8")
            without_embeddings = get_index_status(config)
            self.assertEqual(without_embeddings["preprocess_status"], "full")
            self.assertEqual(without_embeddings["index_status"], "missing")

            changed_raw = {**raw_profile, "headline": "Changed"}
            config.raw_profiles_path.write_text(
                json.dumps(changed_raw) + "\n",
                encoding="utf-8",
            )
            after_raw_change = get_index_status(config)
            self.assertEqual(after_raw_change["preprocess_status"], "missing")
            self.assertEqual(after_raw_change["index_status"], "missing")


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


def _preprocessed_record(
    index: int,
    raw_profile: dict,
    *,
    config: RuntimeConfig | None = None,
) -> dict:
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
    record = {
        "user_id": raw_profile["user_id"],
        "source_row_index": index,
        "raw_profile_hash": canonical_hash(raw_profile),
        "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
        "preprocessed_profile": preprocessed_profile,
    }
    if config is not None:
        record["preprocess_model_hash"] = canonical_hash(
            {"base_url": config.base_url, "model": config.preprocess_model}
        )
        prompt_path = config.build_workspace().preprocess_prompt_path
        if prompt_path is not None:
            record["preprocess_prompt_hash"] = canonical_hash(
                prompt_path.read_text(encoding="utf-8")
            )
    return record


if __name__ == "__main__":
    unittest.main()
