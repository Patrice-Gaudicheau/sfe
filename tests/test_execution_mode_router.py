"""Tests for LLM execution-mode routing contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.execution_mode_router import (
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_EXTERNAL_ACTION,
    EXECUTION_MODE_WORKSPACE_WRITE,
    EXECUTION_MODE_ROUTER_SYSTEM_INSTRUCTION,
    ExecutionModeRouterError,
    build_execution_mode_prompt,
    create_configured_execution_mode_router,
    parse_execution_mode_router_output,
)


class FakeCodexCLIProvider:
    def __init__(self, content: str = "", *, ok: bool = True, error: Exception | None = None) -> None:
        self.content = content
        self.ok = ok
        self.error = error
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": self.ok}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.content}}]}


def test_parse_execution_mode_router_accepts_console_output() -> None:
    decision = parse_execution_mode_router_output(
        '{"execution_mode":"console_output","reason":"The task asks for an explanation.","confidence":0.91}'
    )

    assert decision.execution_mode == EXECUTION_MODE_CONSOLE_OUTPUT
    assert decision.reason == "The task asks for an explanation."
    assert decision.confidence == 0.91


def test_parse_execution_mode_router_accepts_workspace_write() -> None:
    decision = parse_execution_mode_router_output(
        '{"execution_mode":"workspace_write","reason":"The task asks to modify files."}'
    )

    assert decision.execution_mode == EXECUTION_MODE_WORKSPACE_WRITE
    assert decision.reason == "The task asks to modify files."
    assert decision.confidence is None


def test_parse_execution_mode_router_accepts_external_action() -> None:
    decision = parse_execution_mode_router_output(
        '{"execution_mode":"external_action","reason":"The task asks to create a calendar event.","confidence":0.82}'
    )

    assert decision.execution_mode == EXECUTION_MODE_EXTERNAL_ACTION
    assert decision.reason == "The task asks to create a calendar event."
    assert decision.confidence == 0.82


def test_parse_execution_mode_router_rejects_invalid_json() -> None:
    with pytest.raises(ExecutionModeRouterError) as exc_info:
        parse_execution_mode_router_output("not json")

    assert exc_info.value.category == "invalid_execution_mode_router_response"


def test_parse_execution_mode_router_rejects_invalid_execution_mode() -> None:
    with pytest.raises(ExecutionModeRouterError) as exc_info:
        parse_execution_mode_router_output(
            '{"execution_mode":"direct","reason":"not an allowed mode"}'
        )

    assert exc_info.value.category == "invalid_execution_mode_router_response"
    assert "execution_mode" in exc_info.value.reason


def test_parse_execution_mode_router_rejects_empty_reason() -> None:
    with pytest.raises(ExecutionModeRouterError) as exc_info:
        parse_execution_mode_router_output(
            '{"execution_mode":"console_output","reason":"   "}'
        )

    assert exc_info.value.category == "invalid_execution_mode_router_response"
    assert "reason" in exc_info.value.reason


def test_execution_mode_prompt_asks_semantic_routing_question() -> None:
    prompt = build_execution_mode_prompt(task="Connais Symfony ?")

    assert "printing a response in the console" in prompt
    assert "writing files to the workspace" in prompt
    assert "console_output" in prompt
    assert "workspace_write" in prompt
    assert "external_action" in prompt
    assert "outside the workspace" in prompt


def test_execution_mode_router_factory_selects_codexcli_from_sfe_provider() -> None:
    provider = FakeCodexCLIProvider(
        '{"execution_mode":"console_output","reason":"The task asks for an answer.","confidence":0.8}'
    )
    router = create_configured_execution_mode_router(
        environ={
            "SFE_PROVIDER": "openai-codexcli",
            "SFE_OPENAI_ROUTER_MODEL": "gpt-router-test",
        },
        provider_factories={"openai-codexcli": lambda: provider},
    )

    decision = router.decide(task="Explain the architecture.")

    assert router.provider_name == "openai-codexcli"
    assert router.model == "gpt-router-test"
    assert decision.execution_mode == EXECUTION_MODE_CONSOLE_OUTPUT
    assert decision.provider_name == "openai-codexcli"
    assert decision.model == "gpt-router-test"
    assert decision.provider_calls_made == 1
    assert provider.calls[0]["model"] == "gpt-router-test"
    assert provider.calls[0]["system_instruction"] == EXECUTION_MODE_ROUTER_SYSTEM_INSTRUCTION
    assert provider.calls[0]["messages"] == [
        {"role": "user", "content": build_execution_mode_prompt(task="Explain the architecture.")}
    ]


def test_execution_mode_router_codexcli_uses_default_router_model() -> None:
    provider = FakeCodexCLIProvider(
        '{"execution_mode":"workspace_write","reason":"The task asks to edit files."}'
    )
    router = create_configured_execution_mode_router(
        environ={"SFE_PROVIDER": "openai-codexcli"},
        provider_factories={"openai-codexcli": lambda: provider},
    )

    decision = router.decide(task="Update the README.")

    assert router.provider_name == "openai-codexcli"
    assert router.model == "gpt-5.4"
    assert decision.execution_mode == EXECUTION_MODE_WORKSPACE_WRITE
    assert decision.model == "gpt-5.4"


@pytest.mark.parametrize("content", ("", "not json", "{}"))
def test_execution_mode_router_codexcli_invalid_output_fails_safely(content: str) -> None:
    provider = FakeCodexCLIProvider(content)
    router = create_configured_execution_mode_router(
        environ={"SFE_PROVIDER": "openai-codexcli"},
        provider_factories={"openai-codexcli": lambda: provider},
    )

    with pytest.raises(ExecutionModeRouterError) as exc_info:
        router.decide(task="Explain this project.")

    assert exc_info.value.category == "invalid_execution_mode_router_response"
    assert provider.calls


def test_execution_mode_router_codexcli_unavailable_fails_safely() -> None:
    provider = FakeCodexCLIProvider(ok=False)
    router = create_configured_execution_mode_router(
        environ={"SFE_PROVIDER": "openai-codexcli"},
        provider_factories={"openai-codexcli": lambda: provider},
    )

    with pytest.raises(ExecutionModeRouterError) as exc_info:
        router.decide(task="Explain this project.")

    assert exc_info.value.category == "execution_mode_router_not_configured"
    assert not provider.calls


def test_execution_mode_router_codexcli_provider_error_fails_safely() -> None:
    provider = FakeCodexCLIProvider(error=RuntimeError("raw codex failure"))
    router = create_configured_execution_mode_router(
        environ={"SFE_PROVIDER": "openai-codexcli"},
        provider_factories={"openai-codexcli": lambda: provider},
    )

    with pytest.raises(ExecutionModeRouterError) as exc_info:
        router.decide(task="Explain this project.")

    assert exc_info.value.category == "execution_mode_router_provider_error"
