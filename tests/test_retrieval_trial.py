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
from src.schemas import CandidateSearchError, load_config
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
            result = run_retrieval_trial(
                config,
                trial_id="trial_a",
                sample_id="sample_a",
                user_prompt_set_id="set_a",
                model_client=sample_client,
            )

            self.assertEqual(result["trial_status"], "complete")
            self.assertEqual(result["search_count"], 2)
            self.assertEqual(result["error_count"], 0)
            trial_dir = root / "test" / "data" / "retrieval_trials" / "trial_a"
            search_results = _read_jsonl(trial_dir / "search_results.jsonl")
            self.assertEqual({item["prompt_id"] for item in search_results}, {"p1", "p2"})
            self.assertIn("results", search_results[0]["search_result"])
            self.assertFalse((trial_dir / "retrieval_errors.jsonl").exists())


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


if __name__ == "__main__":
    unittest.main()
