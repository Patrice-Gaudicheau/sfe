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
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeRouterError,
    build_execution_mode_prompt,
    parse_execution_mode_router_output,
)


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
