# Usage

SFE can be used through the local TUI or the local MCP server.

## TUI

Start the TUI:

```bash
make doctor
make sfe-tui
```

Minimal workflow:

```text
Workspace: /path/to/project
/task Add usage notes to README.md
/run
```

Common commands:

- `/task <text>` sets the current task.
- `/run` routes and executes the task.
- `/run-report` shows diagnostics from the previous run.
- `/status` shows workspace and provider state.
- `/context` shows selected context summaries.
- `/reset` clears the current task and context state.
- `/quit` exits.

## Write Tasks

When `/run` routes a task to `workspace_write`, SFE uses the configured writer
inside an isolated Git worktree. Aider is the default writer for normal write
runs. If write runs fail before execution, run `make doctor` and check the
Aider and provider lines first.

When Real Loop is enabled and a verifier is available, completed write runs may
show Real Loop status lines in the result. `/run-report` includes the verifier
verdict, attempt count, retry-worthiness, stop reason, and per-iteration
diagnostics. A retry, when allowed, is a targeted correction task and counts
toward `SFE_REAL_LOOP_MAX_ITERATIONS`.

Review the resulting Git diff before publishing or pushing changes.

## Answer Tasks

For read-only tasks, SFE can answer without creating a worktree or modifying
files. The run report still records the route and selected context summary.

## MCP

The package exposes an MCP server command:

```bash
sfe-mcp
```

MCP clients should run the server from the repository where SFE is installed,
with the same environment variables used by the TUI.
