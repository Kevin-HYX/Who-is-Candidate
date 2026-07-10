from __future__ import annotations

import math
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    CONFIG_REQUIRED_FIELDS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_TOP_K,
    HARD_CONSTRAINT_FIELDS,
    HARD_CONSTRAINT_OPERATORS,
    INDUSTRY_VALUES,
    MANAGEMENT_SCOPE_RANK,
    MAX_ABS_SOFT_WEIGHT,
    MAX_TOP_K,
    MIN_ABS_SOFT_WEIGHT,
    PREPROCESS_PROMPT_FILE,
    ROLE_FAMILY_VALUES,
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


def is_english_generated_text(value: str) -> bool:
    has_latin_letter = False
    for character in value:
        if not character.isalpha():
            continue
        unicode_name = unicodedata.name(character, "")
        if "LATIN" not in unicode_name:
            return False
        has_latin_letter = True
    return has_latin_letter


@dataclass(frozen=True)
class BuildWorkspace:
    raw_profiles_path: Path
    processed_dir: Path
    preprocess_prompt_path: Path | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    config_path: Path
    api_key: str
    base_url: str
    preprocess_model: str
    embedding_model: str
    raw_profiles_path: Path
    processed_dir: Path

    def build_workspace(self) -> BuildWorkspace:
        return BuildWorkspace(
            raw_profiles_path=self.raw_profiles_path,
            processed_dir=self.processed_dir,
            preprocess_prompt_path=PREPROCESS_PROMPT_FILE,
        )


@dataclass(frozen=True)
class SearchRequest:
    query_plan: dict[str, Any]
    options: dict[str, Any]
    top_k: int


def search_tool_schema() -> dict[str, Any]:
    def enum_array(values: Any) -> dict[str, Any]:
        return {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(values)},
        }

    field_value_schemas = {
        "years_of_experience": {"type": "number", "minimum": 0},
        "highest_degree_level": {"type": "integer", "enum": [0, 1, 2, 3]},
        "role_family": enum_array(ROLE_FAMILY_VALUES),
        "seniority_level": {"type": "string", "enum": list(SENIORITY_RANK)},
        "industries": enum_array(INDUSTRY_VALUES),
        "is_currently_working": {"type": "boolean"},
    }
    hard_constraint_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "op", "value", "rationale"],
        "properties": {
            "field": {"type": "string", "enum": sorted(HARD_CONSTRAINT_FIELDS)},
            "op": {
                "type": "string",
                "enum": sorted(
                    {
                        operator
                        for operators in HARD_CONSTRAINT_OPERATORS.values()
                        for operator in operators
                    }
                ),
            },
            "value": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "string"},
                    {"type": "boolean"},
                    {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                ]
            },
            "rationale": {"type": "string", "minLength": 1},
        },
        "allOf": [
            *[
                {
                    "if": {
                        "properties": {"field": {"const": field}},
                        "required": ["field"],
                    },
                    "then": {
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": sorted(HARD_CONSTRAINT_OPERATORS[field]),
                            },
                            "value": field_value_schemas[field],
                        }
                    },
                }
                for field in sorted(HARD_CONSTRAINT_FIELDS - {"management_scope"})
            ],
            {
                "if": {
                    "properties": {
                        "field": {"const": "management_scope"},
                        "op": {"enum": ["in", "not_in"]},
                    },
                    "required": ["field", "op"],
                },
                "then": {
                    "properties": {
                        "op": {"type": "string", "enum": ["in", "not_in"]},
                        "value": enum_array(MANAGEMENT_SCOPE_RANK),
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "field": {"const": "management_scope"},
                        "op": {"enum": ["<=", "=", ">="]},
                    },
                    "required": ["field", "op"],
                },
                "then": {
                    "properties": {
                        "op": {"type": "string", "enum": ["<=", "=", ">="]},
                        "value": {
                            "type": "string",
                            "enum": list(MANAGEMENT_SCOPE_RANK),
                        },
                    }
                },
            },
        ],
    }
    soft_preference_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["dimension", "text", "weight"],
        "properties": {
            "dimension": {"type": "string", "enum": sorted(SEARCHABLE_DIMENSIONS)},
            "text": {"type": "string", "minLength": 4},
            "weight": {
                "type": "number",
                "minimum": -MAX_ABS_SOFT_WEIGHT,
                "maximum": MAX_ABS_SOFT_WEIGHT,
                "anyOf": [
                    {
                        "minimum": -MAX_ABS_SOFT_WEIGHT,
                        "maximum": -MIN_ABS_SOFT_WEIGHT,
                    },
                    {
                        "minimum": MIN_ABS_SOFT_WEIGHT,
                        "maximum": MAX_ABS_SOFT_WEIGHT,
                    },
                ],
            },
        },
    }
    return {
        "name": "search_candidates",
        "description": "Search candidates with a complete QueryPlan.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query_plan"],
            "properties": {
                "query_plan": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["hard_constraints", "weighted_soft_preferences"],
                    "properties": {
                        "hard_constraints": {
                            "type": "array",
                            "items": hard_constraint_schema,
                        },
                        "weighted_soft_preferences": {
                            "type": "array",
                            "minItems": 1,
                            "items": soft_preference_schema,
                        },
                    },
                },
                "options": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"top_k": {"type": "integer", "minimum": 1, "maximum": 75}},
                },
            },
        },
    }


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
        api_key=data["openai"]["api_key"].strip(),
        base_url=data["openai"]["base_url"].strip(),
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


def validate_generated_search_arguments(output: Any) -> SearchRequest:
    if not isinstance(output, dict):
        raise CandidateSearchError(
            "INVALID_QUERY_SCHEMA_OUTPUT",
            "query generation output must be an object",
        )
    expected_keys = {"query_plan", "options"}
    actual_keys = set(output)
    if actual_keys != expected_keys:
        raise CandidateSearchError(
            "INVALID_QUERY_SCHEMA_OUTPUT",
            "query generation output must contain exactly query_plan and options",
            missing_fields=sorted(expected_keys - actual_keys),
            unsupported_fields=sorted(actual_keys - expected_keys),
        )
    options = output["options"]
    if not isinstance(options, dict) or set(options) != {"top_k"}:
        actual_option_keys = sorted(options) if isinstance(options, dict) else []
        raise CandidateSearchError(
            "INVALID_QUERY_SCHEMA_OUTPUT",
            "query generation options must contain exactly top_k",
            option_fields=actual_option_keys,
        )
    return validate_search_request(output["query_plan"], options)


def validate_search_arguments(arguments: Any) -> SearchRequest:
    if not isinstance(arguments, dict):
        raise CandidateSearchError(
            "INVALID_SEARCH_ARGUMENTS",
            "search_candidates arguments must be an object",
        )
    allowed_keys = {"query_plan", "options"}
    actual_keys = set(arguments)
    if "query_plan" not in arguments or actual_keys - allowed_keys:
        raise CandidateSearchError(
            "INVALID_SEARCH_ARGUMENTS",
            "search_candidates arguments must contain query_plan and may contain options",
            missing_fields=[] if "query_plan" in arguments else ["query_plan"],
            unsupported_fields=sorted(actual_keys - allowed_keys),
        )
    return validate_search_request(
        arguments["query_plan"],
        arguments.get("options"),
    )


def validate_search_request(
    query_plan: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> SearchRequest:
    if not isinstance(query_plan, dict):
        raise CandidateSearchError("INVALID_QUERY_PLAN", "query_plan must be an object")

    expected_plan_keys = {"hard_constraints", "weighted_soft_preferences"}
    actual_plan_keys = set(query_plan)
    if actual_plan_keys != expected_plan_keys:
        raise CandidateSearchError(
            "INVALID_QUERY_PLAN_FIELD",
            "query_plan must contain exactly hard_constraints and weighted_soft_preferences",
            missing_fields=sorted(expected_plan_keys - actual_plan_keys),
            unsupported_fields=sorted(actual_plan_keys - expected_plan_keys),
        )

    hard_constraints = query_plan["hard_constraints"]
    if not isinstance(hard_constraints, list):
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            "hard_constraints must be a list",
        )

    normalized_hard = []
    for index, item in enumerate(hard_constraints):
        normalized_hard.append(_validate_hard_constraint(index, item))

    soft_preferences = query_plan["weighted_soft_preferences"]
    if not isinstance(soft_preferences, list) or not soft_preferences:
        raise CandidateSearchError(
            "EMPTY_SOFT_PREFERENCES",
            "weighted_soft_preferences must contain at least one item",
        )

    normalized_soft = []
    for index, item in enumerate(soft_preferences):
        normalized_soft.append(_validate_soft_preference(index, item))
    seen_soft_preferences: set[tuple[str, str]] = set()
    for index, item in enumerate(normalized_soft):
        identity = (item["dimension"], item["text"].casefold())
        if identity in seen_soft_preferences:
            raise CandidateSearchError(
                "INVALID_SOFT_PREFERENCE",
                f"weighted_soft_preferences[{index}] duplicates an earlier preference",
                dimension=item["dimension"],
                text=item["text"],
            )
        seen_soft_preferences.add(identity)

    normalized_plan = {
        "hard_constraints": normalized_hard,
        "weighted_soft_preferences": normalized_soft,
    }

    if options is None:
        normalized_options: dict[str, Any] = {}
    elif not isinstance(options, dict):
        raise CandidateSearchError("INVALID_OPTIONS", "options must be an object")
    else:
        unknown_option_keys = set(options) - {"top_k"}
        if unknown_option_keys:
            raise CandidateSearchError(
                "INVALID_OPTIONS_FIELD",
                "options contains unsupported fields",
                fields=sorted(unknown_option_keys),
            )
        normalized_options = dict(options)
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

    expected_keys = {"field", "op", "value", "rationale"}
    actual_keys = set(item)
    if actual_keys != expected_keys:
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            f"hard_constraints[{index}] must contain exactly field, op, value, and rationale",
            missing_fields=sorted(expected_keys - actual_keys),
            unsupported_fields=sorted(actual_keys - expected_keys),
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

    rationale = item["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise CandidateSearchError(
            "INVALID_HARD_CONSTRAINT",
            f"hard_constraints[{index}].rationale must be a non-empty string",
        )
    _require_english_query_text(
        rationale,
        f"hard_constraints[{index}].rationale",
    )

    return {
        "field": field,
        "op": op,
        "value": item["value"],
        "rationale": rationale.strip(),
    }


def _validate_hard_constraint_value(index: int, field: str, op: str, value: Any) -> None:
    if field == "years_of_experience":
        _require_number(index, field, value)
        if value < 0:
            _invalid_hard_value(index, field, value, "must be non-negative")
        return
    if field == "highest_degree_level":
        if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1, 2, 3}:
            _invalid_hard_value(
                index,
                field,
                value,
                "must be one of 0, 1, 2, 3",
                allowed_values=[0, 1, 2, 3],
            )
        return
    if field == "seniority_level":
        if isinstance(value, str) and value in SENIORITY_RANK:
            return
        _invalid_hard_value(
            index,
            field,
            value,
            "must be a known seniority level",
            allowed_values=list(SENIORITY_RANK),
        )
    if field == "management_scope":
        allowed = set(MANAGEMENT_SCOPE_RANK)
        if op in {"in", "not_in"}:
            if _valid_enum_list(value, allowed):
                return
        elif isinstance(value, str) and value in allowed:
            return
        _invalid_hard_value(
            index,
            field,
            value,
            "must be a known management scope",
            allowed_values=list(MANAGEMENT_SCOPE_RANK),
        )
    if field == "role_family":
        if _valid_enum_list(value, set(ROLE_FAMILY_VALUES)):
            return
        _invalid_hard_value(
            index,
            field,
            value,
            "must be a non-empty unique array of canonical role-family values",
            allowed_values=list(ROLE_FAMILY_VALUES),
        )
    if field == "industries":
        if _valid_enum_list(value, set(INDUSTRY_VALUES)):
            return
        _invalid_hard_value(
            index,
            field,
            value,
            "must be a non-empty unique array of LinkedIn Industry V2 top-level values",
            allowed_values=list(INDUSTRY_VALUES),
        )
    if field == "is_currently_working":
        if isinstance(value, bool):
            return
        _invalid_hard_value(index, field, value, "must be boolean")


def _require_number(index: int, field: str, value: Any) -> None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return
    _invalid_hard_value(index, field, value, "must be numeric")


def _invalid_hard_value(
    index: int,
    field: str,
    value: Any,
    reason: str,
    *,
    allowed_values: list[Any] | None = None,
) -> None:
    details: dict[str, Any] = {"field": field, "value": value}
    if allowed_values is not None:
        details["allowed_values"] = allowed_values
    raise CandidateSearchError(
        "INVALID_HARD_CONSTRAINT_VALUE",
        f"hard_constraints[{index}].value is not valid for {field}: {reason}",
        **details,
    )


def _valid_enum_list(value: Any, allowed: set[str]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item in allowed for item in value)
        and len(value) == len(set(value))
    )


def _validate_soft_preference(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CandidateSearchError(
            "INVALID_SOFT_PREFERENCE",
            f"weighted_soft_preferences[{index}] must be an object",
        )

    expected_keys = {"dimension", "text", "weight"}
    actual_keys = set(item)
    if actual_keys != expected_keys:
        raise CandidateSearchError(
            "INVALID_SOFT_PREFERENCE",
            f"weighted_soft_preferences[{index}] must contain exactly dimension, text, and weight",
            missing_fields=sorted(expected_keys - actual_keys),
            unsupported_fields=sorted(actual_keys - expected_keys),
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
    _require_english_query_text(
        text,
        f"weighted_soft_preferences[{index}].text",
    )

    weight = item.get("weight")
    if (
        not isinstance(weight, (int, float))
        or isinstance(weight, bool)
        or not math.isfinite(weight)
    ):
        raise CandidateSearchError(
            "INVALID_WEIGHT",
            f"weighted_soft_preferences[{index}].weight must be numeric",
        )
    weight = float(weight)
    if (
        abs(weight) < MIN_ABS_SOFT_WEIGHT
        or abs(weight) > MAX_ABS_SOFT_WEIGHT
    ):
        raise CandidateSearchError(
            "INVALID_WEIGHT",
            f"weighted_soft_preferences[{index}].weight must be in "
            f"[-{MAX_ABS_SOFT_WEIGHT}, -{MIN_ABS_SOFT_WEIGHT}] or "
            f"[{MIN_ABS_SOFT_WEIGHT}, {MAX_ABS_SOFT_WEIGHT}]",
            weight=weight,
        )

    return {"dimension": dimension, "text": text.strip(), "weight": weight}


def _valid_soft_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    lowered = stripped.casefold()
    forbidden_negation_prefixes = (
        "avoid ",
        "do not ",
        "don't ",
        "no ",
        "not ",
        "without ",
    )
    return not lowered.startswith(forbidden_negation_prefixes)


def _require_english_query_text(value: str, path: str) -> None:
    if not is_english_generated_text(value):
        raise CandidateSearchError(
            "NON_ENGLISH_GENERATED_TEXT",
            f"{path} must be English text",
            field=path,
        )


def _validate_top_k(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CandidateSearchError("INVALID_TOP_K", "top_k must be an integer")
    top_k = value
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
