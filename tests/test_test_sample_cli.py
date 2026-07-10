import json
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from src.constants import EMBEDDING_INDEX_VERSION, PREPROCESS_SCHEMA_VERSION
from src.evaluation import (
    build_test_sample_index,
    create_test_sample,
    preprocess_test_sample,
    read_test_sample,
)
from src.main import main


class FakeTestSampleModelClient:
    def __init__(self) -> None:
        self.preprocess_calls = 0
        self.embedding_calls = 0

    def preprocess_profile(self, prompt: str, raw_profile: dict) -> dict:
        self.preprocess_calls += 1
        return {
            "hard_fields": {
                "role_family": {
                    "value": "Finance & Accounting",
                    "confidence": "high",
                    "source_field": "headline",
                    "evidence": raw_profile["headline"],
                },
                "seniority_level": {
                    "value": "Associate",
                    "confidence": "high",
                    "source_field": "headline",
                    "evidence": raw_profile["headline"],
                },
                "management_scope": {
                    "value": "none",
                    "confidence": "high",
                    "source_field": "headline",
                    "evidence": raw_profile["headline"],
                },
                "industries": {
                    "value": ["Financial Services"],
                    "confidence": "high",
                    "source_field": "headline",
                    "evidence": raw_profile["headline"],
                },
            },
            "embedding_search_texts": {
                "achievements_search_text": raw_profile["headline"],
                "domain_search_text": raw_profile["headline"],
                "education_search_text": raw_profile["headline"],
                "experience_search_text": raw_profile["headline"],
                "ownership_search_text": raw_profile["headline"],
                "responsibilities_search_text": raw_profile["headline"],
                "skills_search_text": raw_profile["headline"],
            },
            "derived_fields": {},
            "keyword_signals": {},
            "risk": {},
        }

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embedding_calls += 1
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


class TestSampleCliTests(unittest.TestCase):
    def test_create_show_and_resample_test_sample_invalidates_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            prompt_path = root / "preprosess-v1.md"
            prompt_path.write_text("preprocess prompt v1", encoding="utf-8")

            create_code = _run_cli(
                "test-sample-create",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--sample-size",
                "2",
                "--seed",
                "7",
                "--preprocess-prompt",
                str(prompt_path),
                "--json",
            )

            self.assertEqual(create_code, 0)
            sample_dir = root / "test" / "data" / "samples" / "sample_a"
            metadata = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sample_id"], "sample_a")
            self.assertEqual(metadata["sample_size"], 2)
            self.assertEqual(metadata["seed"], 7)
            self.assertIn("created_at", metadata)
            self.assertNotIn("status", metadata)
            self.assertEqual((sample_dir / "prompt_snapshot" / "preprosess.md").read_text(encoding="utf-8"), "preprocess prompt v1")
            sample_rows = _read_jsonl(sample_dir / "raw_profiles.jsonl")
            self.assertEqual(len(sample_rows), 2)
            sample_index = json.loads((sample_dir / "sample_index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(sample_index["items"]), 2)

            shown = read_test_sample(_load_config(config_path), "sample_a")
            self.assertEqual(shown["status"]["preprocess_status"], "missing")
            self.assertEqual(shown["status"]["index_status"], "missing")

            (sample_dir / "preprocessed_profiles.jsonl").write_text("{}\n", encoding="utf-8")
            (sample_dir / "embeddings.jsonl").write_text("{}\n", encoding="utf-8")
            (sample_dir / "preprocess_errors.jsonl").write_text("{}\n", encoding="utf-8")
            (sample_dir / "index_errors.jsonl").write_text("{}\n", encoding="utf-8")

            resample_code = _run_cli(
                "test-sample-resample",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--sample-size",
                "3",
                "--seed",
                "9",
                "--json",
            )

            self.assertEqual(resample_code, 0)
            metadata = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sample_size"], 3)
            self.assertEqual(metadata["seed"], 9)
            self.assertEqual(len(_read_jsonl(sample_dir / "raw_profiles.jsonl")), 3)
            self.assertFalse((sample_dir / "preprocessed_profiles.jsonl").exists())
            self.assertFalse((sample_dir / "embeddings.jsonl").exists())
            self.assertFalse((sample_dir / "preprocess_errors.jsonl").exists())
            self.assertFalse((sample_dir / "index_errors.jsonl").exists())
            self.assertFalse((sample_dir / "status.json").exists())

            show_code = _run_cli(
                "test-sample-show",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--json",
            )
            self.assertEqual(show_code, 0)

    def test_test_sample_show_computes_missing_from_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = _load_config(config_path)
            prompt_path = root / "preprosess-v1.md"
            prompt_path.write_text("preprocess prompt v1", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=2,
                seed=7,
                preprocess_prompt=prompt_path,
            )
            sample_dir = root / "test" / "data" / "samples" / "sample_a"
            shown = read_test_sample(config, "sample_a")

            self.assertEqual(shown["status"]["preprocess_status"], "missing")
            self.assertEqual(shown["status"]["index_status"], "missing")

    def test_test_sample_build_skips_successful_generation_cache_until_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = _load_config(config_path)
            prompt_path = root / "preprosess-v1.md"
            prompt_path.write_text("preprocess prompt v1", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=2,
                seed=7,
                preprocess_prompt=prompt_path,
            )
            client = FakeTestSampleModelClient()

            first_preprocess = preprocess_test_sample(config, "sample_a", model_client=client)
            second_preprocess = preprocess_test_sample(config, "sample_a", model_client=client)
            forced_preprocess = preprocess_test_sample(
                config,
                "sample_a",
                model_client=client,
                discard_cache=True,
            )

            self.assertEqual(first_preprocess["processed_count"], 2)
            self.assertEqual(first_preprocess["skipped_count"], 0)
            self.assertEqual(second_preprocess["processed_count"], 0)
            self.assertEqual(second_preprocess["skipped_count"], 2)
            self.assertEqual(forced_preprocess["processed_count"], 2)
            self.assertEqual(client.preprocess_calls, 4)

            first_index = build_test_sample_index(config, "sample_a", model_client=client)
            second_index = build_test_sample_index(config, "sample_a", model_client=client)
            forced_index = build_test_sample_index(
                config,
                "sample_a",
                model_client=client,
                discard_cache=True,
            )

            self.assertEqual(first_index["indexed_count"], 2)
            self.assertEqual(first_index["skipped_count"], 0)
            self.assertEqual(second_index["indexed_count"], 0)
            self.assertEqual(second_index["skipped_count"], 2)
            self.assertEqual(forced_index["indexed_count"], 2)
            self.assertEqual(client.embedding_calls, 4)

    def test_prompt_snapshot_change_invalidates_preprocess_and_index_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = _load_config(config_path)
            prompt_path = root / "preprosess-v1.md"
            prompt_path.write_text("preprocess prompt v1", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=2,
                seed=7,
                preprocess_prompt=prompt_path,
            )
            client = FakeTestSampleModelClient()
            preprocess_test_sample(config, "sample_a", model_client=client)
            build_test_sample_index(config, "sample_a", model_client=client)
            sample_dir = root / "test" / "data" / "samples" / "sample_a"

            (sample_dir / "prompt_snapshot" / "preprosess.md").write_text(
                "preprocess prompt v2",
                encoding="utf-8",
            )
            result = preprocess_test_sample(config, "sample_a", model_client=client)

            self.assertEqual(result["processed_count"], 2)
            self.assertEqual(result["skipped_count"], 0)
            self.assertEqual(client.preprocess_calls, 4)
            self.assertEqual(result["status"]["index_status"], "missing")
            self.assertEqual(_read_jsonl(sample_dir / "embeddings.jsonl"), [])
            records = _read_jsonl(sample_dir / "preprocessed_profiles.jsonl")
            self.assertTrue(all("preprocess_prompt_hash" in item for item in records))
            self.assertTrue(all("preprocess_model_hash" in item for item in records))

    def test_preprocess_model_change_invalidates_preprocess_and_index_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = _load_config(config_path)
            prompt_path = root / "preprosess-v1.md"
            prompt_path.write_text("preprocess prompt v1", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=2,
                seed=7,
                preprocess_prompt=prompt_path,
            )
            client = FakeTestSampleModelClient()
            preprocess_test_sample(config, "sample_a", model_client=client)
            build_test_sample_index(config, "sample_a", model_client=client)
            changed_config = replace(config, preprocess_model="qwen-next")

            stale_status = read_test_sample(changed_config, "sample_a")["status"]

            self.assertEqual(stale_status["preprocess_status"], "missing")
            self.assertEqual(stale_status["index_status"], "missing")
            rebuilt = preprocess_test_sample(
                changed_config,
                "sample_a",
                model_client=client,
            )
            self.assertEqual(rebuilt["processed_count"], 2)
            self.assertEqual(rebuilt["status"]["index_status"], "missing")


def _write_config(root: Path) -> Path:
    raw_path = root / "raw.jsonl"
    with raw_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(5):
            handle.write(json.dumps({"user_id": index + 1, "headline": f"Candidate {index + 1}"}, sort_keys=True))
            handle.write("\n")
    config_path = root / "candidate-search.toml"
    config_path.write_text(
        f"""
[openai]
api_key = "sk-test"
base_url = "https://example.test/compatible-mode/v1"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "{raw_path.as_posix()}"
processed_dir = "{(root / "processed").as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _load_config(path: Path):
    from src.schemas import load_config

    return load_config(path)


def _run_cli(*args: str) -> int:
    with redirect_stdout(StringIO()):
        return main(list(args))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    unittest.main()
