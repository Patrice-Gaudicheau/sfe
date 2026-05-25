# SFE TUI DirectBackend Strategy

This note records the current first-party interface direction for SFE.

## Decision

The SFE-aware TUI is the canonical user-facing path for new SFE workflow
development. The DirectBackend is the default and only exposed backend for the
TUI for now.

The existing SFE Proxy and CodexCLI path are standby compatibility and
stress-test infrastructure. They should stay safe, observable, and
fallback-oriented, but they are no longer the primary interface being optimized
for SFE-aware context routing.

## Rationale

CodexCLI-compatible traffic is useful for exercising the proxy, but realistic
CodexCLI requests can pack large context into protected developer-role payloads.
The project should not keep reverse-engineering those payloads as the canonical
SFE interface.

The first-party TUI can expose the SFE contract directly:

- protected instructions stay protected,
- the user task stays protected,
- context segments are explicit,
- reducibility is explicit,
- routing diagnostics are produced from safe counts and opaque ids.

Keeping DirectBackend as the only exposed TUI backend reduces maintenance
burden, avoids two competing execution structures, and gives users a simpler
surface: launch the TUI, choose a workspace, select context, enter a task, and
run the SFE flow.

## Current Backend Policy

- DirectBackend is canonical for TUI v0/v1.
- ProxyBackend may remain as an internal experimental stub.
- The TUI should not expose backend switching yet.
- No `/backend` command is planned until a concrete need is proven.
- The local lexical preview is not an LLM router result and must be labeled as
  a provider-free local preview.

## Router Before Executor

Router integration comes before executor integration because SFE's core value
is explicit context routing and reduction. The TUI should first prove that it
can pass explicit reducible `context_segments` through a safe routing boundary,
record selected opaque segment ids, and report token estimates without exposing
file contents.

The current `local_lexical_preview` path is the first provider-free DirectBackend
routing implementation for explicit TUI `context_segments`. It tokenizes the
protected task and reducible context segments locally, selects matching segment
ids deterministically, and reports only safe counts, opaque ids, token
estimates, and score categories. It is lexical and deterministic; it is not an
LLM router result.

The existing generic SFE router paths remain provider-backed, and the benchmark
dry-run selector depends on fixture oracle labels rather than arbitrary
first-party TUI context. Provider-backed router integration remains future work
after the local explicit-segment router path is validated.

Real SFE router integration should be introduced before broadening executor
integration. Executor calls remain out of scope for the current TUI dry-run
path.

## Read-Only Ask Phase

`/ask` is the first read-only executor phase. It uses DirectBackend only,
routes explicit `context_segments` through `local_lexical_preview`, and sends
only the selected context segments plus protected instructions and the protected
task to the executor.

This path may call the configured executor provider, but it does not use the
proxy, write files, execute shell commands, expose backend switching, or run an
agent loop. The assistant answer is displayed to the user; diagnostics remain
sanitized to counts, opaque ids, token estimates, provider call count, and
disabled capability flags.

The later `/patch` -> `/apply-patch` path keeps writes behind an explicit
router-reviewed boundary. `/patch` stores structured full-file replacement
proposals and never writes files. `/apply-patch` writes only after the
configured router reviewer returns `OK_APPLY`; `KO_BLOCK` writes nothing.
Worktree isolation can move that explicit write boundary into an SFE-created
Git Worktree, but it still does not merge, push, create PRs, run shell
commands, or run tests.

## Safety Posture

The TUI should continue to avoid:

- hidden developer or system prompt parsing,
- CodexCLI prompt reverse-engineering,
- raw prompt or file-content logging,
- request-body logging,
- provider payload logging,
- API key or header logging,
- automatic writes,
- shell command execution,
- provider or proxy calls in dry-run preview mode.
