"""Run the NoteKeeper full-context OpenAI API baseline.

This runner intentionally bypasses SFE routing, discovery, and context
reduction. Each task receives the complete project brief plus the complete app
snapshot generated so far.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (  # noqa: E402
    MissingOpenAIAPIKeyError,
    OpenAIAPIProvider,
    PROVIDER_NAME,
)
from runtime.metrics import write_json_report, write_text_report  # noqa: E402
from sfe.env import load_repo_env  # noqa: E402


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_MAX_OUTPUT_TOKENS = 20_000
DEFAULT_TIMEOUT_SECONDS = 300.0
SCENARIO_NAME = "baseline_full_context_gpt54"
SCENARIO_DESCRIPTION = "Baseline full-context run with gpt-5.4 only, without SFE."

NOTEKEEPER_ROOT = PROJECT_ROOT / "examples" / "NoteKeeper"
BRIEF_DIR = NOTEKEEPER_ROOT / "00_project_brief"
SCENARIO_DIR = NOTEKEEPER_ROOT / "10_baseline_full_context_gpt54"
APP_DIR = SCENARIO_DIR / "app"
RUNS_DIR = SCENARIO_DIR / "runs"
TOKEN_USAGE_PATH = SCENARIO_DIR / "token_usage.json"
REPORT_PATH = SCENARIO_DIR / "report.md"

PRODUCT_PROMPT_PATH = BRIEF_DIR / "prompt.md"
ACCEPTANCE_CRITERIA_PATH = BRIEF_DIR / "acceptance_criteria.md"
TASK_SEQUENCE_PATH = BRIEF_DIR / "task_sequence.md"

REQUIRED_APP_FILES = ("index.html", "styles.css", "app.js", "README.md")
EXPECTED_TASKS = (
    ("01_initial_scaffold", "Initial static scaffold"),
    ("02_persistence_and_crud", "LocalStorage persistence and CRUD"),
    ("03_labels_search_archive", "Labels, search, and archive"),
    ("04_checklists_and_pinning", "Checklist notes and pinning"),
    ("05_responsive_polish", "Responsive polish, accessibility pass, and README"),
)


class NoteKeeperBaselineError(RuntimeError):
    """Raised for runner validation and execution failures."""


@dataclass(frozen=True)
class TaskInstruction:
    task_id: str
    title: str
    heading: str
    body: str


@dataclass(frozen=True)
class ParsedSnapshot:
    files: dict[str, str]
    notes: str | None


def main() -> int:
    load_repo_env()
    args = _parse_args()
    try:
        config = _validate_args(args)
        context = load_benchmark_context()
        validate_benchmark_layout(context.tasks)
        if config["dry_run_validate_inputs"]:
            _print_dry_run_success(config, context)
            return 0
        if not os.getenv("OPENAI_API_KEY"):
            raise MissingOpenAIAPIKeyError("OPENAI_API_KEY is required for NoteKeeper baseline.")
        run_baseline(context=context, config=config)
        return 0
    except NoteKeeperBaselineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MissingOpenAIAPIKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the NoteKeeper full-context OpenAI API baseline without SFE "
            "routing, discovery, or context reduction."
        )
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--dry-run-validate-inputs",
        action="store_true",
        help="Validate local benchmark inputs and prompt construction without calling the API.",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> dict[str, Any]:
    model = str(args.model or "").strip()
    if not model:
        raise NoteKeeperBaselineError("--model must not be empty.")
    if args.max_output_tokens < 1:
        raise NoteKeeperBaselineError("--max-output-tokens must be at least 1.")
    if args.timeout <= 0:
        raise NoteKeeperBaselineError("--timeout must be greater than 0.")
    return {
        "model": model,
        "max_output_tokens": int(args.max_output_tokens),
        "timeout": float(args.timeout),
        "dry_run_validate_inputs": bool(args.dry_run_validate_inputs),
    }


@dataclass(frozen=True)
class BenchmarkContext:
    product_prompt: str
    acceptance_criteria: str
    task_sequence: str
    tasks: tuple[TaskInstruction, ...]


def load_benchmark_context() -> BenchmarkContext:
    product_prompt = _read_required_text(PRODUCT_PROMPT_PATH)
    acceptance_criteria = _read_required_text(ACCEPTANCE_CRITERIA_PATH)
    task_sequence = _read_required_text(TASK_SEQUENCE_PATH)
    tasks = parse_task_sequence(task_sequence)
    return BenchmarkContext(
        product_prompt=product_prompt,
        acceptance_criteria=acceptance_criteria,
        task_sequence=task_sequence,
        tasks=tasks,
    )


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise NoteKeeperBaselineError(f"Required file is missing: {_rel(path)}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise NoteKeeperBaselineError(f"Required file is empty: {_rel(path)}")
    return text


def parse_task_sequence(task_sequence: str) -> tuple[TaskInstruction, ...]:
    matches = list(re.finditer(r"^##\s+(\d+)\.\s+(.+?)\s*$", task_sequence, flags=re.MULTILINE))
    tasks: list[TaskInstruction] = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(task_sequence)
        body = task_sequence[start:end].strip()
        if not body:
            raise NoteKeeperBaselineError(f"Task {number} has no body in task_sequence.md.")
        expected_id, expected_title = EXPECTED_TASKS[number - 1] if 1 <= number <= len(EXPECTED_TASKS) else ("", "")
        if not expected_id or title != expected_title:
            raise NoteKeeperBaselineError(
                f"Unexpected task heading {number}: {title!r}; expected {expected_title!r}."
            )
        tasks.append(
            TaskInstruction(
                task_id=expected_id,
                title=title,
                heading=match.group(0).strip(),
                body=body,
            )
        )
    if len(tasks) != len(EXPECTED_TASKS):
        raise NoteKeeperBaselineError(
            f"Expected {len(EXPECTED_TASKS)} tasks in task_sequence.md, found {len(tasks)}."
        )
    return tuple(tasks)


def validate_benchmark_layout(tasks: tuple[TaskInstruction, ...]) -> None:
    for path in (BRIEF_DIR, SCENARIO_DIR, APP_DIR, RUNS_DIR):
        if not path.is_dir():
            raise NoteKeeperBaselineError(f"Required directory is missing: {_rel(path)}")
    for path in (TOKEN_USAGE_PATH, REPORT_PATH):
        if not path.is_file():
            raise NoteKeeperBaselineError(f"Required scenario file is missing: {_rel(path)}")
    for task in tasks:
        run_dir = RUNS_DIR / task.task_id
        if not run_dir.is_dir():
            raise NoteKeeperBaselineError(f"Required task run directory is missing: {_rel(run_dir)}")
    unexpected = [
        path.name
        for path in APP_DIR.iterdir()
        if path.is_file() and path.name not in REQUIRED_APP_FILES and path.name != ".gitkeep"
    ]
    if unexpected:
        raise NoteKeeperBaselineError(
            "Unexpected files already exist in app directory: " + ", ".join(sorted(unexpected))
        )


def run_baseline(*, context: BenchmarkContext, config: dict[str, Any]) -> None:
    provider = OpenAIAPIProvider(timeout=config["timeout"])
    APP_DIR.mkdir(parents=True, exist_ok=True)
    run_results: list[dict[str, Any]] = []
    generated_files: list[str] = []
    failed = False

    for task in context.tasks:
        result = execute_task(provider=provider, context=context, task=task, config=config)
        run_results.append(result)
        generated_files = list(result.get("generated_or_modified_files") or generated_files)
        if not result["success"]:
            failed = True
            break

    write_token_usage(run_results, config)
    write_report(run_results, config)
    if failed:
        raise NoteKeeperBaselineError(
            "Baseline run failed; see task run.json and response_raw.txt for diagnostics."
        )
    print("success: true")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"model: {config['model']}")
    print("generated_files:")
    for path in generated_files:
        print(f"- {path}")


def execute_task(
    *,
    provider: OpenAIAPIProvider,
    context: BenchmarkContext,
    task: TaskInstruction,
    config: dict[str, Any],
) -> dict[str, Any]:
    run_dir = RUNS_DIR / task.task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_task_prompt(context=context, task=task, app_files=read_current_app_files())
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    response_text = ""
    response: dict[str, Any] = {}
    parsed_snapshot: ParsedSnapshot | None = None
    parsing_error = ""
    provider_error = ""
    generated_files: list[str] = []
    started = time.perf_counter()
    success = False

    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=config["model"],
            max_tokens=config["max_output_tokens"],
            temperature=None,
            system_instruction=(
                "You are generating a small static web app benchmark artifact. "
                "Return only strict JSON matching the requested schema."
            ),
            provider_role="notekeeper_baseline_executor",
        )
        response_text = extract_response_text(response)
        parsed_snapshot = parse_model_snapshot(response_text)
        write_app_snapshot(parsed_snapshot.files)
        generated_files = [_rel(APP_DIR / filename) for filename in REQUIRED_APP_FILES]
        success = True
    except Exception as exc:
        if isinstance(exc, NoteKeeperBaselineError):
            parsing_error = str(exc)
        else:
            provider_error = _safe_error_message(exc)
    latency_ms = extract_latency_ms(response)
    if latency_ms is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
    usage = extract_usage(response)

    (run_dir / "response_raw.txt").write_text(response_text, encoding="utf-8")
    if parsed_snapshot is not None:
        write_json_report(
            run_dir / "parsed_files.json",
            {
                "files": [
                    {"path": filename, "content": parsed_snapshot.files[filename]}
                    for filename in REQUIRED_APP_FILES
                ],
                "notes": parsed_snapshot.notes,
            },
        )
    run_record = {
        "task_id": task.task_id,
        "task_title": task.title,
        "provider": PROVIDER_NAME,
        "model": config["model"],
        "input_tokens": usage["input_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "total_estimated_cost": None,
        "currency": None,
        "latency_or_wall_clock_duration": latency_ms,
        "latency_ms": latency_ms,
        "success": success,
        "generated_or_modified_files": generated_files,
        "manual_verification_notes": None,
        "parsing_error": parsing_error or None,
        "provider_error": provider_error or None,
        "response_text_length": len(response_text),
        "api_error_retry_count": _metadata_int(response, "api_error_retry_count"),
    }
    write_json_report(run_dir / "run.json", run_record)
    return run_record


def build_task_prompt(
    *,
    context: BenchmarkContext,
    task: TaskInstruction,
    app_files: dict[str, str | None],
) -> str:
    current_files = "\n\n".join(
        _format_current_file(filename, app_files.get(filename)) for filename in REQUIRED_APP_FILES
    )
    return (
        "# NoteKeeper full-context baseline task\n\n"
        "You are executing one task in a five-step benchmark. This is the baseline "
        "run: use the full context below. Do not use SFE routing, discovery, or "
        "context reduction.\n\n"
        "Return only strict JSON with this exact shape:\n\n"
        "```json\n"
        "{\n"
        '  "files": [\n'
        '    {"path": "index.html", "content": "..."},\n'
        '    {"path": "styles.css", "content": "..."},\n'
        '    {"path": "app.js", "content": "..."},\n'
        '    {"path": "README.md", "content": "..."}\n'
        "  ],\n"
        '  "notes": "optional short implementation notes"\n'
        "}\n"
        "```\n\n"
        "Rules for your response:\n"
        "- Return JSON only, with no markdown fences or explanatory text.\n"
        "- Include exactly the four required files.\n"
        "- Use only these paths: index.html, styles.css, app.js, README.md.\n"
        "- Provide complete replacement contents for every file on every task.\n"
        "- Do not include external dependencies, package files, server code, or extra files.\n"
        "- The app must remain runnable by opening index.html directly in a browser.\n\n"
        "## Product brief\n\n"
        f"{context.product_prompt}\n\n"
        "## Acceptance criteria\n\n"
        f"{context.acceptance_criteria}\n\n"
        "## Full task sequence\n\n"
        f"{context.task_sequence}\n\n"
        "## Current task\n\n"
        f"{task.heading}\n\n{task.body}\n\n"
        "## Current generated app files\n\n"
        f"{current_files}\n"
    )


def _format_current_file(filename: str, content: str | None) -> str:
    if content is None:
        return f"### {filename}\n\nFile does not exist yet."
    return f"### {filename}\n\n```text\n{content}\n```"


def read_current_app_files() -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for filename in REQUIRED_APP_FILES:
        path = APP_DIR / filename
        files[filename] = path.read_text(encoding="utf-8") if path.is_file() else None
    return files


def parse_model_snapshot(response_text: str) -> ParsedSnapshot:
    if not response_text.strip():
        raise NoteKeeperBaselineError("Model returned an empty response.")
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise NoteKeeperBaselineError(f"Model response is not strict JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NoteKeeperBaselineError("Model response JSON must be an object.")
    unexpected_keys = set(payload) - {"files", "notes"}
    if unexpected_keys:
        raise NoteKeeperBaselineError(
            "Model response has unexpected top-level keys: " + ", ".join(sorted(unexpected_keys))
        )
    files_payload = payload.get("files")
    if not isinstance(files_payload, list):
        raise NoteKeeperBaselineError('Model response must contain a "files" array.')
    files: dict[str, str] = {}
    for index, item in enumerate(files_payload):
        if not isinstance(item, dict):
            raise NoteKeeperBaselineError(f"files[{index}] must be an object.")
        if set(item) != {"path", "content"}:
            raise NoteKeeperBaselineError(f"files[{index}] must contain exactly path and content.")
        path = item["path"]
        content = item["content"]
        if not isinstance(path, str):
            raise NoteKeeperBaselineError(f"files[{index}].path must be a string.")
        if not isinstance(content, str):
            raise NoteKeeperBaselineError(f"files[{index}].content must be a string.")
        normalized_path = validate_app_file_path(path)
        if normalized_path in files:
            raise NoteKeeperBaselineError(f"Duplicate file path in model response: {normalized_path}")
        files[normalized_path] = content
    missing = set(REQUIRED_APP_FILES) - set(files)
    extra = set(files) - set(REQUIRED_APP_FILES)
    if missing:
        raise NoteKeeperBaselineError("Model response is missing files: " + ", ".join(sorted(missing)))
    if extra:
        raise NoteKeeperBaselineError("Model response includes extra files: " + ", ".join(sorted(extra)))
    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise NoteKeeperBaselineError("notes must be a string when provided.")
    return ParsedSnapshot(files={filename: files[filename] for filename in REQUIRED_APP_FILES}, notes=notes)


def validate_app_file_path(path: str) -> str:
    if not path:
        raise NoteKeeperBaselineError("File path must not be empty.")
    path_obj = Path(path)
    if path_obj.is_absolute():
        raise NoteKeeperBaselineError(f"Absolute file paths are not allowed: {path}")
    if "\\" in path:
        raise NoteKeeperBaselineError(f"Backslash paths are not allowed: {path}")
    if "/" in path:
        raise NoteKeeperBaselineError(f"Subdirectories are not allowed: {path}")
    if path_obj.name != path or path_obj.name in (".", "..") or ".." in path_obj.parts:
        raise NoteKeeperBaselineError(f"Directory traversal is not allowed: {path}")
    if path not in REQUIRED_APP_FILES:
        raise NoteKeeperBaselineError(f"Unexpected file path: {path}")
    return path


def write_app_snapshot(files: dict[str, str]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    gitkeep = APP_DIR / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()
    for existing in APP_DIR.iterdir():
        if existing.is_dir():
            raise NoteKeeperBaselineError(f"Refusing to leave unexpected app directory: {_rel(existing)}")
        if existing.is_file() and existing.name not in REQUIRED_APP_FILES:
            raise NoteKeeperBaselineError(f"Refusing to leave unexpected app file: {_rel(existing)}")
    for filename, content in files.items():
        (APP_DIR / filename).write_text(content, encoding="utf-8")


def write_token_usage(run_results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    runs = []
    for result in run_results:
        runs.append(
            {
                "task_id": result["task_id"],
                "provider": result["provider"],
                "models": {
                    "primary": config["model"],
                    "router": None,
                    "discovery": None,
                    "executor": config["model"],
                    "reviewer": None,
                },
                "input_tokens": result["input_tokens"],
                "cached_input_tokens": result["cached_input_tokens"],
                "output_tokens": result["output_tokens"],
                "total_estimated_cost": None,
                "currency": None,
                "latency_or_wall_clock_duration": result["latency_or_wall_clock_duration"],
                "success": result["success"],
                "generated_or_modified_files": result["generated_or_modified_files"],
                "manual_verification_notes": result["manual_verification_notes"],
                "parsing_error": result["parsing_error"],
                "provider_error": result["provider_error"],
            }
        )
    write_json_report(
        TOKEN_USAGE_PATH,
        {
            "scenario": SCENARIO_NAME,
            "description": SCENARIO_DESCRIPTION,
            "runs": runs,
            "totals": {
                "input_tokens": _sum_optional(result["input_tokens"] for result in run_results),
                "cached_input_tokens": _sum_optional(
                    result["cached_input_tokens"] for result in run_results
                ),
                "output_tokens": _sum_optional(result["output_tokens"] for result in run_results),
                "total_estimated_cost": None,
                "currency": None,
                "latency_or_wall_clock_duration": _sum_optional(
                    result["latency_or_wall_clock_duration"] for result in run_results
                ),
            },
        },
    )


def write_report(run_results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_success = all(result["success"] for result in run_results)
    lines = [
        "# Baseline full context gpt-5.4 report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## Scenario",
        "",
        "- Workflow: full-context baseline without SFE.",
        f"- Provider: `{PROVIDER_NAME}`.",
        f"- Model: `{config['model']}`.",
        "- Routing: disabled.",
        "- Discovery: disabled.",
        "- Context reduction: disabled.",
        "- Project brief: `../00_project_brief/prompt.md`.",
        "- Task sequence: `../00_project_brief/task_sequence.md`.",
        "",
        "## Result",
        "",
        f"- Success: `{str(all_success).lower()}`.",
        "- Total estimated cost: `null`.",
        "- Manual verification: not performed by this runner.",
        "",
        "## Task Runs",
        "",
        "| Task | Success | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in run_results:
        error = result["parsing_error"] or result["provider_error"] or ""
        lines.append(
            f"| `{result['task_id']}` | `{str(result['success']).lower()}` | "
            f"{_format_optional(result['input_tokens'])} | "
            f"{_format_optional(result['cached_input_tokens'])} | "
            f"{_format_optional(result['output_tokens'])} | "
            f"{_format_optional(result['latency_ms'])} | "
            f"{_markdown_cell(error)} |"
        )
    lines.extend(
        [
            "",
            "## Generated Files",
            "",
            *(f"- `{path}`" for path in _final_generated_file_list()),
            "",
            "## Notes",
            "",
            "Task-level prompts, raw responses, parsed file snapshots, and run metadata are stored under `runs/<task>/`.",
        ]
    )
    write_text_report(REPORT_PATH, "\n".join(lines) + "\n")


def extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
            if first.get("text") is not None:
                return str(first["text"]).strip()
    return ""


def extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _optional_int(usage.get("prompt_tokens"))
    cached_input_tokens = _optional_int(usage.get("cached_input_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def extract_latency_ms(response: dict[str, Any]) -> int | None:
    metadata = response.get("openai_api")
    if isinstance(metadata, dict):
        return _optional_int(metadata.get("latency_ms"))
    return None


def _metadata_int(response: dict[str, Any], key: str) -> int | None:
    metadata = response.get("openai_api")
    if isinstance(metadata, dict):
        return _optional_int(metadata.get(key))
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _sum_optional(values: Any) -> int | None:
    numbers = [int(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers)


def _final_generated_file_list() -> list[str]:
    return [_rel(APP_DIR / filename) for filename in REQUIRED_APP_FILES if (APP_DIR / filename).is_file()]


def _format_optional(value: Any) -> str:
    if value is None:
        return "`null`"
    return str(value)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def _print_dry_run_success(config: dict[str, Any], context: BenchmarkContext) -> None:
    prompt_lengths = [
        len(build_task_prompt(context=context, task=task, app_files=read_current_app_files()))
        for task in context.tasks
    ]
    print("success: true")
    print("mode: dry-run-validate-inputs")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"model: {config['model']}")
    print(f"task_count: {len(context.tasks)}")
    print(f"required_app_files: {', '.join(REQUIRED_APP_FILES)}")
    print(f"prompt_char_lengths: {', '.join(str(length) for length in prompt_lengths)}")
    print("api_called: false")


def _rel(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
