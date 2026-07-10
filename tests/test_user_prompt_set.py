import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation import (
    create_user_prompt_set,
    map_user_prompt_set,
    read_user_prompt_set,
)
from src.schemas import CandidateSearchError, load_config


class FakeQueryModelClient:
    def __init__(self, fixed: bool = False) -> None:
        self.fixed = fixed
        self.calls: list[str] = []

    def generate_query_plan(self, query_guide: str, tool_schema: dict, user_prompt: str) -> dict:
        self.calls.append(user_prompt)
        if "bad" in user_prompt and not self.fixed:
            return {"not_query_plan": True}
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


class InterruptingQueryModelClient:
    def generate_query_plan(self, query_guide: str, tool_schema: dict, user_prompt: str) -> dict:
        raise KeyboardInterrupt("mapping interrupted")


class APIConnectionError(Exception):
    pass


class TransientQueryModelClient:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.calls = 0

    def generate_query_plan(self, query_guide: str, tool_schema: dict, user_prompt: str) -> dict:
        self.calls += 1
        if self.always_fail or self.calls == 1:
            raise APIConnectionError("temporary connection failure")
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


class UserPromptSetTests(unittest.TestCase):
    def test_mapping_retries_transport_errors_but_reports_persistent_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(_write_config(root))
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [{"prompt_id": "p1", "text": "medical finance billing work"}],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )

            transient = TransientQueryModelClient()
            recovered = map_user_prompt_set(config, "set_a", model_client=transient)

            self.assertEqual(recovered["mapping_status"], "ready")
            self.assertEqual(transient.calls, 2)

            persistent = TransientQueryModelClient(always_fail=True)
            failed = map_user_prompt_set(
                config,
                "set_a",
                model_client=persistent,
                discard_cache=True,
            )
            errors = _read_jsonl(
                root
                / "test"
                / "data"
                / "user_prompt_sets"
                / "set_a"
                / "mapping_errors.jsonl"
            )
            self.assertEqual(failed["mapping_status"], "partial")
            self.assertEqual(persistent.calls, 3)
            self.assertEqual(errors[0]["code"], "QUERY_MODEL_REQUEST_FAILED")

    def test_mapping_caches_successes_and_exposes_partial_errors_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [
                    {"prompt_id": "p1", "text": "medical finance billing work"},
                    {"prompt_id": "p2", "text": "bad malformed request"},
                ],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )

            first_client = FakeQueryModelClient()
            first = map_user_prompt_set(config, "set_a", model_client=first_client)
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"
            first_errors = _read_jsonl(set_dir / "mapping_errors.jsonl")
            self.assertEqual(first_errors[0]["code"], "INVALID_QUERY_SCHEMA_OUTPUT")
            second = map_user_prompt_set(config, "set_a", model_client=first_client)
            fixed_client = FakeQueryModelClient(fixed=True)
            fixed = map_user_prompt_set(config, "set_a", model_client=fixed_client)
            forced = map_user_prompt_set(
                config,
                "set_a",
                model_client=fixed_client,
                discard_cache=True,
            )

            self.assertEqual(first["mapping_status"], "partial")
            self.assertEqual(first["mapped_count"], 1)
            self.assertEqual(first["failed_count"], 1)
            self.assertEqual(second["skipped_count"], 1)
            self.assertEqual(second["failed_count"], 1)
            self.assertEqual(first_client.calls, ["medical finance billing work", "bad malformed request", "bad malformed request"])
            self.assertEqual(fixed["mapping_status"], "ready")
            self.assertEqual(fixed["mapped_count"], 2)
            self.assertEqual(fixed["failed_count"], 0)
            self.assertEqual(fixed["skipped_count"], 1)
            self.assertEqual(forced["mapped_count"], 2)
            self.assertEqual(forced["skipped_count"], 0)

            generated = _read_jsonl(set_dir / "generated_query_plans.jsonl")
            self.assertEqual({item["prompt_id"] for item in generated}, {"p1", "p2"})
            self.assertEqual((set_dir / "prompt_snapshot" / "query.md").read_text(encoding="utf-8"), "query guide v1")
            self.assertFalse((set_dir / "mapping_errors.jsonl").exists())
            status = read_user_prompt_set(config, "set_a")
            self.assertEqual(status["mapping_status"], "ready")
            self.assertNotIn("generated_count", status)
            self.assertNotIn("skipped_count", status)
            self.assertFalse((set_dir / "status.json").exists())
            prompt_set = json.loads(
                (set_dir / "prompt_set.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("mapping_status", prompt_set)
            self.assertNotIn("mapped_count", prompt_set)

    def test_invalid_cached_mapping_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [{"prompt_id": "p1", "text": "medical finance billing work"}],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )
            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"
            cached = _read_jsonl(set_dir / "generated_query_plans.jsonl")
            cached[0]["options"]["top_k"] = 76
            _write_jsonl(set_dir / "generated_query_plans.jsonl", cached)
            client = FakeQueryModelClient()

            result = map_user_prompt_set(config, "set_a", model_client=client)

            self.assertEqual(result["generated_count"], 1)
            self.assertEqual(result["skipped_count"], 0)
            self.assertEqual(client.calls, ["medical finance billing work"])

    def test_mapping_rejects_stale_tool_schema_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [{"prompt_id": "p1", "text": "medical finance billing work"}],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"
            (set_dir / "tool_schema.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(CandidateSearchError) as ctx:
                map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())

            self.assertEqual(ctx.exception.code, "USER_PROMPT_SET_SCHEMA_STALE")

    def test_discarded_mapping_is_not_left_ready_when_generation_is_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [{"prompt_id": "p1", "text": "medical finance billing work"}],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )
            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"

            with self.assertRaises(KeyboardInterrupt):
                map_user_prompt_set(
                    config,
                    "set_a",
                    model_client=InterruptingQueryModelClient(),
                    discard_cache=True,
                )

            status = read_user_prompt_set(config, "set_a")
            self.assertNotEqual(status["mapping_status"], "ready")
            self.assertEqual(
                (set_dir / "generated_query_plans.jsonl").read_text(encoding="utf-8"),
                "",
            )

    def test_read_marks_changed_mapping_prerequisite_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            user_prompts_path = root / "user_prompts.jsonl"
            _write_jsonl(
                user_prompts_path,
                [{"prompt_id": "p1", "text": "medical finance billing work"}],
            )
            query_prompt_path = root / "query.md"
            query_prompt_path.write_text("query guide v1", encoding="utf-8")
            create_user_prompt_set(
                config,
                set_id="set_a",
                user_prompts_path=user_prompts_path,
                query_prompt_path=query_prompt_path,
            )
            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())
            set_dir = root / "test" / "data" / "user_prompt_sets" / "set_a"
            (set_dir / "prompt_snapshot" / "query.md").write_text(
                "changed query guide",
                encoding="utf-8",
            )

            status = read_user_prompt_set(config, "set_a")

            self.assertEqual(status["mapping_status"], "stale")
            self.assertEqual(
                status["readiness_error"]["code"],
                "USER_PROMPT_SET_SCHEMA_STALE",
            )


def _write_config(root: Path) -> Path:
    raw_path = root / "raw.jsonl"
    raw_path.write_text(json.dumps({"user_id": 1}) + "\n", encoding="utf-8")
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
