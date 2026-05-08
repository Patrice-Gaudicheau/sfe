"""Run a small Lemonade execution comparison for Cognitive Map payloads."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cognitive_map import CognitiveWorkspace
from cognitive_map.zones import CognitiveZone
from providers.lemonade import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, LemonadeProvider
from router.mock_router import route
from runtime.run_cognitive_map_benchmark import _estimate_tokens
from runtime.run_experiment import (
    DEFAULT_EXECUTION_MODEL,
    _build_execution_prompt,
    _extract_response_text,
)


DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "logs" / "cognitive_map_real_benchmark.jsonl"
COGNITIVE_MAP_ZONE_BUILDER_MODES = ("deterministic", "llm_intent")
ZONE_INTENT_TASK_LABELS = {
    "analysis",
    "writing",
    "coding",
    "review",
    "multi_context",
    "other",
}
VISIBLE_ANSWER_INSTRUCTION = (
    "/no_think\n"
    "Return only a concise visible final answer. No reasoning, scratchpad, or "
    "chain-of-thought."
)
MIN_GENERIC_OUTPUT_WORDS = 5
KNOWN_TASK_LABELS = {
    "writing",
    "analysis",
    "review",
    "coding",
    "debugging",
    "summarization",
    "classification",
    "planning",
    "constraint_following",
    "multi_context",
}

REAL_BENCHMARK_TASKS: list[dict[str, str]] = [
    {
        "task_label": "writing",
        "task": (
            "Write a concise project update about the Spatial Field Engine "
            "Cognitive Map prototype and mention one concrete next step."
        ),
    },
    {
        "task_label": "analysis",
        "task": (
            "Compare explicit spatial prompt metadata with a structured Cognitive "
            "Map workspace for traceability and auditability."
        ),
    },
    {
        "task_label": "review",
        "task": (
            "Review the Cognitive Map micro-benchmark design and identify two "
            "small validation risks."
        ),
    },
    {
        "task_label": "coding",
        "task": (
            "Write a tiny Python function that returns True when a result has "
            "success set to True."
        ),
    },
    {
        "task_label": "debugging",
        "task": (
            "Explain the minimal fix for a counter that can divide by zero when "
            "run_count is zero."
        ),
    },
    {
        "task_label": "summarization",
        "task": (
            "Summarize the purpose of a Cognitive Map benchmark in two short "
            "sentences."
        ),
    },
    {
        "task_label": "classification",
        "task": (
            "Classify this task as writing, analysis, coding, review, or "
            "planning: check whether benchmark output includes latency."
        ),
    },
    {
        "task_label": "planning",
        "task": (
            "List three compact steps for validating a deterministic benchmark "
            "before running it live."
        ),
    },
    {
        "task_label": "constraint_following",
        "task": (
            "Answer in exactly two bullet points about why concise prompts help "
            "runtime benchmarks."
        ),
    },
    {
        "task_label": "multi_context",
        "task": (
            "Explain how intent, constraints, execution, verification, and final "
            "output relate in the SFE benchmark."
        ),
    },
]


def main() -> None:
    args = _parse_args()
    zone_router_model = args.zone_router_model or args.model
    zone_router_base_url = args.zone_router_base_url or args.base_url
    results = run_real_benchmark(
        tasks=_limit_tasks(REAL_BENCHMARK_TASKS, args.limit_tasks),
        model=args.model,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        dry_run=args.dry_run,
        repeat=args.repeat,
        max_reflection_attempts=args.max_reflection_attempts,
        cognitive_map_zone_builder=args.cognitive_map_zone_builder,
        zone_router_model=zone_router_model,
        zone_router_base_url=zone_router_base_url,
        zone_router_api_key=args.zone_router_api_key,
        zone_router_timeout_seconds=args.zone_router_timeout_seconds,
    )
    write_jsonl(args.output_path, results)
    print_report(results, args.output_path, dry_run=args.dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("SFE_EXECUTOR_MODEL") or DEFAULT_EXECUTION_MODEL,
        help="Lemonade model id.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_BASE_URL,
        help="Lemonade OpenAI-compatible base URL.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lemonade request timeout.",
    )
    parser.add_argument(
        "--limit-tasks",
        type=int,
        help="Run only the first N fixed benchmark tasks.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for JSONL benchmark results.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads and metrics without calling Lemonade.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run the selected task set N times.",
    )
    parser.add_argument(
        "--max-reflection-attempts",
        type=int,
        default=1,
        help="Maximum Cognitive Map retry attempts after deterministic verification fails.",
    )
    parser.add_argument(
        "--cognitive-map-zone-builder",
        choices=COGNITIVE_MAP_ZONE_BUILDER_MODES,
        default="deterministic",
        help="Cognitive Map zone population mode.",
    )
    parser.add_argument(
        "--zone-router-model",
        default=os.getenv("SFE_ZONE_ROUTER_MODEL"),
        help="Lemonade-compatible model id used for LLM-populated zones.",
    )
    parser.add_argument(
        "--zone-router-base-url",
        default=os.getenv("SFE_ZONE_ROUTER_BASE_URL"),
        help="Lemonade OpenAI-compatible base URL for the zone router.",
    )
    parser.add_argument(
        "--zone-router-api-key",
        default=os.getenv("SFE_ZONE_ROUTER_API_KEY"),
        help="API key for the zone router endpoint.",
    )
    parser.add_argument(
        "--zone-router-timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Zone router request timeout.",
    )
    return parser.parse_args()


def run_real_benchmark(
    tasks: list[dict[str, str]],
    model: str,
    base_url: str,
    timeout_seconds: float,
    dry_run: bool = False,
    repeat: int = 1,
    max_reflection_attempts: int = 1,
    cognitive_map_zone_builder: str = "deterministic",
    zone_router_model: str | None = None,
    zone_router_base_url: str | None = None,
    zone_router_api_key: str | None = None,
    zone_router_timeout_seconds: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    if timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0.")
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if max_reflection_attempts < 0:
        raise ValueError("--max-reflection-attempts must be at least 0.")
    if cognitive_map_zone_builder not in COGNITIVE_MAP_ZONE_BUILDER_MODES:
        raise ValueError(
            "--cognitive-map-zone-builder must be deterministic or llm_intent."
        )
    if zone_router_timeout_seconds <= 0:
        raise ValueError("--zone-router-timeout-seconds must be greater than 0.")

    provider = None
    if not dry_run:
        provider = LemonadeProvider(base_url=base_url)
        provider.timeout = timeout_seconds

    resolved_zone_router_model = zone_router_model or model
    resolved_zone_router_base_url = zone_router_base_url or base_url
    zone_router_provider = None
    if not dry_run and cognitive_map_zone_builder == "llm_intent":
        zone_router_provider = LemonadeProvider(
            base_url=resolved_zone_router_base_url,
            api_key=zone_router_api_key,
        )
        zone_router_provider.timeout = zone_router_timeout_seconds

    results = []
    for repeat_index in range(1, repeat + 1):
        for task in tasks:
            for mode in ("explicit_metadata", "cognitive_map"):
                payload_data = build_payload(
                    task,
                    mode,
                    cognitive_map_zone_builder=cognitive_map_zone_builder,
                    zone_router_provider=zone_router_provider,
                    zone_router_model=resolved_zone_router_model,
                    dry_run=dry_run,
                )
                results.append(
                    execute_payload(
                        task_label=task["task_label"],
                        mode=mode,
                        payload_data=payload_data,
                        provider=provider,
                        model=model,
                        base_url=base_url,
                        dry_run=dry_run,
                        repeat_index=repeat_index,
                        max_reflection_attempts=max_reflection_attempts,
                    )
                )
    return results


def build_payload(
    task: dict[str, str],
    mode: str,
    cognitive_map_zone_builder: str = "deterministic",
    zone_router_provider: LemonadeProvider | None = None,
    zone_router_model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if mode == "explicit_metadata":
        routing_decision = route(task["task"])
        prompt = _build_execution_prompt(task["task"], routing_decision, "spatial")
        return {
            "audit_text": prompt,
            "llm_payload": prompt,
            "task_prompt": task["task"],
            "comparison_mode": "explicit_metadata",
            "trace_available": False,
            "handoff_count": 0,
            "routing_task_type": routing_decision["task_type"],
            "routing_role": routing_decision["role"],
            "zone_builder_metrics": _not_applicable_zone_builder_metrics(),
        }

    if mode == "cognitive_map":
        if cognitive_map_zone_builder not in COGNITIVE_MAP_ZONE_BUILDER_MODES:
            raise ValueError(
                "--cognitive-map-zone-builder must be deterministic or llm_intent."
            )
        workspace = CognitiveWorkspace()
        workspace.run_minimal_flow(
            task["task"], constraints=_default_constraints(task)
        )
        builder_metrics = _deterministic_zone_builder_metrics()
        if cognitive_map_zone_builder == "llm_intent":
            builder_result = build_llm_user_intent_zone(
                task_prompt=task["task"],
                deterministic_zone=workspace.zones["user_intent_zone"],
                provider=zone_router_provider,
                model=zone_router_model or "",
                dry_run=dry_run,
            )
            builder_metrics = builder_result["metrics"]
            if builder_result["zone"] is not None:
                workspace.zones["user_intent_zone"] = builder_result["zone"]

        snapshot = workspace.snapshot()
        llm_payload = build_executor_payload(workspace, task["task_label"])
        return {
            "audit_text": json.dumps(snapshot, sort_keys=True),
            "llm_payload": llm_payload,
            "task_prompt": task["task"],
            "comparison_mode": f"cognitive_map_{cognitive_map_zone_builder}",
            "trace_available": bool(snapshot["handoff_trace"]),
            "handoff_count": len(snapshot["handoff_trace"]),
            "fragment_hashes": [
                entry["fragment_hash"] for entry in snapshot["handoff_trace"]
            ],
            "zone_builder_metrics": builder_metrics,
        }

    raise ValueError(f"Unknown benchmark mode: {mode}")


def build_llm_user_intent_zone(
    task_prompt: str,
    deterministic_zone: CognitiveZone,
    provider: LemonadeProvider | None,
    model: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Build user_intent_zone from one strict JSON router call, with fallback."""

    started = time.perf_counter()
    response: dict[str, Any] = {}
    latency_ms = 0
    fallback_reason = ""

    try:
        if dry_run:
            fallback_reason = "dry_run_skipped_zone_router"
            return {
                "zone": None,
                "metrics": _llm_zone_builder_metrics(
                    model=model,
                    latency_ms=0,
                    usage=_zero_token_usage(),
                    success=False,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                ),
            }
        if provider is None:
            fallback_reason = "missing_zone_router_provider"
            return {
                "zone": None,
                "metrics": _llm_zone_builder_metrics(
                    model=model,
                    latency_ms=0,
                    usage=_zero_token_usage(),
                    success=False,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                ),
            }

        response = provider.chat(
            _zone_router_messages(task_prompt),
            model=model,
            max_tokens=160,
            temperature=0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = _zero_missing_token_usage(response)
        content = _extract_response_text(response).strip()
        validation = _validate_intent_router_json(content, task_prompt=task_prompt)
        if not validation["ok"]:
            fallback_reason = str(validation["reason"])
            return {
                "zone": None,
                "metrics": _llm_zone_builder_metrics(
                    model=model,
                    latency_ms=latency_ms,
                    usage=usage,
                    success=False,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                ),
            }

        return {
            "zone": _build_user_intent_zone_from_router_json(
                task_prompt=task_prompt,
                deterministic_zone=deterministic_zone,
                parsed=validation["parsed"],
            ),
            "metrics": _llm_zone_builder_metrics(
                model=model,
                latency_ms=latency_ms,
                usage=usage,
                success=True,
                fallback_used=False,
                fallback_reason="",
            ),
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "zone": None,
            "metrics": _llm_zone_builder_metrics(
                model=model,
                latency_ms=latency_ms,
                usage=_zero_missing_token_usage(response),
                success=False,
                fallback_used=True,
                fallback_reason=f"zone_router_exception: {exc}",
            ),
        }


def _zone_router_messages(task_prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Classify the user task for a Cognitive Map user_intent_zone. "
                "Return JSON only. No markdown. No explanations."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return exactly this JSON object shape:\n"
                '{"intent":"short natural-language intent",'
                '"task_label":"analysis|writing|coding|review|multi_context|other",'
                '"constraints":["explicit constraint 1"]}\n'
                "Rules: task_label must be one allowed enum value. constraints "
                "must contain only explicit constraints found in the task, not "
                "invented constraints. Keep strings short.\n\n"
                f"Task:\n{task_prompt}"
            ),
        },
    ]


def _validate_intent_router_json(content: str, task_prompt: str) -> dict[str, Any]:
    if not content:
        return {"ok": False, "reason": "empty_zone_router_content"}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "invalid_json"}

    if not isinstance(parsed, dict):
        return {"ok": False, "reason": "json_not_object"}
    expected_keys = {"intent", "task_label", "constraints"}
    if set(parsed) != expected_keys:
        return {"ok": False, "reason": "unexpected_json_schema"}
    if not isinstance(parsed["intent"], str) or not parsed["intent"].strip():
        return {"ok": False, "reason": "invalid_intent"}
    if parsed["task_label"] not in ZONE_INTENT_TASK_LABELS:
        return {"ok": False, "reason": "unknown_task_label"}
    constraints = parsed["constraints"]
    if not isinstance(constraints, list) or not all(
        isinstance(item, str) for item in constraints
    ):
        return {"ok": False, "reason": "invalid_constraints"}

    parsed["intent"] = parsed["intent"].strip()
    parsed["constraints"] = [item.strip() for item in constraints if item.strip()]
    normalized_task = task_prompt.lower()
    if any(item.lower() not in normalized_task for item in parsed["constraints"]):
        return {"ok": False, "reason": "constraint_not_in_input"}
    return {"ok": True, "parsed": parsed}


def _build_user_intent_zone_from_router_json(
    task_prompt: str,
    deterministic_zone: CognitiveZone,
    parsed: dict[str, Any],
) -> CognitiveZone:
    zone = CognitiveZone(
        name="user_intent_zone",
        activation_level=deterministic_zone.activation_level,
        allowed_operations=list(deterministic_zone.allowed_operations),
        suppressed_operations=list(deterministic_zone.suppressed_operations),
        handoff_rules={
            operation: list(targets)
            for operation, targets in deterministic_zone.handoff_rules.items()
        },
    )
    zone.add_input_fragment(task_prompt)
    zone.add_output_fragment(f"Intent extracted from router: {parsed['intent']}")
    zone.add_output_fragment(f"Router task label: {parsed['task_label']}")
    for constraint in parsed["constraints"]:
        zone.add_output_fragment(f"Explicit user constraint: {constraint}")
    return zone


def _not_applicable_zone_builder_metrics() -> dict[str, Any]:
    return {
        "zone_builder_mode": "not_applicable",
        "zone_builder_model": "",
        "zone_builder_latency_ms": 0,
        "zone_builder_prompt_tokens": 0,
        "zone_builder_completion_tokens": 0,
        "zone_builder_total_tokens": 0,
        "zone_builder_success": True,
        "zone_builder_fallback_used": False,
        "zone_builder_fallback_reason": "",
    }


def _deterministic_zone_builder_metrics() -> dict[str, Any]:
    return {
        "zone_builder_mode": "deterministic",
        "zone_builder_model": "",
        "zone_builder_latency_ms": 0,
        "zone_builder_prompt_tokens": 0,
        "zone_builder_completion_tokens": 0,
        "zone_builder_total_tokens": 0,
        "zone_builder_success": True,
        "zone_builder_fallback_used": False,
        "zone_builder_fallback_reason": "",
    }


def _llm_zone_builder_metrics(
    model: str,
    latency_ms: int,
    usage: dict[str, int],
    success: bool,
    fallback_used: bool,
    fallback_reason: str,
) -> dict[str, Any]:
    return {
        "zone_builder_mode": "llm_intent",
        "zone_builder_model": model,
        "zone_builder_latency_ms": latency_ms,
        "zone_builder_prompt_tokens": usage["prompt_tokens"],
        "zone_builder_completion_tokens": usage["completion_tokens"],
        "zone_builder_total_tokens": usage["total_tokens"],
        "zone_builder_success": success,
        "zone_builder_fallback_used": fallback_used,
        "zone_builder_fallback_reason": fallback_reason,
    }


def _zero_missing_token_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = _provider_token_usage(response)
    # Some Lemonade-compatible servers omit usage. Builder token fields use zero
    # for unavailable values so combined benchmark fields stay numeric; reports
    # call out that this may undercount router cost for those providers.
    return {
        "prompt_tokens": usage["prompt_tokens"] or 0,
        "completion_tokens": usage["completion_tokens"] or 0,
        "total_tokens": usage["total_tokens"] or 0,
    }


def _zero_token_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def build_executor_payload(workspace: CognitiveWorkspace, task_label: str) -> str:
    """Build a compact task-specific executor prompt from Cognitive Map zones."""

    task_instruction = _first_fragment(
        workspace.zones["user_intent_zone"].input_fragments
    )
    constraints = _task_constraints(workspace)
    verification_hint = _first_matching_fragment(
        workspace.zones["verification_zone"].input_fragments,
        "Checked that",
    )
    special_instructions = _task_specific_instructions(task_instruction)

    sections = [
        VISIBLE_ANSWER_INSTRUCTION,
        f"Task label: {task_label}",
        f"Task: {task_instruction}",
    ]
    if constraints:
        sections.append("Constraints:\n" + "\n".join(f"- {item}" for item in constraints))
    if verification_hint:
        sections.append(f"Check: {verification_hint}")
    if special_instructions:
        sections.append(special_instructions)
    sections.append(
        "Answer the task directly. Do not mention workspace handoffs or "
        "Cognitive Map status."
    )

    return "\n\n".join(sections)


def verify_task_output(task_label: str, task_prompt: str, output: str) -> dict[str, Any]:
    """Run small deterministic checks on a visible benchmark output."""

    visible_output = output.strip()
    if not visible_output:
        return _verification_result(False, "Output is empty.", "non_empty_output")

    if _is_generic_scaffold_output(visible_output):
        return _verification_result(
            False,
            "Output is generic scaffold/status text.",
            "non_scaffold_output",
        )

    if task_label == "classification":
        allowed_labels = _label_choices(task_prompt)
        if not allowed_labels:
            return _verification_result(True, "No allowed labels found.", None)
        if visible_output in allowed_labels:
            return _verification_result(True, "Output is exactly one allowed label.", None)
        return _verification_result(
            False,
            "Classification output must be exactly one allowed label.",
            "classification_label",
        )

    expected_bullets = _expected_bullet_count(task_prompt)
    if task_label == "constraint_following" and expected_bullets is not None:
        actual_bullets = _bullet_count(visible_output)
        if actual_bullets != expected_bullets:
            return _verification_result(
                False,
                (
                    f"Expected exactly {expected_bullets} bullet points, "
                    f"found {actual_bullets}."
                ),
                "bullet_count",
            )

    if task_label == "coding" and "function" in task_prompt.lower():
        if not _includes_code_like_function(visible_output):
            return _verification_result(
                False,
                "Output should include a code-like function.",
                "code_like_function",
            )

    usefulness_failure = _generic_usefulness_failure(visible_output)
    if usefulness_failure is not None:
        return usefulness_failure

    return _verification_result(True, "Output passed deterministic checks.", None)


def build_reflection_payload(
    original_payload: str,
    previous_output: str,
    verification_result: dict[str, Any],
) -> str:
    """Build a compact retry prompt from the original task and failed output."""

    original_task = _extract_task_instruction(original_payload)
    failure_reason = str(verification_result.get("reason") or "Verification failed.")
    sections = [
        "/no_think",
        "Return only the corrected concise visible final answer.",
        "Do not include reasoning, analysis, workspace status, or metadata.",
        f"Original task:\n{original_task}",
        f"Previous output:\n{previous_output.strip() or '[empty output]'}",
        f"Verification failure:\n{failure_reason}",
        "Correct the answer now.",
    ]
    return "\n\n".join(sections)


def execute_payload(
    task_label: str,
    mode: str,
    payload_data: dict[str, Any],
    provider: LemonadeProvider | None,
    model: str,
    base_url: str,
    dry_run: bool,
    repeat_index: int,
    max_reflection_attempts: int = 1,
) -> dict[str, Any]:
    if mode == "cognitive_map":
        return _execute_cognitive_map_payload(
            task_label=task_label,
            payload_data=payload_data,
            provider=provider,
            model=model,
            base_url=base_url,
            dry_run=dry_run,
            repeat_index=repeat_index,
            max_reflection_attempts=max_reflection_attempts,
        )

    attempt = _execute_single_attempt(
        payload=payload_data["llm_payload"],
        provider=provider,
        model=model,
        dry_run=dry_run,
    )
    verification_result = _verification_result(
        True, "Dry-run skipped execution and verification.", None
    )
    if not dry_run:
        verification_result = verify_task_output(
            task_label=task_label,
            task_prompt=str(payload_data.get("task_prompt") or ""),
            output=str(attempt["response_text"]),
        )

    return _result_row(
        task_label=task_label,
        mode=mode,
        model=model,
        base_url=base_url,
        dry_run=dry_run,
        repeat_index=repeat_index,
        payload_data=payload_data,
        prompt_tokens=attempt["usage"]["prompt_tokens"],
        completion_tokens=attempt["usage"]["completion_tokens"],
        total_tokens=attempt["usage"]["total_tokens"],
        latency_ms=attempt["latency_ms"],
        response_text=attempt["response_text"],
        error=attempt["error"],
        verification_result=verification_result,
        reflection_attempts_used=0,
        reflection_triggered=False,
        final_attempt_index=1,
    )


def _execute_cognitive_map_payload(
    task_label: str,
    payload_data: dict[str, Any],
    provider: LemonadeProvider | None,
    model: str,
    base_url: str,
    dry_run: bool,
    repeat_index: int,
    max_reflection_attempts: int,
) -> dict[str, Any]:
    current_payload = payload_data["llm_payload"]
    final_attempt: dict[str, Any] | None = None
    verification_result: dict[str, Any] = _verification_result(
        True, "Dry-run skipped execution and verification.", None
    )
    reflection_attempts_used = 0
    prompt_tokens: list[int | None] = []
    completion_tokens: list[int | None] = []
    total_tokens: list[int | None] = []
    total_latency_ms = 0

    for attempt_index in range(max_reflection_attempts + 1):
        attempt = _execute_single_attempt(
            payload=current_payload,
            provider=provider,
            model=model,
            dry_run=dry_run,
        )
        final_attempt = attempt
        prompt_tokens.append(attempt["usage"]["prompt_tokens"])
        completion_tokens.append(attempt["usage"]["completion_tokens"])
        total_tokens.append(attempt["usage"]["total_tokens"])
        total_latency_ms += int(attempt["latency_ms"])

        if dry_run:
            break

        verification_result = verify_task_output(
            task_label=task_label,
            task_prompt=str(payload_data.get("task_prompt") or ""),
            output=str(attempt["response_text"]),
        )
        if verification_result["passed"]:
            break
        if attempt_index >= max_reflection_attempts:
            break

        reflection_attempts_used += 1
        current_payload = build_reflection_payload(
            original_payload=payload_data["llm_payload"],
            previous_output=str(attempt["response_text"]),
            verification_result=verification_result,
        )

    if final_attempt is None:
        raise RuntimeError("Cognitive Map execution produced no attempts.")

    error = final_attempt["error"]
    if error is None and not dry_run and not verification_result["passed"]:
        error = f"verification_failed: {verification_result['reason']}"

    return _result_row(
        task_label=task_label,
        mode="cognitive_map",
        model=model,
        base_url=base_url,
        dry_run=dry_run,
        repeat_index=repeat_index,
        payload_data=payload_data,
        prompt_tokens=_sum_nullable(prompt_tokens),
        completion_tokens=_sum_nullable(completion_tokens),
        total_tokens=_sum_nullable(total_tokens),
        latency_ms=total_latency_ms,
        response_text=str(final_attempt["response_text"]),
        error=error,
        verification_result=verification_result,
        reflection_attempts_used=reflection_attempts_used,
        reflection_triggered=reflection_attempts_used > 0,
        final_attempt_index=reflection_attempts_used,
    )


def _execute_single_attempt(
    payload: str,
    provider: LemonadeProvider | None,
    model: str,
    dry_run: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    response: dict[str, Any] = {}
    response_text = ""
    error = None

    try:
        if dry_run:
            latency_ms = 0
        else:
            if provider is None:
                raise ValueError("Provider is required unless dry_run is enabled.")
            response = provider.chat(
                [{"role": "user", "content": payload}],
                model=model,
                max_tokens=160,
                temperature=0.2,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            response_text = _extract_response_text(response)
            if not response_text:
                error = "empty_visible_output"
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = str(exc)

    usage = _provider_token_usage(response)
    return {
        "response_text": response_text,
        "latency_ms": latency_ms,
        "error": error,
        "usage": usage,
    }


def _result_row(
    task_label: str,
    mode: str,
    model: str,
    base_url: str,
    dry_run: bool,
    repeat_index: int,
    payload_data: dict[str, Any],
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    latency_ms: int,
    response_text: str,
    error: str | None,
    verification_result: dict[str, Any] | None,
    reflection_attempts_used: int,
    reflection_triggered: bool,
    final_attempt_index: int,
) -> dict[str, Any]:
    zone_builder_metrics = dict(payload_data.get("zone_builder_metrics") or {})
    zone_builder_metrics = {
        **_not_applicable_zone_builder_metrics(),
        **zone_builder_metrics,
    }
    combined_prompt_tokens = _combine_token_counts(
        prompt_tokens, zone_builder_metrics["zone_builder_prompt_tokens"]
    )
    combined_completion_tokens = _combine_token_counts(
        completion_tokens, zone_builder_metrics["zone_builder_completion_tokens"]
    )
    combined_total_tokens = _combine_token_counts(
        total_tokens, zone_builder_metrics["zone_builder_total_tokens"]
    )
    combined_latency_ms = int(latency_ms) + int(
        zone_builder_metrics["zone_builder_latency_ms"]
    )

    return {
        "task_label": task_label,
        "mode": mode,
        "comparison_mode": payload_data.get("comparison_mode", mode),
        "model": model,
        "base_url": base_url,
        "dry_run": dry_run,
        "repeat_index": repeat_index,
        "audit_size_chars": len(payload_data["audit_text"]),
        "llm_payload_size_chars": len(payload_data["llm_payload"]),
        "approximate_token_estimate_audit": _estimate_tokens(
            len(payload_data["audit_text"])
        ),
        "approximate_token_estimate_llm_payload": _estimate_tokens(
            len(payload_data["llm_payload"])
        ),
        "provider_reported_prompt_tokens": prompt_tokens,
        "provider_reported_completion_tokens": completion_tokens,
        "provider_reported_total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "executor_prompt_tokens": prompt_tokens,
        "executor_completion_tokens": completion_tokens,
        "executor_total_tokens": total_tokens,
        "executor_latency_ms": latency_ms,
        "zone_builder_mode": zone_builder_metrics["zone_builder_mode"],
        "zone_builder_model": zone_builder_metrics["zone_builder_model"],
        "zone_builder_latency_ms": zone_builder_metrics["zone_builder_latency_ms"],
        "zone_builder_prompt_tokens": zone_builder_metrics[
            "zone_builder_prompt_tokens"
        ],
        "zone_builder_completion_tokens": zone_builder_metrics[
            "zone_builder_completion_tokens"
        ],
        "zone_builder_total_tokens": zone_builder_metrics[
            "zone_builder_total_tokens"
        ],
        "zone_builder_success": zone_builder_metrics["zone_builder_success"],
        "zone_builder_fallback_used": zone_builder_metrics[
            "zone_builder_fallback_used"
        ],
        "zone_builder_fallback_reason": zone_builder_metrics[
            "zone_builder_fallback_reason"
        ],
        "combined_prompt_tokens": combined_prompt_tokens,
        "combined_completion_tokens": combined_completion_tokens,
        "combined_total_tokens": combined_total_tokens,
        "combined_latency_ms": combined_latency_ms,
        "output_size_chars": len(response_text),
        "success": error is None,
        "error": error,
        "trace_available": payload_data["trace_available"],
        "handoff_count": payload_data["handoff_count"],
        "output_text": response_text,
        "verification_passed": (
            None if verification_result is None else bool(verification_result["passed"])
        ),
        "verification_reason": (
            None if verification_result is None else verification_result["reason"]
        ),
        "verification_failed_constraint": (
            None
            if verification_result is None
            else verification_result["failed_constraint"]
        ),
        "reflection_attempts_used": reflection_attempts_used,
        "reflection_triggered": reflection_triggered,
        "final_attempt_index": final_attempt_index,
    }


def write_jsonl(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, sort_keys=True) + "\n")


def print_report(results: list[dict[str, Any]], output_path: Path, dry_run: bool) -> None:
    print("Cognitive Map Real Execution Benchmark")
    print("======================================")
    print(f"dry_run: {dry_run}")
    print(f"results_jsonl: {output_path}")
    print()
    print(
        f"{'rep':>3} {'task_label':<10} {'mode':<28} {'audit':>7} {'payload':>8} "
        f"{'ptok':>6} {'ctok':>6} {'total':>6} {'lat_ms':>7} "
        f"{'out':>5} {'trace':>7} {'refl':>4} {'verif':>5} {'ok':>4}"
    )
    print("-" * 123)
    for result in results:
        print(
            f"{result['repeat_index']:>3} "
            f"{result['task_label']:<10} "
            f"{_comparison_mode(result):<28} "
            f"{result['audit_size_chars']:>7} "
            f"{result['llm_payload_size_chars']:>8} "
            f"{_format_nullable(result['provider_reported_prompt_tokens']):>6} "
            f"{_format_nullable(result['provider_reported_completion_tokens']):>6} "
            f"{_format_nullable(result['provider_reported_total_tokens']):>6} "
            f"{result['latency_ms']:>7} "
            f"{result['output_size_chars']:>5} "
            f"{str(result['trace_available']):>7} "
            f"{result['reflection_attempts_used']:>4} "
            f"{_format_boolish(result.get('verification_passed')):>5} "
            f"{str(result['success']):>4}"
        )
    print_aggregate_summary(summarize_results(results))


def summarize_results(results: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    summary = {}
    modes = sorted({_comparison_mode(result) for result in results})
    for mode in modes:
        mode_results = [result for result in results if _comparison_mode(result) == mode]
        total_tokens = _token_values(mode_results, "provider_reported_total_tokens")
        latencies = [int(result["latency_ms"]) for result in mode_results]
        summary[mode] = {
            "runs": len(mode_results),
            "prompt_tokens_sum": sum(
                _token_values(mode_results, "provider_reported_prompt_tokens")
            ),
            "completion_tokens_sum": sum(
                _token_values(mode_results, "provider_reported_completion_tokens")
            ),
            "total_tokens_sum": sum(total_tokens),
            "mean_total_tokens": _mean(total_tokens),
            "latency_ms_sum": sum(latencies),
            "mean_latency_ms": _mean(latencies),
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "success_count": sum(1 for result in mode_results if result["success"]),
            "failure_count": sum(1 for result in mode_results if not result["success"]),
        }
    return summary


def _comparison_mode(row: dict[str, Any]) -> str:
    return str(row.get("comparison_mode") or row.get("mode", "unknown"))


def print_aggregate_summary(summary: dict[str, dict[str, float | int]]) -> None:
    print()
    print("Aggregate Summary")
    print("=================")
    print(
        f"{'mode':<18} {'runs':>5} {'ptok_sum':>9} {'ctok_sum':>9} "
        f"{'total_sum':>10} {'mean_tok':>9} {'lat_sum':>9} "
        f"{'mean_lat':>9} {'min_lat':>8} {'max_lat':>8} {'ok':>4} {'fail':>5}"
    )
    print("-" * 118)
    for mode, metrics in summary.items():
        print(
            f"{mode:<18} "
            f"{metrics['runs']:>5} "
            f"{metrics['prompt_tokens_sum']:>9} "
            f"{metrics['completion_tokens_sum']:>9} "
            f"{metrics['total_tokens_sum']:>10} "
            f"{metrics['mean_total_tokens']:>9.2f} "
            f"{metrics['latency_ms_sum']:>9} "
            f"{metrics['mean_latency_ms']:>9.2f} "
            f"{metrics['min_latency_ms']:>8} "
            f"{metrics['max_latency_ms']:>8} "
            f"{metrics['success_count']:>4} "
            f"{metrics['failure_count']:>5}"
        )


def _token_values(results: list[dict[str, Any]], key: str) -> list[int]:
    return [int(result[key]) for result in results if result.get(key) is not None]


def _mean(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _provider_token_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    return {
        "prompt_tokens": _nullable_int(usage.get("prompt_tokens")),
        "completion_tokens": _nullable_int(usage.get("completion_tokens")),
        "total_tokens": _nullable_int(usage.get("total_tokens")),
    }


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _format_nullable(value: int | None) -> str:
    return "-" if value is None else str(value)


def _format_boolish(value: Any) -> str:
    return "-" if value is None else str(bool(value))


def _sum_nullable(values: list[int | None]) -> int | None:
    usable_values = [int(value) for value in values if value is not None]
    if not usable_values:
        return None
    return sum(usable_values)


def _combine_token_counts(
    executor_tokens: int | None, zone_builder_tokens: int | None
) -> int | None:
    if executor_tokens is None:
        return None
    return int(executor_tokens) + int(zone_builder_tokens or 0)


def _limit_tasks(tasks: list[dict[str, str]], limit_tasks: int | None) -> list[dict[str, str]]:
    if limit_tasks is None:
        return tasks
    if limit_tasks < 1:
        raise ValueError("--limit-tasks must be at least 1.")
    return tasks[:limit_tasks]


def _default_constraints(task: dict[str, str]) -> list[str]:
    return [
        f"Preserve task label: {task['task_label']}.",
        "Keep the real execution benchmark concise.",
        "Return visible final output only.",
    ]


def _first_fragment(fragments: list[str]) -> str:
    return str(fragments[0]) if fragments else ""


def _first_matching_fragment(fragments: list[str], prefix: str) -> str:
    for fragment in fragments:
        if str(fragment).startswith(prefix):
            return str(fragment)
    return ""


def _task_constraints(workspace: CognitiveWorkspace) -> list[str]:
    ignored_prefixes = (
        "user_intent_zone captured input:",
        "Intent extracted from prompt:",
    )
    constraints = []
    for fragment in workspace.zones["task_constraints_zone"].input_fragments:
        if not str(fragment).startswith(ignored_prefixes):
            constraints.append(str(fragment))
    return constraints


def _task_specific_instructions(task_instruction: str) -> str:
    normalized = task_instruction.lower()
    instructions = []
    label_choices = _label_choices(task_instruction)
    if label_choices:
        instructions.append("Allowed labels: " + ", ".join(label_choices))
        if _is_benchmark_output_check(task_instruction):
            instructions.append(
                "For checking or validating benchmark output/results, choose review."
            )
        instructions.append("Return exactly one of the allowed labels. Do not explain.")

    if any(marker in normalized for marker in ("debug", "bug", "zero", "missing")):
        instructions.append(
            "Debugging: preserve edge cases named in the task, including zero-count "
            "or missing-field cases."
        )

    return "\n".join(instructions)


def _label_choices(task_instruction: str) -> list[str]:
    marker = "as "
    lower_instruction = task_instruction.lower()
    marker_index = lower_instruction.find(marker)
    colon_index = task_instruction.find(":")
    if marker_index == -1 or colon_index == -1 or marker_index > colon_index:
        return []

    choice_text = task_instruction[marker_index + len(marker) : colon_index]
    choices = [
        choice.strip(" .")
        for choice in choice_text.replace(" or ", ", ").split(",")
        if choice.strip(" .")
    ]
    return choices if len(choices) > 1 else []


def _is_benchmark_output_check(task_instruction: str) -> bool:
    normalized = task_instruction.lower()
    action_markers = ("check", "validate", "inspect", "review", "assess")
    output_markers = ("benchmark output", "benchmark result", "results")
    return any(marker in normalized for marker in action_markers) and any(
        marker in normalized for marker in output_markers
    )


def _verification_result(
    passed: bool, reason: str, failed_constraint: str | None
) -> dict[str, Any]:
    return {
        "passed": passed,
        "reason": reason,
        "failed_constraint": failed_constraint,
    }


def _is_generic_scaffold_output(output: str) -> bool:
    normalized = " ".join(output.lower().split())
    generic_outputs = {
        "final output ready from verified cognitive-map flow.",
        "final output ready from verified cognitive map flow.",
    }
    return normalized in generic_outputs


def _generic_usefulness_failure(output: str) -> dict[str, Any] | None:
    if _is_known_task_label_output(output):
        return _verification_result(
            False,
            "Output is exactly one known task label, not a useful answer.",
            "label_like_output",
        )

    word_count = len(re.findall(r"\b[\w']+\b", output))
    if word_count < MIN_GENERIC_OUTPUT_WORDS:
        return _verification_result(
            False,
            (
                f"Output is too short to be useful: expected at least "
                f"{MIN_GENERIC_OUTPUT_WORDS} words, found {word_count}."
            ),
            "minimum_word_count",
        )

    return None


def _is_known_task_label_output(output: str) -> bool:
    normalized = output.strip().lower().strip("`*_ .:")
    return normalized in KNOWN_TASK_LABELS


def _expected_bullet_count(task_prompt: str) -> int | None:
    normalized = task_prompt.lower()
    match = re.search(r"exactly\s+(\d+|one|two|three|four|five)\s+bullet points?", normalized)
    if not match:
        return None
    return _number_word_to_int(match.group(1))


def _number_word_to_int(value: str) -> int | None:
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
    }
    if value.isdigit():
        return int(value)
    return words.get(value)


def _bullet_count(output: str) -> int:
    return sum(
        1
        for line in output.splitlines()
        if re.match(r"^\s*[-*]\s+\S", line)
    )


def _includes_code_like_function(output: str) -> bool:
    return bool(
        re.search(r"\bdef\s+[A-Za-z_]\w*\s*\(", output)
        or re.search(r"\bfunction\s+[A-Za-z_]\w*\s*\(", output)
        or re.search(r"[A-Za-z_]\w*\s*=\s*\([^)]*\)\s*=>", output)
    )


def _extract_task_instruction(original_payload: str) -> str:
    for line in original_payload.splitlines():
        if line.startswith("Task:"):
            return line.removeprefix("Task:").strip()
    stripped_payload = original_payload.strip()
    if stripped_payload.startswith("{"):
        return "[original task unavailable]"
    return stripped_payload


if __name__ == "__main__":
    main()
