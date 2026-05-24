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
    PatchSummary,
    validate_patch_paths,
)
from sfe.env import load_repo_env

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
    proposal: FileReplacementProposal
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
    ) -> None:
        self.input_provider = input_provider or TerminalInput()
        self.output = output
        self.cwd = (cwd or Path.cwd()).resolve()
        self.backend = backend or backend_by_name("direct")
        self.patch_reviewer = patch_reviewer or create_tui_patch_reviewer()
        self.workspace_root: Path | None = None
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

    def _handle_discover(self) -> None:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return
        if not self.task.strip():
            self.output(renderer.render_error("missing_task"))
            return
        self.discovery_result = discover_workspace_context(
            workspace_root=self.workspace_root,
            task=self.task,
        )
        self.latest_result = None
        self._clear_pending_patch()
        self.output(renderer.render_discovery_summary(self.discovery_result))

    def _handle_reset(self) -> None:
        self.context_files = []
        self.discovery_result = None
        self.task = ""
        self.latest_result = None
        self._clear_pending_patch()
        self.output(renderer.render_reset())

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

    def _handle_dry_run(self) -> None:
        contract, error = self._build_contract_for_current_state(
            require_discovery=True,
        )
        if error is not None:
            self.output(renderer.render_error(error))
            return
        if contract is None:
            contract = self._empty_contract()
        result = self.backend.dry_run(contract)
        self.latest_result = result
        if self._using_discovered_context():
            self.output(renderer.render_discovery_summary(self.discovery_result))
        self.output(renderer.render_dry_run_summary(contract, result))

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

    def _handle_patch(self) -> None:
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
            self.latest_result = patch_error_result(routed, "no_selected_context")
            self._clear_pending_patch()
            self.output(renderer.render_patch_result(self.latest_result))
            return
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

    def _handle_apply_patch(self) -> None:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return
        if self.pending_patch is None:
            self.output(renderer.render_error("no_pending_patch"))
            return
        guard_issue = validate_patch_paths(
            self.workspace_root,
            self.pending_patch.proposal.paths,
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
            return
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
            return
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
            return
        result = apply_file_replacements(self.workspace_root, self.pending_patch.proposal)
        if result.applied:
            self._clear_pending_patch()
            self.output(renderer.render_apply_patch_success(result, router_decision=review))
            return
        self.output(
            renderer.render_apply_patch_failure(
                result.issue.category if result.issue else "physical_write_failure",
                result.issue,
                pending_patch_cleared=False,
                failure_kind="physical_write_failure",
                router_decision=review,
            )
        )

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
        if parsed.proposal is None or parsed.summary is None:
            return None, parsed.issue
        preview = parsed.proposal.diff_preview or generate_replacement_diff_preview(
            self.workspace_root,
            parsed.proposal,
        )
        proposal = (
            parsed.proposal
            if parsed.proposal.diff_preview
            else FileReplacementProposal(parsed.proposal.edits, preview or None)
        )
        summary = summarize_file_replacements(proposal)
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
                parse_status="structured_replacements",
            ),
            None,
        )

    def _build_patch_review_payload(self) -> dict[str, object]:
        current_files: list[dict[str, object]] = []
        proposed_files: list[dict[str, object]] = []
        summary = self.pending_patch.summary
        if self.workspace_root is not None:
            root = self.workspace_root.resolve()
            for edit in self.pending_patch.proposal.edits:
                source_ref = edit.path
                path = root / source_ref
                proposed_files.append(
                    {
                        "path": source_ref,
                        "action": edit.action,
                        "content": edit.content,
                    }
                )
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
                "use_diff_preview_to_understand_intended_minimal_delta": True,
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

    def _empty_contract(self) -> SFEContract:
        return build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=[],
        )


def main() -> int:
    load_repo_env()
    app = SfeTuiApp()
    return app.run()
