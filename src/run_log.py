from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, TextIO

from .schemas import CandidateSearchError


RUN_EVENTS = {
    "run_started",
    "phase_started",
    "item_skipped",
    "attempt_started",
    "attempt_failed",
    "attempt_succeeded",
    "item_succeeded",
    "item_failed",
    "artifact_written",
    "phase_completed",
    "run_completed",
    "run_failed",
    "run_interrupted",
}
TERMINAL_RUN_EVENTS = {"run_completed", "run_failed", "run_interrupted"}
RUN_STAGES = {
    "transport",
    "response_parse",
    "schema_validation",
    "semantic_validation",
    "embedding_validation",
    "artifact_write",
}
TRANSPORT_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
}
RAW_OUTPUT_EXCERPT_LIMIT = 500


class RawModelOutput(dict[str, Any]):
    def __init__(self, value: dict[str, Any], raw_content: str) -> None:
        super().__init__(value)
        self.raw_content = raw_content


class AttemptFailure(Exception):
    def __init__(
        self,
        error: Exception,
        *,
        stage: str,
        error_code: str,
        field_path: str | None = None,
        raw_output: Any | None = None,
    ) -> None:
        if stage not in RUN_STAGES:
            raise ValueError(f"unsupported run stage: {stage}")
        super().__init__(str(error))
        self.error = error
        self.stage = stage
        self.error_code = error_code
        self.field_path = field_path or _extract_field_path(str(error))
        self.raw_output = raw_output


def raw_model_output(value: Any) -> Any:
    return getattr(value, "raw_content", value)


def attempt_error_details(
    exc: BaseException,
    *,
    default_stage: str = "semantic_validation",
    default_error_code: str = "GENERATION_ATTEMPT_FAILED",
) -> dict[str, Any]:
    if isinstance(exc, AttemptFailure):
        error = exc.error
        return {
            "stage": exc.stage,
            "error_code": exc.error_code,
            "field_path": exc.field_path,
            "message": str(error),
            "error_type": type(error).__name__,
            "raw_output": exc.raw_output,
        }
    if type(exc).__name__ in TRANSPORT_ERROR_NAMES:
        return {
            "stage": "transport",
            "error_code": default_error_code,
            "field_path": None,
            "message": str(exc),
            "error_type": type(exc).__name__,
            "raw_output": None,
        }
    return {
        "stage": default_stage,
        "error_code": default_error_code,
        "field_path": _extract_field_path(str(exc)),
        "message": str(exc),
        "error_type": type(exc).__name__,
        "raw_output": None,
    }


def original_attempt_error(exc: BaseException) -> BaseException:
    if isinstance(exc, AttemptFailure):
        return exc.error
    return exc


class RunEventWriter:
    def __init__(
        self,
        run_dir: Path,
        metadata: dict[str, Any],
        *,
        stream: TextIO | None,
    ) -> None:
        self.run_dir = run_dir
        self.events_path = run_dir / "events.jsonl"
        self.attempts_dir = run_dir / "attempts"
        self.metadata = metadata
        self.run_id = metadata["run_id"]
        self.stream = stream
        self._lock = threading.Lock()
        self._seq = 0
        self._terminal_event: str | None = None

    @classmethod
    def create(
        cls,
        owner_dir: Path,
        *,
        owner_type: str,
        owner_id: str,
        command: str,
        phases: list[str],
        stream: TextIO | None = None,
        run_id: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> "RunEventWriter":
        actual_run_id = run_id or f"run_{uuid.uuid4().hex}"
        _validate_path_component(actual_run_id, "run_id")
        runs_dir = owner_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_dir = runs_dir / actual_run_id
        try:
            run_dir.mkdir()
        except FileExistsError as exc:
            raise CandidateSearchError(
                "GENERATION_RUN_ALREADY_EXISTS",
                "generation run already exists",
                run_id=actual_run_id,
                owner_type=owner_type,
                owner_id=owner_id,
            ) from exc
        (run_dir / "attempts").mkdir()
        metadata = {
            "run_id": actual_run_id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "command": command,
            "phases": list(phases),
            "created_at": _now(),
            "parameters": parameters or {},
        }
        _write_json_file(run_dir / "run.json", metadata)
        (run_dir / "events.jsonl").touch()
        return cls(run_dir, metadata, stream=stream)

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        if event not in RUN_EVENTS:
            raise ValueError(f"unsupported run event: {event}")
        with self._lock:
            if self._terminal_event is not None:
                raise RuntimeError(
                    f"cannot emit {event} after terminal event {self._terminal_event}"
                )
            if event in TERMINAL_RUN_EVENTS:
                self._terminal_event = event
            self._seq += 1
            value = {
                "run_id": self.run_id,
                "seq": self._seq,
                "timestamp": _now(),
                "event": event,
                **fields,
            }
            line = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.write("\n")
                handle.flush()
            if self.stream is not None:
                self.stream.write(line)
                self.stream.write("\n")
                self.stream.flush()
            return value

    def emit_attempt_failed(
        self,
        exc: BaseException,
        *,
        phase: str,
        item: dict[str, Any],
        attempt: int,
        max_attempts: int,
        default_stage: str = "semantic_validation",
        default_error_code: str = "GENERATION_ATTEMPT_FAILED",
    ) -> dict[str, Any]:
        details = attempt_error_details(
            exc,
            default_stage=default_stage,
            default_error_code=default_error_code,
        )
        artifact = self._write_attempt_artifact(
            details.pop("raw_output"),
            phase=phase,
            item=item,
            attempt=attempt,
        )
        event = self.emit(
            "attempt_failed",
            phase=phase,
            **item,
            attempt=attempt,
            max_attempts=max_attempts,
            stage=details["stage"],
            error_code=details["error_code"],
            field_path=details["field_path"],
            message=details["message"],
            error_type=details["error_type"],
            artifact_path=artifact.get("artifact_path"),
            raw_output_hash=artifact.get("sha256"),
            raw_output_excerpt=artifact.get("excerpt"),
        )
        if artifact:
            self.emit(
                "artifact_written",
                phase=phase,
                **item,
                attempt=attempt,
                artifact_kind="failed_attempt_raw_output",
                artifact_path=artifact["artifact_path"],
                sha256=artifact["sha256"],
                content_type=artifact["content_type"],
            )
        return event

    def _write_attempt_artifact(
        self,
        raw_output: Any | None,
        *,
        phase: str,
        item: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        if raw_output is None:
            return {}
        if isinstance(raw_output, bytes):
            payload = raw_output
            suffix = ".bin"
            content_type = "application/octet-stream"
            excerpt = None
        elif isinstance(raw_output, str):
            payload = raw_output.encode("utf-8")
            suffix = ".txt"
            content_type = "text/plain; charset=utf-8"
            excerpt = raw_output[:RAW_OUTPUT_EXCERPT_LIMIT]
        else:
            text = json.dumps(
                raw_output,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                indent=2,
            )
            payload = text.encode("utf-8")
            suffix = ".json"
            content_type = "application/json"
            excerpt = text[:RAW_OUTPUT_EXCERPT_LIMIT]
        identity = next(
            (
                str(item[key])
                for key in ("prompt_id", "user_id", "source_row_index")
                if item.get(key) is not None
            ),
            "item",
        )
        safe_phase = _safe_filename(phase)
        safe_identity = _safe_filename(identity)
        filename = (
            f"{safe_phase}-{safe_identity}-attempt-{attempt}-"
            f"{uuid.uuid4().hex[:8]}{suffix}"
        )
        path = self.attempts_dir / filename
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
        return {
            "artifact_path": path.relative_to(self.run_dir).as_posix(),
            "sha256": sha256(payload).hexdigest(),
            "content_type": content_type,
            "excerpt": excerpt,
        }


def list_runs(owner_dir: Path) -> dict[str, Any]:
    runs_dir = owner_dir / "runs"
    items = []
    if runs_dir.exists():
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
                continue
            items.append(read_run(owner_dir, run_dir.name))
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"total_count": len(items), "items": items}


def read_run(owner_dir: Path, run_id: str) -> dict[str, Any]:
    run_dir = _require_run_dir(owner_dir, run_id)
    metadata = _read_json_file(run_dir / "run.json")
    events = read_run_events(owner_dir, run_id)
    terminal = next(
        (event for event in reversed(events) if event.get("event") in TERMINAL_RUN_EVENTS),
        None,
    )
    return {
        **metadata,
        "event_count": len(events),
        "terminal_event": terminal,
    }


def read_run_events(owner_dir: Path, run_id: str) -> list[dict[str, Any]]:
    run_dir = _require_run_dir(owner_dir, run_id)
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CandidateSearchError(
                    "RUN_EVENT_LOG_INVALID",
                    "run event log contains invalid JSON",
                    run_id=run_id,
                    source_row_index=index,
                ) from exc
            if not isinstance(value, dict):
                raise CandidateSearchError(
                    "RUN_EVENT_LOG_INVALID",
                    "run event log row must be an object",
                    run_id=run_id,
                    source_row_index=index,
                )
            events.append(value)
    return events


def read_attempt_artifact(
    owner_dir: Path,
    run_id: str,
    artifact_path: str,
) -> dict[str, Any]:
    run_dir = _require_run_dir(owner_dir, run_id)
    relative = Path(artifact_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise CandidateSearchError(
            "INVALID_RUN_ATTEMPT_PATH",
            "attempt artifact path must be relative to the run",
            artifact_path=artifact_path,
        )
    if relative.parts[0] != "attempts":
        raise CandidateSearchError(
            "INVALID_RUN_ATTEMPT_PATH",
            "attempt artifact must be inside the run attempts directory",
            artifact_path=artifact_path,
        )
    path = run_dir / relative
    if not path.is_file():
        raise CandidateSearchError(
            "RUN_ATTEMPT_NOT_FOUND",
            "failed attempt artifact does not exist",
            run_id=run_id,
            artifact_path=artifact_path,
        )
    payload = path.read_bytes()
    if path.suffix == ".json":
        content: Any = json.loads(payload.decode("utf-8"))
        content_type = "application/json"
    elif path.suffix == ".txt":
        content = payload.decode("utf-8")
        content_type = "text/plain; charset=utf-8"
    else:
        content = payload.hex()
        content_type = "application/octet-stream"
    return {
        "run_id": run_id,
        "artifact_path": relative.as_posix(),
        "sha256": sha256(payload).hexdigest(),
        "content_type": content_type,
        "content": content,
    }


def _require_run_dir(owner_dir: Path, run_id: str) -> Path:
    _validate_path_component(run_id, "run_id")
    run_dir = owner_dir / "runs" / run_id
    if not (run_dir / "run.json").is_file():
        raise CandidateSearchError(
            "GENERATION_RUN_NOT_FOUND",
            "generation run does not exist for this owner",
            run_id=run_id,
        )
    return run_dir


def _validate_path_component(value: str, name: str) -> None:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise CandidateSearchError(
            "INVALID_GENERATION_RUN_ID",
            f"{name} must be one path component",
            value=value,
        )


def _extract_field_path(message: str) -> str | None:
    match = re.search(
        r"(?:hard_fields|embedding_search_texts|hard_constraints|weighted_soft_preferences)"
        r"(?:\[[0-9]+\]|\.[A-Za-z0-9_]+)+",
        message,
    )
    return match.group(0) if match else None


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return normalized[:80] or "item"


def _write_json_file(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            indent=2,
        )
        handle.write("\n")
        handle.flush()
    os.replace(temp, path)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateSearchError(
            "GENERATION_RUN_METADATA_INVALID",
            "generation run metadata cannot be read",
            path=str(path),
        ) from exc
    if not isinstance(value, dict):
        raise CandidateSearchError(
            "GENERATION_RUN_METADATA_INVALID",
            "generation run metadata must be an object",
            path=str(path),
        )
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()
