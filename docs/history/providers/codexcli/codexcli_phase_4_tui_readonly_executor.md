# CodexCLI Phase 4 TUI Read-Only Executor

Date: 2026-06-05

This note records the narrow Phase 4 CodexCLI integration.

`SFE_PROVIDER=codexcli` is now selectable by the TUI direct executor for
console-style answers and read-only `/ask` answers. The executor uses
`SFE_OPENAI_EXECUTOR_MODEL` with the CodexCLI provider default as fallback, and
passes TUI system instructions through the existing `system_instruction` chat
path.

At this phase, CodexCLI was not enabled for patch proposal, DEV patch execution,
or patch application. Phase 5 later enabled DEV patch proposal only, with SFE
remaining responsible for validation and application.
