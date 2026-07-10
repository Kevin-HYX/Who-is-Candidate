import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from src.evaluation import (
    create_test_sample,
    create_user_prompt_set,
    map_user_prompt_set,
)
from src.main import main
from src.schemas import load_config


class FakeQueryModelClient:
    def generate_query_plan(self, query_guide: str, tool_schema: dict, user_prompt: str) -> dict:
        return {
            "query_plan": {
                "hard_constraints": [],
                "weighted_soft_preferences": [
                    {
                        "dimension": "domain_search_text",
                        "text": user_prompt,
                        "weight": 1.0,
                    }
                ],
            },
            "options": {"top_k": 10},
        }


class EvaluationBrowseCliTests(unittest.TestCase):
    def test_sample_browse_lists_pages_missing_artifacts_and_combined_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            prompt_path = root / "preprosess.md"
            prompt_path.write_text("preprocess prompt", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=3,
                seed=1,
                preprocess_prompt=prompt_path,
            )
            create_test_sample(
                config,
                sample_id="sample_b",
                sample_size=1,
                seed=2,
                preprocess_prompt=prompt_path,
            )
            _update_json(root / "test" / "data" / "samples" / "sample_a" / "sample.json", {"created_at": "2026-01-01T00:00:00+00:00"})
            _update_json(root / "test" / "data" / "samples" / "sample_b" / "sample.json", {"created_at": "2026-01-02T00:00:00+00:00"})

            listed = _run_cli_json(
                "test-sample-list",
                "--config",
                str(config_path),
                "--json",
            )
            self.assertEqual(listed["object_type"], "test_sample")
            self.assertEqual([item["id"] for item in listed["items"]], ["sample_b", "sample_a"])

            raw_page = _run_cli_json(
                "test-sample-read-raw",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--offset",
                "1",
                "--limit",
                "2",
                "--json",
            )
            self.assertEqual(raw_page["artifact"], "raw_profiles")
            self.assertEqual(raw_page["artifact_status"], "available")
            self.assertEqual(raw_page["total_count"], 3)
            self.assertEqual(raw_page["returned_count"], 2)

            missing_preprocessed = _run_cli_json(
                "test-sample-read-preprocessed",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--json",
            )
            self.assertEqual(missing_preprocessed["artifact_status"], "missing")
            self.assertEqual(missing_preprocessed["items"], [])

            sample_dir = root / "test" / "data" / "samples" / "sample_a"
            _write_jsonl(sample_dir / "preprocess_errors.jsonl", [{"user_id": 1, "message": "bad preprocess"}])
            _write_jsonl(sample_dir / "index_errors.jsonl", [{"user_id": 2, "message": "bad index"}])
            errors = _run_cli_json(
                "test-sample-read-errors",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--json",
            )
            self.assertEqual(errors["total_count"], 2)
            self.assertEqual(
                [item["error_source"] for item in errors["items"]],
                ["preprocess", "index"],
            )

    def test_user_prompt_set_browse_reads_prompts_mappings_and_missing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            query_prompt = root / "query.md"
            query_prompt.write_text("query prompt", encoding="utf-8")
            user_prompts = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts,
                [
                    {"prompt_id": "p1", "text": "medical finance billing"},
                    {"prompt_id": "p2", "text": "finance systems implementation"},
                ],
            )
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts,
                query_prompt_path=query_prompt,
            )

            listed = _run_cli_json(
                "user-prompt-set-list",
                "--config",
                str(config_path),
                "--json",
            )
            self.assertEqual(listed["object_type"], "user_prompt_set")
            self.assertEqual(listed["items"][0]["id"], "set_a")

            prompts_page = _run_cli_json(
                "user-prompt-set-read-prompts",
                "--config",
                str(config_path),
                "--set-id",
                "set_a",
                "--limit",
                "1",
                "--json",
            )
            self.assertEqual(prompts_page["artifact"], "user_prompts")
            self.assertEqual(prompts_page["total_count"], 2)
            self.assertEqual(prompts_page["returned_count"], 1)

            missing_mappings = _run_cli_json(
                "user-prompt-set-read-mappings",
                "--config",
                str(config_path),
                "--set-id",
                "set_a",
                "--json",
            )
            self.assertEqual(missing_mappings["artifact_status"], "missing")

            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())
            mappings = _run_cli_json(
                "user-prompt-set-read-mappings",
                "--config",
                str(config_path),
                "--set-id",
                "set_a",
                "--json",
            )
            self.assertEqual(mappings["artifact_status"], "available")
            self.assertEqual(mappings["total_count"], 2)

            errors = _run_cli_json(
                "user-prompt-set-read-errors",
                "--config",
                str(config_path),
                "--set-id",
                "set_a",
                "--json",
            )
            self.assertEqual(errors["artifact_status"], "missing")

    def test_retrieval_trial_browse_reads_results_and_missing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            trial_dir = root / "test" / "data" / "retrieval_trials" / "trial_a"
            trial_dir.mkdir(parents=True)
            (trial_dir / "trial.json").write_text(
                json.dumps(
                    {
                        "trial_id": "trial_a",
                        "expected_search_count": 2,
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                trial_dir / "search_results.jsonl",
                [
                    {"prompt_id": "p1", "search_result": {"results": []}},
                    {"prompt_id": "p2", "search_result": {"results": []}},
                ],
            )

            listed = _run_cli_json(
                "retrieval-trial-list",
                "--config",
                str(config_path),
                "--json",
            )
            self.assertEqual(listed["object_type"], "retrieval_trial")
            self.assertEqual(listed["items"][0]["id"], "trial_a")

            results = _run_cli_json(
                "retrieval-trial-read-results",
                "--config",
                str(config_path),
                "--trial-id",
                "trial_a",
                "--offset",
                "1",
                "--limit",
                "1",
                "--json",
            )
            self.assertEqual(results["artifact"], "search_results")
            self.assertEqual(results["total_count"], 2)
            self.assertEqual(results["items"][0]["prompt_id"], "p2")

            errors = _run_cli_json(
                "retrieval-trial-read-errors",
                "--config",
                str(config_path),
                "--trial-id",
                "trial_a",
                "--json",
            )
            self.assertEqual(errors["artifact_status"], "missing")

    def test_browse_rejects_invalid_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            prompt_path = root / "preprosess.md"
            prompt_path.write_text("preprocess prompt", encoding="utf-8")
            create_test_sample(
                config,
                sample_id="sample_a",
                sample_size=1,
                seed=1,
                preprocess_prompt=prompt_path,
            )
            code, output = _run_cli_capture(
                "test-sample-read-raw",
                "--config",
                str(config_path),
                "--sample-id",
                "sample_a",
                "--limit",
                "201",
                "--json",
            )

            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)["error"]["code"], "INVALID_BROWSE_PAGE")


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


def _run_cli_json(*args: str) -> dict:
    code, output = _run_cli_capture(*args)
    if code != 0:
        raise AssertionError(output)
    return json.loads(output)


def _run_cli_capture(*args: str) -> tuple[int, str]:
    stdout = StringIO()
    with redirect_stdout(stdout):
        code = main(list(args))
    return code, stdout.getvalue()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _update_json(path: Path, updates: dict) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(updates)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
