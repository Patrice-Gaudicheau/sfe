# Workspace Write Multi-Pass

`workspace_write` multi-pass is the SFE run mode used for large file-generation
or scaffold tasks that are too fragile for one large provider patch.

It is part of the same core runtime used by the TUI `/run` command and the MCP
`sfe_run` tool. Small `workspace_write` tasks still use the normal single-pass
patch flow.

## Why It Exists

Large monolithic patches are brittle:

- providers can stay silent while preparing a very large diff;
- long silent patch generation can hit `provider_idle_timeout`;
- one malformed diff can lose the whole scaffold attempt;
- a single patch with many files is harder to validate and diagnose.

Multi-pass reduces that risk by asking the Router to split the work into
bounded batches, then validating and promoting each batch independently.

## How It Works

The core flow is:

1. SFE routes the task to `workspace_write`.
2. SFE discovers context as usual.
3. The Router produces and validates a strict JSON multi-pass plan.
4. The plan contains batches with explicit `allowed_files`.
5. For each validated batch, the Executor produces one strict git diff.
6. SFE rejects patches that touch files outside that batch's `allowed_files`.
7. SFE parses and validates the patch using the normal strict patch machinery.
8. SFE applies and promotes the batch.
9. SFE refreshes lightweight workspace state so later batches can see files
   created or modified by earlier batches.
10. MCP and TUI reports expose one consolidated run result.

The JSON plan is not repaired by another LLM. Patch parsing remains strict; the
multi-pass path does not relax `parse_unified_diff`.

## Configuration

```env
SFE_WORKSPACE_WRITE_MULTIPASS=auto
SFE_MULTIPASS_MAX_PASSES=auto
SFE_MULTIPASS_MAX_FILES_PER_PASS=10
```

`SFE_WORKSPACE_WRITE_MULTIPASS` accepts:

- `auto`: use a cautious heuristic for large project/scaffold requests.
- `true`: force multi-pass, useful for validation and heavy scaffolds.
- `false`: keep normal single-pass behavior.

`SFE_MULTIPASS_MAX_PASSES` accepts `auto` or a positive integer. The default is
`auto`, which lets the Router choose the pass count during multi-pass planning.
Use a numeric value such as `5`, `10`, or `15` to enforce a maximum.

`SFE_MULTIPASS_MAX_FILES_PER_PASS` limits each batch's `allowed_files`. The
default is `10`.

`SFE_FULL_FILE_REPLACEMENT_REVIEW` controls the optional LLM-reviewed full-file
replacement fallback after `hunk_preimage_mismatch`:

- `false`: never use the reviewer fallback.
- `auto`: use it only when deterministic invariants pass.
- `true`: currently equivalent to `auto`.

The reviewer receives the task, target path, pass details, current file content,
proposed replacement content, and related selected paths. It returns strict JSON
approval metadata only; it must not rewrite or repair patches.

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
- `fallback_diagnostics`: per-pass metadata when the LLM-reviewed full-file
  replacement fallback was used successfully.

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

This was a live provider validation, not only a mocked unit test.

## Current Limits

Automatic resume is not implemented in v1. If a later batch fails after earlier
batches were promoted, SFE reports `safe_resume_possible`, the failed pass id,
and promoted files, but it does not yet resume the run automatically.

Multi-pass also remains bounded by provider quality: the Router planner must
produce valid strict JSON, and the Executor must produce a valid strict patch
for each batch.
