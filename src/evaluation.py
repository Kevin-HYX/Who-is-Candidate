from __future__ import annotations

import json
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_CONCURRENCY,
    EMBEDDINGS_FILE,
    INDEX_ERRORS_FILE,
    PREPROCESS_ERRORS_FILE,
    PROCESSED_PROFILES_FILE,
)
from .preprocess import preprocess_profiles
from .retrieval import (
    OpenAICompatibleModelClient,
    build_index,
    canonical_hash,
    load_raw_dataset,
    search_candidates,
)
from .schemas import (
    BuildWorkspace,
    CandidateSearchError,
    search_tool_schema,
    validate_search_request,
)

BROWSE_DEFAULT_LIMIT = 20
BROWSE_MAX_LIMIT = 200


def create_test_sample(
    config: Any,
    *,
    sample_id: str,
    sample_size: int,
    seed: int | None,
    preprocess_prompt: Path,
) -> dict[str, Any]:
    sample_dir = _test_sample_dir(config, sample_id)
    if sample_dir.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_ALREADY_EXISTS",
            "test sample already exists",
            sample_id=sample_id,
        )
    prompt_path = _resolve_prompt_path(preprocess_prompt)
    sample_dir.mkdir(parents=True)
    (sample_dir / "prompt_snapshot").mkdir()
    shutil.copyfile(prompt_path, sample_dir / "prompt_snapshot" / "preprosess.md")
    return _write_test_sample_cohort(
        config,
        sample_dir,
        sample_id=sample_id,
        sample_size=sample_size,
        seed=seed,
    )


def resample_test_sample(
    config: Any,
    *,
    sample_id: str,
    sample_size: int,
    seed: int | None,
) -> dict[str, Any]:
    sample_dir = _test_sample_dir(config, sample_id)
    if not sample_dir.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_FOUND",
            "test sample does not exist",
            sample_id=sample_id,
        )
    if not (sample_dir / "prompt_snapshot" / "preprosess.md").exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_PROMPT_NOT_FOUND",
            "test sample preprocess prompt snapshot is missing",
            sample_id=sample_id,
        )
    _discard_test_sample_build_artifacts(sample_dir)
    return _write_test_sample_cohort(
        config,
        sample_dir,
        sample_id=sample_id,
        sample_size=sample_size,
        seed=seed,
    )


def read_test_sample(config: Any, sample_id: str) -> dict[str, Any]:
    sample_dir = _test_sample_dir(config, sample_id)
    metadata_path = sample_dir / "sample.json"
    if not metadata_path.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_FOUND",
            "test sample does not exist",
            sample_id=sample_id,
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    status = _read_json_file_if_exists(sample_dir / "status.json")
    if status is not None:
        metadata["status"] = status
        metadata["updated_at"] = status.get("updated_at", metadata.get("updated_at"))
    return metadata


def list_test_samples(config: Any) -> dict[str, Any]:
    root = _evaluation_data_dir(config) / "samples"
    items = []
    for sample_dir in _object_dirs(root):
        metadata = _read_json_file_if_exists(sample_dir / "sample.json")
        status = _read_json_file_if_exists(sample_dir / "status.json") or metadata.get("status", {})
        item = {
            "id": metadata.get("sample_id", sample_dir.name),
            "status": status,
            "updated_at": status.get("updated_at") or metadata.get("updated_at"),
        }
        for key in ("sample_size", "seed", "total_raw_candidates"):
            if key in metadata:
                item[key] = metadata[key]
        items.append(item)
    return _list_envelope("test_sample", items)


def read_test_sample_raw(
    config: Any,
    sample_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    sample_dir = _require_test_sample_dir(config, sample_id)
    return _read_jsonl_artifact_page(
        object_type="test_sample",
        object_id=sample_id,
        artifact="raw_profiles",
        path=sample_dir / "raw_profiles.jsonl",
        offset=offset,
        limit=limit,
    )


def read_test_sample_preprocessed(
    config: Any,
    sample_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    sample_dir = _require_test_sample_dir(config, sample_id)
    return _read_jsonl_artifact_page(
        object_type="test_sample",
        object_id=sample_id,
        artifact="preprocessed_profiles",
        path=sample_dir / PROCESSED_PROFILES_FILE,
        offset=offset,
        limit=limit,
    )


def read_test_sample_errors(
    config: Any,
    sample_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    sample_dir = _require_test_sample_dir(config, sample_id)
    return _read_combined_jsonl_artifact_page(
        object_type="test_sample",
        object_id=sample_id,
        artifact="errors",
        sources=[
            ("preprocess", sample_dir / PREPROCESS_ERRORS_FILE),
            ("index", sample_dir / INDEX_ERRORS_FILE),
        ],
        source_field="error_source",
        offset=offset,
        limit=limit,
    )


def preprocess_test_sample(
    config: Any,
    sample_id: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    sample_dir = _require_test_sample_dir(config, sample_id)
    prompt_path = sample_dir / "prompt_snapshot" / "preprosess.md"
    if not prompt_path.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_PROMPT_NOT_FOUND",
            "test sample preprocess prompt snapshot is missing",
            sample_id=sample_id,
        )
    return preprocess_profiles(
        config,
        workspace=_test_sample_workspace(sample_dir),
        concurrency=concurrency,
        model_client=model_client,
        prompt_path=prompt_path,
        discard_cache=discard_cache,
    )


def build_test_sample_index(
    config: Any,
    sample_id: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    sample_dir = _require_test_sample_dir(config, sample_id)
    return build_index(
        config,
        workspace=_test_sample_workspace(sample_dir),
        concurrency=concurrency,
        model_client=model_client,
        discard_cache=discard_cache,
    )


def build_test_sample(
    config: Any,
    sample_id: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    preprocess_result = preprocess_test_sample(
        config,
        sample_id,
        concurrency=concurrency,
        model_client=model_client,
        discard_cache=discard_cache,
    )
    index_result = build_test_sample_index(
        config,
        sample_id,
        concurrency=concurrency,
        model_client=model_client,
        discard_cache=discard_cache,
    )
    return {
        "preprocess": preprocess_result,
        "build_index": index_result,
    }


def create_user_prompt_set(
    config: Any,
    *,
    set_id: str,
    user_prompts_path: Path,
    query_prompt_path: Path,
) -> dict[str, Any]:
    set_dir = _user_prompt_set_dir(config, set_id)
    if set_dir.exists():
        raise CandidateSearchError(
            "USER_PROMPT_SET_ALREADY_EXISTS",
            "user prompt set already exists",
            set_id=set_id,
        )
    prompts = _load_user_prompts(user_prompts_path)
    query_prompt = _resolve_prompt_path(query_prompt_path)
    set_dir.mkdir(parents=True)
    (set_dir / "prompt_snapshot").mkdir()
    shutil.copyfile(query_prompt, set_dir / "prompt_snapshot" / "query.md")
    _write_json_file(set_dir / "tool_schema.json", search_tool_schema())
    _write_jsonl_file(set_dir / "user_prompts.jsonl", prompts)
    return _write_user_prompt_set_status(
        set_dir,
        set_id=set_id,
        total_prompts=len(prompts),
        mapped_count=0,
        failed_count=0,
        mapping_status="missing",
    )


def read_user_prompt_set(config: Any, set_id: str) -> dict[str, Any]:
    set_dir = _user_prompt_set_dir(config, set_id)
    status_path = set_dir / "status.json"
    if not status_path.exists():
        raise CandidateSearchError(
            "USER_PROMPT_SET_NOT_FOUND",
            "user prompt set does not exist",
            set_id=set_id,
        )
    return json.loads(status_path.read_text(encoding="utf-8"))


def list_user_prompt_sets(config: Any) -> dict[str, Any]:
    root = _evaluation_data_dir(config) / "user_prompt_sets"
    items = []
    for set_dir in _object_dirs(root):
        status = _read_json_file_if_exists(set_dir / "status.json")
        items.append(
            {
                "id": status.get("set_id", set_dir.name),
                "status": status,
                "updated_at": status.get("updated_at"),
            }
        )
    return _list_envelope("user_prompt_set", items)


def read_user_prompt_set_prompts(
    config: Any,
    set_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    set_dir = _require_user_prompt_set_dir(config, set_id)
    return _read_jsonl_artifact_page(
        object_type="user_prompt_set",
        object_id=set_id,
        artifact="user_prompts",
        path=set_dir / "user_prompts.jsonl",
        offset=offset,
        limit=limit,
    )


def read_user_prompt_set_mappings(
    config: Any,
    set_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    set_dir = _require_user_prompt_set_dir(config, set_id)
    return _read_jsonl_artifact_page(
        object_type="user_prompt_set",
        object_id=set_id,
        artifact="generated_query_plans",
        path=set_dir / "generated_query_plans.jsonl",
        offset=offset,
        limit=limit,
    )


def read_user_prompt_set_errors(
    config: Any,
    set_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    set_dir = _require_user_prompt_set_dir(config, set_id)
    return _read_jsonl_artifact_page(
        object_type="user_prompt_set",
        object_id=set_id,
        artifact="mapping_errors",
        path=set_dir / "mapping_errors.jsonl",
        offset=offset,
        limit=limit,
    )


def map_user_prompt_set(
    config: Any,
    set_id: str,
    *,
    model_client: Any | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    set_dir = _require_user_prompt_set_dir(config, set_id)
    user_prompts = _read_jsonl_file(set_dir / "user_prompts.jsonl")
    query_guide = (set_dir / "prompt_snapshot" / "query.md").read_text(encoding="utf-8")
    tool_schema = json.loads((set_dir / "tool_schema.json").read_text(encoding="utf-8"))
    query_guide_hash = canonical_hash(query_guide)
    tool_schema_hash = canonical_hash(tool_schema)
    model_config_hash = canonical_hash(
        {
            "base_url": config.base_url,
            "model": config.preprocess_model,
        }
    )
    existing = {}
    generated_path = set_dir / "generated_query_plans.jsonl"
    if generated_path.exists() and not discard_cache:
        existing = {
            record["prompt_id"]: record
            for record in _read_jsonl_file(generated_path)
        }

    client = model_client or OpenAICompatibleModelClient(config)
    generated = dict(existing)
    errors = []
    skipped_count = 0
    generated_count = 0
    prompt_order = [prompt["prompt_id"] for prompt in user_prompts]

    for prompt in user_prompts:
        prompt_id = prompt["prompt_id"]
        user_prompt_hash = canonical_hash(prompt["text"])
        cached = existing.get(prompt_id)
        if cached and _mapping_cache_matches(
            cached,
            user_prompt_hash=user_prompt_hash,
            query_guide_hash=query_guide_hash,
            tool_schema_hash=tool_schema_hash,
            model_config_hash=model_config_hash,
        ):
            skipped_count += 1
            continue
        try:
            output = client.generate_query_plan(query_guide, tool_schema, prompt["text"])
            if "query_plan" not in output:
                raise CandidateSearchError(
                    "INVALID_QUERY_SCHEMA_OUTPUT",
                    "query generation output must contain query_plan",
                    prompt_id=prompt_id,
                )
            request = validate_search_request(output["query_plan"], output.get("options", {}))
            generated[prompt_id] = {
                "prompt_id": prompt_id,
                "user_prompt": prompt["text"],
                "user_prompt_hash": user_prompt_hash,
                "query_guide_hash": query_guide_hash,
                "tool_schema_hash": tool_schema_hash,
                "model_config_hash": model_config_hash,
                "query_plan": request.query_plan,
                "options": request.options,
            }
            generated_count += 1
        except Exception as exc:  # noqa: BLE001 - persisted for Agent review.
            generated.pop(prompt_id, None)
            errors.append(
                {
                    "prompt_id": prompt_id,
                    "user_prompt_hash": user_prompt_hash,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    ordered_generated = [
        generated[prompt_id]
        for prompt_id in prompt_order
        if prompt_id in generated
    ]
    _write_jsonl_file(generated_path, ordered_generated)
    errors_path = set_dir / "mapping_errors.jsonl"
    if errors:
        _write_jsonl_file(errors_path, errors)
    elif errors_path.exists():
        errors_path.unlink()

    mapped_count = len(ordered_generated)
    failed_count = len(errors)
    mapping_status = "ready" if mapped_count == len(user_prompts) and failed_count == 0 else "partial"
    return _write_user_prompt_set_status(
        set_dir,
        set_id=set_id,
        total_prompts=len(user_prompts),
        mapped_count=mapped_count,
        failed_count=failed_count,
        mapping_status=mapping_status,
        generated_count=generated_count,
        skipped_count=skipped_count,
    )


def run_retrieval_trial(
    config: Any,
    *,
    trial_id: str,
    sample_id: str,
    user_prompt_set_id: str,
    model_client: Any | None = None,
) -> dict[str, Any]:
    sample_dir = _require_ready_test_sample(config, sample_id)
    prompt_set_dir = _require_ready_user_prompt_set(config, user_prompt_set_id)
    trial_dir = _retrieval_trial_dir(config, trial_id)
    if trial_dir.exists():
        raise CandidateSearchError(
            "RETRIEVAL_TRIAL_ALREADY_EXISTS",
            "retrieval trial already exists",
            trial_id=trial_id,
        )
    trial_dir.mkdir(parents=True)
    generated = _read_jsonl_file(prompt_set_dir / "generated_query_plans.jsonl")
    sample_workspace = _test_sample_workspace(sample_dir)
    client = model_client or OpenAICompatibleModelClient(config)
    search_results = []
    errors = []
    for mapping in generated:
        prompt_id = mapping["prompt_id"]
        options = dict(mapping.get("options", {}))
        options["top_k"] = 10
        try:
            result = search_candidates(
                config,
                mapping["query_plan"],
                options,
                model_client=client,
                workspace=sample_workspace,
            )
            search_results.append(
                {
                    "prompt_id": prompt_id,
                    "search_result": result,
                }
            )
        except Exception as exc:  # noqa: BLE001 - persisted for Agent review.
            errors.append(
                {
                    "prompt_id": prompt_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    _write_jsonl_file(trial_dir / "search_results.jsonl", search_results)
    if errors:
        _write_jsonl_file(trial_dir / "retrieval_errors.jsonl", errors)
    status = {
        "trial_id": trial_id,
        "sample_id": sample_id,
        "user_prompt_set_id": user_prompt_set_id,
        "trial_status": "complete" if not errors else "partial",
        "search_count": len(search_results),
        "error_count": len(errors),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _write_json_file(trial_dir / "status.json", status)
    return status


def read_retrieval_trial(config: Any, trial_id: str) -> dict[str, Any]:
    status_path = _retrieval_trial_dir(config, trial_id) / "status.json"
    if not status_path.exists():
        raise CandidateSearchError(
            "RETRIEVAL_TRIAL_NOT_FOUND",
            "retrieval trial does not exist",
            trial_id=trial_id,
        )
    return json.loads(status_path.read_text(encoding="utf-8"))


def list_retrieval_trials(config: Any) -> dict[str, Any]:
    root = _evaluation_data_dir(config) / "retrieval_trials"
    items = []
    for trial_dir in _object_dirs(root):
        status = _read_json_file_if_exists(trial_dir / "status.json")
        items.append(
            {
                "id": status.get("trial_id", trial_dir.name),
                "status": status,
                "updated_at": status.get("updated_at"),
            }
        )
    return _list_envelope("retrieval_trial", items)


def read_retrieval_trial_results(
    config: Any,
    trial_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    trial_dir = _require_retrieval_trial_dir(config, trial_id)
    return _read_jsonl_artifact_page(
        object_type="retrieval_trial",
        object_id=trial_id,
        artifact="search_results",
        path=trial_dir / "search_results.jsonl",
        offset=offset,
        limit=limit,
    )


def read_retrieval_trial_errors(
    config: Any,
    trial_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    trial_dir = _require_retrieval_trial_dir(config, trial_id)
    return _read_jsonl_artifact_page(
        object_type="retrieval_trial",
        object_id=trial_id,
        artifact="retrieval_errors",
        path=trial_dir / "retrieval_errors.jsonl",
        offset=offset,
        limit=limit,
    )


def _require_ready_test_sample(config: Any, sample_id: str) -> Path:
    sample_dir = _require_test_sample_dir(config, sample_id)
    status_path = sample_dir / "status.json"
    if not status_path.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_READY",
            "test sample has not been preprocessed and indexed",
            sample_id=sample_id,
        )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("preprocess_status") != "full" or status.get("index_status") != "full":
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_READY",
            "test sample must have full preprocessing and index coverage",
            sample_id=sample_id,
            status=status,
        )
    return sample_dir


def _require_ready_user_prompt_set(config: Any, set_id: str) -> Path:
    set_dir = _require_user_prompt_set_dir(config, set_id)
    status = json.loads((set_dir / "status.json").read_text(encoding="utf-8"))
    if status.get("mapping_status") != "ready":
        raise CandidateSearchError(
            "USER_PROMPT_SET_NOT_READY",
            "user prompt set mapping must be ready before retrieval trial",
            set_id=set_id,
            status=status,
        )
    return set_dir


def _mapping_cache_matches(
    record: dict[str, Any],
    *,
    user_prompt_hash: str,
    query_guide_hash: str,
    tool_schema_hash: str,
    model_config_hash: str,
) -> bool:
    return (
        record.get("user_prompt_hash") == user_prompt_hash
        and record.get("query_guide_hash") == query_guide_hash
        and record.get("tool_schema_hash") == tool_schema_hash
        and record.get("model_config_hash") == model_config_hash
    )


def _load_user_prompts(path: Path) -> list[dict[str, Any]]:
    prompt_path = path.expanduser()
    if not prompt_path.is_absolute():
        prompt_path = (Path.cwd() / prompt_path).resolve()
    prompts = _read_jsonl_file(prompt_path)
    seen = set()
    normalized = []
    for index, prompt in enumerate(prompts):
        prompt_id = prompt.get("prompt_id")
        text = prompt.get("text")
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise CandidateSearchError(
                "INVALID_USER_PROMPT",
                "user prompt prompt_id must be a non-empty string",
                source_row_index=index,
            )
        if prompt_id in seen:
            raise CandidateSearchError(
                "DUPLICATE_USER_PROMPT_ID",
                "user prompt prompt_id is duplicated",
                prompt_id=prompt_id,
            )
        if not isinstance(text, str) or not text.strip():
            raise CandidateSearchError(
                "INVALID_USER_PROMPT",
                "user prompt text must be a non-empty string",
                prompt_id=prompt_id,
            )
        seen.add(prompt_id)
        normalized.append({"prompt_id": prompt_id, "text": text.strip()})
    if not normalized:
        raise CandidateSearchError("EMPTY_USER_PROMPT_SET", "user prompt set must not be empty")
    return normalized


def _write_user_prompt_set_status(
    set_dir: Path,
    *,
    set_id: str,
    total_prompts: int,
    mapped_count: int,
    failed_count: int,
    mapping_status: str,
    generated_count: int = 0,
    skipped_count: int = 0,
) -> dict[str, Any]:
    status = {
        "set_id": set_id,
        "total_prompts": total_prompts,
        "mapped_count": mapped_count,
        "failed_count": failed_count,
        "generated_count": generated_count,
        "skipped_count": skipped_count,
        "mapping_status": mapping_status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _write_json_file(set_dir / "status.json", status)
    return status


def _write_test_sample_cohort(
    config: Any,
    sample_dir: Path,
    *,
    sample_id: str,
    sample_size: int,
    seed: int | None,
) -> dict[str, Any]:
    if sample_size < 1:
        raise CandidateSearchError(
            "INVALID_SAMPLE_SIZE",
            "sample_size must be >= 1",
            sample_size=sample_size,
        )
    raw_dataset = load_raw_dataset(config.raw_profiles_path)
    if sample_size > len(raw_dataset.rows):
        raise CandidateSearchError(
            "SAMPLE_SIZE_TOO_LARGE",
            "sample_size is larger than raw candidate count",
            sample_size=sample_size,
            total_raw_candidates=len(raw_dataset.rows),
        )
    actual_seed = seed if seed is not None else random.SystemRandom().randrange(0, 2**31)
    selected = sorted(
        random.Random(actual_seed).sample(raw_dataset.rows, sample_size),
        key=lambda item: item[0],
    )
    sample_records = [raw_profile for _, raw_profile in selected]
    _write_jsonl_file(sample_dir / "raw_profiles.jsonl", sample_records)
    index = {
        "items": [
            {
                "source_row_index": source_row_index,
                "user_id": int(raw_profile["user_id"]),
                "raw_profile_hash": canonical_hash(raw_profile),
            }
            for source_row_index, raw_profile in selected
        ]
    }
    _write_json_file(sample_dir / "sample_index.json", index)
    metadata = {
        "sample_id": sample_id,
        "sample_size": sample_size,
        "seed": actual_seed,
        "total_raw_candidates": len(raw_dataset.rows),
        "status": {
            "preprocess_status": "missing",
            "index_status": "missing",
        },
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _write_json_file(sample_dir / "sample.json", metadata)
    return metadata


def _discard_test_sample_build_artifacts(sample_dir: Path) -> None:
    for name in (
        "preprocessed_profiles.jsonl",
        "embeddings.jsonl",
        "preprocess_errors.jsonl",
        "index_errors.jsonl",
        "status.json",
    ):
        path = sample_dir / name
        if path.exists():
            path.unlink()


def _resolve_prompt_path(path: Path) -> Path:
    prompt = path.expanduser()
    if not prompt.is_absolute():
        prompt = (Path.cwd() / prompt).resolve()
    if not prompt.exists():
        raise CandidateSearchError(
            "PROMPT_FILE_NOT_FOUND",
            "prompt file does not exist",
            path=str(prompt),
        )
    return prompt


def _test_sample_dir(config: Any, sample_id: str) -> Path:
    if not sample_id.strip():
        raise CandidateSearchError("INVALID_TEST_SAMPLE_ID", "sample_id must not be empty")
    return _evaluation_data_dir(config) / "samples" / sample_id


def _user_prompt_set_dir(config: Any, set_id: str) -> Path:
    if not set_id.strip():
        raise CandidateSearchError("INVALID_USER_PROMPT_SET_ID", "set_id must not be empty")
    return _evaluation_data_dir(config) / "user_prompt_sets" / set_id


def _retrieval_trial_dir(config: Any, trial_id: str) -> Path:
    if not trial_id.strip():
        raise CandidateSearchError("INVALID_RETRIEVAL_TRIAL_ID", "trial_id must not be empty")
    return _evaluation_data_dir(config) / "retrieval_trials" / trial_id


def _evaluation_data_dir(config: Any) -> Path:
    return config.config_path.parent / "test" / "data"


def _require_user_prompt_set_dir(config: Any, set_id: str) -> Path:
    set_dir = _user_prompt_set_dir(config, set_id)
    if not set_dir.exists():
        raise CandidateSearchError(
            "USER_PROMPT_SET_NOT_FOUND",
            "user prompt set does not exist",
            set_id=set_id,
        )
    return set_dir


def _require_test_sample_dir(config: Any, sample_id: str) -> Path:
    sample_dir = _test_sample_dir(config, sample_id)
    if not sample_dir.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_FOUND",
            "test sample does not exist",
            sample_id=sample_id,
        )
    return sample_dir


def _require_retrieval_trial_dir(config: Any, trial_id: str) -> Path:
    trial_dir = _retrieval_trial_dir(config, trial_id)
    if not trial_dir.exists():
        raise CandidateSearchError(
            "RETRIEVAL_TRIAL_NOT_FOUND",
            "retrieval trial does not exist",
            trial_id=trial_id,
        )
    return trial_dir


def _test_sample_workspace(sample_dir: Path) -> BuildWorkspace:
    sample_path = sample_dir / "raw_profiles.jsonl"
    if not sample_path.exists():
        raise CandidateSearchError(
            "TEST_SAMPLE_NOT_FOUND",
            "test sample raw profile file is missing",
            sample_id=sample_dir.name,
        )
    return BuildWorkspace(
        raw_profiles_path=sample_path,
        processed_dir=sample_dir,
    )


def _write_jsonl_file(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _write_json_file(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {index} must be an object: {path}")
            records.append(value)
    return records


def _read_json_file_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"JSON file must contain an object: {path}")
        return value
    except (json.JSONDecodeError, ValueError) as exc:
        raise CandidateSearchError(
            "ARTIFACT_READ_FAILED",
            "artifact JSON could not be read",
            path=str(path),
            reason=str(exc),
        ) from exc


def _object_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.iterdir() if path.is_dir()]


def _list_envelope(object_type: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: item.get("updated_at") or "",
        reverse=True,
    )
    return {
        "object_type": object_type,
        "total_count": len(ordered),
        "items": ordered,
    }


def _read_jsonl_artifact_page(
    *,
    object_type: str,
    object_id: str,
    artifact: str,
    path: Path,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    offset, limit = _validate_browse_page(offset, limit)
    if not path.exists():
        return _browse_envelope(
            object_type=object_type,
            object_id=object_id,
            artifact=artifact,
            artifact_status="missing",
            total_count=0,
            offset=offset,
            limit=limit,
            items=[],
        )
    records = _read_jsonl_file_for_browse(path)
    items = records[offset : offset + limit]
    return _browse_envelope(
        object_type=object_type,
        object_id=object_id,
        artifact=artifact,
        artifact_status="available",
        total_count=len(records),
        offset=offset,
        limit=limit,
        items=items,
    )


def _read_combined_jsonl_artifact_page(
    *,
    object_type: str,
    object_id: str,
    artifact: str,
    sources: list[tuple[str, Path]],
    source_field: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    offset, limit = _validate_browse_page(offset, limit)
    existing_sources = [(name, path) for name, path in sources if path.exists()]
    if not existing_sources:
        return _browse_envelope(
            object_type=object_type,
            object_id=object_id,
            artifact=artifact,
            artifact_status="missing",
            total_count=0,
            offset=offset,
            limit=limit,
            items=[],
        )
    records = []
    for source_name, path in existing_sources:
        for record in _read_jsonl_file_for_browse(path):
            item = dict(record)
            item[source_field] = source_name
            records.append(item)
    items = records[offset : offset + limit]
    return _browse_envelope(
        object_type=object_type,
        object_id=object_id,
        artifact=artifact,
        artifact_status="available",
        total_count=len(records),
        offset=offset,
        limit=limit,
        items=items,
    )


def _browse_envelope(
    *,
    object_type: str,
    object_id: str,
    artifact: str,
    artifact_status: str,
    total_count: int,
    offset: int,
    limit: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "artifact": artifact,
        "artifact_status": artifact_status,
        "total_count": total_count,
        "offset": offset,
        "limit": limit,
        "returned_count": len(items),
        "items": items,
    }


def _validate_browse_page(offset: int, limit: int) -> tuple[int, int]:
    if offset < 0:
        raise CandidateSearchError(
            "INVALID_BROWSE_PAGE",
            "offset must be >= 0",
            offset=offset,
        )
    if limit < 1:
        raise CandidateSearchError(
            "INVALID_BROWSE_PAGE",
            "limit must be >= 1",
            limit=limit,
        )
    if limit > BROWSE_MAX_LIMIT:
        raise CandidateSearchError(
            "INVALID_BROWSE_PAGE",
            f"limit must be <= {BROWSE_MAX_LIMIT}",
            limit=limit,
            max_limit=BROWSE_MAX_LIMIT,
        )
    return offset, limit


def _read_jsonl_file_for_browse(path: Path) -> list[dict[str, Any]]:
    try:
        return _read_jsonl_file(path)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CandidateSearchError(
            "ARTIFACT_READ_FAILED",
            "artifact JSONL could not be read",
            path=str(path),
            reason=str(exc),
        ) from exc
