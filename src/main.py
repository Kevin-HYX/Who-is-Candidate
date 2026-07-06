from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .preprocess import preprocess_profiles
from .retrieval import (
    DashScopeModelClient,
    get_index_status,
    search_candidates,
)
from .retrieval import write_status as _write_status
from .retrieval import (
    canonical_hash,
    load_preprocessed_map,
    load_raw_dataset,
    merge_write_jsonl_by_user_id,
    parallel_map_with_retries,
    search_text_hash,
    write_latest_errors,
)
from .constants import (
    DEFAULT_CONCURRENCY,
    EMBEDDING_INDEX_VERSION,
    EMBEDDINGS_FILE,
    INDEX_ERRORS_FILE,
    PREPROCESS_SCHEMA_VERSION,
    SEARCHABLE_DIMENSIONS,
)
from .schemas import CandidateSearchError, ProcessConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except ProcessConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    except CandidateSearchError as exc:
        if getattr(args, "json", False) or args.command == "search":
            print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate-search")
    subparsers = parser.add_subparsers(dest="command")

    preprocess_parser = subparsers.add_parser("preprocess")
    add_common_config(preprocess_parser)
    add_range(preprocess_parser)
    preprocess_parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    preprocess_parser.add_argument("--json", action="store_true")
    preprocess_parser.set_defaults(func=cmd_preprocess)

    build_parser_ = subparsers.add_parser("build-index")
    add_common_config(build_parser_)
    add_range(build_parser_)
    build_parser_.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    build_parser_.add_argument("--json", action="store_true")
    build_parser_.set_defaults(func=cmd_build_index)

    search_parser = subparsers.add_parser("search")
    add_common_config(search_parser)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int, default=None)
    search_parser.add_argument("--json", action="store_true", default=True)
    search_parser.set_defaults(func=cmd_search)

    status_parser = subparsers.add_parser("index-status")
    add_common_config(status_parser)
    status_parser.set_defaults(func=cmd_index_status)

    mcp_parser = subparsers.add_parser("serve-mcp")
    add_common_config(mcp_parser)
    mcp_parser.set_defaults(func=cmd_serve_mcp)

    return parser


def add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)


def add_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)


def cmd_preprocess(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = preprocess_profiles(
        config,
        start=args.start,
        end=args.end,
        concurrency=args.concurrency,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_build_index(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_index(
        config,
        start=args.start,
        end=args.end,
        concurrency=args.concurrency,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    payload = json.loads(Path(args.query).read_text(encoding="utf-8"))
    if "query_plan" in payload:
        query_plan = payload["query_plan"]
        options = payload.get("options", {})
    else:
        query_plan = payload
        options = {}
    if args.top_k is not None:
        options = dict(options)
        options["top_k"] = args.top_k
    result = search_candidates(config, query_plan, options)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_index_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(json.dumps(get_index_status(config), ensure_ascii=False, indent=2))
    return 0


def cmd_serve_mcp(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    serve_mcp(config)
    return 0


def print_output(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key, value in result.items():
        if key != "status":
            print(f"{key}: {value}")


def build_index(
    config: Any,
    *,
    start: int | None = None,
    end: int | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_client: Any | None = None,
) -> dict[str, Any]:
    raw_dataset = load_raw_dataset(config.raw_profiles_path)
    preprocessed = load_preprocessed_map(config)
    lower = 0 if start is None else start
    upper = len(raw_dataset.rows) if end is None else end
    selected = []
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
        selected.append(record)

    client = model_client or DashScopeModelClient(config)

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
    merge_write_jsonl_by_user_id(config.processed_dir / EMBEDDINGS_FILE, successes)
    write_latest_errors(config.processed_dir / INDEX_ERRORS_FILE, errors)
    status = _write_status(config)
    if errors:
        raise CandidateSearchError(
            "BUILD_INDEX_FAILED",
            "some embeddings failed",
            failed_count=len(errors),
            succeeded_count=len(successes),
        )
    return {
        "indexed_count": len(successes),
        "failed_count": 0,
        "status": status,
    }


def serve_mcp(config: Any) -> None:
    server = MinimalMcpServer(config)
    server.serve()


class MinimalMcpServer:
    def __init__(self, config: Any) -> None:
        self.config = config

    def serve(self) -> None:
        stdin = sys.stdin.buffer
        stdout = sys.stdout.buffer
        while True:
            message = read_mcp_message(stdin)
            if message is None:
                break
            response = self.handle(message)
            if response is not None:
                write_mcp_message(stdout, response)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        message_id = message.get("id")
        if message_id is None and str(method).startswith("notifications/"):
            return None
        try:
            result = self.dispatch(method, message.get("params") or {})
            return {"jsonrpc": "2.0", "id": message_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - JSON-RPC error surface.
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "candidate-search", "version": "0.1.0"},
            }
        if method == "tools/list":
            return {"tools": [search_tool_schema()]}
        if method == "tools/call":
            return self.call_tool(params)
        if method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": "candidate://query-guide",
                        "name": "Candidate query guide",
                        "mimeType": "text/markdown",
                    },
                    {
                        "uri": "candidate://index-status",
                        "name": "Candidate index status",
                        "mimeType": "application/json",
                    },
                ]
            }
        if method == "resources/read":
            return self.read_resource(params)
        raise ValueError(f"Unsupported MCP method: {method}")

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("name") != "search_candidates":
            raise ValueError(f"Unsupported tool: {params.get('name')}")
        arguments = params.get("arguments") or {}
        try:
            result = search_candidates(
                self.config,
                arguments.get("query_plan"),
                arguments.get("options"),
            )
        except CandidateSearchError as exc:
            result = exc.to_dict()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ]
        }

    def read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if uri == "candidate://index-status":
            text = json.dumps(get_index_status(self.config), ensure_ascii=False, indent=2)
            mime = "application/json"
        elif uri == "candidate://query-guide":
            text = query_guide_text()
            mime = "text/markdown"
        else:
            raise ValueError(f"Unsupported resource: {uri}")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": mime,
                    "text": text,
                }
            ]
        }


def search_tool_schema() -> dict[str, Any]:
    return {
        "name": "search_candidates",
        "description": "Search candidates with a complete QueryPlan.",
        "inputSchema": {
            "type": "object",
            "required": ["query_plan"],
            "properties": {
                "query_plan": {"type": "object"},
                "options": {
                    "type": "object",
                    "properties": {"top_k": {"type": "integer", "minimum": 1, "maximum": 75}},
                },
            },
        },
    }


def query_guide_text() -> str:
    return """# Candidate Search Query Guide

Use `search_candidates` with a complete `query_plan`.

`hard_constraints` may only use: `years_of_experience`, `highest_degree_level`, `role_family`, `seniority_level`, `management_scope`, `industries`, `is_currently_working`.

`weighted_soft_preferences` must contain at least one item. Write `text` as concrete work content, not just a title or keyword. Use negative `weight` for "avoid X" needs.

Read `candidate://index-status` before assuming the index is available or full. If `index_status` is `partial`, tell the user results are from a partial index.

Explain candidate facts only from `results[].raw_profile`. Use `soft_preference_scores` only to explain sorting.
"""


def read_mcp_message(stream: Any) -> dict[str, Any] | None:
    headers = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        line = line.decode("ascii").strip()
        if not line:
            break
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers["content-length"])
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def write_mcp_message(stream: Any, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(header)
    stream.write(body)
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
