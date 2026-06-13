# Workspace Write Multi-Pass

`workspace_write` multi-pass is the SFE run mode used for large file-generation
or scaffold tasks that are too large or fragile for one provider response.

It is part of the same core runtime used by the TUI `/run` command and the MCP
`sfe_run` tool. Small `workspace_write` tasks still use the normal single-pass
workspace-write flow.

## Why It Exists

Large monolithic file-generation responses are brittle:

- providers can stay silent while preparing many files;
- long silent patch generation can hit `provider_idle_timeout`;
- one malformed transport response can lose the whole scaffold attempt;
- one response with many files is harder to validate and diagnose.

Multi-pass reduces that risk by asking the Router to split the work into
bounded batches, then validating and promoting each batch independently.

## How It Works

The core flow is:

1. SFE routes the task to `workspace_write`.
2. SFE discovers context as usual.
3. The Router produces and validates a strict JSON multi-pass plan.
4. The plan contains batches with explicit `allowed_files` guidance.
5. For each validated batch, text-returning API Executors return full-file
   `SFE_FILE` blocks; strict Git diffs remain accepted as a compatibility path.
6. SFE reports patches that touch files outside that batch's `allowed_files` as
   warnings, as long as all paths remain inside the workspace and avoid blocked
   internal directories.
7. SFE writes the transported files into the controlled worktree.
8. SFE applies and promotes the batch.
9. SFE refreshes lightweight workspace state so later batches can see files
   created or modified by earlier batches.
10. MCP and TUI reports expose one consolidated run result.

The JSON plan is not repaired by another LLM. The executor response is not
repaired by another LLM; text-returning API providers such as OpenAI,
Anthropic, Google, Alibaba, Lemonade, Ollama, and similar endpoints must return
deterministic `SFE_FILE` blocks or a valid strict Git diff.

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

Multi-pass `workspace_write` follows the same reliability rule as single-pass
`workspace_write`: SFE writes deterministic text transports into the isolated
worktree, captures the actual filesystem changes, and then verifies that every
created, modified, or deleted path is inside the selected destination directory.
It no longer uses hunk/preimage validation, patch repair, or LLM-reviewed
full-file replacement fallback as a blocking promotion gate. This is a
deliberate reliability tradeoff: fewer false failures, with the safety boundary
enforced at filesystem scope.

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

Multi-pass also remains bounded by provider quality: the Router planner must
produce valid strict JSON, and text-returning Executors must return `SFE_FILE`
blocks or a valid strict Git diff for each batch. Filesystem-capable local or
CLI executors are a separate path when they actually write files inside the
controlled worktree.
