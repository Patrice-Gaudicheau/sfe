# CodexCLI Phase 4.5 Provider Rename

Date: 2026-06-05

This note records a narrow public SFE provider naming cleanup before Phase 5.

The public SFE selector is now `SFE_PROVIDER=codexcli`. The previous
`SFE_PROVIDER=openai-codexcli` value is not kept as a public alias because the
integration is not yet published as a stable SFE provider contract.

Benchmark dispatch still uses the existing `openai-codexcli` provider enum from
`providers.codexcli.PROVIDER_NAME`. That value is kept for now because Phase 2
benchmark paths and historical benchmark reports already use it, and changing
benchmark enums is separate from the SFE configuration surface rename.

This change does not enable CodexCLI for patch proposal, DEV patch execution,
or patch application. Phase 5 remains future work.
