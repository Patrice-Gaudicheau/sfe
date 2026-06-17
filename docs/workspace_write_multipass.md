# Workspace Write Multi-Pass

`workspace_write` multi-pass is the SFE run mode used for large file-generation
or scaffold tasks that are too large or fragile for one workspace-writer pass.

It is part of the same core runtime used by the TUI `/run` command and the MCP
`sfe_run` tool. Small `workspace_write` tasks still use the normal single-pass
workspace-write flow.

## Why It Exists

Large monolithic workspace-write attempts are brittle:

- providers or local executors can stay silent while preparing many files;
- long silent execution can hit configured idle or process timeouts;
- one malformed text transport can lose the whole scaffold attempt when the
  legacy text executor is explicitly selected;
- one pass with many files is harder to validate and diagnose.

Multi-pass reduces that risk by asking the Router to split the work into
bounded batches, then validating and promoting each batch independently.

Multi-pass is not Real Loop. Multi-pass divides one `workspace_write` attempt
into planned batches. Real Loop verifies the final state after a completed
attempt and may launch a new targeted correction attempt when its
verifier/governor says the retry is worthwhile.

## How It Works

The core flow is:

1. SFE routes the task to `workspace_write`.
2. SFE discovers context as usual.
3. The Router produces and validates a strict JSON multi-pass plan.
4. The plan contains batches with explicit `allowed_files` guidance.
5. For each validated batch, SFE invokes the configured workspace writer inside
   the controlled worktree. The default writer is Aider.
6. SFE captures actual filesystem changes from the worktree as the source of
   truth.
7. SFE reports changes outside that batch's `allowed_files` as warnings, as long
   as all paths remain inside the workspace and avoid blocked internal
   directories.
8. SFE validates and promotes the accepted batch file state.
9. SFE refreshes lightweight workspace state so later batches can see files
   created or modified by earlier batches.
10. MCP and TUI reports expose one consolidated run result.

The JSON plan is not repaired by another LLM. In the default Aider-backed path,
SFE relies on generated disk state rather than treating provider text as the
file transport. When `SFE_WORKSPACE_WRITE_EXECUTOR=text` is explicitly selected
for legacy/debug rollback, text-returning API providers must return
deterministic `SFE_FILE` blocks or a valid strict Git diff; that text response is
not repaired by another LLM.

## Configuration

```env
SFE_WORKSPACE_WRITE_MULTIPASS=auto
SFE_MULTIPASS_MAX_PASSES=auto
SFE_MULTIPASS_MAX_FILES_PER_PASS=10
```

`SFE_WORKSPACE_WRITE_MULTIPASS` accepts:

- `auto`: use a cautious heuristic for large project/scaffold requests or
  tasks that list many explicit target files.
- `true`: force multi-pass, useful for validation and heavy scaffolds.
- `false`: keep normal single-pass behavior.

`SFE_MULTIPASS_MAX_PASSES` accepts `auto` or a positive integer. The default is
`auto`, which lets the Router choose the pass count during multi-pass planning.
Use a numeric value such as `5`, `10`, or `15` to enforce a maximum.

`SFE_MULTIPASS_MAX_FILES_PER_PASS` limits each batch's `allowed_files`. The
default is `10`.

Multi-pass `workspace_write` follows the same reliability rule as single-pass
`workspace_write`: SFE runs the configured workspace writer in the isolated
worktree, captures the actual filesystem changes, and then verifies that every
created, modified, or deleted path is inside the selected destination directory.
In legacy text mode, SFE first writes deterministic text transports into the
worktree. The current workspace-write path no longer uses hunk/preimage
validation, patch repair, or LLM-reviewed full-file replacement fallback as a
blocking promotion gate. This is a deliberate reliability tradeoff: fewer false
failures, with the safety boundary enforced at filesystem scope.

Aider command splitting is separate from SFE multi-pass. When the Aider
filesystem executor receives a large editable file list, it may invoke Aider in
smaller command chunks inside one SFE pass. Run reports expose this as
filesystem/Aider command metadata, while `multi-pass` refers only to the
Router-planned SFE batch workflow.

`SFE_MULTIPASS_PLANNER_MODEL` is deprecated and ignored. Existing `.env` files
containing it still load, but the value no longer influences planning. Configure
multi-pass planning quality through the Router provider and model settings,
such as `SFE_PROVIDER_ROUTER`, `SFE_OPENAI_ROUTER_MODEL`,
`SFE_CODEXCLI_ROUTER_MODEL`, or another supported Router model variable.

## Report Fields

`sfe_run_report` and TUI `/run-report` expose the multi-pass state:

- `multi_pass`: whether the run used multi-pass.
- `multi_pass_status`: completed or failed.
- `passes_total`: number of planned passes.
- `passes_completed`: number of successfully promoted passes.
- `failed_pass_id`: failed batch id, if any.
- `failed_pass_issue`: structured issue for the failed batch.
- `safe_resume_possible`: whether partial promotion makes manual continuation
  plausible.
- `promoted_files_by_pass`: files promoted by each batch.
- `all_promoted_files`: consolidated promoted file list.
- `fallback_diagnostics`: retained as a report field for compatibility; current
  workspace-write runs do not use patch fallback repair.

Provider timeout diagnostics are also attached per pass when a timeout happens
during batch generation.

## Live Validation

The mode was validated through Antigravity / SFE MCP on a Symfony-style
`AI Signal Blog` scaffold:

- execution mode: `workspace_write`
- multi-pass: enabled
- result: completed
- passes: 8
- promoted application files: 31
- no `vendor/` directory generated

`allowed_files` is intentionally not the main safety boundary. It keeps planning
and reporting understandable, but the hard write boundary is the declared
workspace/worktree plus blocked internal directories such as `.git` and
`.sfe-worktrees`.

This was a live provider validation, not only a mocked unit test.

## Current Limits

Automatic resume is not implemented in v1. If a later batch fails after earlier
batches were promoted, SFE reports `safe_resume_possible`, the failed pass id,
and promoted files, but it does not yet resume the run automatically.

Multi-pass also remains bounded by provider and executor quality: the Router
planner must produce valid strict JSON, and the configured workspace writer must
produce useful in-worktree changes for each batch. When the legacy text executor
is explicitly selected, text-returning Executors must return `SFE_FILE` blocks
or a valid strict Git diff for each batch.
