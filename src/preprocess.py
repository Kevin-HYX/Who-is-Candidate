from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .constants import (
    CONFIDENCE_VALUES,
    DEFAULT_CONCURRENCY,
    EMBEDDINGS_FILE,
    HARD_CONSTRAINT_FIELDS,
    INDUSTRY_VALUES,
    MANAGEMENT_SCOPE_RANK,
    MISSING_SEARCH_TEXT,
    PREPROCESS_ERRORS_FILE,
    PREPROCESS_INFERRED_HARD_FIELDS,
    PREPROCESS_OUTPUT_FIELDS,
    PREPROCESS_PROMPT_FILE,
    PREPROCESS_SCHEMA_VERSION,
    PROCESSED_PROFILES_FILE,
    ROLE_FAMILY_VALUES,
    SEARCHABLE_DIMENSIONS,
    SENIORITY_RANK,
)
from .retrieval import (
    OpenAICompatibleModelClient,
    canonical_hash,
    get_index_status,
    load_embedding_map,
    load_preprocessed_map,
    load_raw_dataset,
    merge_write_jsonl_by_user_id,
    parallel_map_with_retries,
    preprocess_model_hash,
    write_latest_errors,
    write_jsonl,
)
from .schemas import (
    BuildWorkspace,
    CandidateSearchError,
    RuntimeConfig,
    is_english_generated_text,
)
from .run_log import AttemptFailure, RunEventWriter, raw_model_output


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
    event_writer: RunEventWriter | None = None,
    event_phase: str = "preprocess",
) -> dict[str, Any]:
    build_workspace = workspace or config.build_workspace()
    raw_dataset = load_raw_dataset(build_workspace.raw_profiles_path)
    selected = _select_rows(raw_dataset.rows, start, end)
    prompt_file = prompt_path or PREPROCESS_PROMPT_FILE
    prompt = prompt_file.read_text(encoding="utf-8")
    prompt_hash = canonical_hash(prompt)
    model_hash = preprocess_model_hash(config)
    client = model_client or OpenAICompatibleModelClient(config)
    existing = load_preprocessed_map(build_workspace, require_file=False)

    if any(
        not _cache_identity_matches(
            record,
            prompt_hash=prompt_hash,
            model_hash=model_hash,
        )
        for record in existing.values()
    ):
        existing = {}
        _replace_cache_records(build_workspace, {}, {})

    skipped = []
    items = [
        {"source_row_index": source_row_index, "raw_profile": raw_profile}
        for source_row_index, raw_profile in selected
        if discard_cache
        or not _has_current_preprocess_cache(
            existing,
            raw_profile,
            prompt_hash=prompt_hash,
            model_hash=model_hash,
        )
    ]
    if not discard_cache:
        skipped = [
            {"source_row_index": source_row_index, "raw_profile": raw_profile}
            for source_row_index, raw_profile in selected
            if _has_current_preprocess_cache(
                existing,
                raw_profile,
                prompt_hash=prompt_hash,
                model_hash=model_hash,
            )
        ]
        if event_writer is not None:
            for item in skipped:
                event_writer.emit(
                    "item_skipped",
                    phase=event_phase,
                    source_row_index=item["source_row_index"],
                    user_id=int(item["raw_profile"]["user_id"]),
                    reason="current_preprocess_cache",
                )

    invalidated_user_ids = {
        int(item["raw_profile"]["user_id"])
        for item in items
    }
    if invalidated_user_ids:
        remaining_preprocessed = {
            user_id: record
            for user_id, record in existing.items()
            if user_id not in invalidated_user_ids
        }
        embeddings = load_embedding_map(build_workspace, require_file=False)
        remaining_embeddings = {
            user_id: record
            for user_id, record in embeddings.items()
            if user_id not in invalidated_user_ids
        }
        _replace_cache_records(
            build_workspace,
            remaining_preprocessed,
            remaining_embeddings,
        )
        existing = remaining_preprocessed

    def worker(item: dict[str, Any]) -> dict[str, Any]:
        raw_profile = item["raw_profile"]
        source_row_index = item["source_row_index"]
        llm_output = client.preprocess_profile(prompt, raw_profile)
        try:
            validate_preprocess_model_output(llm_output)
        except ValueError as exc:
            raise AttemptFailure(
                exc,
                stage=_preprocess_validation_stage(str(exc)),
                error_code="PREPROCESS_OUTPUT_INVALID",
                raw_output=raw_model_output(llm_output),
            ) from exc
        preprocessed_profile = _merge_formula_fields(raw_profile, llm_output)
        try:
            _validate_preprocessed_profile(preprocessed_profile)
        except ValueError as exc:
            raise AttemptFailure(
                exc,
                stage="semantic_validation",
                error_code="PREPROCESSED_PROFILE_INVALID",
                raw_output=raw_model_output(llm_output),
            ) from exc
        return {
            "user_id": int(raw_profile["user_id"]),
            "source_row_index": source_row_index,
            "raw_profile_hash": canonical_hash(raw_profile),
            "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
            "preprocess_prompt_hash": prompt_hash,
            "preprocess_model_hash": model_hash,
            "preprocessed_profile": preprocessed_profile,
        }

    successes, errors = parallel_map_with_retries(
        items,
        worker,
        concurrency=concurrency,
        attempts=3,
        event_writer=event_writer,
        event_phase=event_phase,
        default_error_code="PREPROCESS_ATTEMPT_FAILED",
    )
    profiles_path = build_workspace.processed_dir / PROCESSED_PROFILES_FILE
    errors_path = build_workspace.processed_dir / PREPROCESS_ERRORS_FILE
    try:
        merge_write_jsonl_by_user_id(profiles_path, successes)
        write_latest_errors(errors_path, errors)
    except Exception as exc:  # noqa: BLE001 - surfaced as a run artifact failure.
        raise AttemptFailure(
            exc,
            stage="artifact_write",
            error_code="PREPROCESS_ARTIFACT_WRITE_FAILED",
        ) from exc
    if event_writer is not None:
        event_writer.emit(
            "artifact_written",
            phase=event_phase,
            artifact_kind="preprocessed_profiles",
            artifact_path=profiles_path.name,
        )
        if errors_path.exists():
            event_writer.emit(
                "artifact_written",
                phase=event_phase,
                artifact_kind="preprocess_errors",
                artifact_path=errors_path.name,
            )
    status = get_index_status(config, build_workspace)
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


def _preprocess_validation_stage(message: str) -> str:
    structural_markers = (
        "must be a JSON object",
        "must be an object",
        "has invalid fields",
        "missing hard fields",
        "missing embedding search texts",
    )
    if any(marker in message for marker in structural_markers):
        return "schema_validation"
    return "semantic_validation"


def _has_current_preprocess_cache(
    existing: dict[int, dict[str, Any]],
    raw_profile: dict[str, Any],
    *,
    prompt_hash: str,
    model_hash: str,
) -> bool:
    user_id = int(raw_profile["user_id"])
    record = existing.get(user_id)
    if not record:
        return False
    return (
        _cache_identity_matches(
            record,
            prompt_hash=prompt_hash,
            model_hash=model_hash,
        )
        and record.get("raw_profile_hash") == canonical_hash(raw_profile)
    )


def _cache_identity_matches(
    record: dict[str, Any],
    *,
    prompt_hash: str,
    model_hash: str,
) -> bool:
    return (
        record.get("preprocess_schema_version") == PREPROCESS_SCHEMA_VERSION
        and record.get("preprocess_prompt_hash") == prompt_hash
        and record.get("preprocess_model_hash") == model_hash
    )


def _replace_cache_records(
    workspace: BuildWorkspace,
    preprocessed: dict[int, dict[str, Any]],
    embeddings: dict[int, dict[str, Any]],
) -> None:
    ordered_preprocessed = sorted(
        preprocessed.values(),
        key=lambda item: (item.get("source_row_index", 10**12), int(item["user_id"])),
    )
    ordered_embeddings = sorted(
        embeddings.values(),
        key=lambda item: (item.get("source_row_index", 10**12), int(item["user_id"])),
    )
    write_jsonl(workspace.processed_dir / PROCESSED_PROFILES_FILE, ordered_preprocessed)
    write_jsonl(workspace.processed_dir / EMBEDDINGS_FILE, ordered_embeddings)


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
                "confidence": "low",
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
            "confidence": "low",
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
    experiences = raw_profile.get("experience", [])
    if any(exp.get("is_current") is True for exp in experiences):
        return {
            "value": True,
            "confidence": "high",
            "source_field": "experience[].is_current",
            "evidence": "At least one experience has is_current=true.",
        }
    if experiences and all(isinstance(exp.get("is_current"), bool) for exp in experiences):
        return {
            "value": False,
            "confidence": "high",
            "source_field": "experience[].is_current",
            "evidence": "All experiences have is_current=false.",
        }
    return {
        "value": "unknown",
        "confidence": "low",
        "source_field": "experience[].is_current",
        "evidence": "not_provided",
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
        "confidence": "low",
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
            "confidence": "low",
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


def validate_preprocess_model_output(profile: Any) -> None:
    if not isinstance(profile, dict):
        raise ValueError("preprocessed model output must be a JSON object")
    _require_exact_keys(profile, PREPROCESS_OUTPUT_FIELDS, "preprocessed model output")

    for section in ("derived_fields", "keyword_signals", "risk"):
        if not isinstance(profile[section], dict):
            raise ValueError(f"{section} must be an object")
        _validate_nested_generated_text(profile[section], section)

    hard_fields = profile["hard_fields"]
    if not isinstance(hard_fields, dict):
        raise ValueError("hard_fields must be an object")
    _require_exact_keys(
        hard_fields,
        PREPROCESS_INFERRED_HARD_FIELDS,
        "hard_fields",
    )
    for field in sorted(PREPROCESS_INFERRED_HARD_FIELDS):
        _validate_inferred_hard_field(field, hard_fields[field])

    search_texts = profile["embedding_search_texts"]
    if not isinstance(search_texts, dict):
        raise ValueError("embedding_search_texts must be an object")
    _require_exact_keys(search_texts, SEARCHABLE_DIMENSIONS, "embedding_search_texts")
    for dimension in sorted(SEARCHABLE_DIMENSIONS):
        text = search_texts[dimension]
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"embedding_search_texts.{dimension} must be a non-empty string"
            )
        _require_english_generated_text(
            text,
            f"embedding_search_texts.{dimension}",
        )
        normalized = " ".join(text.strip().lower().split())
        if normalized != MISSING_SEARCH_TEXT and len(text.split()) > 60:
            raise ValueError(
                f"embedding_search_texts.{dimension} must contain at most "
                "60 English words"
            )
        if normalized != MISSING_SEARCH_TEXT and (
            normalized in {"unknown", "insufficient_evidence"}
            or re.search(
                r"(?:^no (?:specific |explicit )?|^insufficient |^evidence is insufficient|"
                r"without evidence|absence of evidence|not provided)",
                normalized,
            )
        ):
            raise ValueError(
                f"embedding_search_texts.{dimension} must use {MISSING_SEARCH_TEXT!r} "
                "instead of an absence statement"
            )


def _validate_inferred_hard_field(field: str, item: Any) -> None:
    path = f"hard_fields.{field}"
    if not isinstance(item, dict):
        raise ValueError(f"{path} must be an object")
    _require_exact_keys(
        item,
        {"value", "confidence", "source_field", "evidence"},
        path,
    )

    confidence = item["confidence"]
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_VALUES:
        raise ValueError(
            f"{path}.confidence must be one of {sorted(CONFIDENCE_VALUES)}"
        )
    for key in ("source_field", "evidence"):
        value = item[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}.{key} must be a non-empty string")
    _require_english_generated_text(item["source_field"], f"{path}.source_field")
    _require_english_generated_text(item["evidence"], f"{path}.evidence")

    value = item["value"]
    if field == "role_family":
        _validate_scalar_enum(path, value, set(ROLE_FAMILY_VALUES))
    elif field == "seniority_level":
        _validate_scalar_enum(path, value, set(SENIORITY_RANK))
    elif field == "management_scope":
        _validate_scalar_enum(path, value, set(MANAGEMENT_SCOPE_RANK))
    elif field == "industries":
        _validate_industries(path, value)
    else:
        raise AssertionError(f"unsupported inferred hard field: {field}")

    is_unknown = value == "unknown" or value == ["unknown"]
    if is_unknown and confidence == "high":
        raise ValueError(f"{path}.confidence cannot be high when value is unknown")
    absence_states = {"unknown", "not_provided", "insufficient_evidence"}
    evidence = item["evidence"].strip()
    if is_unknown and confidence == "medium" and evidence in absence_states:
        raise ValueError(
            f"{path}.evidence must describe the conflicting or ambiguous evidence when value is unknown with medium confidence"
        )
    if not is_unknown and evidence in absence_states:
        raise ValueError(f"{path}.evidence does not support its concrete value")


def _validate_scalar_enum(path: str, value: Any, allowed: set[str]) -> None:
    if value == "unknown":
        return
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            f"{path}.value must be unknown or one of {sorted(allowed)}; got {value!r}"
        )


def _validate_industries(path: str, value: Any) -> None:
    if value == ["unknown"]:
        return
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}.value must be a non-empty array")
    if not all(isinstance(item, str) and item in INDUSTRY_VALUES for item in value):
        raise ValueError(
            f"{path}.value must contain only LinkedIn Industry V2 top-level values; got {value!r}"
        )
    if len(value) != len(set(value)):
        raise ValueError(f"{path}.value must not contain duplicates")


def _require_exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unsupported = sorted(actual - expected)
    raise ValueError(
        f"{path} has invalid fields; missing={missing}, unsupported={unsupported}"
    )


def _require_english_generated_text(value: str, path: str) -> None:
    if not is_english_generated_text(value):
        raise ValueError(f"{path} must be English text")


def _validate_nested_generated_text(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_nested_generated_text(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_nested_generated_text(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and any(character.isalpha() for character in value):
        _require_english_generated_text(value, path)


def ensure_prompt_file() -> Path:
    return PREPROCESS_PROMPT_FILE
