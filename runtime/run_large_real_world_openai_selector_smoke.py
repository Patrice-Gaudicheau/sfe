"""Run OpenAI selector smoke test for the large real-world benchmark.

This runner tests source selection only. It never uses an LLM executor and never
falls back to fixture/oracle source selection for pass purposes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (
    DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    MissingOpenAIAPIKeyError,
    OpenAIAPIProvider,
)
from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from runtime.run_large_real_world_multi_zone_benchmark import (
    LargeRealWorldTask,
    format_source,
    get_large_real_world_tasks,
    source_by_id,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/large_real_world_openai_selector_smoke"
BENCHMARK_NAME = "large_real_world_openai_selector_smoke"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "large_real_world_openai_selector_smoke.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "large_real_world_openai_selector_smoke.md"
OPENAI_SELECTOR_API_PATH = "/v1/responses"
DEFAULT_MAX_OUTPUT_TOKENS = 900


class SelectorProvider(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class SelectorConfig:
    model: str
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout: float | None = None


def main() -> None:
    args = _parse_args()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    timeout = args.timeout
    if timeout is None and os.getenv("SFE_OPENAI_API_TIMEOUT"):
        timeout = float(os.environ["SFE_OPENAI_API_TIMEOUT"])
    provider = OpenAIAPIProvider(timeout=timeout)
    if not provider.health()["ok"]:
        raise MissingOpenAIAPIKeyError(provider.health()["error"])
    report = run_smoke(
        tasks=get_large_real_world_tasks(),
        provider=provider,
        config=SelectorConfig(
            model=model,
            timeout=timeout,
            max_output_tokens=args.max_output_tokens,
        ),
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenAI selector smoke over the large real-world benchmark."
    )
    parser.add_argument(
        "--model",
        help=(
            "OpenAI selector model. Defaults to SFE_OPENAI_ROUTER_MODEL, then the "
            "project OpenAI router default."
        ),
    )
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def run_smoke(
    *,
    tasks: list[LargeRealWorldTask],
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one large real-world task is required.")
    if not config.model:
        raise ValueError("OpenAI selector model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    runs = [
        execute_selector_smoke(task=task, provider=provider, config=config)
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "router_model": config.model,
            "fixture_count": len(tasks),
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "selector_scope": "source_selection_only",
            "executor": "deterministic_validator_only",
            "fallback_policy": "no oracle fallback; fallback counts as failure",
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def execute_selector_smoke(
    *,
    task: LargeRealWorldTask,
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    prompt = build_selector_prompt(task)
    started = time.perf_counter()
    raw_response_text = ""
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    error = ""
    fallback_used = False
    parse_success = False
    parsed: dict[str, Any] | None = None
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=config.model,
            max_tokens=config.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You are selecting source documents for a benchmark. Return only strict JSON."
            ),
        )
        raw_response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        provider_latency_ms = _extract_latency_ms(response)
        parsed = parse_selector_output(raw_response_text)
        parse_success = True
    except Exception as exc:
        error = _safe_error_message(exc)
        fallback_used = True

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    latency_ms = provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms
    selected_source_ids = parsed["selected_source_ids"] if parsed else []
    rationale = parsed["selection_rationale"] if parsed else {}
    validation = validate_selection(task, selected_source_ids)
    exact_selector_match = validation["exact_selector_match"]
    selected_context_tokens = _selected_context_tokens(task, selected_source_ids)
    full_context_tokens = _full_context_tokens(task)
    token_reduction = percent_reduction(full_context_tokens, selected_context_tokens)
    honest_pass = bool(
        parse_success
        and not fallback_used
        and exact_selector_match
        and validation["required_source_complete"]
        and validation["distractors_omitted"]
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "task_theme": task.task_theme,
        "router_model": config.model,
        "provider": OPENAI_API_PROVIDER,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "selected_source_ids": selected_source_ids,
        "required_source_ids": list(task.required_source_ids),
        "distractor_source_ids": list(task.distractor_source_ids),
        "missing_required_source_ids": validation["missing_required_source_ids"],
        "extra_selected_source_ids": validation["extra_selected_source_ids"],
        "unknown_selected_source_ids": validation["unknown_selected_source_ids"],
        "duplicate_selected_source_ids": validation["duplicate_selected_source_ids"],
        "selected_distractor_source_ids": validation["selected_distractor_source_ids"],
        "selection_rationale": rationale,
        "parse_success": parse_success,
        "parse_error": "" if parse_success else error,
        "selector_error": error,
        "fallback_used": fallback_used,
        "exact_selector_match": exact_selector_match,
        "required_source_complete": validation["required_source_complete"],
        "distractors_omitted": validation["distractors_omitted"],
        "honest_selector_pass": honest_pass,
        "full_context_token_estimate": full_context_tokens,
        "selected_context_token_estimate": selected_context_tokens,
        "token_reduction_percent": token_reduction,
        "latency_ms": latency_ms,
        "usage": usage,
        "raw_response_text": raw_response_text,
    }


def build_selector_prompt(task: LargeRealWorldTask) -> str:
    source_catalog = "\n\n".join(format_source(source) for source in task.sources)
    source_ids = ", ".join(f'"{source.source_id}"' for source in task.sources)
    return (
        "Select the exact source documents needed to answer the task.\n"
        "This is an OpenAI selector smoke test. You are selecting source IDs only; "
        "do not answer the task.\n\n"
        "Return strict JSON only with this exact shape:\n"
        "{\n"
        '  "selected_source_ids": ["source-id-1", "source-id-2", "source-id-3", "source-id-4"],\n'
        '  "selection_rationale": {"source-id-1": "short reason"}\n'
        "}\n\n"
        "Selection rules:\n"
        "- Select by sufficiency, not topical similarity.\n"
        "- Exactly 4 source IDs are required.\n"
        "- No single source is enough.\n"
        "- Obsolete, partial, draft, announcement, operational, and vocabulary-overlap distractors must be rejected.\n"
        "- selected_source_ids must contain exact canonical source IDs only.\n"
        "- Do not prefix IDs with DOC or SOURCE.\n"
        "- Do not append roles in parentheses.\n"
        "- Do not include markdown, prose, comments, or decorated IDs.\n"
        "- Do not invent IDs.\n"
        f"- Valid IDs are exactly: {source_ids}\n\n"
        f"Fixture ID: {task.fixture_id}\n"
        f"Task:\n{task.question}\n\n"
        f"Candidate sources:\n{source_catalog}"
    )


def parse_selector_output(response_text: str) -> dict[str, Any]:
    data = json.loads(response_text.strip())
    if not isinstance(data, dict):
        raise ValueError("selector response must be a JSON object")
    selected = data.get("selected_source_ids")
    if not isinstance(selected, list):
        raise ValueError("selected_source_ids must be a list")
    selected_source_ids = [str(source_id).strip() for source_id in selected]
    if not selected_source_ids:
        raise ValueError("selected_source_ids must not be empty")
    duplicate_ids = sorted(
        {
            source_id
            for source_id in selected_source_ids
            if selected_source_ids.count(source_id) > 1
        }
    )
    if duplicate_ids:
        raise ValueError(
            "selected_source_ids must not contain duplicates: "
            + ", ".join(duplicate_ids)
        )
    rationale = data.get("selection_rationale", {})
    if not isinstance(rationale, dict):
        raise ValueError("selection_rationale must be an object")
    return {
        "selected_source_ids": selected_source_ids,
        "selection_rationale": {str(key): str(value) for key, value in rationale.items()},
    }


def validate_selection(task: LargeRealWorldTask, selected_source_ids: list[str]) -> dict[str, Any]:
    valid_ids = {source.source_id for source in task.sources}
    required_ids = set(task.required_source_ids)
    distractor_ids = set(task.distractor_source_ids)
    selected_set = set(selected_source_ids)
    duplicate_ids = sorted(
        {source_id for source_id in selected_source_ids if selected_source_ids.count(source_id) > 1}
    )
    unknown_ids = [source_id for source_id in selected_source_ids if source_id not in valid_ids]
    missing_required = [
        source_id for source_id in task.required_source_ids if source_id not in selected_set
    ]
    extra_selected = [
        source_id for source_id in selected_source_ids if source_id not in required_ids
    ]
    selected_distractors = [
        source_id for source_id in selected_source_ids if source_id in distractor_ids
    ]
    exact = (
        not duplicate_ids
        and not unknown_ids
        and len(selected_source_ids) == len(task.required_source_ids)
        and selected_set == required_ids
    )
    return {
        "exact_selector_match": exact,
        "required_source_complete": not missing_required,
        "distractors_omitted": not selected_distractors,
        "missing_required_source_ids": missing_required,
        "extra_selected_source_ids": extra_selected,
        "unknown_selected_source_ids": unknown_ids,
        "duplicate_selected_source_ids": duplicate_ids,
        "selected_distractor_source_ids": selected_distractors,
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixture_count": len(runs),
        "selector_exact_match_rate": _rate(run["exact_selector_match"] for run in runs),
        "required_source_completeness_rate": _rate(
            run["required_source_complete"] for run in runs
        ),
        "distractor_rejection_rate": _rate(run["distractors_omitted"] for run in runs),
        "honest_selector_pass_rate": _rate(run["honest_selector_pass"] for run in runs),
        "honest_selector_pass_count": sum(1 for run in runs if run["honest_selector_pass"]),
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "parse_failure_count": sum(1 for run in runs if not run["parse_success"]),
        "average_selector_latency_ms": _average(
            run["latency_ms"] for run in runs if run["latency_ms"] is not None
        ),
        "average_prompt_tokens": _average_usage(runs, "input_tokens"),
        "average_completion_tokens": _average_usage(runs, "output_tokens"),
        "average_total_tokens": _average_usage(runs, "total_tokens"),
        "total_prompt_tokens": _sum_usage(runs, "input_tokens"),
        "total_completion_tokens": _sum_usage(runs, "output_tokens"),
        "total_tokens": _sum_usage(runs, "total_tokens"),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"]
            for run in runs
            if run["token_reduction_percent"] is not None
        ),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Large Real-World OpenAI Selector Smoke",
        "",
        "This is an OpenAI selector smoke test. It tests source selection only, "
        "not end-to-end answer quality.",
        "",
        "Deterministic validation is the source of truth. No oracle fallback is "
        "counted as success.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        "",
        "## Summary",
        "",
        f"Selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}",
        f"Honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}",
        f"Required source completeness rate: {_format_percent(summary['required_source_completeness_rate'])}",
        f"Distractor rejection rate: {_format_percent(summary['distractor_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Parse failure count: {summary['parse_failure_count']}",
        f"Average selector latency ms: {_format_optional_float(summary['average_selector_latency_ms'])}",
        f"Average prompt tokens: {_format_optional_float(summary['average_prompt_tokens'])}",
        f"Average completion tokens: {_format_optional_float(summary['average_completion_tokens'])}",
        f"Average total tokens: {_format_optional_float(summary['average_total_tokens'])}",
        f"Average selected-context token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Fixtures",
        "",
        "| Fixture | Exact match | Honest pass | Selected sources | Required sources | Missing required | Extra/distractor selected | Token reduction |",
        "| --- | ---: | ---: | --- | --- | --- | --- | ---: |",
    ]
    for run in report["runs"]:
        extras = run["extra_selected_source_ids"] or run["selected_distractor_source_ids"]
        lines.append(
            f"| `{run['fixture_id']}` | "
            f"{run['exact_selector_match']} | "
            f"{run['honest_selector_pass']} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{', '.join(run['required_source_ids'])} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(extras) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Large real-world OpenAI selector smoke")
    print(f"router model: {report['metadata']['router_model']}")
    print(f"selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}")
    print(f"honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}")
    print(f"fallback count: {summary['fallback_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(
        "average selected-context token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _full_context_tokens(task: LargeRealWorldTask) -> int:
    return sum(_source_tokens(task, source.source_id) for source in task.sources)


def _selected_context_tokens(task: LargeRealWorldTask, selected_source_ids: list[str]) -> int:
    return sum(_source_tokens(task, source_id) for source_id in selected_source_ids if _known(task, source_id))


def _source_tokens(task: LargeRealWorldTask, source_id: str) -> int:
    return estimate_text_tokens(format_source(source_by_id(task, source_id)))


def _known(task: LargeRealWorldTask, source_id: str) -> bool:
    return any(source.source_id == source_id for source in task.sources)


def _extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message", {})
    if isinstance(message, dict) and message.get("content") is not None:
        return str(message["content"]).strip()
    if first_choice.get("text") is not None:
        return str(first_choice["text"]).strip()
    return ""


def _extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _optional_int(usage.get("prompt_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _extract_latency_ms(response: dict[str, Any]) -> int | None:
    metadata = response.get("openai_api")
    if isinstance(metadata, dict) and metadata.get("latency_ms") is not None:
        return int(metadata["latency_ms"])
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def _average(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def _sum_usage(runs: list[dict[str, Any]], key: str) -> int | None:
    values = [run["usage"].get(key) for run in runs if run["usage"].get(key) is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def _average_usage(runs: list[dict[str, Any]], key: str) -> float | None:
    return _average(run["usage"].get(key) for run in runs)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    main()
