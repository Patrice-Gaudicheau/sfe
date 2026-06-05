# CodexCLI Phase 5 DEV Patch Executor

This note records the Phase 5 CodexCLI integration.

`SFE_PROVIDER=codexcli` is now available in the DEV patch executor path. In
this path CodexCLI is used only as a text-producing provider: it receives the
patch-generation instruction and proposes a unified diff or other supported
patch text.

SFE remains responsible for parsing patch output, validating patch format and
paths, applying changes through the existing isolated worktree machinery, and
rejecting invalid, unsafe, or malformed proposals. The CodexCLI sandbox is not
treated as the primary safety boundary.

This completes the planned CodexCLI provider integration phases.
