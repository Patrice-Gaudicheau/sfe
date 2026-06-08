"""Tests for Ollama provider routing through SFE surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.discovery_router import create_configured_discovery_router
from sfe.execution_mode_router import create_configured_execution_mode_router
from sfe.router_review import create_configured_router_json_reviewer
from sfe.segment_selector import (
    CandidateSegment,
    SegmentSelectionInput,
    create_configured_segment_selector,
)
from sfe_tui.executors import READ_ONLY_SYSTEM_INSTRUCTION, create_tui_executor
from sfe_tui.patch_json_repair import create_tui_patch_json_repairer


class FakeProvider:
    def __init__(self, content: str = "provider answer") -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": self.content}}]}


def test_ollama_can_be_selected_as_canonical_provider() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={
            "SFE_PROVIDER": "ollama",
            "SFE_OLLAMA_EXECUTOR_MODEL": "ollama-executor",
        },
        provider_factories={"ollama": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "ollama"
    assert result.provider_name == "ollama"
    assert result.answer == "provider answer"
    assert provider.calls[0]["model"] == "ollama-executor"
    assert provider.calls[0]["messages"][0] == {
        "role": "system",
        "content": READ_ONLY_SYSTEM_INSTRUCTION,
    }
    assert "system_instruction" not in provider.calls[0]


def test_ollama_router_reviewer_uses_router_model_and_system_message() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "decision": "OK_TEST",
                "reason": "valid test decision",
                "files_reviewed": ["example.py"],
                "risk_level": "low",
            }
        )
    )
    reviewer = create_configured_router_json_reviewer(
        system_instruction="Return JSON.",
        prompt_builder=lambda payload: json.dumps(payload, sort_keys=True),
        valid_decisions={"OK_TEST", "KO_BLOCK"},
        max_tokens=128,
        environ={
            "SFE_PROVIDER": "openai",
            "SFE_PROVIDER_ROUTER": "ollama",
            "SFE_OLLAMA_ROUTER_MODEL": "ollama-router",
            "SFE_OLLAMA_MODEL": "ollama-shared",
        },
        provider_factories={"ollama": lambda: provider},
    )

    decision = reviewer.review({"task": "check"})

    assert decision.provider_name == "ollama"
    assert decision.model == "ollama-router"
    assert provider.calls[0]["model"] == "ollama-router"
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert "system_instruction" not in provider.calls[0]


def test_ollama_discovery_router_accepts_role_specific_provider() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "files_to_inspect": ["README.md"],
                "reason": "README likely documents provider setup.",
            }
        )
    )
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER": "openai",
            "SFE_PROVIDER_DISCOVERY": "ollama",
            "SFE_OLLAMA_DISCOVERY_MODEL": "ollama-discovery",
        },
        provider_factories={"ollama": lambda: provider},
    )

    selection = router.select_files(
        task="document ollama",
        workspace_map=[{"path": "README.md", "kind": "file"}],
        max_files=3,
    )

    assert selection.provider_name == "ollama"
    assert selection.model == "ollama-discovery"
    assert selection.files_to_inspect == ("README.md",)
    assert provider.calls[0]["model"] == "ollama-discovery"


def test_ollama_execution_mode_router_accepts_run_routing_provider() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "execution_mode": "workspace_write",
                "reason": "task asks to modify files",
                "confidence": 0.7,
            }
        )
    )
    router = create_configured_execution_mode_router(
        environ={
            "SFE_PROVIDER_ROUTER": "ollama",
            "SFE_OLLAMA_MODEL": "ollama-shared",
        },
        provider_factories={"ollama": lambda: provider},
    )

    decision = router.decide(task="change README")

    assert decision.provider_name == "ollama"
    assert decision.model == "ollama-shared"
    assert decision.execution_mode == "workspace_write"
    assert provider.calls[0]["model"] == "ollama-shared"


def test_ollama_patch_json_repair_uses_shared_model() -> None:
    provider = FakeProvider('{"edits":[]}')
    repairer = create_tui_patch_json_repairer(
        environ={
            "SFE_PROVIDER": "ollama",
            "SFE_OLLAMA_MODEL": "ollama-shared",
        },
        provider_factories={"ollama": lambda: provider},
    )

    result = repairer.repair(raw_response="{bad", parse_error="invalid JSON")

    assert result.repaired_text == '{"edits":[]}'
    assert result.provider_name == "ollama"
    assert result.model == "ollama-shared"
    assert provider.calls[0]["model"] == "ollama-shared"


def test_ollama_segment_selector_accepts_provider_and_model() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "router_status": "selected",
                "router_reason": "payment segment is relevant",
                "selected_segment_ids": ["payments"],
            }
        )
    )
    selector = create_configured_segment_selector(
        provider_name="ollama",
        environ={"SFE_OLLAMA_ROUTER_MODEL": "ollama-router"},
        provider_factories={"ollama": lambda: provider},
    )

    result = selector.select(
        SegmentSelectionInput(
            request_id="req-1",
            task="inspect payment code",
            output_contract="answer",
            candidate_segments=(
                CandidateSegment("payments", "payments.py", "payment code"),
            ),
        )
    )

    assert result.provider_name == "ollama"
    assert result.model == "ollama-router"
    assert result.selected_segment_ids == ("payments",)
    assert provider.calls[0]["model"] == "ollama-router"
