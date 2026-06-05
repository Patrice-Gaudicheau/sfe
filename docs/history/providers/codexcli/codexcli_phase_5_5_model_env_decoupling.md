# CodexCLI Phase 5.5 Model Env Decoupling

This note records the Phase 5.5 CodexCLI configuration cleanup.

Public SFE CodexCLI routing now uses `SFE_CODEXCLI_ROUTER_MODEL`, and public
SFE CodexCLI execution now uses `SFE_CODEXCLI_EXECUTOR_MODEL`.

OpenAI API provider paths continue to use `SFE_OPENAI_ROUTER_MODEL` and
`SFE_OPENAI_EXECUTOR_MODEL`.

This avoids accidental coupling between API-provider model configuration and
CLI-provider model configuration. CodexCLI patch behavior is unchanged:
CodexCLI proposes patch text only, while SFE remains responsible for validation
and application.
