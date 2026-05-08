"""Experimental Lemonade-backed LLM router for sfe."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import LemonadeProvider
from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTION_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_CODEXCLI_PROVIDER_NAME,
    CodexCLIProvider,
)
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_API_ROUTER_MODEL,
    OpenAIAPIError,
    PROVIDER_NAME as OPENAI_API_PROVIDER_NAME,
    OpenAIAPIProvider,
)
from router.mock_router import route as mock_route


DEFAULT_ROUTER_MODEL = "Qwen3-0.6B-GGUF"
DEFAULT_EXECUTION_MODEL = "Qwen3.5-35B-A3B-GGUF"
LOGGER = logging.getLogger(__name__)

REQUIRED_FIELDS = {
    "task_type",
    "role",
    "provider",
    "model",
    "memory_zones",
    "execution_mode",
    "max_input_tokens",
    "max_output_tokens",
    "requires_review",
    "confidence",
    "rationale",
}

TASK_TYPES = {"writing", "coding", "review", "analysis", "planning", "multi_context"}
ROLES = {"writer", "executor", "architect", "reviewer"}
EXECUTION_MODES = {"direct", "tool_assisted", "multi_step"}


def route_with_llm(
    task: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    disable_thinking: bool = True,
) -> dict:
    """Ask a local Lemonade model for a routing decision, falling back safely on errors."""
    decision, _diagnostics = route_with_llm_diagnostics(
        task,
        model=model,
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
    )
    return decision


def route_with_llm_diagnostics(
    task: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    disable_thinking: bool = True,
) -> tuple[dict, dict[str, Any]]:
    """Return a contract-compliant routing decision and parser/fallback diagnostics."""
    return _route_with_llm_diagnostics(
        task,
        apply_classification_guard=True,
        router_name="llm",
        model=model,
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
    )


def route_with_llm_raw_diagnostics(
    task: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    disable_thinking: bool = True,
) -> tuple[dict, dict[str, Any]]:
    """Return a contract-compliant LLM routing decision without deterministic correction."""
    return _route_with_llm_diagnostics(
        task,
        apply_classification_guard=False,
        router_name="llm_raw",
        model=model,
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
    )


def route_with_codexcli(
    task: str,
    router_model: str | None = None,
    executor_model: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """Ask CodexCLI/OpenAI for a routing decision, falling back safely on errors."""
    decision, _diagnostics = route_with_codexcli_diagnostics(
        task,
        router_model=router_model,
        executor_model=executor_model,
        timeout_seconds=timeout_seconds,
    )
    return decision


def route_with_codexcli_diagnostics(
    task: str,
    router_model: str | None = None,
    executor_model: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[dict, dict[str, Any]]:
    """Return a contract-compliant routing decision from CodexCLI/OpenAI."""
    router_model = (
        router_model
        or os.getenv("SFE_OPENAI_ROUTER_MODEL")
        or DEFAULT_CODEXCLI_ROUTER_MODEL
    )
    executor_model = (
        executor_model
        or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
        or DEFAULT_OPENAI_EXECUTION_MODEL
    )
    provider = CodexCLIProvider(timeout=timeout_seconds)
    diagnostics = {
        "router": OPENAI_CODEXCLI_PROVIDER_NAME,
        "provider": OPENAI_CODEXCLI_PROVIDER_NAME,
        "model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": provider.timeout,
        "attempt_count": 0,
        "success": False,
        "json_valid": False,
        "used_fallback": False,
        "decision_source": "",
        "errors": [],
    }

    prompts = [_build_prompt(task), _build_retry_prompt(task)]
    for attempt_index, prompt in enumerate(prompts, start=1):
        diagnostics["attempt_count"] = attempt_index
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=router_model,
                max_tokens=512,
                temperature=0.0,
            )
            router_metrics = _codexcli_router_metrics(response, error="")
            output = _extract_response_text(response)
            decision = _parse_json(output)
            diagnostics["json_valid"] = True
            _validate_decision(decision)
            decision, correction = _apply_classification_guard(task, decision)
            if correction:
                diagnostics.setdefault("corrections", []).append(correction)
                LOGGER.warning("CodexCLI router classification corrected; %s", correction)
            decision["provider"] = OPENAI_CODEXCLI_PROVIDER_NAME
            decision["router_model"] = router_model
            decision["model"] = executor_model
            decision.update(router_metrics)
            diagnostics["success"] = True
            diagnostics["decision_source"] = OPENAI_CODEXCLI_PROVIDER_NAME
            return decision, diagnostics
        except Exception as exc:
            error = f"attempt {attempt_index}: {exc}"
            diagnostics["errors"].append(error)
            LOGGER.warning("CodexCLI router attempt failed; %s", error)

    fallback = _safe_fallback(task, "CodexCLI router failed after retry", diagnostics["errors"])
    fallback["provider"] = OPENAI_CODEXCLI_PROVIDER_NAME
    fallback["router_model"] = router_model
    fallback["model"] = executor_model
    fallback.update(_empty_router_metrics(router_error="; ".join(diagnostics["errors"])))
    diagnostics["used_fallback"] = True
    diagnostics["decision_source"] = "mock_fallback"
    diagnostics["fallback_reason"] = "CodexCLI router failed after retry"
    return fallback, diagnostics


def route_with_openai_api(
    task: str,
    router_model: str | None = None,
    executor_model: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """Ask the direct OpenAI API for a routing decision, falling back explicitly on errors."""
    decision, _diagnostics = route_with_openai_api_diagnostics(
        task,
        router_model=router_model,
        executor_model=executor_model,
        timeout_seconds=timeout_seconds,
    )
    return decision


def route_with_openai_api_diagnostics(
    task: str,
    router_model: str | None = None,
    executor_model: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[dict, dict[str, Any]]:
    """Return a contract-compliant routing decision from the direct OpenAI API."""
    router_model = (
        router_model
        or os.getenv("SFE_OPENAI_ROUTER_MODEL")
        or DEFAULT_OPENAI_API_ROUTER_MODEL
    )
    executor_model = (
        executor_model
        or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
        or DEFAULT_OPENAI_EXECUTION_MODEL
    )
    provider = OpenAIAPIProvider(timeout=timeout_seconds)
    diagnostics = {
        "router": OPENAI_API_PROVIDER_NAME,
        "provider": OPENAI_API_PROVIDER_NAME,
        "model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": provider.timeout,
        "attempt_count": 0,
        "success": False,
        "json_valid": False,
        "used_fallback": False,
        "decision_source": "",
        "errors": [],
    }

    prompts = [_build_prompt(task), _build_retry_prompt(task)]
    for attempt_index, prompt in enumerate(prompts, start=1):
        diagnostics["attempt_count"] = attempt_index
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=router_model,
                max_tokens=512,
                temperature=0.0,
            )
            router_metrics = _provider_router_metrics(
                response, metadata_key="openai_api", error=""
            )
            output = _extract_response_text(response)
            decision = _parse_json(output)
            diagnostics["json_valid"] = True
            _validate_decision(decision)
            decision, correction = _apply_classification_guard(task, decision)
            if correction:
                diagnostics.setdefault("corrections", []).append(correction)
                LOGGER.warning("OpenAI API router classification corrected; %s", correction)
            decision["provider"] = OPENAI_API_PROVIDER_NAME
            decision["router_model"] = router_model
            decision["model"] = executor_model
            decision.update(router_metrics)
            diagnostics["success"] = True
            diagnostics["decision_source"] = OPENAI_API_PROVIDER_NAME
            diagnostics["api_error_retry_count"] = router_metrics.get(
                "api_error_retry_count", 0
            )
            diagnostics["api_error_attempts"] = router_metrics.get("api_error_attempts", [])
            return decision, diagnostics
        except OpenAIAPIError as exc:
            api_error = dict(exc.diagnostics)
            error = f"attempt {attempt_index}: {exc}"
            diagnostics["errors"].append(error)
            diagnostics.setdefault("api_errors", []).append(api_error)
            diagnostics["api_error_retry_count"] = api_error.get("api_error_retry_count", 0)
            LOGGER.warning("OpenAI API router attempt failed; %s", error)
            if api_error.get("api_error_type") in {
                "insufficient_quota",
                "unsupported_parameter",
                "authentication",
                "invalid_api_key",
                "model_access",
            }:
                break
        except Exception as exc:
            error = f"attempt {attempt_index}: {exc}"
            diagnostics["errors"].append(error)
            LOGGER.warning("OpenAI API router attempt failed; %s", error)

    fallback = _safe_fallback(task, "OpenAI API router failed after retry", diagnostics["errors"])
    fallback["provider"] = OPENAI_API_PROVIDER_NAME
    fallback["router_model"] = router_model
    fallback["model"] = executor_model
    fallback.update(_empty_router_metrics(router_error="; ".join(diagnostics["errors"])))
    if diagnostics.get("api_errors"):
        last_api_error = diagnostics["api_errors"][-1]
        fallback.update(
            {
                "api_error_status": last_api_error.get("api_error_status"),
                "api_error_type": last_api_error.get("api_error_type"),
                "api_error_code": last_api_error.get("api_error_code"),
                "api_error_message": last_api_error.get("api_error_message"),
                "api_error_retry_count": int(last_api_error.get("api_error_retry_count") or 0),
                "api_error_attempts": last_api_error.get("api_error_attempts") or [],
            }
        )
    diagnostics["used_fallback"] = True
    diagnostics["decision_source"] = "mock_fallback"
    diagnostics["fallback_reason"] = "OpenAI API router failed after retry"
    return fallback, diagnostics


def _codexcli_router_metrics(response: dict[str, Any], error: str) -> dict[str, Any]:
    return _provider_router_metrics(response, metadata_key="codexcli", error=error)


def _provider_router_metrics(
    response: dict[str, Any], metadata_key: str, error: str
) -> dict[str, Any]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    metadata = response.get(metadata_key, {})
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "router_latency_ms": _nullable_int(usage_value=metadata.get("latency_ms")),
        "router_input_tokens": _nullable_int(usage_value=usage.get("prompt_tokens")),
        "router_output_tokens": _nullable_int(usage_value=usage.get("completion_tokens")),
        "router_total_tokens": _nullable_int(usage_value=usage.get("total_tokens")),
        "router_error": error,
        "api_error_status": metadata.get("api_error_status"),
        "api_error_type": metadata.get("api_error_type"),
        "api_error_code": metadata.get("api_error_code"),
        "api_error_message": metadata.get("api_error_message"),
        "api_error_retry_count": int(metadata.get("api_error_retry_count") or 0),
        "api_error_attempts": metadata.get("api_error_attempts") or [],
    }


def _empty_router_metrics(router_error: str = "") -> dict[str, Any]:
    return {
        "router_latency_ms": None,
        "router_input_tokens": None,
        "router_output_tokens": None,
        "router_total_tokens": None,
        "router_error": router_error,
        "api_error_status": None,
        "api_error_type": None,
        "api_error_code": None,
        "api_error_message": None,
        "api_error_retry_count": 0,
        "api_error_attempts": [],
    }


def _nullable_int(usage_value: Any) -> int | None:
    if usage_value is None:
        return None
    return int(usage_value)


def _route_with_llm_diagnostics(
    task: str,
    apply_classification_guard: bool,
    router_name: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
    disable_thinking: bool = True,
) -> tuple[dict, dict[str, Any]]:
    model = model or os.getenv("SFE_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    provider = LemonadeProvider()
    if timeout_seconds is not None:
        if timeout_seconds <= 0:
            raise ValueError("Router timeout must be greater than 0.")
        provider.timeout = timeout_seconds
    diagnostics = {
        "router": router_name,
        "model": model,
        "timeout_seconds": provider.timeout,
        "disable_thinking": disable_thinking,
        "attempt_count": 0,
        "success": False,
        "json_valid": False,
        "used_fallback": False,
        "classification_guard_enabled": apply_classification_guard,
        "decision_source": "",
        "errors": [],
    }

    prompts = [_build_prompt(task), _build_retry_prompt(task)]
    for attempt_index, prompt in enumerate(prompts, start=1):
        diagnostics["attempt_count"] = attempt_index
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=model,
                max_tokens=512,
                temperature=0.0,
                chat_template_kwargs=(
                    {"enable_thinking": False} if disable_thinking else None
                ),
            )
            output = _extract_response_text(response)
            decision = _parse_json(output)
            diagnostics["json_valid"] = True
            _validate_decision(decision)
            if apply_classification_guard:
                decision, correction = _apply_classification_guard(task, decision)
                if correction:
                    diagnostics.setdefault("corrections", []).append(correction)
                    LOGGER.warning("LLM router classification corrected; %s", correction)
            diagnostics["success"] = True
            diagnostics["decision_source"] = router_name
            return decision, diagnostics
        except Exception as exc:
            error = f"attempt {attempt_index}: {exc}"
            diagnostics["errors"].append(error)
            LOGGER.warning("LLM router attempt failed; %s", error)

    fallback = _safe_fallback(task, "LLM router failed after retry", diagnostics["errors"])
    diagnostics["used_fallback"] = True
    diagnostics["decision_source"] = "mock_fallback"
    diagnostics["fallback_reason"] = "LLM router failed after retry"
    return fallback, diagnostics


def _build_prompt(task: str) -> str:
    return f"""
/no_think
You are the sfe routing layer. You are not the executor.
Your only job is to classify the user task and return a routing decision.
Do not answer the task. Do not solve it. Do not explain your reasoning.

sfe tests whether LLM systems become more efficient through routing,
context separation, constrained prompts, controlled activation, and
separation between decision and execution.

Routing principles:
- Select the smallest useful context.
- Prefer narrow context over broad context.
- Classify the requested work, not incidental nouns in the prompt.
- Use multi_context only when the user asks for two or more distinct output domains, not merely
  because the task mentions a technical topic.
- Planning must mean the user explicitly asks to create a plan, roadmap, milestones, schedule,
  phased sequence, implementation strategy, or ordered action plan.
- Do not classify as planning merely because the prompt contains "next step", "risk", "explain",
  "fix", "compare", "validate", "progress", "evaluation", or "write-up".
- Writing tasks remain writing even if they mention progress, next step, or risk.
- Coding tasks remain coding when the user asks to write, fix, validate, debug, or return code.
- Analysis tasks remain analysis when the user asks to compare, evaluate, explain tradeoffs,
  or reason conceptually.
- Avoid over-routing.
- Preserve comparability between baseline and spatial execution modes.

Return strict JSON only.
The first character must be "{{" and the last character must be "}}".
Do not use markdown, code fences, comments, prose, or reasoning dumps.
Do not emit fields outside the required schema.

Allowed task_type values:
- writing: rewriting, drafting, editing, style improvement, article or post composition
- coding: code generation, debugging, CLI work, Python, project implementation
- review: checking or critiquing an existing artifact, answer, implementation, or decision
- analysis: single-domain conceptual reasoning, comparison, evaluation, critique, abstract thinking
- planning: plans, roadmaps, milestones, task decomposition, sequencing, dependencies, success criteria, risks
- multi_context: tasks requiring two or more distinct domains or outputs, such as code plus explanation, analysis plus writing, architecture plus experimental reporting, or implementation plus scientific framing

Classification contrast:
- analysis = single-domain reasoning or comparison
- planning = explicit request to create a plan, roadmap, milestones, schedule, phased sequence, implementation strategy, or ordered action plan
- multi_context = multiple distinct outputs or domains; not just a technical topic
- review = evaluating an existing claim, answer, implementation, artifact, or decision

Classification precedence:
1. If the task asks to write, fix, validate, debug, or return code, use coding unless it also asks for a separate explanatory or reporting output.
2. If the task asks to review an existing claim, answer, or artifact, use review.
3. If the task asks to write or rewrite prose, use writing even when it mentions progress, next step, or risk.
4. If the task asks to compare, evaluate, explain tradeoffs, or reason conceptually, use analysis.
5. Use planning only for explicit planning deliverables.
6. Use multi_context only for distinct combined output domains, such as code plus explanation or evaluation metrics plus report format.

Allowed role values:
- writer for writing
- executor for coding
- reviewer for review or analysis
- architect for planning or multi_context

Planning routing rule:
- For task_type "planning", set role to "architect".
- Return only the routing JSON. Never draft the plan, milestones, risks, dependencies, or success criteria.

Required fields and fixed defaults:
- task_type: one of ["writing", "coding", "review", "analysis", "planning", "multi_context"]
- role: one of ["writer", "executor", "architect", "reviewer"]
- provider: "local"
- model: "{DEFAULT_EXECUTION_MODEL}"
- memory_zones: [] unless a small specific zone is clearly required
- execution_mode: "direct" unless the task clearly requires tools or multiple steps
- max_input_tokens: 4000
- max_output_tokens: 1000
- requires_review: false unless quality or risk clearly requires a review pass
- confidence: number from 0 to 1
- rationale: one short sentence about classification only

Return exactly one JSON object in this shape:
{{
  "task_type": "writing",
  "role": "writer",
  "provider": "local",
  "model": "{DEFAULT_EXECUTION_MODEL}",
  "memory_zones": [],
  "execution_mode": "direct",
  "max_input_tokens": 4000,
  "max_output_tokens": 1000,
  "requires_review": false,
  "confidence": 0.5,
  "rationale": "short reason"
}}

Planning guard:
- If the task says "write", "rewrite", "fix", "validate", "debug", "compare", "explain", or "review", do not choose planning unless it explicitly asks for a plan/roadmap/milestones/schedule/strategy as the main deliverable.
- Do not write the plan. Return routing JSON only.

Task:
{task}
""".strip()


def _build_retry_prompt(task: str) -> str:
    return f"""
/no_think
Return one valid JSON object and nothing else.
No markdown. No code fence. No prose. No comments. No trailing text.
The output must parse with json.loads as a single JSON object.

Schema:
{{
  "task_type": "writing|coding|review|analysis|planning|multi_context",
  "role": "writer|executor|architect|reviewer",
  "provider": "local",
  "model": "{DEFAULT_EXECUTION_MODEL}",
  "memory_zones": [],
  "execution_mode": "direct|tool_assisted|multi_step",
  "max_input_tokens": 4000,
  "max_output_tokens": 1000,
  "requires_review": false,
  "confidence": 0.5,
  "rationale": "one short classification reason"
}}

Task:
{task}
""".strip()


def _extract_response_text(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return ""

    first_choice = choices[0]
    message = first_choice.get("message", {})

    if isinstance(message, dict):
        content = str(message.get("content") or "").strip()
        if content:
            return content

        reasoning_content = str(message.get("reasoning_content") or "").strip()
        if reasoning_content:
            return reasoning_content

    return str(first_choice.get("text") or "").strip()


def _parse_json(output: str) -> dict:
    json_text = _extract_strict_json_object(output)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Router output is not valid JSON: {output}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Router output must be a JSON object.")

    return parsed


def _extract_strict_json_object(output: str) -> str:
    stripped = _strip_markdown_fences(output).strip()
    if not stripped:
        raise ValueError("Router output is empty.")

    object_start = stripped.find("{")
    if object_start == -1:
        raise ValueError(f"Router output does not contain a JSON object: {output}")

    candidate = stripped[object_start:]
    decoder = json.JSONDecoder()
    try:
        parsed, object_end = decoder.raw_decode(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Router output does not contain a valid JSON object: {output}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Router output JSON value must be an object.")

    trailing = candidate[object_end:].strip()
    if trailing:
        raise ValueError(f"Router output contains trailing text after JSON object: {trailing}")

    return candidate[:object_end]


def _strip_markdown_fences(output: str) -> str:
    stripped = output.strip()
    fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        return fenced_match.group(1)

    lines = []
    for line in stripped.splitlines():
        if re.fullmatch(r"\s*```(?:json)?\s*", line, flags=re.IGNORECASE):
            continue
        lines.append(line)
    return "\n".join(lines)


def _validate_decision(decision: dict) -> None:
    fields = set(decision)
    missing_fields = sorted(REQUIRED_FIELDS - fields)
    extra_fields = sorted(fields - REQUIRED_FIELDS)

    if missing_fields:
        raise ValueError(f"Router decision missing required field(s): {', '.join(missing_fields)}")

    if extra_fields:
        raise ValueError(f"Router decision contains extra field(s): {', '.join(extra_fields)}")

    if decision["task_type"] not in TASK_TYPES:
        raise ValueError(f"Invalid task_type: {decision['task_type']}")

    if decision["role"] not in ROLES:
        raise ValueError(f"Invalid role: {decision['role']}")

    if decision["task_type"] == "planning" and decision["role"] != "architect":
        raise ValueError('Planning tasks must use role "architect".')

    if decision["provider"] != "local":
        raise ValueError(f"Invalid provider: {decision['provider']}")

    if not isinstance(decision["model"], str) or not decision["model"].strip():
        raise ValueError("Router decision model must be a non-empty string.")

    if not isinstance(decision["memory_zones"], list):
        raise ValueError("Router decision memory_zones must be a list.")

    if decision["execution_mode"] not in EXECUTION_MODES:
        raise ValueError(f"Invalid execution_mode: {decision['execution_mode']}")

    if not isinstance(decision["max_input_tokens"], int) or decision["max_input_tokens"] <= 0:
        raise ValueError("Router decision max_input_tokens must be a positive integer.")

    if not isinstance(decision["max_output_tokens"], int) or decision["max_output_tokens"] <= 0:
        raise ValueError("Router decision max_output_tokens must be a positive integer.")

    if not isinstance(decision["requires_review"], bool):
        raise ValueError("Router decision requires_review must be a boolean.")

    confidence = decision["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        raise ValueError("Router decision confidence must be a number from 0 to 1.")

    if not isinstance(decision["rationale"], str) or not decision["rationale"].strip():
        raise ValueError("Router decision rationale must be a non-empty string.")


def _apply_classification_guard(task: str, decision: dict) -> tuple[dict, dict[str, Any] | None]:
    guarded_decision = mock_route(task)
    guarded_task_type = guarded_decision["task_type"]
    guarded_role = guarded_decision["role"]

    if (
        decision["task_type"] == guarded_task_type
        and decision["role"] == guarded_role
    ):
        return decision, None

    corrected = dict(decision)
    corrected["task_type"] = guarded_task_type
    corrected["role"] = guarded_role
    corrected["rationale"] = (
        "Deterministic classification guard corrected the route based on task wording."
    )
    _validate_decision(corrected)
    return corrected, {
        "original_task_type": decision["task_type"],
        "original_role": decision["role"],
        "corrected_task_type": guarded_task_type,
        "corrected_role": guarded_role,
        "reason": "deterministic_task_wording_guard",
    }


def _safe_fallback(task: str, reason: str, errors: list[str]) -> dict:
    LOGGER.error("LLM router fallback to mock_router: %s; errors=%s", reason, errors)
    try:
        decision = mock_route(task)
        _validate_decision(decision)
        return decision
    except Exception as exc:
        LOGGER.error("mock_router fallback failed; using hardcoded safe decision: %s", exc)
        return {
            "task_type": "planning",
            "role": "architect",
            "provider": "local",
            "model": DEFAULT_EXECUTION_MODEL,
            "memory_zones": [],
            "execution_mode": "direct",
            "max_input_tokens": 4000,
            "max_output_tokens": 1000,
            "requires_review": False,
            "confidence": 0.0,
            "rationale": "Hardcoded fallback after router errors.",
        }


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Write a short article about spatial cognition"
    print(json.dumps(route_with_llm(task), indent=2, sort_keys=True))
