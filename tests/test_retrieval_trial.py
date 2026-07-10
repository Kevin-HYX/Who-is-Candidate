import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation import (
    build_test_sample_index,
    create_test_sample,
    create_user_prompt_set,
    map_user_prompt_set,
    preprocess_test_sample,
    run_retrieval_trial,
)
from src.retrieval import search_candidates
from src.schemas import BuildWorkspace, CandidateSearchError, load_config
from tests.test_test_sample_cli import FakeTestSampleModelClient
from tests.test_user_prompt_set import FakeQueryModelClient


class RetrievalTrialTests(unittest.TestCase):
    def test_trial_refuses_unready_inputs_then_saves_search_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            preprocess_prompt = root / "preprosess-v1.md"
            preprocess_prompt.write_text("preprocess prompt v1", encoding="utf-8")
            query_prompt = root / "query.md"
            query_prompt.write_text("query guide v1", encoding="utf-8")
            user_prompts = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts,
                [
                    {"prompt_id": "p1", "text": "medical finance billing work"},
                    {"prompt_id": "p2", "text": "bad malformed request"},
                ],
            )
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=3,
                seed=2,
                preprocess_prompt=preprocess_prompt,
            )
            sample_client = FakeTestSampleModelClient()
            preprocess_test_sample(config, "sample_a", model_client=sample_client)
            build_test_sample_index(config, "sample_a", model_client=sample_client)
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts,
                query_prompt_path=query_prompt,
            )
            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())

            with self.assertRaises(CandidateSearchError) as ctx:
                run_retrieval_trial(
                    config,
                    trial_id="trial_a",
                    sample_id="sample_a",
                    user_prompt_set_id="set_a",
                    model_client=sample_client,
                )
            self.assertEqual(ctx.exception.code, "USER_PROMPT_SET_NOT_READY")

            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient(fixed=True))
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"
            query_snapshot = set_dir / "prompt_snapshot" / "query.md"
            query_snapshot.write_text("changed query guide", encoding="utf-8")
            with self.assertRaises(CandidateSearchError) as ctx:
                run_retrieval_trial(
                    config,
                    trial_id="stale_trial",
                    sample_id="sample_a",
                    user_prompt_set_id="set_a",
                    model_client=sample_client,
                )
            self.assertEqual(ctx.exception.code, "USER_PROMPT_SET_NOT_READY")
            query_snapshot.write_text("query guide v1", encoding="utf-8")

            sample_dir = root / "test" / "data" / "samples" / "sample_a"
            sample_metadata_path = sample_dir / "sample.json"
            sample_metadata = sample_metadata_path.read_bytes()
            sample_metadata_path.unlink()
            with self.assertRaises(CandidateSearchError) as ctx:
                run_retrieval_trial(
                    config,
                    trial_id="broken_trial",
                    sample_id="sample_a",
                    user_prompt_set_id="set_a",
                    model_client=sample_client,
                )
            self.assertEqual(ctx.exception.code, "RETRIEVAL_TRIAL_INPUT_MISSING")
            trial_root = root / "test" / "data" / "retrieval_trials"
            self.assertFalse((trial_root / "broken_trial").exists())
            self.assertEqual(list(trial_root.glob(".broken_trial-*")), [])
            sample_metadata_path.write_bytes(sample_metadata)

            trial_client = TransientEmbeddingClient()
            result = run_retrieval_trial(
                config,
                trial_id="trial_a",
                sample_id="sample_a",
                user_prompt_set_id="set_a",
                model_client=trial_client,
            )

            self.assertEqual(result["trial_status"], "complete")
            self.assertEqual(result["search_count"], 2)
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["coverage"], {"completed": 2, "total": 2})
            self.assertEqual(trial_client.calls, 3)
            trial_dir = root / "test" / "data" / "retrieval_trials" / "trial_a"
            search_results = _read_jsonl(trial_dir / "search_results.jsonl")
            self.assertEqual({item["prompt_id"] for item in search_results}, {"p1", "p2"})
            self.assertIn("results", search_results[0]["search_result"])
            self.assertIn("query_plan", search_results[0])
            self.assertEqual(search_results[0]["options"], {"top_k": 10})
            self.assertIn("query_vectors", search_results[0])
            self.assertFalse((trial_dir / "retrieval_errors.jsonl").exists())

            sample_snapshot = trial_dir / "input_snapshot" / "test_sample"
            prompt_set_snapshot = trial_dir / "input_snapshot" / "user_prompt_set"
            expected_sample_files = {
                "sample.json",
                "sample_index.json",
                "raw_profiles.jsonl",
                "preprocessed_profiles.jsonl",
                "embeddings.jsonl",
                "prompt_snapshot/preprosess.md",
            }
            expected_prompt_set_files = {
                "prompt_set.json",
                "user_prompts.jsonl",
                "generated_query_plans.jsonl",
                "tool_schema.json",
                "prompt_snapshot/query.md",
            }
            self.assertEqual(
                {
                    path.relative_to(sample_snapshot).as_posix()
                    for path in sample_snapshot.rglob("*")
                    if path.is_file()
                },
                expected_sample_files,
            )
            self.assertEqual(
                {
                    path.relative_to(prompt_set_snapshot).as_posix()
                    for path in prompt_set_snapshot.rglob("*")
                    if path.is_file()
                },
                expected_prompt_set_files,
            )
            self.assertEqual(len(result["test_sample_snapshot_hash"]), 64)
            self.assertEqual(len(result["user_prompt_set_snapshot_hash"]), 64)
            self.assertIn("retrieval_version", result)
            self.assertEqual(
                set(result["input_files"]),
                {"test_sample", "user_prompt_set"},
            )
            self.assertEqual(
                set(result["input_files"]["test_sample"]),
                expected_sample_files,
            )
            self.assertTrue((trial_dir / "trial.json").is_file())
            self.assertFalse((trial_dir / "status.json").exists())

            first_result = search_results[0]
            replayed = search_candidates(
                config,
                first_result["query_plan"],
                first_result["options"],
                model_client=ForbiddenEmbeddingClient(),
                workspace=BuildWorkspace(
                    raw_profiles_path=sample_snapshot / "raw_profiles.jsonl",
                    processed_dir=sample_snapshot,
                    preprocess_prompt_path=(
                        sample_snapshot / "prompt_snapshot" / "preprosess.md"
                    ),
                ),
                query_vectors=first_result["query_vectors"],
            )
            self.assertEqual(replayed, first_result["search_result"])

            frozen_raw = (sample_snapshot / "raw_profiles.jsonl").read_bytes()
            frozen_mappings = (
                prompt_set_snapshot / "generated_query_plans.jsonl"
            ).read_bytes()
            (root / "test" / "data" / "samples" / "sample_a" / "raw_profiles.jsonl").write_text(
                "changed\n",
                encoding="utf-8",
            )
            (
                root
                / "test"
                / "data"
                / "user_prompt_sets"
                / "set_a"
                / "generated_query_plans.jsonl"
            ).write_text("changed\n", encoding="utf-8")
            self.assertEqual(
                (sample_snapshot / "raw_profiles.jsonl").read_bytes(),
                frozen_raw,
            )
            self.assertEqual(
                (prompt_set_snapshot / "generated_query_plans.jsonl").read_bytes(),
                frozen_mappings,
            )


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


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class ForbiddenEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("offline replay must not call the embedding model")


class APIConnectionError(Exception):
    pass


class TransientEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            raise APIConnectionError("temporary connection failure")
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


if __name__ == "__main__":
    unittest.main()
