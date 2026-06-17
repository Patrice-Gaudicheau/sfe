# SFE MCP Antigravity Dogfooding 001

Status note: this is a compressed historical dogfooding record. It preserves
the operational lesson from one local SFE MCP run through Antigravity IDE. It
is not current setup guidance, production-readiness evidence, or a benchmark.

## Context

Antigravity IDE was opened over a playground directory containing independent
Git repositories. The SFE MCP runtime was launched from the SFE checkout with
the plain local entry point:

```bash
sfe-mcp
```

The dogfooding path exercised the five-tool local MCP control surface:

```text
sfe_set_target_directory
sfe_set_task
sfe_run
sfe_run_report
sfe_workspace_status
```

Provider roles used CodexCLI during the dogfooding session. The successful path
validated that MCP drove the shared `RuntimeSession` and run pipeline rather
than a separate MCP-specific execution implementation.

## Successful Baseline Observation

The first successful target was a small repository containing `hello.py`. The
task changed `hello()` from returning `hello` to returning `hello from SFE MCP`.

The run completed with:

- `status`: `completed`;
- `execution_mode`: `workspace_write`;
- selected and changed file: `hello.py`;
- executor provider: `codexcli`;
- successful validation, application, and promotion through the shared runtime.

This established that Antigravity could invoke the local SFE MCP server and
complete a real write-oriented run against a dedicated Git repository.

## Target-Switch State Leak

A follow-up case switched the MCP session target to a different repository and
asked SFE to create `greet.py`. That exposed a serious `RuntimeSession` state
leak:

- the active workspace label pointed to the new target;
- `isolated_session` still pointed to the previous target and worktree;
- `git_status` still described the previous repository.

As a result, `sfe_run` wrote `greet.py` into the stale previous SFE worktree
instead of the newly selected target repository.

## Why It Mattered

The bug was a stale worktree safety issue, not a cosmetic status problem. A
local control surface may switch targets repeatedly, so target-bound runtime
state must not survive a target directory change. Otherwise a correct-looking
MCP session can mutate the wrong isolated worktree or report mixed status from
two repositories.

## Fix And Retest

The fix was committed as:

```text
ea8a37027dbf0a6bd2b5613343159b399b252da7
Reset SFE session state on target directory change
```

The fix reset target-bound `RuntimeSession` state when the selected target
directory changed, including stale isolated worktree session metadata, latest
run/report source data, discovery/latest result state, and captured progress
events.

After the fix, a fresh target reported original workspace mode, no isolated
session, clean Git status, and the correct repository label before the run. The
create-file task then promoted `greet.py` into the intended target repository.

## Final Lesson

MCP is a local control surface over the same `RuntimeSession` used by the TUI.
That makes target-switch hygiene part of the shared runtime contract: changing
the target directory must reset target-bound state before any status report,
discovery result, isolated worktree, or later run can be reused.
