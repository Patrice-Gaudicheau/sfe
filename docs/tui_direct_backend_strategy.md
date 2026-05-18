# SFE TUI DirectBackend Strategy

This note records the current first-party interface direction for SFE.

## Decision

The SFE-aware TUI is the canonical user-facing path for new SFE workflow
development. The DirectBackend is the default and only exposed backend for the
TUI for now.

The existing SFE Proxy and CodexCLI path remain compatibility and stress-test
infrastructure. They should stay safe, observable, and fallback-oriented, but
they are no longer the primary interface being optimized for SFE-aware context
routing.

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
- The deterministic preview is not an LLM router result and must be labeled as
  a local preview.

## Safety Posture

The TUI should continue to avoid:

- hidden developer or system prompt parsing,
- CodexCLI prompt reverse-engineering,
- raw prompt or file-content logging,
- request-body logging,
- provider payload logging,
- API key or header logging,
- writes,
- shell command execution,
- provider or proxy calls in dry-run preview mode.
