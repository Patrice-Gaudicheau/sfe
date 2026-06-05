# CodexCLI Phase 1.5 Provider Hardening

Date: 2026-06-05

This note records a narrow CodexCLI provider hardening pass before any `/run`,
TUI executor, or DEV patch executor wiring.

Phase 1.5 closes two audit gaps:

- `providers.codexcli` now enforces an independent total wall-clock timeout
  around the Codex CLI subprocess in addition to idle-timeout supervision.
- `providers.codexcli` now exposes a minimal `build_codex_resume_command`
  helper for explicit `codex exec resume` command generation. Normal
  non-resume `CodexCLIProvider.chat` calls still use the existing
  non-interactive `codex exec --json` command path.

This change does not add `SFE_PROVIDER=openai-codexcli`, does not wire CodexCLI
into the configured `/run` execution-mode router, and does not enable CodexCLI
for TUI or DEV patch execution.
