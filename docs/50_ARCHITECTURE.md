# Architecture

SFE separates task routing, context selection, and filesystem execution.

## Core Flow

1. A user selects a workspace and provides a task.
2. SFE routes the task to an execution mode.
3. Discovery builds a bounded context set from the workspace.
4. The executor receives the task and selected context.
5. Write tasks run in an isolated Git worktree.
6. Accepted changes are promoted back to the source workspace.
7. For eligible completed write runs, Real Loop can verify the result and run a
   bounded targeted correction attempt.

## Execution Modes

- `console_output`: answer without modifying files.
- `workspace_write`: create, edit, or delete files through the worktree path.
- `external_action`: recognized but not executed by the current local runtime.

## Worktree Boundary

For write tasks, SFE prepares a `.sfe-worktrees/` worktree instead of writing
directly into the source checkout. Promotion copies accepted changes back only
after path validation.

Path checks reject absolute paths, parent traversal, internal repository paths,
and changes outside the selected workspace.

## Runtime Surfaces

The TUI `/run` command and the MCP server share the same runtime path. This
keeps routing, worktree behavior, reports, and safety checks consistent across
local interfaces.

## Real Loop

Real Loop sits after a completed `workspace_write` attempt in the shared runtime
session. It sends the verifier the original task, current task, run-result
metadata, previous retry tasks, previous failure categories, and a bounded
workspace snapshot.

The verifier may return `pass`, `needs_retry`, `blocked`, or `abort`. A
`needs_retry` decision must include a targeted executor retry task, and SFE
routes that retry task before running it. The controller stops on configured
attempt limits, no meaningful progress, duplicate retry tasks, repeated failure,
verifier failure, retry failure, or terminal verifier verdicts.

## What SFE Is Not

SFE is not a security sandbox, a model-quality guarantee, or a replacement for
reviewing diffs. It is a practical routing and isolation layer for local coding
workflows.
