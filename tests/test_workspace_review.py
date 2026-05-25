"""Tests for isolated workspace router review objects."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.router_review import RouterReviewError
from sfe.workspace_isolation import WorkspaceStatus
from sfe.workspace_review import (
    WORKSPACE_REVIEW_SYSTEM_INSTRUCTION,
    build_workspace_review_payload,
    build_workspace_review_prompt,
    parse_workspace_review_decision,
)


def test_workspace_review_parses_ok_promote() -> None:
    decision = parse_workspace_review_decision(
        """
        {
          "decision": "OK_PROMOTE",
          "reason": "changes match the task",
          "files_reviewed": ["example.txt"],
          "risk_level": "low"
        }
        """
    )

    assert decision.decision == "OK_PROMOTE"
    assert decision.reason == "changes match the task"
    assert decision.files_reviewed == ("example.txt",)
    assert decision.risk_level == "low"


def test_workspace_review_parses_ko_block() -> None:
    decision = parse_workspace_review_decision(
        """
        {
          "decision": "KO_BLOCK",
          "reason": "diff contains unrelated changes",
          "files_reviewed": ["example.txt"],
          "risk_level": "high"
        }
        """
    )

    assert decision.decision == "KO_BLOCK"
    assert decision.reason == "diff contains unrelated changes"
    assert decision.risk_level == "high"


def test_workspace_review_rejects_patch_decision_schema() -> None:
    with pytest.raises(RouterReviewError) as exc_info:
        parse_workspace_review_decision(
            """
            {
              "decision": "OK_APPLY",
              "reason": "wrong review schema",
              "files_reviewed": ["example.txt"],
              "risk_level": "low"
            }
            """
        )

    assert exc_info.value.category == "invalid_router_response"
    assert exc_info.value.reason == "router decision was invalid"


def test_workspace_review_payload_contains_task_diff_status_and_metadata(tmp_path) -> None:
    status = WorkspaceStatus(
        git_status_porcelain=" M example.txt\n",
        git_diff="diff --git a/example.txt b/example.txt\n",
        changed_files=("example.txt",),
        source_path=tmp_path / "repo",
        worktree_path=tmp_path / "worktree",
        source_branch="main",
        worktree_branch="sfe/worktree/session123",
    )

    payload = build_workspace_review_payload(
        original_user_task="Update the example text.",
        workspace_status=status,
        test_results={"ran": False},
        discovered_constraints={"existing_files_only": True},
    )
    prompt = build_workspace_review_prompt(payload)

    assert payload["original_user_task"] == "Update the example text."
    assert payload["git_status_porcelain"] == " M example.txt\n"
    assert payload["git_diff_preview"] == "diff --git a/example.txt b/example.txt\n"
    assert payload["changed_files"] == ["example.txt"]
    assert payload["test_results"] == {"ran": False}
    assert payload["discovered_constraints"] == {"existing_files_only": True}
    assert payload["workspace_metadata"]["source_branch"] == "main"
    assert payload["workspace_metadata"]["worktree_branch"] == "sfe/worktree/session123"
    assert "Workspace review payload JSON:" in prompt
    assert "OK_PROMOTE" in prompt
    assert "decision must be OK_PROMOTE or KO_BLOCK" in WORKSPACE_REVIEW_SYSTEM_INSTRUCTION
    assert "risk_level must be low, medium, or high" in WORKSPACE_REVIEW_SYSTEM_INSTRUCTION
    assert "files_reviewed must be a JSON array of strings" in (
        WORKSPACE_REVIEW_SYSTEM_INSTRUCTION
    )
    assert "Do not return a string, object, count, or comma-separated text" in (
        WORKSPACE_REVIEW_SYSTEM_INSTRUCTION
    )
