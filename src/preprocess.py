from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_CONCURRENCY,
    HARD_CONSTRAINT_FIELDS,
    PREPROCESS_ERRORS_FILE,
    PREPROCESS_PROMPT_FILE,
    PREPROCESS_SCHEMA_VERSION,
    PROCESSED_PROFILES_FILE,
    SEARCHABLE_DIMENSIONS,
)
from .retrieval import (
    OpenAICompatibleModelClient,
    canonical_hash,
    load_preprocessed_map,
    load_raw_dataset,
    merge_write_jsonl_by_user_id,
    parallel_map_with_retries,
    write_latest_errors,
    write_status,
)
from .schemas import BuildWorkspace, CandidateSearchError, RuntimeConfig


def preprocess_profiles(
    config: RuntimeConfig,
    *,
    workspace: BuildWorkspace | None = None,
    start: int | None = None,
    end: int | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
    prompt_path: Path | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    build_workspace = workspace or config.build_workspace()
    raw_dataset = load_raw_dataset(build_workspace.raw_profiles_path)
    selected = _select_rows(raw_dataset.rows, start, end)
    prompt_file = prompt_path or PREPROCESS_PROMPT_FILE
    prompt = prompt_file.read_text(encoding="utf-8")
    client = model_client or OpenAICompatibleModelClient(config)
    existing = load_preprocessed_map(build_workspace, require_file=False)

    skipped = []
    items = [
        {"source_row_index": source_row_index, "raw_profile": raw_profile}
        for source_row_index, raw_profile in selected
        if discard_cache or not _has_current_preprocess_cache(existing, raw_profile)
    ]
    if not discard_cache:
        skipped = [
            raw_profile
            for _, raw_profile in selected
            if _has_current_preprocess_cache(existing, raw_profile)
        ]

    def worker(item: dict[str, Any]) -> dict[str, Any]:
        raw_profile = item["raw_profile"]
        source_row_index = item["source_row_index"]
        llm_output = client.preprocess_profile(prompt, raw_profile)
        preprocessed_profile = _merge_formula_fields(raw_profile, llm_output)
        _validate_preprocessed_profile(preprocessed_profile)
        return {
            "user_id": int(raw_profile["user_id"]),
            "source_row_index": source_row_index,
            "raw_profile_hash": canonical_hash(raw_profile),
            "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
            "preprocessed_profile": preprocessed_profile,
        }

    successes, errors = parallel_map_with_retries(
        items,
        worker,
        concurrency=concurrency,
        attempts=3,
    )
    merge_write_jsonl_by_user_id(build_workspace.processed_dir / PROCESSED_PROFILES_FILE, successes)
    write_latest_errors(build_workspace.processed_dir / PREPROCESS_ERRORS_FILE, errors)
    status = write_status(build_workspace)
    if errors:
        raise CandidateSearchError(
            "PREPROCESS_FAILED",
            "some profiles failed preprocessing",
            failed_count=len(errors),
            succeeded_count=len(successes),
        )
    return {
        "processed_count": len(successes),
        "skipped_count": len(skipped),
        "failed_count": 0,
        "status": status,
    }


def _has_current_preprocess_cache(
    existing: dict[int, dict[str, Any]],
    raw_profile: dict[str, Any],
) -> bool:
    user_id = int(raw_profile["user_id"])
    record = existing.get(user_id)
    if not record:
        return False
    return (
        record.get("preprocess_schema_version") == PREPROCESS_SCHEMA_VERSION
        and record.get("raw_profile_hash") == canonical_hash(raw_profile)
    )


def _select_rows(
    rows: list[tuple[int, dict[str, Any]]],
    start: int | None,
    end: int | None,
) -> list[tuple[int, dict[str, Any]]]:
    lower = 0 if start is None else start
    upper = len(rows) if end is None else end
    return [(index, profile) for index, profile in rows if lower <= index < upper]


def _merge_formula_fields(
    raw_profile: dict[str, Any],
    llm_output: dict[str, Any],
) -> dict[str, Any]:
    result = dict(llm_output)
    hard_fields = dict(result.get("hard_fields", {}))
    hard_fields["years_of_experience"] = _years_of_experience(raw_profile)
    hard_fields["highest_degree_level"] = _highest_degree_level(raw_profile)
    hard_fields["is_currently_working"] = _is_currently_working(raw_profile)
    result["hard_fields"] = hard_fields
    derived = dict(result.get("derived_fields", {}))
    derived["current_role_tenure_months"] = _current_role_tenure_months(raw_profile)
    derived["avg_tenure_months"] = _avg_tenure_months(raw_profile)
    result["derived_fields"] = derived
    return result


def _years_of_experience(raw_profile: dict[str, Any]) -> dict[str, Any]:
    months = raw_profile.get("total_experience_duration_months")
    source = "total_experience_duration_months"
    confidence = "high"
    if not isinstance(months, (int, float)):
        durations = [
            exp.get("duration_months")
            for exp in raw_profile.get("experience", [])
            if isinstance(exp.get("duration_months"), (int, float))
        ]
        if not durations:
            return {
                "value": "unknown",
                "unit": "years",
                "confidence": "unknown",
                "source_field": "total_experience_duration_months",
                "evidence": "not_provided",
            }
        months = sum(durations)
        source = "experience[].duration_months"
        confidence = "medium"
    return {
        "value": int(months // 12),
        "unit": "years",
        "confidence": confidence,
        "source_field": source,
        "evidence": f"{int(months)} months",
    }


def _highest_degree_level(raw_profile: dict[str, Any]) -> dict[str, Any]:
    levels = [
        education.get("degree_level")
        for education in raw_profile.get("education", [])
        if isinstance(education.get("degree_level"), int)
    ]
    if not levels:
        return {
            "value": "unknown",
            "confidence": "unknown",
            "source_field": "education[].degree_level",
            "evidence": "not_provided",
        }
    value = max(levels)
    return {
        "value": value,
        "confidence": "high",
        "source_field": "education[].degree_level",
        "evidence": f"max degree_level={value}",
    }


def _is_currently_working(raw_profile: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_profile.get("is_working"), bool):
        return {
            "value": raw_profile["is_working"],
            "confidence": "high",
            "source_field": "is_working",
            "evidence": f"is_working={raw_profile['is_working']}",
        }
    has_current = any(exp.get("is_current") is True for exp in raw_profile.get("experience", []))
    return {
        "value": has_current,
        "confidence": "high",
        "source_field": "experience[].is_current",
        "evidence": f"has current experience={has_current}",
    }


def _current_role_tenure_months(raw_profile: dict[str, Any]) -> dict[str, Any]:
    for exp in raw_profile.get("experience", []):
        if exp.get("is_current") is True and isinstance(exp.get("duration_months"), int):
            return {
                "value": exp["duration_months"],
                "confidence": "high",
                "source_field": "experience[is_current].duration_months",
                "evidence": f"{exp['duration_months']} months",
            }
    return {
        "value": None,
        "confidence": "unknown",
        "source_field": "experience[is_current].duration_months",
        "evidence": "not_provided",
    }


def _avg_tenure_months(raw_profile: dict[str, Any]) -> dict[str, Any]:
    durations = [
        exp.get("duration_months")
        for exp in raw_profile.get("experience", [])
        if isinstance(exp.get("duration_months"), int)
    ]
    if not durations:
        return {
            "value": None,
            "confidence": "unknown",
            "source_field": "experience[].duration_months",
            "evidence": "not_provided",
        }
    value = round(sum(durations) / len(durations))
    return {
        "value": value,
        "confidence": "high",
        "source_field": "experience[].duration_months",
        "evidence": f"{len(durations)} jobs",
    }


def _validate_preprocessed_profile(profile: dict[str, Any]) -> None:
    hard_fields = profile.get("hard_fields")
    if not isinstance(hard_fields, dict):
        raise ValueError("preprocessed_profile.hard_fields is required")
    missing_hard_fields = [
        field
        for field in sorted(HARD_CONSTRAINT_FIELDS)
        if not isinstance(hard_fields.get(field), dict)
    ]
    if missing_hard_fields:
        raise ValueError("missing hard fields: " + ", ".join(missing_hard_fields))
    search_texts = profile.get("embedding_search_texts")
    if not isinstance(search_texts, dict):
        raise ValueError("preprocessed_profile.embedding_search_texts is required")
    missing_dimensions = [
        dimension
        for dimension in sorted(SEARCHABLE_DIMENSIONS)
        if not isinstance(search_texts.get(dimension), str) or not search_texts[dimension].strip()
    ]
    if missing_dimensions:
        raise ValueError("missing embedding search texts: " + ", ".join(missing_dimensions))


def ensure_prompt_file() -> Path:
    return PREPROCESS_PROMPT_FILE
