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
    INVALID_PATCH_PROPOSAL,
    PATCH_PREIMAGE_MISMATCH,
    ParsedPatch,
    PatchSummary,
    apply_patch_to_workspace,
    parse_unified_diff,
    validate_patch_targets,
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
from . import renderer


OutputFunc = Callable[[str], None]


@dataclass(frozen=True)
class PendingPatchProposal:
    text: str
    parsed_patch: ParsedPatch
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
    ) -> None:
        self.input_provider = input_provider or TerminalInput()
        self.output = output
        self.cwd = (cwd or Path.cwd()).resolve()
        self.backend = backend or backend_by_name("direct")
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
            )
        )

    def _handle_apply_patch(self) -> None:
        if self.workspace_root is None:
            self.output(renderer.render_error("workspace_not_selected"))
            return
        if self.pending_patch is None:
            self.output(renderer.render_error("no_pending_patch"))
            return
        parsed = parse_unified_diff(self.pending_patch.text)
        if parsed.patch is None:
            self._clear_pending_patch()
            self.output(
                renderer.render_apply_patch_failure(
                    INVALID_PATCH_PROPOSAL,
                    parsed.issue,
                    pending_patch_cleared=True,
                )
            )
            return
        validation = validate_patch_targets(self.workspace_root, parsed.patch)
        if not validation.ok:
            self._clear_pending_patch()
            self.output(
                renderer.render_apply_patch_failure(
                    validation.issue.category if validation.issue else "unsafe_patch",
                    validation.issue,
                    pending_patch_cleared=True,
                )
            )
            return
        result = apply_patch_to_workspace(self.workspace_root, parsed.patch)
        if result.applied:
            self._clear_pending_patch()
            self.output(renderer.render_apply_patch_success(result))
            return
        if result.issue is not None and result.issue.category == PATCH_PREIMAGE_MISMATCH:
            self.output(renderer.render_apply_patch_failure(
                result.issue.category,
                result.issue,
                pending_patch_cleared=False,
            ))
            return
        self._clear_pending_patch()
        self.output(
            renderer.render_apply_patch_failure(
                result.issue.category if result.issue else "unsafe_patch",
                result.issue,
                pending_patch_cleared=True,
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
        parsed = parse_unified_diff(result.answer)
        if parsed.patch is None:
            return None, parsed.issue
        validation = validate_patch_targets(self.workspace_root, parsed.patch)
        if not validation.ok or validation.summary is None:
            return None, validation.issue
        selected_ids = list(result.contract.audit.get("selected_segment_ids") or [])
        selected_refs = tuple(
            segment.source_ref
            for segment in result.contract.context_segments
            if segment.id in selected_ids
        )
        return (
            PendingPatchProposal(
                text=result.answer,
                parsed_patch=parsed.patch,
                source="patch",
                created_from_task_hash=self._task_hash(),
                selected_source_refs=selected_refs,
                provider_name=(
                    str(result.summary.get("executor_provider"))
                    if result.summary.get("executor_provider") is not None
                    else None
                ),
                summary=validation.summary,
            ),
            None,
        )

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
    app = SfeTuiApp()
    return app.run()
