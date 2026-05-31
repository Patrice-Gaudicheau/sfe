# SFE TUI DirectBackend Strategy

Status: historical. The current doctrine is summarized in
`../../sfe_product_doctrine.md`; the current architecture status is in
`../../current_architecture_status.md`. This note preserves the earlier
DirectBackend strategy decision.

## Decision

The SFE-aware TUI was selected as the first local user-facing path for SFE
workflow development. The DirectBackend is the default and only exposed backend
for the TUI for now.

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
surface: launch the TUI, choose a workspace, enter a task, and run the
intention-aware SFE flow with `/run`.

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

The current primary task path is `/run`: the core execution-mode router first
chooses `console_output`, `workspace_write`, or `external_action`.
`console_output` renders a direct answer in the TUI with no worktree or patch.
`workspace_write` discovers context, routes a reduced executor payload,
generates a patch, and applies inside an SFE-created Git worktree without
mandatory router review or diff inspection. `external_action` is recognized but
not implemented yet. The older `/patch` -> `/apply-patch` path remains
available as an advanced/debug router-reviewed boundary. These paths do not
merge, push, create PRs, run shell commands, or run tests/lint by default.

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
