# CodexCLI Phase 3 Run Router Wiring

Date: 2026-06-05

This note records the narrow Phase 3 CodexCLI integration.

`SFE_PROVIDER=openai-codexcli` is now accepted by shared provider
configuration and wired into the `/run` execution-mode router through
`CodexCLIProvider`. The router uses the existing `SFE_OPENAI_ROUTER_MODEL`
convention and the existing `system_instruction` chat path.

This change is router-only. It does not enable CodexCLI as a TUI executor,
console/read-only answer provider, or DEV patch executor.
