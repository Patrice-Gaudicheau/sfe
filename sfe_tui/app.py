"""Blocking application loop for the first-party SFE-aware TUI."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Callable

from .backends import (
    BackendAdapter,
    BackendResult,
    ask_error_result,
    backend_by_name,
    patch_error_result,
)
from .contracts import (
    ContextLoadResult,
    build_contract,
    load_context_file,
    resolve_workspace,
)
from .input import TerminalInput
from . import renderer


OutputFunc = Callable[[str], None]


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
        self.task = ""
        self.latest_result: BackendResult | None = None

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
        if name == "/pwd":
            if self.workspace_root is None:
                self.output("Workspace: not selected")
            else:
                self.output(
                    renderer.render_workspace_selected(self.workspace_root, self.cwd)
                )
            return False
        if name == "/status":
            self.output(
                renderer.render_status(
                    workspace_selected=self.workspace_root is not None,
                    loaded_context_files=sum(
                        1 for result in self.context_files if result.loaded
                    ),
                    skipped_context_files=sum(
                        1 for result in self.context_files if not result.loaded
                    ),
                    task_present=bool(self.task.strip()),
                    backend_name=self.backend.name,
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
            self.task = rest.strip()
            self.latest_result = None
            self.output(renderer.render_task_set())
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
        self.output(renderer.render_file_selection(self.context_files))

    def _handle_reset(self) -> None:
        self.context_files = []
        self.task = ""
        self.latest_result = None
        self.output(renderer.render_reset())

    def _handle_context(self) -> None:
        contract = build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=self.context_files,
        )
        self.output(
            renderer.render_context_summary(
                contract=contract,
                context_files=self.context_files,
                latest_result=self.latest_result,
            )
        )

    def _handle_dry_run(self) -> None:
        contract = build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=self.context_files,
        )
        result = self.backend.dry_run(contract)
        self.latest_result = result
        self.output(renderer.render_dry_run_summary(contract, result))

    def _handle_ask(self) -> None:
        self.output("building contract")
        contract = build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=self.context_files,
        )
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
        contract = build_contract(
            workspace_root=self.workspace_root,
            task=self.task,
            file_paths=[],
            context_files=self.context_files,
        )
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
            self.output(renderer.render_patch_result(self.latest_result))
            return
        self.output("calling provider")
        result = self.backend.patch(contract)
        self.latest_result = result
        self.output(renderer.render_patch_result(result))


def main() -> int:
    app = SfeTuiApp()
    return app.run()
