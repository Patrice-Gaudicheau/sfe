"""Blocking application loop for the first-party SFE-aware TUI."""

from __future__ import annotations

import shlex
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sfe.discovery import (
    DiscoveryResult,
    discover_workspace_context,
    load_discovered_context,
)
from sfe.patching import (
    MECHANICAL_GUARD_REJECTED,
    ParsedPatch,
    PatchIssue,
    PatchSummary,
    apply_patch_to_workspace,
    parse_unified_diff,
    preview_file_patch_text,
    validate_patch_paths,
    validate_patch_targets,
)
from sfe.env import load_repo_env
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.workspace_isolation import (
    WorkspaceIsolationPolicy,
    WorkspaceManager,
    WorkspaceSession,
)
from sfe.workspace_review import (
    WorkspaceReviewError,
    WorkspaceReviewer,
    build_workspace_review_payload,
    create_workspace_reviewer,
)

from .backends import (
    BackendAdapter,
    BackendResult,
    ask_error_result,
    backend_by_name,
    patch_error_result,
)
from .contracts import (
    ContextLoadResult,
    SFEContract,
    build_contract,
    load_context_file,
    resolve_workspace,
)
from .input import TerminalInput
from .file_edits import (
    FileReplacementProposal,
    apply_file_replacements,
    generate_replacement_diff_preview,
    parse_file_replacement_proposal,
    summarize_file_replacements,
)
from .patch_review import (
    PatchReviewError,
    PatchReviewer,
    create_tui_patch_reviewer,
)
from . import renderer


OutputFunc = Callable[[str], None]


@dataclass(frozen=True)
class PendingPatchProposal:
    text: str
    proposal: FileReplacementProposal | ParsedPatch
    preview: str
    source: str
    created_from_task_hash: str
    selected_source_refs: tuple[str, ...]
    provider_name: str | None
    summary: PatchSummary
    parse_status: str = "accepted"


class SfeTuiApp:
    def __init__(
        self,
        *,
        input_provider: TerminalInput | None = None,
        output: OutputFunc = print,
        cwd: Path | None = None,
        backend: BackendAdapter | None = None,
        patch_reviewer: PatchReviewer | None = None,
        workspace_manager: WorkspaceManager | None = None,
        workspace_reviewer: WorkspaceReviewer | None = None,
    ) -> None:
        self.input_provider = input_provider or TerminalInput()
        self.output = output
        self.cwd = (cwd or Path.cwd()).resolve()
        self.backend = backend or backend_by_name("direct")
        self.patch_reviewer = patch_reviewer or create_tui_patch_reviewer()
        self.workspace_manager = workspace_manager or WorkspaceManager(GitWorktreeBackend())
        self.workspace_reviewer = workspace_reviewer or create_workspace_reviewer()
        self.workspace_root: Path | None = None
        self.workspace_session: WorkspaceSession | None = None
        self.context_files: list[ContextLoadResult] = []
        self.discovery_result: DiscoveryResult | None = None
        self.task = ""
        self.latest_result: BackendResult | None = None
        self.pending_patch: PendingPatchProposal | None = None

    def run(self) -> int:
        if not self._select_workspace():
            return 1
        self.output(renderer.render_help())
        while True:
            command = self.input_provider.prompt("sfe> ").strip()
            if not command:
                continue
            if self._handle_command(command):
                return 0

    def _select_workspace(self) -> bool:
        raw = self.input_provider.prompt(
            "Workspace [current]: ",
            default="",
        )
        try:
            self.workspace_root = resolve_workspace(raw, self.cwd)
        except ValueError as exc:
            self.output(renderer.render_error(str(exc)))
            return False
        self.output(renderer.render_workspace_selected(self.workspace_root, self.cwd))
        return True

    def _handle_command(self, command: str) -> bool:
        name, _, rest = command.partition(" ")
        if name == "/help":
            self.output(renderer.render_help())
            return False
        if name in {"/quit", "/exit"}:
            return True
        if name in {"/directory", "/pwd"}:
            if self.workspace_root is None:
                self.output("Workspace: not selected")
            else:
                self.output(
                    renderer.render_workspace_selected(self.workspace_root, self.cwd)
                )
            return False
        if name == "/status":
            loaded_context_files = sum(
                1 for result in self.context_files if result.loaded
            )
            skipped_context_files = sum(
                1 for result in self.context_files if not result.loaded
            )
            self.output(
                renderer.render_status(
                    workspace_selected=self.workspace_root is not None,
                    workspace_label=(
                        renderer.safe_workspace_label(self.workspace_root, self.cwd)
                        if self.workspace_root is not None
                        else None
                    ),
                    loaded_context_files=loaded_context_files,
                    skipped_context_files=skipped_context_files,
                    loaded_context_segments=loaded_context_files,
                    task_present=bool(self.task.strip()),
                    discovery_result=self.discovery_result,
                    backend_name=self.backend.name,
                    executor_provider_name=getattr(
                        self.backend,
                        "executor_provider_name",
                        None,
                    ),
                    latest_result=self.latest_result,
                    pending_patch_summary=(
                        self.pending_patch.summary
                        if self.pending_patch is not None
                        else None
                    ),
                )
            )
            return False
        if name == "/context":
            self._handle_context()
            return False
        if name == "/files":
            self._handle_files(rest)
            return False
        if name == "/task":
            task = rest.strip()
            if not task:
                self.output(renderer.render_error("missing_task"))
                return False
            self.task = task
            self.discovery_result = None
            self.latest_result = None
            self._clear_pending_patch()
            self.output(renderer.render_task_set())
            return False
        if name == "/discover":
            self._handle_discover()
            return False
        if name == "/dry-run":
            self._handle_dry_run()
            return False
        if name == "/ask":
            self._handle_ask()
            return False
        if name == "/patch":
            self._handle_patch()
            return False
        if name == "/apply-patch":
            self._handle_apply_patch()
            return False
        if name == "/isolate":
            self._handle_isolate()
            return False
        if name == "/workspace-status":
            self._handle_workspace_status()
            return False
        if name == "/worktree-diff":
            self._handle_worktree_diff()
            return False
        if name == "/review-worktree":
            self._handle_review_worktree()
            return False
        if name == "/cleanup-worktree":
            self._handle_cleanup_worktree()
            return False
        if name == "/gc-worktrees":
            self._handle_gc_worktrees(rest)
            return False
        if name == "/auto-patch":
            self._handle_auto_patch()
            return False
        if name == "/auto-worktree":
            self._handle_auto_worktree()
            return False
        if name == "/reset":
            self._handle_reset()
            return False
        self.output(renderer.render_error("unknown_command"))
        return False

    def _handle_files(self, rest: str) -> None:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return
        try:
            values = shlex.split(rest)
        except ValueError:
            self.output(renderer.render_error("invalid_file_command"))
            return
        if not values:
            self.output(renderer.render_error("no_files_provided"))
            return
        self.context_files = [
            load_context_file(self.workspace_root, value) for value in values
        ]
        self.latest_result = None
        self._clear_pending_patch()
        self.output(renderer.render_file_selection(self.context_files))

    def _handle_discover(self) -> bool:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return False
        if not self.task.strip():
            self.output(renderer.render_error("missing_task"))
            return False
        self.discovery_result = discover_workspace_context(
            workspace_root=self.workspace_root,
            task=self.task,
        )
        self.latest_result = None
        self._clear_pending_patch()
        self.output(renderer.render_discovery_summary(self.discovery_result))
        return True

    def _handle_reset(self) -> None:
        self.context_files = []
        self.discovery_result = None
        self.task = ""
        self.latest_result = None
        self._clear_pending_patch()
        self.output(renderer.render_reset())

    def _handle_isolate(self) -> bool:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return False
        if self.workspace_session is not None:
            self.output(renderer.render_error("workspace_already_isolated"))
            return False
        result = self.workspace_manager.create(
            self.workspace_root,
            WorkspaceIsolationPolicy(),
        )
        if not result.created or result.session is None:
            self.output(renderer.render_isolate_failure(result.issue))
            return False
        session = result.session
        self.workspace_session = session
        self.workspace_root = self._active_path_for_session(session)
        self.context_files = []
        self.discovery_result = None
        self.latest_result = None
        self._clear_pending_patch()
        self.output(
            renderer.render_isolate_success(
                session,
                active_workspace=self.workspace_root,
                launch_cwd=self.cwd,
            )
        )
        return True

    def _handle_workspace_status(self) -> None:
        status_result = (
            self.workspace_manager.status(self.workspace_session)
            if self.workspace_session is not None
            else None
        )
        self.output(
            renderer.render_workspace_mode_status(
                workspace_root=self.workspace_root,
                workspace_session=self.workspace_session,
                status_result=status_result,
                launch_cwd=self.cwd,
            )
        )

    def _handle_worktree_diff(self) -> bool:
        if self.workspace_session is None:
            self.output(renderer.render_error("no_isolated_workspace"))
            return False
        status_result = self.workspace_manager.status(self.workspace_session)
        self.output(renderer.render_worktree_diff(status_result))
        return status_result.ok

    def _handle_review_worktree(self) -> bool:
        if self.workspace_session is None:
            self.output(renderer.render_error("no_isolated_workspace"))
            return False
        status_result = self.workspace_manager.status(self.workspace_session)
        if not status_result.ok or status_result.status is None:
            self.output(renderer.render_worktree_review_failure(status_result.issue))
            return False
        payload = build_workspace_review_payload(
            original_user_task=self.task,
            workspace_status=status_result.status,
            test_results={"ran": False},
            discovered_constraints=self._infer_task_constraints(),
        )
        try:
            decision = self.workspace_reviewer.review(payload)
        except WorkspaceReviewError as exc:
            self.output(
                renderer.render_worktree_review_failure(
                    None,
                    failure_category=exc.category,
                    router_reason=exc.reason,
                    router_provider=getattr(self.workspace_reviewer, "provider_name", None),
                    router_model=getattr(self.workspace_reviewer, "model", None),
                )
            )
            return False
        self.output(renderer.render_worktree_review_success(decision))
        return decision.decision == "OK_PROMOTE"

    def _handle_cleanup_worktree(self) -> bool:
        if self.workspace_session is None:
            self.output(renderer.render_error("no_isolated_workspace"))
            return False
        session = self.workspace_session
        result = self.workspace_manager.cleanup(session)
        if result.cleaned:
            self.workspace_session = None
            self.workspace_root = session.source_path
            self.context_files = []
            self.discovery_result = None
            self.latest_result = None
            self._clear_pending_patch()
        self.output(
            renderer.render_cleanup_worktree_result(
                result,
                restored_workspace=session.source_path if result.cleaned else None,
                launch_cwd=self.cwd,
            )
        )
        return result.cleaned

    def _handle_gc_worktrees(self, rest: str) -> bool:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return False
        try:
            values = shlex.split(rest)
        except ValueError:
            self.output(renderer.render_error("invalid_gc_command"))
            return False
        clean = False
        for value in values:
            if value == "--clean":
                clean = True
                continue
            self.output(renderer.render_error("invalid_gc_command"))
            return False
        gc_root = (
            self.workspace_session.source_path
            if self.workspace_session is not None
            else self.workspace_root
        )
        result = self.workspace_manager.gc(
            gc_root,
            clean=clean,
            protected_session_ids=(
                (self.workspace_session.session_id,)
                if self.workspace_session is not None
                else ()
            ),
        )
        self.output(renderer.render_gc_worktrees_result(result, launch_cwd=self.cwd))
        return result.issue is None

    def _handle_auto_patch(self) -> bool:
        self.output(renderer.render_macro_start("auto-patch"))
        if not self.task.strip():
            self.output(renderer.render_macro_stop("auto-patch", "missing_task"))
            self.output(renderer.render_error("missing_task"))
            return False
        if not self.context_files and self.discovery_result is None:
            self.output(renderer.render_macro_step("auto-patch", "discover"))
            if not self._handle_discover():
                self.output(renderer.render_macro_stop("auto-patch", "discover_failed"))
                return False
        self.output(renderer.render_macro_step("auto-patch", "dry-run"))
        if not self._handle_dry_run():
            self.output(renderer.render_macro_stop("auto-patch", "dry_run_failed"))
            return False
        self.output(renderer.render_macro_step("auto-patch", "patch"))
        if not self._handle_patch():
            self.output(renderer.render_macro_stop("auto-patch", "patch_failed"))
            return False
        self.output(renderer.render_macro_step("auto-patch", "apply-patch"))
        if not self._handle_apply_patch():
            self.output(renderer.render_macro_stop("auto-patch", "apply_patch_failed"))
            return False
        self.output(renderer.render_macro_done("auto-patch"))
        return True

    def _handle_auto_worktree(self) -> bool:
        self.output(renderer.render_macro_start("auto-worktree"))
        if not self.task.strip():
            self.output(renderer.render_macro_stop("auto-worktree", "missing_task"))
            self.output(renderer.render_error("missing_task"))
            return False
        manual_context_refs = tuple(
            result.source_ref
            for result in self.context_files
            if result.loaded and result.source_ref is not None
        )
        if self.workspace_session is None:
            self.output(renderer.render_macro_step("auto-worktree", "isolate"))
            if not self._handle_isolate():
                self.output(renderer.render_macro_stop("auto-worktree", "isolate_failed"))
                return False
            if manual_context_refs:
                self.context_files = [
                    load_context_file(self.workspace_root, source_ref)
                    for source_ref in manual_context_refs
                ]
                self.output(renderer.render_file_selection(self.context_files))
                if not any(result.loaded for result in self.context_files):
                    self.output(renderer.render_macro_stop("auto-worktree", "manual_context_failed"))
                    return False
        if not self.context_files and self.discovery_result is None:
            self.output(renderer.render_macro_step("auto-worktree", "discover"))
            if not self._handle_discover():
                self.output(renderer.render_macro_stop("auto-worktree", "discover_failed"))
                return False
        self.output(renderer.render_macro_step("auto-worktree", "patch"))
        if not self._handle_patch():
            self.output(renderer.render_macro_stop("auto-worktree", "patch_failed"))
            return False
        self.output(renderer.render_macro_step("auto-worktree", "apply-patch"))
        if not self._handle_apply_patch():
            self.output(renderer.render_macro_stop("auto-worktree", "apply_patch_failed"))
            return False
        self.output(renderer.render_macro_step("auto-worktree", "worktree-diff"))
        if not self._handle_worktree_diff():
            self.output(renderer.render_macro_stop("auto-worktree", "worktree_diff_failed"))
            return False
        self.output(renderer.render_macro_step("auto-worktree", "review-worktree"))
        if not self._handle_review_worktree():
            self.output(renderer.render_macro_stop("auto-worktree", "review_worktree_blocked"))
            return False
        self.output(renderer.render_macro_done("auto-worktree"))
        return True

    def _handle_context(self) -> None:
        contract = self._build_contract_for_current_state(require_discovery=False)[0]
        if contract is None:
            contract = self._empty_contract()
        self.output(
            renderer.render_context_summary(
                contract=contract,
                context_files=self._active_context_files(require_discovery=False),
                latest_result=self.latest_result,
                discovery_result=self.discovery_result,
                pending_patch_summary=(
                    self.pending_patch.summary
                    if self.pending_patch is not None
                    else None
                ),
            )
        )

    def _handle_dry_run(self) -> bool:
        contract, error = self._build_contract_for_current_state(
            require_discovery=True,
        )
        if error is not None:
            self.output(renderer.render_error(error))
            return False
        if contract is None:
            contract = self._empty_contract()
        result = self.backend.dry_run(contract)
        self.latest_result = result
        if self._using_discovered_context():
            self.output(renderer.render_discovery_summary(self.discovery_result))
        self.output(renderer.render_dry_run_summary(contract, result))
        return True

    def _handle_ask(self) -> None:
        self._clear_pending_patch()
        self.output("building contract")
        contract, error = self._build_contract_for_current_state(
            require_discovery=True,
        )
        if error is not None:
            self.output(renderer.render_error(error))
            return
        if contract is None:
            contract = self._empty_contract()
        if contract.task is None:
            self.output(renderer.render_error("missing_task"))
            return
        if not contract.context_segments:
            self.output(renderer.render_error("no_context_loaded"))
            return
        self.output("routing context")
        routed = self.backend.dry_run(contract)
        if not routed.contract.audit.get("selected_segment_ids"):
            self.latest_result = ask_error_result(routed, "no_selected_context")
            self.output(renderer.render_ask_result(self.latest_result))
            return
        self.output("calling provider")
        result = self.backend.run(contract)
        self.latest_result = result
        if result.answer:
            self.output("answer received")
        self.output(renderer.render_ask_result(result))

    def _handle_patch(self) -> bool:
        self.output("building contract")
        contract, error = self._build_contract_for_current_state(
            require_discovery=True,
        )
        if error is not None:
            self.output(renderer.render_error(error))
            return False
        if contract is None:
            contract = self._empty_contract()
        if contract.task is None:
            self.output(renderer.render_error("missing_task"))
            return False
        if not contract.context_segments:
            self.output(renderer.render_error("no_context_loaded"))
            return False
        self.output("routing context")
        routed = self.backend.dry_run(contract)
        if not routed.contract.audit.get("selected_segment_ids"):
            self.latest_result = patch_error_result(routed, "no_selected_context")
            self._clear_pending_patch()
            self.output(renderer.render_patch_result(self.latest_result))
            return False
        self.output("calling provider")
        result = self.backend.patch(contract)
        self.latest_result = result
        pending_patch, pending_issue = self._pending_patch_from_result(result)
        self.pending_patch = pending_patch
        self.output(
            renderer.render_patch_result(
                result,
                pending_patch_summary=(
                    pending_patch.summary if pending_patch is not None else None
                ),
                pending_patch_issue=pending_issue,
                pending_patch_preview=(
                    pending_patch.preview if pending_patch is not None else None
                ),
            )
        )
        return pending_patch is not None

    def _handle_apply_patch(self) -> bool:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return False
        if self.pending_patch is None:
            self.output(renderer.render_error("no_pending_patch"))
            return False
        guard_issue = validate_patch_paths(
            self.workspace_root,
            _pending_patch_paths(self.pending_patch.proposal),
        )
        if guard_issue is not None:
            self._clear_pending_patch()
            self.output(
                renderer.render_apply_patch_failure(
                    guard_issue.category or MECHANICAL_GUARD_REJECTED,
                    guard_issue,
                    pending_patch_cleared=True,
                    failure_kind="mechanical_safety_guard",
                )
            )
            return False
        review_payload = self._build_patch_review_payload()
        try:
            review = self.patch_reviewer.review(review_payload)
        except PatchReviewError as exc:
            self.output(
                renderer.render_apply_patch_failure(
                    exc.category,
                    None,
                    pending_patch_cleared=False,
                    failure_kind="router_review_failed",
                    router_reason=exc.reason,
                    router_provider=getattr(self.patch_reviewer, "provider_name", None),
                    router_model=getattr(self.patch_reviewer, "model", None),
                )
            )
            return False
        if review.decision == "KO_BLOCK":
            self.output(
                renderer.render_apply_patch_failure(
                    "router_rejected_patch",
                    None,
                    pending_patch_cleared=False,
                    failure_kind="router_rejected",
                    router_decision=review,
                )
            )
            return False
        if isinstance(self.pending_patch.proposal, ParsedPatch):
            result = apply_patch_to_workspace(self.workspace_root, self.pending_patch.proposal)
        else:
            result = apply_file_replacements(self.workspace_root, self.pending_patch.proposal)
        if result.applied:
            self._clear_pending_patch()
            self.output(renderer.render_apply_patch_success(result, router_decision=review))
            return True
        self.output(
            renderer.render_apply_patch_failure(
                result.issue.category if result.issue else "physical_write_failure",
                result.issue,
                pending_patch_cleared=False,
                failure_kind="physical_write_failure",
                router_decision=review,
            )
        )
        return False

    def _build_contract_for_current_state(
        self,
        *,
        require_discovery: bool,
    ) -> tuple[SFEContract | None, str | None]:
        if self.context_files:
            context_files = self.context_files
        elif not self.task.strip():
            context_files = []
        elif self.discovery_result is None:
            if require_discovery:
                return None, "discovery_not_run"
            context_files = []
        else:
            context_files = list(
                load_discovered_context(
                    workspace_root=self.workspace_root,
                    discovery_result=self.discovery_result,
                )
            )
        return (
            build_contract(
                workspace_root=self.workspace_root,
                task=self.task,
                file_paths=[],
                context_files=context_files,
            ),
            None,
        )

    def _active_context_files(self, *, require_discovery: bool) -> list[ContextLoadResult]:
        if self.context_files:
            return self.context_files
        if self.discovery_result is None:
            return []
        if require_discovery or self.task.strip():
            return list(
                load_discovered_context(
                    workspace_root=self.workspace_root,
                    discovery_result=self.discovery_result,
                )
            )
        return []

    def _using_discovered_context(self) -> bool:
        return not self.context_files and self.discovery_result is not None

    def _pending_patch_from_result(
        self,
        result: BackendResult,
    ) -> tuple[PendingPatchProposal | None, object | None]:
        if self.workspace_root is None or not result.answer:
            return None, result.error_category
        parsed = parse_file_replacement_proposal(result.answer)
        if parsed.proposal is not None and parsed.summary is not None:
            preview = generate_replacement_diff_preview(
                self.workspace_root,
                parsed.proposal,
            )
            proposal = FileReplacementProposal(parsed.proposal.edits, preview or None)
            summary = summarize_file_replacements(proposal)
            parse_status = "structured_replacements"
        else:
            diff_parsed = parse_unified_diff(result.answer)
            if diff_parsed.patch is None or diff_parsed.summary is None:
                if result.answer.lstrip().startswith("diff --git "):
                    return None, diff_parsed.issue or parsed.issue
                return None, parsed.issue
            validation = validate_patch_targets(self.workspace_root, diff_parsed.patch)
            if not validation.ok:
                return None, validation.issue
            proposal = diff_parsed.patch
            preview = result.answer
            summary = validation.summary or diff_parsed.summary
            parse_status = "unified_diff"
        selected_ids = list(result.contract.audit.get("selected_segment_ids") or [])
        selected_refs = tuple(
            segment.source_ref
            for segment in result.contract.context_segments
            if segment.id in selected_ids
        )
        return (
            PendingPatchProposal(
                text=result.answer,
                proposal=proposal,
                preview=preview,
                source="patch",
                created_from_task_hash=self._task_hash(),
                selected_source_refs=selected_refs,
                provider_name=(
                    str(result.summary.get("executor_provider"))
                    if result.summary.get("executor_provider") is not None
                    else None
                ),
                summary=summary,
                parse_status=parse_status,
            ),
            None,
        )

    def _build_patch_review_payload(self) -> dict[str, object]:
        current_files: list[dict[str, object]] = []
        proposed_files: list[dict[str, object]] = []
        summary = self.pending_patch.summary
        if self.workspace_root is not None:
            root = self.workspace_root.resolve()
            for proposed in _pending_patch_proposed_files(
                self.pending_patch.proposal,
                root,
            ):
                source_ref = proposed["path"]
                path = root / str(source_ref)
                proposed_files.append(proposed)
                try:
                    raw = path.read_bytes()
                except OSError:
                    current_files.append(
                        {
                            "path": source_ref,
                            "available": False,
                            "reason": "read_error",
                        }
                    )
                    continue
                current_files.append(
                    {
                        "path": source_ref,
                        "available": True,
                        "content": raw.decode("utf-8", errors="replace"),
                    }
                )
        allowed_paths = sorted(
            set(self.pending_patch.selected_source_refs if self.pending_patch else ())
            | {
                result.source_ref
                for result in self._active_context_files(require_discovery=False)
                if result.loaded and result.source_ref is not None
            }
            | {
                candidate.source_ref
                for candidate in (
                    self.discovery_result.candidates
                    if self.discovery_result is not None
                    else ()
                )
            }
        )
        return {
            "original_user_task": self.task,
            "proposal_format": "file_replacements",
            "review_guidance": {
                "full_file_replacements_are_expected": True,
                "full_file_replacement_is_transport_format_only": True,
                "do_not_reject_solely_because_full_file_replacement": True,
                "judge_effective_delta_between_current_and_proposed_content": True,
                "effective_diff_is_computed_by_sfe_from_current_and_proposed_content": True,
                "reject_unrelated_or_surprising_effective_diff_changes": True,
                "ok_apply_when_effective_delta_is_small_task_aligned_and_preserves_unrelated_content": True,
                "ko_block_when_delta_is_unrelated_dangerous_missing_required_changes_or_preview_mismatch": True,
            },
            "diff_preview": self.pending_patch.preview if self.pending_patch else "",
            "patch_summary": {
                "paths": list(summary.paths),
                "file_count": summary.file_count,
                "hunk_count": summary.hunk_count,
                "lines_added": summary.lines_added,
                "lines_removed": summary.lines_removed,
                "modified_paths": list(summary.modified_paths),
                "created_paths": list(summary.created_paths),
                "refused_paths": list(summary.refused_paths),
                "refused_reasons": list(summary.refused_reasons),
            },
            "selected_context_metadata": {
                "selected_source_refs": list(
                    self.pending_patch.selected_source_refs if self.pending_patch else ()
                ),
                "provider_name": self.pending_patch.provider_name if self.pending_patch else None,
                "created_from_task_hash": (
                    self.pending_patch.created_from_task_hash if self.pending_patch else None
                ),
            },
            "discovery_metadata": self._patch_review_discovery_metadata(),
            "current_files": current_files,
            "proposed_full_replacements": proposed_files,
            "allowed_workspace_relative_paths": allowed_paths,
            "inferred_task_constraints": self._infer_task_constraints(),
        }

    def _patch_review_discovery_metadata(self) -> dict[str, object]:
        if self.discovery_result is None:
            return {"discovery_ran": False}
        return {
            "discovery_ran": True,
            "candidate_count": self.discovery_result.candidate_count,
            "loaded_candidate_count": self.discovery_result.loaded_candidate_count,
            "candidate_source_refs": [
                candidate.source_ref for candidate in self.discovery_result.candidates
            ],
        }

    def _infer_task_constraints(self) -> dict[str, object]:
        normalized = self.task.lower()
        existing_only = (
            "existing files only" in normalized
            or "existing source files only" in normalized
            or "modify existing files only" in normalized
            or "modify the existing source files only" in normalized
        )
        return {"existing_files_only": existing_only}

    def _clear_pending_patch(self) -> None:
        self.pending_patch = None

    def _task_hash(self) -> str:
        return hashlib.sha256(self.task.encode("utf-8")).hexdigest()[:16]

    def _active_path_for_session(self, session: WorkspaceSession) -> Path:
        try:
            relative_source = session.source_path.relative_to(session.source_git_root)
        except ValueError:
            relative_source = Path()
        return (session.worktree_path / relative_source).resolve()

    def _empty_contract(self) -> SFEContract:
        return build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=[],
        )


def _pending_patch_paths(proposal: FileReplacementProposal | ParsedPatch) -> tuple[str, ...]:
    if isinstance(proposal, ParsedPatch):
        return tuple(file_patch.new_path for file_patch in proposal.files)
    return proposal.paths


def _pending_patch_proposed_files(
    proposal: FileReplacementProposal | ParsedPatch,
    root: Path,
) -> list[dict[str, object]]:
    if not isinstance(proposal, ParsedPatch):
        return [
            {
                "path": edit.path,
                "action": edit.action,
                "content": edit.content,
            }
            for edit in proposal.edits
        ]
    proposed: list[dict[str, object]] = []
    for file_patch in proposal.files:
        source_ref = file_patch.new_path
        current_text = ""
        if file_patch.operation != "create":
            try:
                current_text = (root / source_ref).read_bytes().decode(
                    "utf-8",
                    errors="replace",
                )
            except OSError:
                current_text = ""
        proposed_text = preview_file_patch_text(current_text, file_patch)
        if isinstance(proposed_text, PatchIssue):
            proposed_text = current_text
        proposed.append(
            {
                "path": source_ref,
                "action": "create_file" if file_patch.operation == "create" else "patch_file",
                "content": proposed_text,
            }
        )
    return proposed


def main() -> int:
    load_repo_env()
    app = SfeTuiApp()
    return app.run()
