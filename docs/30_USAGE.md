# Usage

SFE can be used through the local TUI or the local MCP server.

## TUI

Start the TUI:

```bash
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
runs.

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
