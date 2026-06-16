# Real Loop

Real Loop is the bounded verification-and-correction layer for supported local
SFE `/run` `workspace_write` workflows.

It is intentionally LLM-verifier based. Many SFE tasks are qualitative,
architectural, editorial, or implementation-oriented, so the MVP does not claim
fully deterministic correctness. The goal is structured, bounded, observable,
and auditable verifier judgment.

## Behavior

For an eligible completed `workspace_write` attempt, SFE asks a verifier and
loop governor model to compare the final workspace state with the original user
task. The verifier returns strict JSON with:

- `verdict`: `pass`, `needs_retry`, `blocked`, or `abort`.
- `retry_worthwhile`: whether spending another bounded attempt is useful.
- `progress_since_previous_iteration`: `none`, `minor`, `meaningful`, or
  `unknown`.
- `detected_issues`, `correction_objective`, and `executor_retry_task` when a
  retry is useful.
- `stop_reason` when the loop should stop.

`needs_retry` is not a request to run the original task again. The verifier must
produce a targeted `executor_retry_task` that preserves the original intent,
focuses only on failed or missing requirements, and avoids expanding scope.

## Stop Conditions

Real Loop stops on verified pass, blocked requirements, abort, max attempts, no
meaningful progress, repeated failure category, duplicate retry task, no
relevant workspace changes, or a correction task that would route away from
`workspace_write`.

`abort` means the task is still incomplete, but further retries are not expected
to improve the result. Reports must not present aborted runs as successful.
For executor/no-progress aborts, reports show:
`Loop Stopped: Executor failed. Try a stronger model for Executor (SFE_PROVIDER_EXECUTOR in the file .env)`.

## Configuration

```env
SFE_REAL_LOOP=auto
SFE_REAL_LOOP_MAX_ITERATIONS=3
SFE_REAL_LOOP_ABORT_ON_NO_PROGRESS=true
SFE_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK=true
SFE_REAL_LOOP_VERIFIER_MAX_TOKENS=1600
SFE_REAL_LOOP_DIFF_MAX_CHARS=40000
SFE_REAL_LOOP_FILE_PREVIEW_MAX_CHARS=12000
SFE_PROVIDER_VERIFIER=
```

`auto` enables Real Loop only when a verifier provider is available. `true`
requires Real Loop for eligible workspace-write runs. `false` disables it.
`SFE_REAL_LOOP_MAX_ITERATIONS` is the total number of `workspace_write`
attempts, including the original task attempt. The default `3` allows the
original attempt plus up to two targeted correction attempts when the governor
reports meaningful progress and worthwhile retry guidance.

The verifier provider resolves from `SFE_PROVIDER_VERIFIER`, then
`SFE_PROVIDER_ROUTER`, then `SFE_PROVIDER`, then `openai`.

## Relationship To Multi-Pass

Multi-pass splits one large workspace-write attempt into bounded batches. Real
Loop verifies the final state after a completed attempt and may launch a new
targeted correction attempt. They are separate layers.
