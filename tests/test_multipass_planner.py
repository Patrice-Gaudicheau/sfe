"""Tests for Router-owned multi-pass planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.contracts import ContextSegment, ProtectedText, SFEContract
from sfe.multipass import MultiPassConfig
from sfe.multipass_planner import (
    MULTIPASS_PLANNER_SYSTEM_INSTRUCTION,
    build_multipass_planner_prompt,
    create_configured_multipass_planner,
)


class FakeProvider:
    def __init__(self, content: str, *, ok: bool = True) -> None:
        self.content = content
        self.ok = ok
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": self.ok}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": self.content}}]}


def test_multipass_planner_factory_uses_router_model_and_ignores_legacy_model() -> None:
    provider = FakeProvider(_plan_json({"foundation": ["composer.json"]}))
    planner = create_configured_multipass_planner(
        environ={
            "SFE_PROVIDER": "openai",
            "SFE_OPENAI_ROUTER_MODEL": "router-model",
            "SFE_MULTIPASS_PLANNER_MODEL": "legacy-planner-model",
        },
        provider_factories={"openai": lambda: provider},
    )

    response = planner.plan(_contract(), config=MultiPassConfig())

    assert response.plan is not None
    assert response.issue is None
    assert planner.provider_name == "openai"
    assert planner.model == "router-model"
    assert response.model == "router-model"
    assert provider.calls[0]["model"] == "router-model"
    assert provider.calls[0]["model"] != "legacy-planner-model"


def test_multipass_planner_prompt_forbids_patch_generation() -> None:
    prompt = build_multipass_planner_prompt(
        contract=_contract(),
        config=MultiPassConfig(max_passes=4, max_files_per_pass=3),
    )

    assert "Return strict JSON only" in prompt
    assert "Do not return Markdown" in prompt
    assert "diffs" in prompt
    assert "patches" in prompt
    assert "file edits" in prompt
    assert "Executor generates patches later" in prompt
    assert "Return only one strict JSON object" in MULTIPASS_PLANNER_SYSTEM_INSTRUCTION
    assert "Do not return Markdown" in MULTIPASS_PLANNER_SYSTEM_INSTRUCTION
    assert "diffs" in MULTIPASS_PLANNER_SYSTEM_INSTRUCTION
    assert "patches" in MULTIPASS_PLANNER_SYSTEM_INSTRUCTION
    assert "file edits" in MULTIPASS_PLANNER_SYSTEM_INSTRUCTION


def test_multipass_planner_returns_validated_plan() -> None:
    provider = FakeProvider(
        _plan_json(
            {
                "foundation": ["composer.json"],
                "public": ["public/index.php"],
            },
            depends_on={"public": ["foundation"]},
        )
    )
    planner = create_configured_multipass_planner(
        environ={"SFE_PROVIDER_ROUTER": "codexcli", "SFE_CODEXCLI_ROUTER_MODEL": "gpt-router"},
        provider_factories={"codexcli": lambda: provider},
    )

    response = planner.plan(_contract(), config=MultiPassConfig())

    assert response.plan is not None
    assert response.plan.project_summary == "Mock scaffold"
    assert tuple(batch.id for batch in response.plan.batches) == ("foundation", "public")
    assert response.issue is None
    assert response.provider_name == "codexcli"
    assert response.provider_calls_made == 1
    assert provider.calls[0]["system_instruction"] == MULTIPASS_PLANNER_SYSTEM_INSTRUCTION


def _plan_json(
    batch_files: dict[str, list[str]],
    *,
    depends_on: dict[str, list[str]] | None = None,
) -> str:
    depends_on = depends_on or {}
    return json.dumps(
        {
            "project_summary": "Mock scaffold",
            "batches": [
                {
                    "id": batch_id,
                    "title": batch_id.title(),
                    "goal": f"Create {batch_id} files.",
                    "allowed_files": files,
                    "depends_on": depends_on.get(batch_id, []),
                    "validation_notes": ["mock validation"],
                }
                for batch_id, files in batch_files.items()
            ],
        }
    )


@pytest.mark.parametrize(
    ("content", "reason"),
    (
        ("{bad json", "invalid_plan_json"),
        (_plan_json({"foundation": []}), "empty_allowed_files"),
        (
            _plan_json(
                {"templates": ["templates/base.html.twig"], "foundation": ["composer.json"]},
                depends_on={"templates": ["foundation"]},
            ),
            "invalid_dependency",
        ),
        (_plan_json({"foundation": ["../outside.txt"]}), "unsafe_allowed_path"),
        (_plan_json({"one": ["one.txt"], "two": ["two.txt"], "three": ["three.txt"]}), "too_many_passes"),
        (_plan_json({"foundation": ["one.txt", "two.txt", "three.txt"]}), "too_many_files_per_pass"),
        ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md", "invalid_plan_json"),
    ),
)
def test_multipass_planner_invalid_plans_fail_safely(
    content: str,
    reason: str,
) -> None:
    provider = FakeProvider(content)
    planner = create_configured_multipass_planner(
        environ={"SFE_PROVIDER": "openai"},
        provider_factories={"openai": lambda: provider},
    )

    response = planner.plan(
        _contract(),
        config=MultiPassConfig(max_passes=2, max_files_per_pass=2),
    )

    assert response.plan is None
    assert response.issue is not None
    assert response.issue.reason == reason
    assert response.provider_calls_made == 1


def _contract() -> SFEContract:
    return SFEContract(
        instructions=[ProtectedText(id="system", text="Use selected context.")],
        task=ProtectedText(id="task_current", text="Create a small scaffold."),
        context_segments=[
            ContextSegment(
                id="ctx_readme",
                source_ref="README.md",
                text="# Existing project\n",
            )
        ],
        protected_segments=[],
    )

