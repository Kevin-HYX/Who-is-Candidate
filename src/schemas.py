from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    CONFIG_REQUIRED_FIELDS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_TOP_K,
    HARD_CONSTRAINT_FIELDS,
    HARD_CONSTRAINT_OPERATORS,
    MANAGEMENT_SCOPE_RANK,
    MAX_TOP_K,
    SEARCHABLE_DIMENSIONS,
    SENIORITY_RANK,
)


class CandidateSearchError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        payload.update(self.details)
        return {"error": payload}


class ProcessConfigError(Exception):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    config_path: Path
    api_key: str
    preprocess_model: str
    embedding_model: str
    raw_profiles_path: Path
    processed_dir: Path


@dataclass(frozen=True)
class SearchRequest:
    query_plan: dict[str, Any]
    options: dict[str, Any]
    top_k: int


def load_config(config_path: str | Path | None = None) -> RuntimeConfig:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    path = path.expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()

    if not path.exists():
        raise ProcessConfigError(f"配置文件不存在: {path}")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ProcessConfigError(f"配置文件不是合法 TOML: {path}: {exc}") from exc

    missing = []
    for section, key in CONFIG_REQUIRED_FIELDS:
        value = data.get(section, {}).get(key)
        if not isinstance(value, str) or not value.strip():
            missing.append(f"{section}.{key}")
    if missing:
        raise ProcessConfigError("配置文件缺少必填项或为空: " + ", ".join(missing))

    base = path.parent
    raw_profiles_path = _resolve_path(base, data["paths"]["raw_profiles"])
    processed_dir = _resolve_path(base, data["paths"]["processed_dir"])

    return RuntimeConfig(
        config_path=path,
        api_key=data["dashscope"]["api_key"].strip(),
        preprocess_model=data["models"]["preprocess"].strip(),
        embedding_model=data["models"]["embedding"].strip(),
        raw_profiles_path=raw_profiles_path,
        processed_dir=processed_dir,
    )


def _resolve_path(base: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def validate_search_request(
    query_plan: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> SearchRequest:
    if not isinstance(query_plan, dict):
        raise CandidateSearchError("INVALID_QUERY_PLAN", "query_plan must be an object")

    unknown_keys = set(query_plan) - {"hard_constraints", "weighted_soft_preferences"}
    if unknown_keys:
        raise CandidateSearchError(
            "INVALID_QUERY_PLAN_FIELD",
            "query_plan contains unsupported fields",
            fields=sorted(unknown_keys),
        )

    hard_constraints = query_plan.get("hard_constraints", [])
    if hard_constraints is None:
        hard_constraints = []
    if not isinstance(hard_constraints, list):
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            "hard_constraints must be a list",
        )

    normalized_hard = []
    for index, item in enumerate(hard_constraints):
        normalized_hard.append(_validate_hard_constraint(index, item))

    soft_preferences = query_plan.get("weighted_soft_preferences")
    if not isinstance(soft_preferences, list) or not soft_preferences:
        raise CandidateSearchError(
            "EMPTY_SOFT_PREFERENCES",
            "weighted_soft_preferences must contain at least one item",
        )

    normalized_soft = []
    for index, item in enumerate(soft_preferences):
        normalized_soft.append(_validate_soft_preference(index, item))

    normalized_plan = {
        "hard_constraints": normalized_hard,
        "weighted_soft_preferences": normalized_soft,
    }

    normalized_options = dict(options or {})
    top_k = _validate_top_k(normalized_options.get("top_k", DEFAULT_TOP_K))
    normalized_options["top_k"] = top_k

    return SearchRequest(
        query_plan=normalized_plan,
        options=normalized_options,
        top_k=top_k,
    )


def _validate_hard_constraint(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            f"hard_constraints[{index}] must be an object",
        )

    field = item.get("field")
    if field not in HARD_CONSTRAINT_FIELDS:
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT_FIELD",
            f"hard_constraints[{index}].field is not allowed",
            field=field,
            allowed_fields=sorted(HARD_CONSTRAINT_FIELDS),
        )

    op = item.get("op")
    allowed_ops = HARD_CONSTRAINT_OPERATORS[field]
    if op not in allowed_ops:
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT_OPERATOR",
            f"hard_constraints[{index}].op is not allowed for {field}",
            field=field,
            op=op,
            allowed_operators=sorted(allowed_ops),
        )

    if "value" not in item:
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            f"hard_constraints[{index}].value is required",
        )
    _validate_hard_constraint_value(index, field, op, item["value"])

    return {
        "field": field,
        "op": op,
        "value": item["value"],
        "rationale": str(item.get("rationale", "")),
    }


def _validate_hard_constraint_value(index: int, field: str, op: str, value: Any) -> None:
    if field == "years_of_experience":
        _require_number(index, field, value)
        return
    if field == "highest_degree_level":
        if value not in {0, 1, 2, 3}:
            _invalid_hard_value(index, field, value, "must be one of 0, 1, 2, 3")
        return
    if field == "seniority_level":
        if isinstance(value, str) and value in SENIORITY_RANK:
            return
        _invalid_hard_value(index, field, value, "must be a known seniority level")
    if field == "management_scope":
        allowed = set(MANAGEMENT_SCOPE_RANK)
        if op in {"in", "not_in"}:
            values = value if isinstance(value, list) else [value]
            if values and all(isinstance(item, str) and item in allowed for item in values):
                return
        elif isinstance(value, str) and value in allowed:
            return
        _invalid_hard_value(index, field, value, "must be a known management scope")
    if field in {"role_family", "industries"}:
        values = value if isinstance(value, list) else [value]
        if values and all(isinstance(item, str) and item.strip() for item in values):
            return
        _invalid_hard_value(index, field, value, "must be a non-empty string or list of strings")
    if field == "is_currently_working":
        if isinstance(value, bool):
            return
        _invalid_hard_value(index, field, value, "must be boolean")


def _require_number(index: int, field: str, value: Any) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return
    _invalid_hard_value(index, field, value, "must be numeric")


def _invalid_hard_value(index: int, field: str, value: Any, reason: str) -> None:
    raise CandidateSearchError(
        "INVALID_HARD_CONSTRAINT_VALUE",
        f"hard_constraints[{index}].value is not valid for {field}: {reason}",
        field=field,
        value=value,
    )


def _validate_soft_preference(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CandidateSearchError(
            "INVALID_SOFT_PREFERENCE",
            f"weighted_soft_preferences[{index}] must be an object",
        )

    dimension = item.get("dimension")
    if dimension not in SEARCHABLE_DIMENSIONS:
        raise CandidateSearchError(
            "INVALID_SEARCH_DIMENSION",
            f"weighted_soft_preferences[{index}].dimension is not allowed",
            dimension=dimension,
            allowed_dimensions=sorted(SEARCHABLE_DIMENSIONS),
        )

    text = item.get("text")
    if not isinstance(text, str) or not _valid_soft_text(text):
        raise CandidateSearchError(
            "INVALID_SOFT_PREFERENCE_TEXT",
            f"weighted_soft_preferences[{index}].text is not valid",
        )

    weight = item.get("weight")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        raise CandidateSearchError(
            "INVALID_WEIGHT",
            f"weighted_soft_preferences[{index}].weight must be numeric",
        )
    weight = float(weight)
    if weight == 0 or weight < -3.0 or weight > 3.0:
        raise CandidateSearchError(
            "INVALID_WEIGHT",
            f"weighted_soft_preferences[{index}].weight must be in [-3.0, 3.0] and not 0",
            weight=weight,
        )

    return {"dimension": dimension, "text": text.strip(), "weight": weight}


def _valid_soft_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    negation_only = {
        "不要",
        "别",
        "避免",
        "排除",
        "not",
        "no",
        "without",
        "none",
    }
    return stripped.lower() not in negation_only


def _validate_top_k(value: Any) -> int:
    if isinstance(value, bool):
        raise CandidateSearchError("INVALID_TOP_K", "top_k must be an integer")
    try:
        top_k = int(value)
    except (TypeError, ValueError) as exc:
        raise CandidateSearchError("INVALID_TOP_K", "top_k must be an integer") from exc
    if top_k < 1:
        raise CandidateSearchError("INVALID_TOP_K", "top_k must be >= 1")
    if top_k > MAX_TOP_K:
        raise CandidateSearchError(
            "TOP_K_TOO_LARGE",
            f"top_k must be <= {MAX_TOP_K}",
            max_top_k=MAX_TOP_K,
            requested_top_k=top_k,
        )
    return top_k
