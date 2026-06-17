"""Tests for Real Loop verifier/governor and bounded retry control."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.execution_mode_router import (  # noqa: E402
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
)
from sfe.patching import PatchSummary  # noqa: E402
from sfe.real_loop import (  # noqa: E402
    REAL_LOOP_EXECUTOR_FAILURE_MESSAGE,
    REAL_LOOP_STATUS_ABORTED,
    REAL_LOOP_STATUS_BLOCKED,
    REAL_LOOP_STATUS_VERIFIED_PASS,
    RealLoopConfig,
    RealLoopController,
    RealLoopRouteDecision,
    build_real_loop_workspace_snapshot,
    resolve_real_loop_config,
)
from sfe.real_loop_verifier import (  # noqa: E402
    REAL_LOOP_VERIFIER_SCHEMA_VERSION,
    RealLoopVerifierDecision,
    RealLoopVerifierResponse,
    create_configured_real_loop_verifier,
    parse_real_loop_verifier_json,
)
from sfe.run_pipeline import RUN_STATUS_COMPLETED, RunResult  # noqa: E402
from sfe.workspace_isolation import WorkspaceSession  # noqa: E402
from sfe_mcp.serializers import serialize_run_result  # noqa: E402
from sfe_tui.renderer import render_run_result, render_run_result_normal  # noqa: E402


class FakeVerifier:
    provider_name = "fake-verifier"
    model = "fake-model"

    def __init__(
        self,
        decisions: list[RealLoopVerifierDecision] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self.decisions = list(decisions or [])
        self.available = available
        self.requests = []

    def is_available(self) -> bool:
        return self.available

    def verify(self, request):
        self.requests.append(request)
        return RealLoopVerifierResponse(decision=self.decisions.pop(0))


class FakeProvider:
    def __init__(self, content: str | None = None) -> None:
        self.content = content or json.dumps(_decision_payload("pass"))
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": self.content}}]}


def test_parse_real_loop_verifier_accepts_all_terminal_verdicts() -> None:
    for verdict in ("pass", "blocked", "abort"):
        decision = parse_real_loop_verifier_json(json.dumps(_decision_payload(verdict)))

        assert decision.verdict == verdict
        assert decision.retry_worthwhile is False
        assert decision.executor_retry_task is None


def test_parse_real_loop_verifier_accepts_fenced_needs_retry() -> None:
    payload = _decision_payload(
        "needs_retry",
        retry_worthwhile=True,
        detected_issues=["README is missing usage notes"],
        correction_objective="Add usage notes",
        executor_retry_task="Update README.md with concise usage notes only.",
    )

    decision = parse_real_loop_verifier_json(
        "```json\n" + json.dumps(payload) + "\n```"
    )

    assert decision.verdict == "needs_retry"
    assert decision.retry_worthwhile is True
    assert decision.detected_issues == ("README is missing usage notes",)
    assert decision.executor_retry_task == "Update README.md with concise usage notes only."


def test_parse_real_loop_verifier_rejects_invalid_contract() -> None:
    payload = _decision_payload("needs_retry")

    with pytest.raises(Exception) as exc_info:
        parse_real_loop_verifier_json(json.dumps(payload))

    assert getattr(exc_info.value, "category") == "invalid_verifier_response"
    assert "needs_retry" in getattr(exc_info.value, "reason")


def test_parse_real_loop_verifier_rejects_non_string_lists() -> None:
    payload = _decision_payload("pass")
    payload["detected_issues"] = [123]

    with pytest.raises(Exception) as exc_info:
        parse_real_loop_verifier_json(json.dumps(payload))

    assert getattr(exc_info.value, "reason") == "verifier list item was invalid"


def test_config_defaults_are_conservative() -> None:
    config = resolve_real_loop_config({})

    assert config.mode == "auto"
    assert config.max_iterations == 3
    assert config.abort_on_no_progress is True
    assert config.abort_on_duplicate_retry_task is True


@pytest.mark.parametrize(
    ("environ", "expected_mode"),
    [
        ({}, "auto"),
        ({"SFE_REAL_LOOP": "   "}, "auto"),
        ({"SFE_REAL_LOOP": "false"}, "false"),
        ({"SFE_REAL_LOOP": "auto"}, "auto"),
        ({"SFE_REAL_LOOP": "true"}, "true"),
    ],
)
def test_real_loop_mode_resolution(
    environ: dict[str, str],
    expected_mode: str,
) -> None:
    assert resolve_real_loop_config(environ).mode == expected_mode


def test_workspace_snapshot_preserves_relative_preview_paths(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "src/index.html")

    snapshot = build_real_loop_workspace_snapshot(result, RealLoopConfig(mode="true"))

    assert snapshot["file_previews"][0]["path"] == "src/index.html"


def test_verifier_provider_prefers_explicit_verifier_provider_and_model() -> None:
    provider = FakeProvider()
    verifier = create_configured_real_loop_verifier(
        environ={
            "SFE_PROVIDER": "openai",
            "SFE_PROVIDER_ROUTER": "openai",
            "SFE_PROVIDER_VERIFIER": "lemonade",
            "SFE_LEMONADE_VERIFIER_MODEL": "loop-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    response = verifier.verify(_verifier_request())

    assert response.decision is not None
    assert response.decision.provider_name == "lemonade"
    assert response.decision.model == "loop-model"
    assert provider.calls[0]["model"] == "loop-model"


def test_verifier_needs_retry_without_correction_objective_has_diagnostics() -> None:
    payload = _decision_payload(
        "needs_retry",
        retry_worthwhile=True,
        detected_issues=["Missing status panel"],
        executor_retry_task="Add the missing status panel.",
    )
    provider = FakeProvider(json.dumps(payload))
    verifier = create_configured_real_loop_verifier(
        environ={
            "SFE_PROVIDER_VERIFIER": "openai",
            "OPENAI_API_KEY": "fixture-key",
            "SFE_OPENAI_VERIFIER_MODEL": "verifier-model",
        },
        provider_factories={"openai": lambda: provider},
    )

    response = verifier.verify(_verifier_request())

    assert response.decision is None
    assert response.issue is not None
    assert response.issue.reason == "needs_retry verdict requires correction_objective"
    assert response.issue.diagnostics is not None
    assert (
        response.issue.diagnostics["schema_validation_reason"]
        == "needs_retry verdict requires correction_objective"
    )
    assert '"verdict": "needs_retry"' in str(
        response.issue.diagnostics["raw_answer_preview"]
    )


def test_real_loop_report_includes_verifier_failure_preview(tmp_path: Path) -> None:
    payload = _decision_payload(
        "needs_retry",
        retry_worthwhile=True,
        detected_issues=["Missing status panel"],
        executor_retry_task="Add the missing status panel.",
    )
    provider = FakeProvider(json.dumps(payload))
    verifier = create_configured_real_loop_verifier(
        environ={
            "SFE_PROVIDER_VERIFIER": "openai",
            "OPENAI_API_KEY": "fixture-key",
            "SFE_OPENAI_VERIFIER_MODEL": "verifier-model",
        },
        provider_factories={"openai": lambda: provider},
    )
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=verifier,
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )
    rendered = render_run_result(final)

    assert final.real_loop_summary.real_loop_status == "verifier_failed"
    assert (
        "iteration 1 verifier schema reason: "
        "needs_retry verdict requires correction_objective"
    ) in rendered
    assert "iteration 1 verifier raw preview:" in rendered
    assert '"verdict": "needs_retry"' in rendered


def test_real_loop_passes_first_attempt(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier([_decision("pass")]),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create index.html",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_VERIFIED_PASS
    assert final.real_loop_summary.llm_verifier_verdict == "pass"


def test_real_loop_retries_with_targeted_task_then_passes(tmp_path: Path) -> None:
    first = _run_result(tmp_path, "index.html")
    retry = _run_result(tmp_path, "README.md")
    retry_sessions = []
    controller = RealLoopController(
        config=RealLoopConfig(mode="true", max_iterations=2),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                ),
                _decision("pass"),
            ]
        ),
    )

    def run_attempt(task, session):
        retry_sessions.append((task, session))
        return retry

    final = controller.run(
        initial_result=first,
        original_task="Create app files",
        run_attempt=run_attempt,
        route_correction_task=lambda task: RealLoopRouteDecision(
            EXECUTION_MODE_WORKSPACE_WRITE,
            "still writes files",
        ),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_VERIFIED_PASS
    assert final.real_loop_summary.attempts_total == 2
    assert retry_sessions[0][0] != "Create app files"
    assert retry_sessions == [
        ("Update README.md with usage notes only.", first.workspace_session)
    ]


def test_real_loop_blocks_without_retry(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier([_decision("blocked", stop_reason="missing_info")]),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_BLOCKED
    assert final.real_loop_summary.stop_reason == "missing_info"


def test_real_loop_aborts_duplicate_retry_task(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    retry_task="Create app files",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "duplicate_retry_task"
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE


def test_real_loop_aborts_no_progress_repeated_failure(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    progress="none",
                    repeated_failure=True,
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "no_meaningful_progress_repeated_failure"
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE
    assert REAL_LOOP_EXECUTOR_FAILURE_MESSAGE in render_run_result_normal(final)


def test_real_loop_aborts_no_progress_without_spending_retry(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    progress="none",
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "no_meaningful_progress"
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE


def test_real_loop_aborts_repeated_failure_without_spending_retry(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    repeated_failure=True,
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "repeated_failure"
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE


def test_real_loop_aborts_repeated_failure_category(tmp_path: Path) -> None:
    first = _run_result(tmp_path, "index.html")
    retry = _run_result(tmp_path, "README.md")
    retry_calls = []
    controller = RealLoopController(
        config=RealLoopConfig(mode="true", max_iterations=3),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                ),
                _decision(
                    "needs_retry",
                    retry_task="Add the remaining README usage caveat only.",
                    failure_category="missing_docs",
                ),
            ]
        ),
    )

    def run_attempt(task, session):
        retry_calls.append((task, session))
        return retry

    final = controller.run(
        initial_result=first,
        original_task="Create app files",
        run_attempt=run_attempt,
        route_correction_task=lambda task: RealLoopRouteDecision(
            EXECUTION_MODE_WORKSPACE_WRITE,
            "still writes files",
        ),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "repeated_failure_category"
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE
    assert len(retry_calls) == 1


def test_real_loop_aborts_when_executor_produces_no_relevant_changes(
    tmp_path: Path,
) -> None:
    first = _run_result(tmp_path, "index.html")
    retry = _run_result(tmp_path, "README.md", promoted_files=())
    controller = RealLoopController(
        config=RealLoopConfig(mode="true", max_iterations=3),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    retry_task="Update README.md with usage notes only.",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=first,
        original_task="Create app files",
        run_attempt=lambda task, session: retry,
        route_correction_task=lambda task: RealLoopRouteDecision(
            EXECUTION_MODE_WORKSPACE_WRITE,
            "still writes files",
        ),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert (
        final.real_loop_summary.stop_reason
        == "executor_produced_no_relevant_workspace_changes"
    )
    assert final.real_loop_summary.reason == REAL_LOOP_EXECUTOR_FAILURE_MESSAGE


def test_real_loop_aborts_when_retry_routes_away_from_workspace_write(
    tmp_path: Path,
) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier(
            [
                _decision(
                    "needs_retry",
                    retry_task="Explain what remains in the console.",
                    failure_category="missing_docs",
                )
            ]
        ),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: RealLoopRouteDecision(
            EXECUTION_MODE_CONSOLE_OUTPUT,
            "asks for explanation",
        ),
    )

    assert final.real_loop_summary.real_loop_status == REAL_LOOP_STATUS_ABORTED
    assert final.real_loop_summary.stop_reason == "correction_task_not_workspace_write"


def test_real_loop_report_surfaces_safe_summary(tmp_path: Path) -> None:
    result = _run_result(tmp_path, "index.html")
    controller = RealLoopController(
        config=RealLoopConfig(mode="true"),
        verifier=FakeVerifier([_decision("abort", stop_reason="retry_not_useful")]),
    )

    final = controller.run(
        initial_result=result,
        original_task="Create app files",
        run_attempt=lambda task, session: pytest.fail("retry should not run"),
        route_correction_task=lambda task: pytest.fail("route should not run"),
    )
    normal = render_run_result_normal(final)
    debug = render_run_result(final)
    serialized = serialize_run_result(final, include_diagnostics=True)

    assert REAL_LOOP_EXECUTOR_FAILURE_MESSAGE in normal
    assert "SFE Real Loop" in debug
    assert serialized["real_loop"]["real_loop_status"] == REAL_LOOP_STATUS_ABORTED
    assert "User task:" not in repr(serialized)
    assert "api_key" not in repr(serialized).lower()


def _decision_payload(verdict: str, **overrides):
    payload = {
        "schema_version": REAL_LOOP_VERIFIER_SCHEMA_VERSION,
        "verdict": verdict,
        "confidence": "medium",
        "satisfied_requirements": ["some requirements satisfied"],
        "missing_or_failed_requirements": [],
        "progress_since_previous_iteration": "unknown",
        "repeated_failure": False,
        "retry_worthwhile": False,
        "failure_category": None,
        "detected_issues": [],
        "correction_objective": None,
        "executor_retry_task": None,
        "files_or_areas_to_focus": [],
        "reason": "reasonable verifier explanation",
        "stop_reason": "verified_success"
        if verdict == "pass"
        else "blocked_reason"
        if verdict == "blocked"
        else "abort_reason"
        if verdict == "abort"
        else None,
    }
    payload.update(overrides)
    return payload


def _decision(
    verdict: str,
    *,
    progress: str = "meaningful",
    repeated_failure: bool = False,
    retry_task: str | None = None,
    failure_category: str | None = None,
    stop_reason: str | None = None,
) -> RealLoopVerifierDecision:
    payload = _decision_payload(
        verdict,
        progress_since_previous_iteration=progress,
        repeated_failure=repeated_failure,
        failure_category=failure_category,
    )
    if verdict == "needs_retry":
        payload.update(
            {
                "retry_worthwhile": True,
                "detected_issues": ["missing docs"],
                "missing_or_failed_requirements": ["docs"],
                "correction_objective": "Add only the missing docs",
                "executor_retry_task": retry_task
                or "Update README.md with the missing documentation only.",
                "files_or_areas_to_focus": ["README.md"],
                "stop_reason": None,
            }
        )
    if stop_reason is not None:
        payload["stop_reason"] = stop_reason
    return parse_real_loop_verifier_json(json.dumps(payload))


def _verifier_request():
    from sfe.real_loop_verifier import RealLoopVerifierRequest

    return RealLoopVerifierRequest(
        original_task="Create app files",
        current_task="Create app files",
        attempt_index=1,
        max_iterations=3,
        previous_retry_tasks=(),
        previous_failure_categories=(),
        run_result={},
        workspace_snapshot={},
    )


def _run_result(
    tmp_path: Path,
    changed_path: str,
    *,
    promoted_files: tuple[str, ...] | None = None,
) -> RunResult:
    target = tmp_path / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    session = WorkspaceSession(
        session_id="session-1",
        source_path=tmp_path,
        source_git_root=tmp_path,
        worktree_path=tmp_path,
        source_branch="main",
        worktree_branch="sfe/worktree/session-1",
        backend_name="git-worktree",
    )
    return RunResult(
        status=RUN_STATUS_COMPLETED,
        execution_mode_decision=ExecutionModeDecision(
            execution_mode=EXECUTION_MODE_WORKSPACE_WRITE,
            reason="writes files",
            confidence=0.9,
            provider_name="fake-router",
            model="fake-router-model",
            provider_calls_made=1,
        ),
        workspace_session=session,
        active_workspace=tmp_path,
        patch_summary=PatchSummary(
            paths=(changed_path,),
            file_count=1,
            hunk_count=0,
            lines_added=1,
            lines_removed=0,
            modified_paths=(changed_path,),
            created_paths=(),
        ),
        changed_files=(changed_path,),
        promoted_files=promoted_files if promoted_files is not None else (changed_path,),
        promotion_status="applied",
        promotion_applied=promoted_files != (),
        executor_provider="fake-executor",
    )
