from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .evaluation import (
    BROWSE_DEFAULT_LIMIT,
    build_test_sample,
    build_test_sample_index,
    create_test_sample,
    create_user_prompt_set,
    list_retrieval_trials,
    list_generation_runs,
    list_test_samples,
    list_user_prompt_sets,
    map_user_prompt_set,
    preprocess_test_sample,
    read_retrieval_trial,
    read_retrieval_trial_errors,
    read_retrieval_trial_results,
    read_generation_attempt,
    read_generation_run,
    read_generation_run_events,
    read_test_sample,
    read_test_sample_errors,
    read_test_sample_preprocessed,
    read_test_sample_raw,
    read_user_prompt_set,
    read_user_prompt_set_errors,
    read_user_prompt_set_mappings,
    read_user_prompt_set_prompts,
    resample_test_sample,
    run_retrieval_trial,
)
from .preprocess import preprocess_profiles
from .retrieval import (
    build_index,
    get_index_status,
    parse_strict_json_object,
    search_candidates,
)
from .constants import (
    DEFAULT_CONCURRENCY,
    MCP_GUIDE_FILE,
    QUERY_GUIDE_FILE,
)
from .schemas import (
    CandidateSearchError,
    ProcessConfigError,
    load_config,
    search_tool_schema,
    validate_search_arguments,
)


STREAMING_RUN_COMMANDS = {
    "test-sample-preprocess",
    "test-sample-build-index",
    "test-sample-build",
    "user-prompt-set-map",
    "retrieval-trial-run",
}


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
        if args.command in STREAMING_RUN_COMMANDS:
            print(
                json.dumps(exc.to_dict(), ensure_ascii=False, separators=(",", ":")),
                file=sys.stderr,
            )
            return 1
        if getattr(args, "json", False) or args.command == "search":
            print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate-search")
    subparsers = parser.add_subparsers(dest="command")

    preprocess_parser = subparsers.add_parser("preprocess")
    add_common_config(preprocess_parser)
    add_range(preprocess_parser)
    preprocess_parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    preprocess_parser.add_argument("--discard-cache", action="store_true")
    preprocess_parser.add_argument("--json", action="store_true")
    preprocess_parser.set_defaults(func=cmd_preprocess)

    build_parser_ = subparsers.add_parser("build-index")
    add_common_config(build_parser_)
    add_range(build_parser_)
    build_parser_.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    build_parser_.add_argument("--discard-cache", action="store_true")
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

    test_sample_create_parser = subparsers.add_parser("test-sample-create")
    add_common_config(test_sample_create_parser)
    test_sample_create_parser.add_argument("--sample-id", required=True)
    test_sample_create_parser.add_argument("--sample-size", type=int, required=True)
    test_sample_create_parser.add_argument("--seed", type=int, default=None)
    test_sample_create_parser.add_argument("--preprocess-prompt", required=True)
    test_sample_create_parser.add_argument("--json", action="store_true")
    test_sample_create_parser.set_defaults(func=cmd_test_sample_create)

    test_sample_resample_parser = subparsers.add_parser("test-sample-resample")
    add_common_config(test_sample_resample_parser)
    test_sample_resample_parser.add_argument("--sample-id", required=True)
    test_sample_resample_parser.add_argument("--sample-size", type=int, required=True)
    test_sample_resample_parser.add_argument("--seed", type=int, default=None)
    test_sample_resample_parser.add_argument("--json", action="store_true")
    test_sample_resample_parser.set_defaults(func=cmd_test_sample_resample)

    test_sample_show_parser = subparsers.add_parser("test-sample-show")
    add_common_config(test_sample_show_parser)
    test_sample_show_parser.add_argument("--sample-id", required=True)
    test_sample_show_parser.add_argument("--json", action="store_true")
    test_sample_show_parser.set_defaults(func=cmd_test_sample_show)

    test_sample_list_parser = subparsers.add_parser("test-sample-list")
    add_common_config(test_sample_list_parser)
    test_sample_list_parser.add_argument("--json", action="store_true")
    test_sample_list_parser.set_defaults(func=cmd_test_sample_list)

    test_sample_read_raw_parser = subparsers.add_parser("test-sample-read-raw")
    add_common_config(test_sample_read_raw_parser)
    add_common_page(test_sample_read_raw_parser)
    test_sample_read_raw_parser.add_argument("--sample-id", required=True)
    test_sample_read_raw_parser.add_argument("--json", action="store_true")
    test_sample_read_raw_parser.set_defaults(func=cmd_test_sample_read_raw)

    test_sample_read_preprocessed_parser = subparsers.add_parser("test-sample-read-preprocessed")
    add_common_config(test_sample_read_preprocessed_parser)
    add_common_page(test_sample_read_preprocessed_parser)
    test_sample_read_preprocessed_parser.add_argument("--sample-id", required=True)
    test_sample_read_preprocessed_parser.add_argument("--json", action="store_true")
    test_sample_read_preprocessed_parser.set_defaults(func=cmd_test_sample_read_preprocessed)

    test_sample_read_errors_parser = subparsers.add_parser("test-sample-read-errors")
    add_common_config(test_sample_read_errors_parser)
    add_common_page(test_sample_read_errors_parser)
    test_sample_read_errors_parser.add_argument("--sample-id", required=True)
    test_sample_read_errors_parser.add_argument("--json", action="store_true")
    test_sample_read_errors_parser.set_defaults(func=cmd_test_sample_read_errors)

    test_sample_preprocess_parser = subparsers.add_parser("test-sample-preprocess")
    add_common_config(test_sample_preprocess_parser)
    test_sample_preprocess_parser.add_argument("--sample-id", required=True)
    test_sample_preprocess_parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    test_sample_preprocess_parser.add_argument("--discard-cache", action="store_true")
    test_sample_preprocess_parser.set_defaults(func=cmd_test_sample_preprocess)

    test_sample_build_index_parser = subparsers.add_parser("test-sample-build-index")
    add_common_config(test_sample_build_index_parser)
    test_sample_build_index_parser.add_argument("--sample-id", required=True)
    test_sample_build_index_parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    test_sample_build_index_parser.add_argument("--discard-cache", action="store_true")
    test_sample_build_index_parser.set_defaults(func=cmd_test_sample_build_index)

    test_sample_build_parser = subparsers.add_parser("test-sample-build")
    add_common_config(test_sample_build_parser)
    test_sample_build_parser.add_argument("--sample-id", required=True)
    test_sample_build_parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    test_sample_build_parser.add_argument("--discard-cache", action="store_true")
    test_sample_build_parser.set_defaults(func=cmd_test_sample_build)

    user_prompt_set_create_parser = subparsers.add_parser("user-prompt-set-create")
    add_common_config(user_prompt_set_create_parser)
    user_prompt_set_create_parser.add_argument("--set-id", required=True)
    user_prompt_set_create_parser.add_argument("--user-prompts", required=True)
    user_prompt_set_create_parser.add_argument("--query-prompt", required=True)
    user_prompt_set_create_parser.add_argument("--json", action="store_true")
    user_prompt_set_create_parser.set_defaults(func=cmd_user_prompt_set_create)

    user_prompt_set_map_parser = subparsers.add_parser("user-prompt-set-map")
    add_common_config(user_prompt_set_map_parser)
    user_prompt_set_map_parser.add_argument("--set-id", required=True)
    user_prompt_set_map_parser.add_argument("--discard-cache", action="store_true")
    user_prompt_set_map_parser.set_defaults(func=cmd_user_prompt_set_map)

    user_prompt_set_show_parser = subparsers.add_parser("user-prompt-set-show")
    add_common_config(user_prompt_set_show_parser)
    user_prompt_set_show_parser.add_argument("--set-id", required=True)
    user_prompt_set_show_parser.add_argument("--json", action="store_true")
    user_prompt_set_show_parser.set_defaults(func=cmd_user_prompt_set_show)

    user_prompt_set_list_parser = subparsers.add_parser("user-prompt-set-list")
    add_common_config(user_prompt_set_list_parser)
    user_prompt_set_list_parser.add_argument("--json", action="store_true")
    user_prompt_set_list_parser.set_defaults(func=cmd_user_prompt_set_list)

    user_prompt_set_read_prompts_parser = subparsers.add_parser("user-prompt-set-read-prompts")
    add_common_config(user_prompt_set_read_prompts_parser)
    add_common_page(user_prompt_set_read_prompts_parser)
    user_prompt_set_read_prompts_parser.add_argument("--set-id", required=True)
    user_prompt_set_read_prompts_parser.add_argument("--json", action="store_true")
    user_prompt_set_read_prompts_parser.set_defaults(func=cmd_user_prompt_set_read_prompts)

    user_prompt_set_read_mappings_parser = subparsers.add_parser("user-prompt-set-read-mappings")
    add_common_config(user_prompt_set_read_mappings_parser)
    add_common_page(user_prompt_set_read_mappings_parser)
    user_prompt_set_read_mappings_parser.add_argument("--set-id", required=True)
    user_prompt_set_read_mappings_parser.add_argument("--json", action="store_true")
    user_prompt_set_read_mappings_parser.set_defaults(func=cmd_user_prompt_set_read_mappings)

    user_prompt_set_read_errors_parser = subparsers.add_parser("user-prompt-set-read-errors")
    add_common_config(user_prompt_set_read_errors_parser)
    add_common_page(user_prompt_set_read_errors_parser)
    user_prompt_set_read_errors_parser.add_argument("--set-id", required=True)
    user_prompt_set_read_errors_parser.add_argument("--json", action="store_true")
    user_prompt_set_read_errors_parser.set_defaults(func=cmd_user_prompt_set_read_errors)

    retrieval_trial_run_parser = subparsers.add_parser("retrieval-trial-run")
    add_common_config(retrieval_trial_run_parser)
    retrieval_trial_run_parser.add_argument("--trial-id", required=True)
    retrieval_trial_run_parser.add_argument("--sample-id", required=True)
    retrieval_trial_run_parser.add_argument("--user-prompt-set-id", required=True)
    retrieval_trial_run_parser.set_defaults(func=cmd_retrieval_trial_run)

    retrieval_trial_show_parser = subparsers.add_parser("retrieval-trial-show")
    add_common_config(retrieval_trial_show_parser)
    retrieval_trial_show_parser.add_argument("--trial-id", required=True)
    retrieval_trial_show_parser.add_argument("--json", action="store_true")
    retrieval_trial_show_parser.set_defaults(func=cmd_retrieval_trial_show)

    retrieval_trial_list_parser = subparsers.add_parser("retrieval-trial-list")
    add_common_config(retrieval_trial_list_parser)
    retrieval_trial_list_parser.add_argument("--json", action="store_true")
    retrieval_trial_list_parser.set_defaults(func=cmd_retrieval_trial_list)

    retrieval_trial_read_results_parser = subparsers.add_parser("retrieval-trial-read-results")
    add_common_config(retrieval_trial_read_results_parser)
    add_common_page(retrieval_trial_read_results_parser)
    retrieval_trial_read_results_parser.add_argument("--trial-id", required=True)
    retrieval_trial_read_results_parser.add_argument("--json", action="store_true")
    retrieval_trial_read_results_parser.set_defaults(func=cmd_retrieval_trial_read_results)

    retrieval_trial_read_errors_parser = subparsers.add_parser("retrieval-trial-read-errors")
    add_common_config(retrieval_trial_read_errors_parser)
    add_common_page(retrieval_trial_read_errors_parser)
    retrieval_trial_read_errors_parser.add_argument("--trial-id", required=True)
    retrieval_trial_read_errors_parser.add_argument("--json", action="store_true")
    retrieval_trial_read_errors_parser.set_defaults(func=cmd_retrieval_trial_read_errors)

    run_list_parser = subparsers.add_parser("run-list")
    add_common_config(run_list_parser)
    add_run_owner(run_list_parser)
    run_list_parser.add_argument("--json", action="store_true")
    run_list_parser.set_defaults(func=cmd_run_list)

    run_show_parser = subparsers.add_parser("run-show")
    add_common_config(run_show_parser)
    add_run_owner(run_show_parser)
    run_show_parser.add_argument("--run-id", required=True)
    run_show_parser.add_argument("--json", action="store_true")
    run_show_parser.set_defaults(func=cmd_run_show)

    run_events_parser = subparsers.add_parser("run-events")
    add_common_config(run_events_parser)
    add_run_owner(run_events_parser)
    add_common_page(run_events_parser)
    run_events_parser.add_argument("--run-id", required=True)
    run_events_parser.add_argument("--json", action="store_true")
    run_events_parser.set_defaults(func=cmd_run_events)

    run_attempt_parser = subparsers.add_parser("run-attempt")
    add_common_config(run_attempt_parser)
    add_run_owner(run_attempt_parser)
    run_attempt_parser.add_argument("--run-id", required=True)
    run_attempt_parser.add_argument("--artifact", required=True)
    run_attempt_parser.add_argument("--json", action="store_true")
    run_attempt_parser.set_defaults(func=cmd_run_attempt)

    return parser


def add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)


def add_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)


def add_common_page(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=BROWSE_DEFAULT_LIMIT)


def add_run_owner(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--owner-type",
        required=True,
        choices=("test-sample", "user-prompt-set", "retrieval-trial"),
    )
    parser.add_argument("--owner-id", required=True)


def cmd_preprocess(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = preprocess_profiles(
        config,
        start=args.start,
        end=args.end,
        concurrency=args.concurrency,
        discard_cache=args.discard_cache,
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
        discard_cache=args.discard_cache,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        payload = parse_strict_json_object(Path(args.query).read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise CandidateSearchError(
            "INVALID_JSON",
            "query file must contain one standards-compliant JSON object",
            reason=str(exc),
        ) from exc
    if "query_plan" in payload:
        arguments = dict(payload)
        if args.top_k is not None:
            file_options = arguments.get("options", {})
            if not isinstance(file_options, dict):
                raise CandidateSearchError("INVALID_OPTIONS", "options must be an object")
            arguments["options"] = {**file_options, "top_k": args.top_k}
        request = validate_search_arguments(arguments)
        query_plan = request.query_plan
        options = request.options
    else:
        query_plan = payload
        options = {} if args.top_k is None else {"top_k": args.top_k}
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


def cmd_test_sample_create(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = create_test_sample(
        config,
        sample_id=args.sample_id,
        sample_size=args.sample_size,
        seed=args.seed,
        preprocess_prompt=Path(args.preprocess_prompt),
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_resample(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = resample_test_sample(
        config,
        sample_id=args.sample_id,
        sample_size=args.sample_size,
        seed=args.seed,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_test_sample(config, args.sample_id)
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = list_test_samples(config)
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_read_raw(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_test_sample_raw(
        config,
        args.sample_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_read_preprocessed(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_test_sample_preprocessed(
        config,
        args.sample_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_read_errors(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_test_sample_errors(
        config,
        args.sample_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_test_sample_preprocess(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = preprocess_test_sample(
        config,
        args.sample_id,
        concurrency=args.concurrency,
        discard_cache=args.discard_cache,
        event_stream=sys.stdout,
    )
    return 0


def cmd_test_sample_build_index(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_test_sample_index(
        config,
        args.sample_id,
        concurrency=args.concurrency,
        discard_cache=args.discard_cache,
        event_stream=sys.stdout,
    )
    return 0


def cmd_test_sample_build(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_test_sample(
        config,
        args.sample_id,
        concurrency=args.concurrency,
        discard_cache=args.discard_cache,
        event_stream=sys.stdout,
    )
    return 0


def cmd_user_prompt_set_create(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = create_user_prompt_set(
        config,
        set_id=args.set_id,
        user_prompts_path=Path(args.user_prompts),
        query_prompt_path=Path(args.query_prompt),
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_user_prompt_set_map(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = map_user_prompt_set(
        config,
        args.set_id,
        discard_cache=args.discard_cache,
        event_stream=sys.stdout,
    )
    return 0


def cmd_user_prompt_set_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_user_prompt_set(config, args.set_id)
    print_output(result, as_json=args.json)
    return 0


def cmd_user_prompt_set_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = list_user_prompt_sets(config)
    print_output(result, as_json=args.json)
    return 0


def cmd_user_prompt_set_read_prompts(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_user_prompt_set_prompts(
        config,
        args.set_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_user_prompt_set_read_mappings(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_user_prompt_set_mappings(
        config,
        args.set_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_user_prompt_set_read_errors(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_user_prompt_set_errors(
        config,
        args.set_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_retrieval_trial_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = run_retrieval_trial(
        config,
        trial_id=args.trial_id,
        sample_id=args.sample_id,
        user_prompt_set_id=args.user_prompt_set_id,
        event_stream=sys.stdout,
    )
    return 0


def cmd_retrieval_trial_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_retrieval_trial(config, args.trial_id)
    print_output(result, as_json=args.json)
    return 0


def cmd_retrieval_trial_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = list_retrieval_trials(config)
    print_output(result, as_json=args.json)
    return 0


def cmd_retrieval_trial_read_results(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_retrieval_trial_results(
        config,
        args.trial_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_retrieval_trial_read_errors(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_retrieval_trial_errors(
        config,
        args.trial_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_run_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = list_generation_runs(
        config,
        _run_owner_type(args.owner_type),
        args.owner_id,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_run_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_generation_run(
        config,
        _run_owner_type(args.owner_type),
        args.owner_id,
        args.run_id,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_run_events(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_generation_run_events(
        config,
        _run_owner_type(args.owner_type),
        args.owner_id,
        args.run_id,
        offset=args.offset,
        limit=args.limit,
    )
    print_output(result, as_json=args.json)
    return 0


def cmd_run_attempt(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = read_generation_attempt(
        config,
        _run_owner_type(args.owner_type),
        args.owner_id,
        args.run_id,
        args.artifact,
    )
    print_output(result, as_json=args.json)
    return 0


def _run_owner_type(value: str) -> str:
    return value.replace("-", "_")


def print_output(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key, value in result.items():
        if key != "status":
            print(f"{key}: {value}")



def serve_mcp(config: Any) -> None:
    server = MinimalMcpServer(config)
    server.serve()


class MinimalMcpServer:
    def __init__(self, config: Any) -> None:
        self.config = config

    def serve(self, stdin: Any | None = None, stdout: Any | None = None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        while True:
            try:
                message = read_mcp_message(stdin)
            except (KeyError, UnicodeError, ValueError):
                write_mcp_message(
                    stdout,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    },
                )
                continue
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
                        "uri": "candidate://help",
                        "name": "Candidate search help",
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
        is_error = False
        try:
            request = validate_search_arguments(arguments)
            result = search_candidates(
                self.config,
                request.query_plan,
                request.options,
            )
        except CandidateSearchError as exc:
            result = exc.to_dict()
            is_error = True
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ],
            "isError": is_error,
        }

    def read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if uri == "candidate://index-status":
            text = json.dumps(get_index_status(self.config), ensure_ascii=False, indent=2)
            mime = "application/json"
        elif uri == "candidate://help":
            text = help_text()
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


def help_text() -> str:
    mcp_guide = MCP_GUIDE_FILE.read_text(encoding="utf-8").strip()
    query_guide = QUERY_GUIDE_FILE.read_text(encoding="utf-8").strip()
    return f"{mcp_guide}\n\n---\n\n{query_guide}\n"


def read_mcp_message(stream: Any) -> dict[str, Any] | None:
    line = stream.readline()
    if line == b"":
        return None
    body = line.decode("utf-8").rstrip("\r\n")
    if not body:
        raise ValueError("MCP stdio message must not be empty")
    return parse_strict_json_object(body)


def write_mcp_message(stream: Any, message: dict[str, Any]) -> None:
    body = json.dumps(
        message,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    stream.write(body)
    stream.write(b"\n")
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
