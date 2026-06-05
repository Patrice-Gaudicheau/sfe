# CodexCLI Phase 3 Run Router Wiring

Date: 2026-06-05

This note records the narrow Phase 3 CodexCLI integration.

`SFE_PROVIDER=codexcli` is now accepted by shared provider
configuration and wired into the `/run` execution-mode router through
`CodexCLIProvider`. At this phase, the router used the existing
`SFE_OPENAI_ROUTER_MODEL` convention and the existing `system_instruction` chat
path. Phase 5.5 later decoupled CodexCLI from OpenAI API model variables by
moving public SFE CodexCLI routing to `SFE_CODEXCLI_ROUTER_MODEL`.

This change is router-only. It does not enable CodexCLI as a TUI executor,
console/read-only answer provider, or DEV patch executor.
