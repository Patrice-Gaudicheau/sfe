"""Deterministic mock router for sfe."""

from __future__ import annotations

import re


WRITING_KEYWORDS = ("write", "article", "rewrite", "draft", "update", "sentence")
CODING_KEYWORDS = ("code", "function", "fix", "bug", "python", "debug", "validate")
REVIEW_KEYWORDS = ("review", "check", "inspect", "critique")
ANALYSIS_KEYWORDS = (
    "analyze",
    "analysis",
    "compare",
    "comparison",
    "evaluate",
    "evaluation",
    "critique",
    "explain",
    "reason",
)
LONG_TASK_WORDS = 40

PLANNING_KEYWORDS = (
    "plan",
    "roadmap",
    "milestone",
    "milestones",
    "schedule",
    "phased sequence",
    "implementation strategy",
    "ordered action plan",
)

DOMAIN_KEYWORDS = {
    "writing": ("article", "rewrite", "draft", "essay", "post", "style", "editing"),
    "coding": CODING_KEYWORDS,
    "review": REVIEW_KEYWORDS,
    "analysis": ANALYSIS_KEYWORDS,
    "architecture": ("architecture", "architectural", "provider", "routing", "router"),
    "reporting": ("report", "reporting", "metrics", "experiment", "evaluation"),
    "research": ("research", "paper", "study", "evidence", "source"),
    "planning": PLANNING_KEYWORDS,
}


def route(task: str) -> dict:
    """Return a valid mock routing decision for a task."""
    normalized_task = task.lower()

    if _has_coding_and_explanation_patterns(normalized_task):
        task_type = "multi_context"
        role = "architect"
        rationale = "Task combines a code change with explanation, so it is routed as multi-context."
    elif _contains_keyword(normalized_task, CODING_KEYWORDS):
        task_type = "coding"
        role = "executor"
        rationale = "Task contains a coding keyword, so it is routed to the executor role."
    elif _has_multi_context_output_domains(normalized_task):
        task_type = "multi_context"
        role = "architect"
        rationale = "Task asks for multiple distinct output domains, so it is routed as multi-context."
    elif _contains_keyword(normalized_task, WRITING_KEYWORDS):
        task_type = "writing"
        role = "writer"
        rationale = "Task contains a writing keyword, so it is routed to the writer role."
    elif _contains_keyword(normalized_task, REVIEW_KEYWORDS):
        task_type = "review"
        role = "reviewer"
        rationale = "Task contains a review keyword, so it is routed to the reviewer role."
    elif _contains_keyword(normalized_task, ANALYSIS_KEYWORDS):
        task_type = "analysis"
        role = "reviewer"
        rationale = "Task contains an analysis keyword, so it is routed to the reviewer role."
    elif _is_structured_writing_task(normalized_task):
        task_type = "writing"
        role = "writer"
        rationale = "Task asks for structured text output, so it is routed to the writer role."
    elif _contains_keyword(normalized_task, PLANNING_KEYWORDS):
        task_type = "planning"
        role = "architect"
        rationale = "Task explicitly asks for planning, so it is classified as planning for the architect role."
    elif _is_long_task(normalized_task) or _has_multiple_domains(normalized_task):
        task_type = "multi_context"
        role = "architect"
        rationale = "Task is long or spans multiple simple domains, so it is routed as multi-context."
    else:
        task_type = "planning"
        role = "architect"
        rationale = "No specific routing keyword matched, so the task defaults to planning."

    return {
        "task_type": task_type,
        "role": role,
        "provider": "local",
        "model": "mock-model",
        "memory_zones": [],
        "execution_mode": "direct",
        "max_input_tokens": 4000,
        "max_output_tokens": 1000,
        "requires_review": False,
        "confidence": 0.5,
        "rationale": rationale,
    }


def _contains_keyword(task: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(keyword)}\b", task) for keyword in keywords)


def _is_long_task(task: str) -> bool:
    return len(task.split()) >= LONG_TASK_WORDS


def _has_multiple_domains(task: str) -> bool:
    if _has_coding_and_explanation_patterns(task):
        return True

    matched_domains = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if _contains_keyword(task, keywords):
            matched_domains.append(domain)

    if len(matched_domains) >= 2 and _contains_connector(task):
        return True

    return len(matched_domains) >= 3


def _has_coding_and_explanation_patterns(task: str) -> bool:
    coding_terms = ("code", "function", "fix", "bug", "python", "debug", "implementation")
    explanation_terms = ("explain", "describe", "document", "report", "write-up")
    return _contains_keyword(task, coding_terms) and _contains_keyword(task, explanation_terms)


def _has_multi_context_output_domains(task: str) -> bool:
    domain_markers = (
        "routing accuracy",
        "prompt token savings",
        "latency",
        "write-up",
        "reporting",
        "software architecture",
        "cognitive routing",
        "token savings",
    )
    matched_count = sum(1 for marker in domain_markers if marker in task)
    return matched_count >= 3 and _contains_connector(task)


def _is_structured_writing_task(task: str) -> bool:
    return bool(re.search(r"\breturn\b.*\bjson\b", task))


def _contains_connector(task: str) -> bool:
    return bool(re.search(r"\b(and|plus|with|including|relate)\b", task))


if __name__ == "__main__":
    print(route("example task"))
