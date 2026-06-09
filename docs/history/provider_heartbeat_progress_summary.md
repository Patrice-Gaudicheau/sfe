# Provider heartbeat/progress summary

This note summarizes the provider waiting model completed through commit
`58e8097`.

## Motivation

SFE previously relied on provider-specific timeout environment variables as the
main waiting contract. That model was too coarse for SFE because provider calls
can be short, long-running, local, remote, streaming, non-streaming, benchmark
driven, or structural. A fixed provider timeout does not describe
whether a call is actually making progress.

## Core model

Provider calls now use core SFE progress supervision through
`sfe/provider_progress.py`.

The core emits structured `ProviderProgressEvent` records and supervises calls
with `ProviderCallSupervisor`. A call remains live when admissible progress is
observed. If no admissible progress arrives within the idle supervision window,
the call fails with a stalled/idle-supervision error.

The event model distinguishes:

- Real provider progress: a signal that came from the provider side, such as
  response headers, streaming chunks, SSE lines, or CodexCLI JSONL stdout.
- Streaming chunks and SSE events: treated as real provider progress only where
  they are actually forwarded or read from the provider stream.
- Internal wait events: local SFE supervision events emitted while waiting on an
  opaque blocking call. They are never marked as real provider signals and do
  not reset idle supervision.
- Idle supervision: a core liveness rule based on the absence of admissible
  progress, not a task-duration timeout.
- Low-level transport safeguards: retained as secondary protection for network
  or process boundaries. They are not the primary provider liveness contract.

The first implementation does not add a full cancellation API. Some blocking
worker paths can still rely on transport safeguards to unwind after idle
supervision reports a stalled call.

## Provider notes

OpenAI, Anthropic, Alibaba/Qwen, Lemonade, and CodexCLI provider paths emit core
progress events. Retry/backoff points emit progress metadata without pretending
to be provider heartbeats.

CodexCLI was changed from a fully buffered `subprocess.run()` path to
incremental process supervision. A follow-up fix ensures stdout and stderr
reader threads start before stdin is written. If CodexCLI exits early and closes
stdin, stderr is still drained, the process return code is still handled, and a
clean provider failure is surfaced instead of a raw `BrokenPipeError`.

## Configuration cleanup

The obsolete provider timeout environment variables were removed from public
configuration, examples, docs, tests, and runtime fallbacks:

- `SFE_OPENAI_API_TIMEOUT`
- `SFE_ANTHROPIC_API_TIMEOUT`
- `SFE_LEMONADE_TIMEOUT_SECONDS`
- `SFE_CODEXCLI_TIMEOUT`

Benchmark pacing, provider rate-limit controls, retry/backoff controls, idle
supervision configuration, and internal transport safeguards remain preserved.

## Validation

The final merge validation after timeout cleanup passed on `main`:

- Focused provider/TUI/router/env tests: `468 passed`
- Full test suite: `1252 passed`
- `python -m py_compile` on modified Python files: passed
- `git diff --check`: passed

This is an architectural improvement to SFE provider supervision. It is not a
complete production cancellation framework, and future work should define an
explicit cancellation API if SFE needs to actively stop in-flight provider work.
