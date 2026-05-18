"""Read-only executor adapters for the SFE-aware TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)


DEFAULT_MAX_OUTPUT_TOKENS = 800
READ_ONLY_SYSTEM_INSTRUCTION = (
    "You are the read-only SFE TUI executor. Answer only from the selected "
    "context and the user's task. Do not claim to edit files, run commands, "
    "or use tools."
)


@dataclass(frozen=True)
class ExecutorResponse:
    answer: str | None
    error_category: str | None
    provider_calls_made: int


class ReadOnlyExecutor(Protocol):
    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        ...


class OpenAIReadOnlyExecutor:
    """Small OpenAI-backed read-only executor for selected TUI context."""

    def __init__(
        self,
        *,
        provider: OpenAIAPIProvider | None = None,
        model: str | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self.provider = provider or OpenAIAPIProvider()
        self.model = (
            model
            or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
            or DEFAULT_EXECUTOR_MODEL
        )
        self.max_output_tokens = max_output_tokens

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        health = self.provider.health()
        if not health.get("ok"):
            return ExecutorResponse(
                answer=None,
                error_category="provider_not_configured",
                provider_calls_made=0,
            )
        try:
            response = self.provider.chat(
                [{"role": "user", "content": _build_user_prompt(executor_payload)}],
                model=self.model,
                max_tokens=self.max_output_tokens,
                temperature=None,
                system_instruction=READ_ONLY_SYSTEM_INSTRUCTION,
            )
        except MissingOpenAIAPIKeyError:
            return ExecutorResponse(
                answer=None,
                error_category="provider_not_configured",
                provider_calls_made=0,
            )
        except TimeoutError:
            return ExecutorResponse(
                answer=None,
                error_category="timeout",
                provider_calls_made=1,
            )
        except OpenAIAPIError:
            return ExecutorResponse(
                answer=None,
                error_category="provider_error",
                provider_calls_made=1,
            )
        except Exception:
            return ExecutorResponse(
                answer=None,
                error_category="provider_error",
                provider_calls_made=1,
            )

        answer = _extract_answer(response)
        if not answer:
            return ExecutorResponse(
                answer=None,
                error_category="invalid_response",
                provider_calls_made=1,
            )
        return ExecutorResponse(
            answer=answer,
            error_category=None,
            provider_calls_made=1,
        )


def _build_user_prompt(executor_payload: dict[str, Any]) -> str:
    instructions = executor_payload.get("instructions") or []
    task = executor_payload.get("task")
    selected_segments = executor_payload.get("selected_context_segments") or []
    instruction_text = "\n".join(
        str(item.text) for item in instructions if getattr(item, "text", "")
    )
    task_text = str(getattr(task, "text", "") or "")
    context_parts = [
        f"[{segment.id}]\n{segment.text}"
        for segment in selected_segments
        if getattr(segment, "text", "")
    ]
    return "\n\n".join(
        part
        for part in (
            "Protected instructions:\n" + instruction_text,
            "User task:\n" + task_text,
            "Selected context:\n" + "\n\n".join(context_parts),
        )
        if part.strip()
    )


def _extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if content is not None:
                    return str(content).strip()
    return ""
