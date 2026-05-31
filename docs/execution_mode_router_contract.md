# Execution Mode Router Contract

This is the current routing contract used by the `/run` pipeline. Historical
router concepts such as task type, role, memory zones, and older
direct/tool-assisted/multi-step execution patterns are preserved in
`docs/history/router/router_contract_legacy.md`, but they are not the current
TUI `/run` execution-mode contract.

## Responsibility

The execution-mode router receives the protected user task and decides how SFE
should resolve it at the top level. It does not execute the task, inspect file
contents, apply patches, call tools, promote worktrees, or run benchmarks.

It returns one of three modes:

- `console_output`: answer in the TUI console; no Git preparation, worktree,
  patch generation, or workspace mutation.
- `workspace_write`: create, modify, or delete workspace files through the
  developer patch/worktree execution mode.
- `external_action`: the task requires action outside the workspace, such as
  sending mail, publishing, opening a PR, or calling external services. This is
  recognized but not implemented in the current `/run` path.

## Required Output

The router must return a single JSON object:

```json
{
  "execution_mode": "console_output|workspace_write|external_action",
  "reason": "short explanation",
  "confidence": 0.0
}
```

`confidence` is optional. If present, it must be a number from `0` to `1`.
`reason` must be non-empty. Extra prose, Markdown, invalid JSON, unsupported
modes, empty reasons, and invalid confidence values are rejected.

## Pipeline Boundary

After mode selection, the `/run` pipeline branches:

- `console_output` prepares an executor prompt and displays the answer.
- `workspace_write` prepares the workspace, discovers context, selects relevant
  context, prepares the executor prompt, runs the patch/worktree flow, validates
  the patch, and promotes only when promotion actually succeeds.
- `external_action` fails closed before workspace work starts.

The TUI renders compact `SFE:` progress lines for these boundaries. Those lines
are observability of the current run, not benchmark results.

## Validation

The implementation lives in `sfe/execution_mode_router.py` and is exercised by
`tests/test_execution_mode_router.py`, `tests/test_sfe_run_pipeline.py`, and
`tests/test_sfe_tui.py`.
