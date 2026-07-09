from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from .constants import (
    DEFAULT_CONCURRENCY,
    EMBEDDING_INDEX_VERSION,
    EMBEDDINGS_FILE,
    HARD_CONSTRAINT_FIELDS,
    INDEX_ERRORS_FILE,
    MANAGEMENT_SCOPE_RANK,
    PREPROCESS_SCHEMA_VERSION,
    PREPROCESS_ERRORS_FILE,
    PROCESSED_PROFILES_FILE,
    SEARCHABLE_DIMENSIONS,
    SENIORITY_RANK,
    STATUS_FILE,
)
from .schemas import BuildWorkspace, CandidateSearchError, RuntimeConfig, validate_search_request


class ModelClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def preprocess_profile(self, prompt: str, raw_profile: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAICompatibleModelClient:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._client()
        response = client.embeddings.create(
            model=self.config.embedding_model,
            input=texts,
        )
        embeddings = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in embeddings]

    def preprocess_profile(self, prompt: str, raw_profile: dict[str, Any]) -> dict[str, Any]:
        client = self._client()
        response = client.chat.completions.create(
            model=self.config.preprocess_model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(raw_profile, ensure_ascii=False, sort_keys=True),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM output is empty")
        return _parse_json_content(content)

    def generate_query_plan(
        self,
        query_guide: str,
        tool_schema: dict[str, Any],
        user_prompt: str,
    ) -> dict[str, Any]:
        client = self._client()
        response = client.chat.completions.create(
            model=self.config.preprocess_model,
            messages=[
                {
                    "role": "system",
                    "content": query_guide
                    + "\n\nTool schema:\n"
                    + json.dumps(tool_schema, ensure_ascii=False, sort_keys=True),
                },
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM output is empty")
        return _parse_json_content(content)

    def _client(self) -> Any:
        openai = _load_openai()
        return openai.OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)


def _load_openai() -> Any:
    try:
        import openai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "缺少 openai SDK。请先安装依赖: pip install openai"
        ) from exc
    return openai


def _parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a JSON object")
    return parsed


@dataclass(frozen=True)
class RawDataset:
    rows: list[tuple[int, dict[str, Any]]]
    by_user_id: dict[int, dict[str, Any]]
    row_by_user_id: dict[int, int]


def _as_workspace(workspace: BuildWorkspace | RuntimeConfig) -> BuildWorkspace:
    if isinstance(workspace, BuildWorkspace):
        return workspace
    return workspace.build_workspace()


def search_candidates(
    config: RuntimeConfig,
    query_plan: dict[str, Any],
    options: dict[str, Any] | None = None,
    model_client: ModelClient | None = None,
    workspace: BuildWorkspace | None = None,
) -> dict[str, Any]:
    build_workspace = workspace or config.build_workspace()
    request = validate_search_request(query_plan, options)
    status = read_status(build_workspace)
    if status is None:
        raise CandidateSearchError(
            "PREPROCESS_AND_INDEX_NOT_BUILT",
            "preprocessed profiles and search index are not built",
        )
    if status.get("preprocess_status") == "missing" and status.get("index_status") == "missing":
        raise CandidateSearchError(
            "PREPROCESS_AND_INDEX_NOT_BUILT",
            "preprocessed profiles and search index are not built",
        )
    if status.get("index_status") == "missing":
        raise CandidateSearchError(
            "SEARCH_INDEX_NOT_BUILT",
            "search index is not built",
        )

    raw_dataset = load_raw_dataset(build_workspace.raw_profiles_path)
    preprocessed = load_preprocessed_map(build_workspace)
    embeddings = load_embedding_map(build_workspace)
    indexed_records = _usable_embedding_records(embeddings)
    if not indexed_records:
        raise CandidateSearchError("SEARCH_INDEX_NOT_BUILT", "search index is not built")

    _validate_cache_consistency(raw_dataset, preprocessed, indexed_records)

    client = model_client or OpenAICompatibleModelClient(config)
    preferences = request.query_plan["weighted_soft_preferences"]
    query_vectors = client.embed_texts([item["text"] for item in preferences])
    if len(query_vectors) != len(preferences):
        raise RuntimeError("embedding model returned unexpected query vector count")

    candidates = []
    for user_id, embedding_record in indexed_records.items():
        profile_record = preprocessed[user_id]
        hard_status = _evaluate_hard_constraints(
            profile_record["preprocessed_profile"],
            request.query_plan["hard_constraints"],
        )
        if hard_status is None:
            continue
        candidates.append(
            {
                "user_id": user_id,
                "embedding_record": embedding_record,
                "preprocessed_profile": profile_record["preprocessed_profile"],
                "hard_filter_status": hard_status,
            }
        )

    scored = _score_candidates(candidates, preferences, query_vectors)
    ranked = _rank_candidates(scored)
    selected, beyond_reason = _select_top_k(ranked, request.top_k)

    results = []
    for item in selected:
        raw_profile = raw_dataset.by_user_id[item["user_id"]]
        results.append(
            {
                "rank": item["rank"],
                "user_id": item["user_id"],
                "final_score": item["final_score"],
                "hard_filter_status": item["hard_filter_status"],
                "soft_preference_scores": item["soft_preference_scores"],
                "raw_profile": raw_profile,
            }
        )

    return {
        "search_meta": {
            "total_raw_candidates": status.get("total_raw_candidates"),
            "indexed_candidates": status.get("indexed_candidates"),
            "index_status": status.get("index_status"),
            "source_ranges": status.get("source_ranges", []),
            "passed_hard_filter": len(candidates),
            "requested_top_k": request.top_k,
            "returned_count": len(results),
            "normalization": "percentile",
            "returned_beyond_top_k_reason": beyond_reason,
            "score_formula": "final_score = sum(score_after_weight); score_after_weight = weight * score_before_weight",
        },
        "results": results,
    }


def get_index_status(config: RuntimeConfig, workspace: BuildWorkspace | None = None) -> dict[str, Any]:
    build_workspace = workspace or config.build_workspace()
    status = read_status(build_workspace)
    if status is None:
        return {
            "preprocess_status": "missing",
            "index_status": "missing",
            "total_raw_candidates": None,
            "preprocessed_candidates": 0,
            "indexed_candidates": 0,
            "source_ranges": [],
            "next_actions": ["preprocess", "build-index"],
        }
    return status


def read_status(workspace: BuildWorkspace | RuntimeConfig) -> dict[str, Any] | None:
    build_workspace = _as_workspace(workspace)
    path = build_workspace.processed_dir / STATUS_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(workspace: BuildWorkspace | RuntimeConfig) -> dict[str, Any]:
    build_workspace = _as_workspace(workspace)
    build_workspace.processed_dir.mkdir(parents=True, exist_ok=True)
    raw_count = _count_jsonl(build_workspace.raw_profiles_path)
    preprocessed = load_preprocessed_map(build_workspace, require_file=False)
    embeddings = load_embedding_map(build_workspace, require_file=False)
    preprocessed_rows = [
        record.get("source_row_index")
        for record in preprocessed.values()
        if record.get("preprocess_schema_version") == PREPROCESS_SCHEMA_VERSION
    ]
    indexed_rows = [
        record.get("source_row_index")
        for record in embeddings.values()
        if record.get("embedding_index_version") == EMBEDDING_INDEX_VERSION
    ]
    status = {
        "preprocess_schema_version": PREPROCESS_SCHEMA_VERSION,
        "embedding_index_version": EMBEDDING_INDEX_VERSION,
        "total_raw_candidates": raw_count,
        "preprocessed_candidates": len(preprocessed_rows),
        "indexed_candidates": len(indexed_rows),
        "preprocess_status": _coverage_status(len(preprocessed_rows), raw_count),
        "index_status": _coverage_status(len(indexed_rows), raw_count),
        "source_ranges": merge_source_ranges(indexed_rows),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(build_workspace.processed_dir / STATUS_FILE, status)
    return status


def _coverage_status(count: int, total: int) -> str:
    if count <= 0:
        return "missing"
    if count >= total:
        return "full"
    return "partial"


def load_raw_dataset(path: Path) -> RawDataset:
    rows = []
    by_user_id = {}
    row_by_user_id = {}
    for source_row_index, profile in read_jsonl(path):
        user_id = profile.get("user_id")
        if user_id is None:
            raise CandidateSearchError(
                "RAW_PROFILE_ID_MISSING",
                "raw profile is missing user_id",
                source_row_index=source_row_index,
            )
        if user_id in by_user_id:
            raise CandidateSearchError(
                "RAW_PROFILE_ID_DUPLICATE",
                "raw profile user_id is duplicated",
                user_id=user_id,
            )
        rows.append((source_row_index, profile))
        by_user_id[int(user_id)] = profile
        row_by_user_id[int(user_id)] = source_row_index
    return RawDataset(rows=rows, by_user_id=by_user_id, row_by_user_id=row_by_user_id)


def load_preprocessed_map(
    workspace: BuildWorkspace | RuntimeConfig,
    require_file: bool = True,
) -> dict[int, dict[str, Any]]:
    build_workspace = _as_workspace(workspace)
    path = build_workspace.processed_dir / PROCESSED_PROFILES_FILE
    if not path.exists():
        if require_file:
            raise CandidateSearchError(
                "PREPROCESS_AND_INDEX_NOT_BUILT",
                "preprocessed profiles are not built",
            )
        return {}
    return {int(record["user_id"]): record for _, record in read_jsonl(path)}


def load_embedding_map(
    workspace: BuildWorkspace | RuntimeConfig,
    require_file: bool = True,
) -> dict[int, dict[str, Any]]:
    build_workspace = _as_workspace(workspace)
    path = build_workspace.processed_dir / EMBEDDINGS_FILE
    if not path.exists():
        if require_file:
            raise CandidateSearchError("SEARCH_INDEX_NOT_BUILT", "search index is not built")
        return {}
    return {int(record["user_id"]): record for _, record in read_jsonl(path)}


def read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {index} must be an object: {path}")
            rows.append((index, value))
    return rows


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    os.replace(temp, path)


def merge_write_jsonl_by_user_id(path: Path, new_records: list[dict[str, Any]]) -> None:
    existing = {}
    if path.exists():
        existing = {int(record["user_id"]): record for _, record in read_jsonl(path)}
    for record in new_records:
        existing[int(record["user_id"])] = record
    ordered = sorted(
        existing.values(),
        key=lambda item: (item.get("source_row_index", 10**12), int(item["user_id"])),
    )
    write_jsonl(path, ordered)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def search_text_hash(preprocessed_profile: dict[str, Any]) -> str:
    texts = preprocessed_profile.get("embedding_search_texts", {})
    selected = {dimension: texts.get(dimension, "") for dimension in sorted(SEARCHABLE_DIMENSIONS)}
    return canonical_hash(selected)


def merge_source_ranges(row_indices: list[int | None]) -> list[list[int]]:
    indices = sorted({int(value) for value in row_indices if value is not None})
    if not indices:
        return []
    ranges = []
    start = previous = indices[0]
    for value in indices[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append([start, previous + 1])
        start = previous = value
    ranges.append([start, previous + 1])
    return ranges


def _validate_cache_consistency(
    raw_dataset: RawDataset,
    preprocessed: dict[int, dict[str, Any]],
    embeddings: dict[int, dict[str, Any]],
) -> None:
    for user_id, embedding_record in embeddings.items():
        if user_id not in raw_dataset.by_user_id:
            raise CandidateSearchError(
                "RAW_PROFILE_NOT_FOUND",
                "indexed user_id is missing from raw profiles",
                user_id=user_id,
            )
        if user_id not in preprocessed:
            raise CandidateSearchError(
                "SEARCH_TEXT_HASH_MISMATCH",
                "indexed user_id is missing from preprocessed profiles",
                user_id=user_id,
            )
        profile_record = preprocessed[user_id]
        if profile_record.get("preprocess_schema_version") != PREPROCESS_SCHEMA_VERSION:
            raise CandidateSearchError(
                "PREPROCESS_AND_INDEX_NOT_BUILT",
                "preprocessed profile version is not usable",
                user_id=user_id,
            )
        if embedding_record.get("embedding_index_version") != EMBEDDING_INDEX_VERSION:
            raise CandidateSearchError(
                "SEARCH_INDEX_NOT_BUILT",
                "embedding index version is not usable",
                user_id=user_id,
            )
        current_raw_hash = canonical_hash(raw_dataset.by_user_id[user_id])
        if profile_record.get("raw_profile_hash") != current_raw_hash:
            raise CandidateSearchError(
                "RAW_PROFILE_HASH_MISMATCH",
                "raw profile changed after preprocess",
                user_id=user_id,
            )
        current_search_hash = search_text_hash(profile_record["preprocessed_profile"])
        if embedding_record.get("search_text_hash") != current_search_hash:
            raise CandidateSearchError(
                "SEARCH_TEXT_HASH_MISMATCH",
                "search texts changed after build-index",
                user_id=user_id,
            )


def _usable_embedding_records(
    embeddings: dict[int, dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    return {
        user_id: record
        for user_id, record in embeddings.items()
        if record.get("embedding_index_version") == EMBEDDING_INDEX_VERSION
    }


def _evaluate_hard_constraints(
    preprocessed_profile: dict[str, Any],
    constraints: list[dict[str, Any]],
) -> dict[str, Any] | None:
    insufficient = []
    for constraint in constraints:
        field = constraint["field"]
        hard_value = _extract_hard_value(preprocessed_profile, field)
        if not hard_value["usable"]:
            insufficient.append(field)
            continue
        if not _constraint_satisfied(hard_value["value"], constraint["op"], constraint["value"], field):
            return None
    if insufficient:
        return {
            "status": "kept_with_insufficient_evidence",
            "insufficient_evidence_fields": sorted(set(insufficient)),
        }
    return {"status": "passed", "insufficient_evidence_fields": []}


def _extract_hard_value(preprocessed_profile: dict[str, Any], field: str) -> dict[str, Any]:
    hard_fields = preprocessed_profile.get("hard_fields", {})
    item = hard_fields.get(field)
    if not isinstance(item, dict):
        return {"usable": False, "value": None}
    confidence = item.get("confidence")
    value: Any
    if field == "role_family":
        values = item.get("all") or []
        primary = item.get("primary")
        if primary and primary not in values:
            values.append(primary)
        value = values
    elif field == "industries":
        values = item.get("all") or item.get("value") or []
        primary = item.get("primary")
        if primary and primary not in values:
            values.append(primary)
        value = values
    elif field == "seniority_level":
        value = item.get("rank")
        if value is None and item.get("value") in SENIORITY_RANK:
            value = SENIORITY_RANK[item["value"]]
    elif field == "management_scope":
        value = item.get("rank")
        if value is None and item.get("value") in MANAGEMENT_SCOPE_RANK:
            value = MANAGEMENT_SCOPE_RANK[item["value"]]
    else:
        value = item.get("value")

    if value in (None, "unknown", "not_provided", "insufficient_evidence"):
        return {"usable": False, "value": value}
    if confidence != "high":
        return {"usable": False, "value": value}
    return {"usable": True, "value": value}


def _constraint_satisfied(candidate_value: Any, op: str, expected: Any, field: str) -> bool:
    if field in {"role_family", "industries"}:
        candidate_values = set(candidate_value or [])
        expected_values = set(expected if isinstance(expected, list) else [expected])
        if op == "in":
            return bool(candidate_values & expected_values)
        if op == "not_in":
            return not bool(candidate_values & expected_values)
    if field == "is_currently_working":
        return bool(candidate_value) == bool(expected)
    if field == "management_scope" and op in {"in", "not_in"}:
        candidate_label = _management_label(candidate_value)
        expected_values = set(expected if isinstance(expected, list) else [expected])
        matched = candidate_label in expected_values or candidate_value in expected_values
        return matched if op == "in" else not matched

    left = _coerce_number(candidate_value)
    right = _coerce_comparable_expected(expected, field)
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == "=":
        return left == right
    raise ValueError(f"Unsupported operator: {op}")


def _coerce_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"Expected numeric comparable value, got {value!r}")


def _coerce_comparable_expected(value: Any, field: str) -> float:
    if field == "seniority_level" and isinstance(value, str):
        return float(SENIORITY_RANK[value])
    if field == "management_scope" and isinstance(value, str):
        return float(MANAGEMENT_SCOPE_RANK[value])
    return _coerce_number(value)


def _management_label(rank: int) -> str | None:
    for label, value in MANAGEMENT_SCOPE_RANK.items():
        if value == rank:
            return label
    return None


def _score_candidates(
    candidates: list[dict[str, Any]],
    preferences: list[dict[str, Any]],
    query_vectors: list[list[float]],
) -> list[dict[str, Any]]:
    raw_scores_by_pref: list[list[float]] = []
    for pref_index, preference in enumerate(preferences):
        dimension = preference["dimension"]
        query_vector = query_vectors[pref_index]
        scores = []
        for candidate in candidates:
            vectors = candidate["embedding_record"].get("vectors", {})
            candidate_vector = vectors.get(dimension)
            if candidate_vector is None:
                raise CandidateSearchError(
                    "SEARCH_TEXT_HASH_MISMATCH",
                    "embedding record is missing a searchable dimension",
                    user_id=candidate["user_id"],
                    dimension=dimension,
                )
            scores.append(cosine_similarity(query_vector, candidate_vector))
        raw_scores_by_pref.append(scores)

    percentiles_by_pref = [_percentiles(scores) for scores in raw_scores_by_pref]
    scored = []
    for candidate_index, candidate in enumerate(candidates):
        soft_scores = []
        final_score = 0.0
        for pref_index, preference in enumerate(preferences):
            before = percentiles_by_pref[pref_index][candidate_index]
            after = before * preference["weight"]
            final_score += after
            soft_scores.append(
                {
                    "preference_index": pref_index,
                    "dimension": preference["dimension"],
                    "weight": preference["weight"],
                    "score_before_weight": round(before, 6),
                    "score_after_weight": round(after, 6),
                }
            )
        scored.append(
            {
                "user_id": candidate["user_id"],
                "final_score": round(final_score, 6),
                "hard_filter_status": candidate["hard_filter_status"],
                "soft_preference_scores": soft_scores,
            }
        )
    return scored


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _percentiles(scores: list[float]) -> list[float]:
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]
    return [sum(1 for other in scores if other < score) / (len(scores) - 1) for score in scores]


def _rank_candidates(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(scored, key=lambda item: (-item["final_score"], item["user_id"]))
    previous_score = None
    previous_rank = 0
    for index, item in enumerate(ordered, start=1):
        if previous_score is not None and item["final_score"] == previous_score:
            item["rank"] = previous_rank
        else:
            item["rank"] = index
            previous_rank = index
            previous_score = item["final_score"]
    return ordered


def _select_top_k(
    ranked: list[dict[str, Any]],
    top_k: int,
) -> tuple[list[dict[str, Any]], str | None]:
    if len(ranked) <= top_k:
        return ranked, None
    boundary_rank = ranked[top_k - 1]["rank"]
    selected = [item for item in ranked if item["rank"] <= boundary_rank]
    if len(selected) > top_k:
        return selected, "top_k boundary shared the same rank; returned all candidates with that rank"
    return selected, None


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def build_index(
    config: RuntimeConfig,
    *,
    workspace: BuildWorkspace | None = None,
    start: int | None = None,
    end: int | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
    discard_cache: bool = False,
) -> dict[str, Any]:
    build_workspace = workspace or config.build_workspace()
    raw_dataset = load_raw_dataset(build_workspace.raw_profiles_path)
    preprocessed = load_preprocessed_map(build_workspace)
    lower = 0 if start is None else start
    upper = len(raw_dataset.rows) if end is None else end
    selected = []
    embeddings = load_embedding_map(build_workspace, require_file=False)
    skipped_count = 0
    for source_row_index, raw_profile in raw_dataset.rows:
        if not (lower <= source_row_index < upper):
            continue
        user_id = int(raw_profile["user_id"])
        if user_id not in preprocessed:
            raise CandidateSearchError(
                "PREPROCESSED_PROFILE_NOT_FOUND",
                "requested raw row has no preprocessed profile",
                user_id=user_id,
                source_row_index=source_row_index,
            )
        record = preprocessed[user_id]
        if record.get("preprocess_schema_version") != PREPROCESS_SCHEMA_VERSION:
            raise CandidateSearchError(
                "PREPROCESS_AND_INDEX_NOT_BUILT",
                "preprocessed profile version is not usable",
                user_id=user_id,
            )
        if record.get("raw_profile_hash") != canonical_hash(raw_profile):
            raise CandidateSearchError(
                "RAW_PROFILE_HASH_MISMATCH",
                "raw profile changed after preprocess",
                user_id=user_id,
            )
        current_search_text_hash = search_text_hash(record["preprocessed_profile"])
        cached_embedding = embeddings.get(user_id)
        if (
            not discard_cache
            and cached_embedding
            and cached_embedding.get("embedding_index_version") == EMBEDDING_INDEX_VERSION
            and cached_embedding.get("search_text_hash") == current_search_text_hash
        ):
            skipped_count += 1
            continue
        selected.append(record)

    client = model_client or OpenAICompatibleModelClient(config)

    def worker(record: dict[str, Any]) -> dict[str, Any]:
        profile = record["preprocessed_profile"]
        texts = profile["embedding_search_texts"]
        dimensions = sorted(SEARCHABLE_DIMENSIONS)
        vectors = client.embed_texts([texts[dimension] for dimension in dimensions])
        if len(vectors) != len(dimensions):
            raise RuntimeError("embedding model returned unexpected vector count")
        return {
            "user_id": int(record["user_id"]),
            "source_row_index": record["source_row_index"],
            "embedding_index_version": EMBEDDING_INDEX_VERSION,
            "search_text_hash": search_text_hash(profile),
            "vectors": {
                dimension: vector
                for dimension, vector in zip(dimensions, vectors)
            },
        }

    successes, errors = parallel_map_with_retries(
        selected,
        worker,
        concurrency=concurrency,
        attempts=3,
    )
    merge_write_jsonl_by_user_id(build_workspace.processed_dir / EMBEDDINGS_FILE, successes)
    write_latest_errors(build_workspace.processed_dir / INDEX_ERRORS_FILE, errors)
    status = write_status(build_workspace)
    if errors:
        raise CandidateSearchError(
            "BUILD_INDEX_FAILED",
            "some embeddings failed",
            failed_count=len(errors),
            succeeded_count=len(successes),
        )
    return {
        "indexed_count": len(successes),
        "skipped_count": skipped_count,
        "failed_count": 0,
        "status": status,
    }


def run_with_retries(
    fn: Any,
    *,
    attempts: int = 3,
) -> Any:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - the error is persisted for CLI visibility.
            last_error = exc
    assert last_error is not None
    raise last_error


def write_latest_errors(path: Path, errors: list[dict[str, Any]]) -> None:
    if errors:
        write_jsonl(path, errors)
    elif path.exists():
        path.unlink()


def parallel_map_with_retries(
    items: list[Any],
    worker: Any,
    *,
    concurrency: int,
    attempts: int = 3,
) -> tuple[list[Any], list[dict[str, Any]]]:
    successes = []
    errors = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(lambda item=item: run_with_retries(lambda: worker(item), attempts=attempts)): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                successes.append(future.result())
            except Exception as exc:  # noqa: BLE001 - surfaced in latest error JSONL.
                errors.append(
                    {
                        "item": _error_item_identity(item),
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    return successes, errors


def _error_item_identity(item: Any) -> Any:
    if isinstance(item, dict):
        return {
            key: item.get(key)
            for key in ("user_id", "source_row_index")
            if key in item
        }
    return item
