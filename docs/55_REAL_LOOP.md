# Real Loop

Real Loop is the bounded verifier-driven retry path for completed `/run`
`workspace_write` attempts. It runs after the first write attempt has completed
and only applies to the shared runtime path used by the TUI and MCP server.

## What It Does

1. SFE runs the requested `workspace_write` task.
2. A verifier inspects the run result and a bounded snapshot of the active
   workspace.
3. The verifier returns a structured verdict: `pass`, `needs_retry`, `blocked`,
   or `abort`. The parser also accepts `completed` as a `pass` alias.
4. When the verdict is `needs_retry`, the verifier must provide a targeted
   correction task. SFE routes that correction task and only retries if it still
   routes to `workspace_write`.
5. The retry uses the same workspace session and is counted against the total
   attempt limit.

The retry instruction is expected to target only the missing or failed
requirements. It is not a repeat of the original user request.

## Bounded Stops

Real Loop stops instead of looping forever. Current stop behavior includes:

- `verified_pass` when the verifier says the result passes.
- `blocked` when the verifier says retry should not continue.
- `aborted` when retry is not worthwhile, there is no meaningful progress, a
  repeated failure is detected, a retry task duplicates the original or a prior
  retry, the correction task does not route to `workspace_write`, or a retry
  leaves the eligible write path.
- `retry_failed` when a retry attempt itself fails.
- `verifier_failed` when the verifier response cannot be parsed or validated.
- `verifier_unavailable` when Real Loop is forced but no verifier is available.
- `max_iterations` when the configured total attempt limit is reached.

The surfaced `stop_reason` is more specific. Examples covered by tests include
`duplicate_retry_task`, `no_meaningful_progress`,
`no_meaningful_progress_repeated_failure`, `repeated_failure`,
`repeated_failure_category`, `executor_produced_no_relevant_workspace_changes`,
`correction_task_not_workspace_write`, `retry_attempt_failed`, and
`max_total_attempts_reached`.

## Configuration

Real Loop configuration lives in `.env`:

```env
SFE_REAL_LOOP=auto
SFE_REAL_LOOP_MAX_ITERATIONS=3
SFE_REAL_LOOP_ABORT_ON_NO_PROGRESS=true
SFE_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK=true
SFE_REAL_LOOP_VERIFIER_MAX_TOKENS=1600
SFE_REAL_LOOP_DIFF_MAX_CHARS=40000
SFE_REAL_LOOP_FILE_PREVIEW_MAX_CHARS=12000
```

`SFE_REAL_LOOP` supports:

- `auto`: use Real Loop only when a verifier provider is available.
- `true`: force Real Loop for eligible write runs.
- `false`: disable Real Loop.

`SFE_REAL_LOOP_MAX_ITERATIONS` is the total number of write attempts, including
the original attempt. With the default value of `3`, SFE can spend the original
attempt plus at most two retries.

Verifier provider configuration uses the normal provider chain, with an optional
role override:

```env
SFE_PROVIDER_VERIFIER=
SFE_OPENAI_VERIFIER_MODEL=
SFE_ANTHROPIC_VERIFIER_MODEL=
SFE_ALIBABA_VERIFIER_MODEL=
SFE_GOOGLE_VERIFIER_MODEL=
SFE_CODEXCLI_VERIFIER_MODEL=
SFE_OLLAMA_VERIFIER_MODEL=
```

Blank verifier provider configuration falls back to the Router provider, then
the shared provider, then OpenAI. Provider availability still depends on local
keys, URLs, models, and health checks.

## Reports

When Real Loop runs, the normal TUI result includes the Real Loop status,
verifier verdict, retry-worthiness, stop reason, and a short reason when
available. `/run-report` includes more diagnostic detail, such as attempt count,
progress since the previous iteration, detected issues, retry task, verifier
provider, verifier model, and per-iteration summary fields.

MCP run serialization exposes the same Real Loop summary fields in structured
form.

## Limits

Real Loop is a bounded recovery mechanism, not an autonomous correctness
guarantee. The verifier is model-backed, provider quality can vary, and SFE
still expects a developer to review the final diff.
