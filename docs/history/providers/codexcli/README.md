# CodexCLI Provider History

This directory preserves historical CodexCLI provider notes. CodexCLI behavior
has changed over time, so these notes should be read as implementation history,
benchmark evidence, or diagnostic context rather than current setup guidance.
Current public configuration starts from `README.md`, `docs/INDEX.md`, and the
current provider sections.

## Phase Timeline Summary

The original tiny phase breadcrumb files were merged into this table and then
removed.

| Phase | Historical change | Current interpretation |
| --- | --- | --- |
| 1.5 provider hardening | Added independent total wall-clock timeout supervision around the Codex CLI subprocess and a helper for explicit `codex exec resume` command generation. | Provider hardening milestone before public `/run` wiring. |
| 3 run router wiring | Accepted `SFE_PROVIDER=codexcli` in shared provider configuration and wired CodexCLI into the `/run` execution-mode router. | Early router-only integration; later model env variables were decoupled. |
| 4 TUI read-only executor | Allowed CodexCLI for console-style answers and read-only `/ask` answers. | Read-only TUI execution milestone before write-oriented paths. |
| 4.5 provider rename | Standardized the public SFE selector as `SFE_PROVIDER=codexcli` while retaining internal benchmark enum compatibility. | Public naming cleanup; benchmark-local enum history remains separate. |
| 5 DEV patch executor | Enabled CodexCLI as a text-producing DEV patch executor while SFE retained parsing, validation, worktree isolation, and rejection. | Historical text-patch milestone, not the current Aider-backed default writer story. |
| 5.5 model env decoupling | Moved public CodexCLI routing/execution model selection to `SFE_CODEXCLI_ROUTER_MODEL` and `SFE_CODEXCLI_EXECUTOR_MODEL`. | Avoided accidental coupling to OpenAI API provider model variables. |

## Retained Detailed Notes

- [codexcli_output_token_dev_patch_benchmark_protocol.md](codexcli_output_token_dev_patch_benchmark_protocol.md):
  controlled protocol for the DEV/Patch output-token benchmark.
- [codexcli_role_split_effort_benchmark_note.md](codexcli_role_split_effort_benchmark_note.md):
  role-split effort benchmark observations.
- [codexcli_full_role_discovery_run_benchmark_note.md](codexcli_full_role_discovery_run_benchmark_note.md):
  full-role discovery `/run` benchmark sample and failure modes.
- [codexcli_openai_discovery_tui_run_note.md](codexcli_openai_discovery_tui_run_note.md):
  one manual TUI `/run` observation using CodexCLI with OpenAI discovery.
- [codexcli_large_contextual_practical_fixture_note.md](codexcli_large_contextual_practical_fixture_note.md):
  first benchmark-local CodexCLI executor validation on the practical fixture tier.
- [codexcli_large_contextual_router_inclusive_note.md](codexcli_large_contextual_router_inclusive_note.md):
  router-inclusive CodexCLI large/contextual observations.
- [codexcli_openai_api_practical_repeat3_comparison.md](codexcli_openai_api_practical_repeat3_comparison.md):
  directional comparison between CodexCLI and OpenAI API practical repeat-3 evidence.
- [codexcli_raw_envelope_smoke_note.md](codexcli_raw_envelope_smoke_note.md):
  raw CodexCLI token-envelope diagnostics.

## Caveats

- Historical files may use older patch-first terminology because they describe
  the implementation state at the time.
- CodexCLI is an agentic CLI provider path, not a thin OpenAI API equivalent.
- Benchmark notes are local observations, not provider rankings or production
  reliability claims.
