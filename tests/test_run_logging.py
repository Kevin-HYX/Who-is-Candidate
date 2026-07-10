import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.evaluation import (
    build_test_sample,
    build_test_sample_index,
    create_test_sample,
    create_user_prompt_set,
    map_user_prompt_set,
    preprocess_test_sample,
    run_retrieval_trial,
)
from src.main import main
from src.run_log import AttemptFailure, RunEventWriter
from src.schemas import CandidateSearchError, load_config
from tests.test_test_sample_cli import FakeTestSampleModelClient
from tests.test_user_prompt_set import FakeQueryModelClient, InterruptingQueryModelClient


class PersistedBeforeStream(StringIO):
    def __init__(self, events_path: Path) -> None:
        super().__init__()
        self.events_path = events_path

    def write(self, value: str) -> int:
        if value.endswith("\n") and value.strip():
            persisted = self.events_path.read_text(encoding="utf-8").splitlines()
            if not persisted or persisted[-1] != value.strip():
                raise AssertionError("event must be flushed before streaming")
        return super().write(value)


class InvalidThenValidPreprocessClient(FakeTestSampleModelClient):
    def preprocess_profile(self, prompt: str, raw_profile: dict) -> dict:
        output = super().preprocess_profile(prompt, raw_profile)
        if self.preprocess_calls == 1:
            return {"invalid": "raw model output"}
        return output


class APIConnectionError(Exception):
    pass


class PersistentEmbeddingFailureClient:
    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        raise APIConnectionError("query embedding unavailable")


class RunLoggingTests(unittest.TestCase):
    def test_writer_assigns_one_global_sequence_and_persists_before_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            owner_dir = Path(tmp) / "sample_a"
            events_path = owner_dir / "runs" / "run_test" / "events.jsonl"
            stream = PersistedBeforeStream(events_path)
            writer = RunEventWriter.create(
                owner_dir,
                owner_type="test_sample",
                owner_id="sample_a",
                command="test-sample-preprocess",
                phases=["preprocess"],
                stream=stream,
                run_id="run_test",
            )
            writer.emit("run_started")
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(
                    executor.map(
                        lambda item: writer.emit(
                            "item_skipped",
                            phase="preprocess",
                            user_id=item,
                        ),
                        range(20),
                    )
                )
            writer.emit("run_completed", summary={"skipped_count": 20})

            persisted = _read_jsonl(events_path)
            streamed = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(streamed, persisted)
            self.assertEqual([event["seq"] for event in persisted], list(range(1, 23)))
            self.assertEqual(persisted[0]["event"], "run_started")
            self.assertEqual(persisted[-1]["event"], "run_completed")
            self.assertTrue((events_path.parent / "run.json").is_file())
            self.assertTrue((events_path.parent / "attempts").is_dir())

    def test_preprocess_retry_keeps_failed_attempt_raw_output_and_cache_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(_write_config(root))
            _create_sample(config, root, sample_size=1)
            stream = StringIO()
            client = InvalidThenValidPreprocessClient()

            result = preprocess_test_sample(
                config,
                "sample_a",
                concurrency=1,
                model_client=client,
                event_stream=stream,
            )

            self.assertEqual(result["processed_count"], 1)
            run_dir = _only_run_dir(_sample_dir(root))
            events = _read_jsonl(run_dir / "events.jsonl")
            self.assertEqual(
                [event["event"] for event in events if event["event"].startswith("attempt_")],
                ["attempt_started", "attempt_failed", "attempt_started", "attempt_succeeded"],
            )
            failure = next(event for event in events if event["event"] == "attempt_failed")
            self.assertEqual(failure["stage"], "schema_validation")
            self.assertEqual(failure["attempt"], 1)
            self.assertEqual(failure["max_attempts"], 3)
            self.assertTrue(failure["artifact_path"].startswith("attempts/"))
            self.assertEqual(
                json.loads((run_dir / failure["artifact_path"]).read_text(encoding="utf-8")),
                {"invalid": "raw model output"},
            )
            self.assertEqual(
                [json.loads(line) for line in stream.getvalue().splitlines()],
                events,
            )

            preprocess_test_sample(
                config,
                "sample_a",
                concurrency=1,
                model_client=client,
            )
            run_dirs = sorted((_sample_dir(root) / "runs").iterdir())
            self.assertEqual(len(run_dirs), 2)
            skipped_run = next(
                path
                for path in run_dirs
                if any(event["event"] == "item_skipped" for event in _read_jsonl(path / "events.jsonl"))
            )
            skipped_events = _read_jsonl(skipped_run / "events.jsonl")
            self.assertFalse(any(event["event"] == "attempt_started" for event in skipped_events))

    def test_mapping_interrupt_is_retained_as_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(_write_config(root))
            _create_prompt_set(config, root)

            with self.assertRaises(KeyboardInterrupt):
                map_user_prompt_set(
                    config,
                    "set_a",
                    model_client=InterruptingQueryModelClient(),
                    event_stream=StringIO(),
                )

            run_dir = _only_run_dir(_prompt_set_dir(root))
            events = _read_jsonl(run_dir / "events.jsonl")
            self.assertEqual(events[-1]["event"], "run_interrupted")
            self.assertEqual(events[-1]["seq"], len(events))

    def test_combined_build_uses_one_run_with_two_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(_write_config(root))
            _create_sample(config, root, sample_size=2)

            build_test_sample(
                config,
                "sample_a",
                concurrency=1,
                model_client=FakeTestSampleModelClient(),
            )

            run_dir = _only_run_dir(_sample_dir(root))
            metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            events = _read_jsonl(run_dir / "events.jsonl")
            self.assertEqual(metadata["phases"], ["preprocess", "build_index"])
            self.assertEqual(
                [event["phase"] for event in events if event["event"] == "phase_started"],
                ["preprocess", "build_index"],
            )
            self.assertEqual(events[-1]["event"], "run_completed")

    def test_cli_reads_owner_scoped_runs_events_and_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            _create_sample(config, root, sample_size=1)
            owner_dir = _sample_dir(root)
            writer = RunEventWriter.create(
                owner_dir,
                owner_type="test_sample",
                owner_id="sample_a",
                command="test-sample-preprocess",
                phases=["preprocess"],
                run_id="run_debug",
            )
            writer.emit("run_started")
            writer.emit("phase_started", phase="preprocess")
            writer.emit("attempt_started", phase="preprocess", user_id=1, attempt=1, max_attempts=3)
            failure = AttemptFailure(
                ValueError("invalid field"),
                stage="schema_validation",
                error_code="PREPROCESS_OUTPUT_INVALID",
                field_path="hard_fields",
                raw_output='{"hard_fields":',
            )
            writer.emit_attempt_failed(
                failure,
                phase="preprocess",
                item={"user_id": 1, "source_row_index": 0},
                attempt=1,
                max_attempts=3,
            )
            writer.emit("run_failed", stage="schema_validation", message="invalid field")
            events = _read_jsonl(writer.events_path)
            artifact_path = next(
                event["artifact_path"]
                for event in events
                if event["event"] == "attempt_failed"
            )

            listed = _run_cli_json(
                "run-list",
                "--config",
                str(config_path),
                "--owner-type",
                "test-sample",
                "--owner-id",
                "sample_a",
                "--json",
            )
            self.assertEqual(listed["total_count"], 1)
            shown = _run_cli_json(
                "run-show",
                "--config",
                str(config_path),
                "--owner-type",
                "test-sample",
                "--owner-id",
                "sample_a",
                "--run-id",
                "run_debug",
                "--json",
            )
            self.assertEqual(shown["terminal_event"]["event"], "run_failed")
            page = _run_cli_json(
                "run-events",
                "--config",
                str(config_path),
                "--owner-type",
                "test-sample",
                "--owner-id",
                "sample_a",
                "--run-id",
                "run_debug",
                "--offset",
                "1",
                "--limit",
                "2",
                "--json",
            )
            self.assertEqual(page["total_count"], len(events))
            self.assertEqual(page["returned_count"], 2)
            artifact = _run_cli_json(
                "run-attempt",
                "--config",
                str(config_path),
                "--owner-type",
                "test-sample",
                "--owner-id",
                "sample_a",
                "--run-id",
                "run_debug",
                "--artifact",
                artifact_path,
                "--json",
            )
            self.assertEqual(artifact["content"], '{"hard_fields":')

    def test_generation_cli_stdout_is_exact_persisted_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            config = load_config(config_path)
            _create_sample(config, root, sample_size=1)
            stdout = StringIO()
            stderr = StringIO()
            with patch(
                "src.preprocess.OpenAICompatibleModelClient",
                return_value=FakeTestSampleModelClient(),
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "test-sample-preprocess",
                        "--config",
                        str(config_path),
                        "--sample-id",
                        "sample_a",
                        "--concurrency",
                        "1",
                    ]
                )

            self.assertEqual(code, 0, stderr.getvalue())
            streamed = [json.loads(line) for line in stdout.getvalue().splitlines()]
            run_dir = _only_run_dir(_sample_dir(root))
            self.assertEqual(streamed, _read_jsonl(run_dir / "events.jsonl"))
            self.assertEqual(streamed[0]["event"], "run_started")
            self.assertEqual(streamed[-1]["event"], "run_completed")

    def test_trial_prerequisite_failure_does_not_consume_id_but_execution_failure_does(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(_write_config(root))
            _create_sample(config, root, sample_size=1)
            sample_client = FakeTestSampleModelClient()
            preprocess_test_sample(config, "sample_a", model_client=sample_client)
            build_test_sample_index(config, "sample_a", model_client=sample_client)
            _create_prompt_set(config, root)
            trial_root = root / "test" / "data" / "retrieval_trials"

            with self.assertRaises(CandidateSearchError):
                run_retrieval_trial(
                    config,
                    trial_id="trial_a",
                    sample_id="sample_a",
                    user_prompt_set_id="set_a",
                    model_client=PersistentEmbeddingFailureClient(),
                )
            self.assertFalse((trial_root / "trial_a").exists())

            map_user_prompt_set(config, "set_a", model_client=FakeQueryModelClient())
            client = PersistentEmbeddingFailureClient()
            result = run_retrieval_trial(
                config,
                trial_id="trial_a",
                sample_id="sample_a",
                user_prompt_set_id="set_a",
                model_client=client,
            )
            self.assertEqual(result["trial_status"], "partial")
            trial_dir = trial_root / "trial_a"
            self.assertTrue((trial_dir / "trial.json").is_file())
            run_dir = _only_run_dir(trial_dir)
            events = _read_jsonl(run_dir / "events.jsonl")
            self.assertEqual(client.calls, 3)
            self.assertEqual(
                [event["event"] for event in events if event["event"] == "attempt_failed"],
                ["attempt_failed", "attempt_failed", "attempt_failed"],
            )
            self.assertEqual(events[-1]["event"], "run_completed")
            with self.assertRaises(CandidateSearchError) as ctx:
                run_retrieval_trial(
                    config,
                    trial_id="trial_a",
                    sample_id="sample_a",
                    user_prompt_set_id="set_a",
                    model_client=client,
                )
            self.assertEqual(ctx.exception.code, "RETRIEVAL_TRIAL_ALREADY_EXISTS")


def _create_sample(config: object, root: Path, *, sample_size: int) -> None:
    prompt = root / "preprosess.md"
    prompt.write_text("preprocess prompt", encoding="utf-8")
    create_test_sample(
        config,
        sample_id="sample_a",
        sample_size=sample_size,
        seed=1,
        preprocess_prompt=prompt,
    )


def _create_prompt_set(config: object, root: Path) -> None:
    prompt = root / "query.md"
    prompt.write_text("query prompt", encoding="utf-8")
    user_prompts = root / "user_prompts.jsonl"
    _write_jsonl(
        user_prompts,
        [{"prompt_id": "p1", "text": "medical finance billing work"}],
    )
    create_user_prompt_set(
        config,
        set_id="set_a",
        user_prompts_path=user_prompts,
        query_prompt_path=prompt,
    )


def _write_config(root: Path) -> Path:
    raw_path = root / "raw.jsonl"
    _write_jsonl(
        raw_path,
        [
            {"user_id": index + 1, "headline": f"Candidate {index + 1}"}
            for index in range(3)
        ],
    )
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
processed_dir = "{(root / 'processed').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _sample_dir(root: Path) -> Path:
    return root / "test" / "data" / "samples" / "sample_a"


def _prompt_set_dir(root: Path) -> Path:
    return root / "test" / "data" / "user_prompt_sets" / "set_a"


def _only_run_dir(owner_dir: Path) -> Path:
    runs = [path for path in (owner_dir / "runs").iterdir() if path.is_dir()]
    if len(runs) != 1:
        raise AssertionError(f"expected one run, got {len(runs)}")
    return runs[0]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _run_cli_json(*args: str) -> dict:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(list(args))
    if code != 0:
        raise AssertionError(stderr.getvalue() or stdout.getvalue())
    return json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
