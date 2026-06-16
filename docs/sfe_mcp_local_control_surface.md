# SFE MCP Local Control Surface

This note defines the local Model Context Protocol (`MCP`) integration for
SFE. It is a design and v1 entry-point boundary, not a production-readiness
claim.

For the current local TUI workflow, see
[tui_v0_1_user_guide.md](tui_v0_1_user_guide.md). For the current architecture
status, see
[current_architecture_status.md](current_architecture_status.md).

## Purpose

The MCP integration should expose SFE to local MCP clients as a small control
surface over the same runtime path that the first-party TUI already uses.
The v1 local stdio entry point is:

```bash
sfe-mcp
```

The user-facing goal is to let a local MCP client perform the same canonical
flow as the TUI:

```text
select target directory
set task
run
inspect run report
inspect workspace status
```

The MCP integration is not a new agent runtime, not a replacement for the TUI,
and not an alternate execution pipeline. Its job is to adapt MCP tool calls to
the existing SFE session/runtime behavior with structured inputs and outputs.

## Control Surface, Not New Runtime

MCP must not reimplement SFE task routing, context discovery, executor calling,
patch parsing, validation, Git worktree handling, promotion, or run reporting.
Those behaviors belong in the shared SFE runtime path.

The MCP server should only own:

- MCP protocol setup and tool registration;
- per-session state for the selected target directory, current task, latest
  run result, and current workspace session metadata;
- conversion from MCP tool input into shared runtime/session calls;
- conversion from shared runtime/session results into safe structured MCP
  output.

If a behavior is already exercised by `/run`, `/run-report`, or
`/workspace-status`, the MCP version should call the same internal layer rather
than duplicating command-specific logic.

Shared session logic lives in `sfe.runtime_session.RuntimeSession`. The MCP
implementation depends on that shared layer rather than `sfe_tui.app`.

## TUI/MCP ISO Requirement

The TUI and MCP must be ISO at the runtime level. For the same configured
providers, target directory, task, and environment, they must use the same
effective behavior for:

- target directory resolution and display-safe path handling;
- task storage and task replacement;
- `/run` execution-mode routing;
- `console_output`, `workspace_write`, and unsupported `external_action`
  behavior;
- discovery and context loading;
- executor prompt preparation;
- core `SFE_FILE` text transport and compatible Git diff parsing;
- mechanical path validation;
- Git repository preparation;
- Git worktree creation and reuse;
- patch application inside the active SFE worktree;
- promotion from the worktree back to the target directory when the current
  runtime path promotes changes;
- latest run-report data;
- workspace status data;
- final file modifications in the target directory.

MCP output formatting may differ from TUI text rendering, but the underlying
state transitions and file effects must match the TUI runtime.

## Minimal V1 Tools

The v1 MCP surface should expose only the canonical TUI-equivalent flow.

### `sfe_set_target_directory`

Select the one target directory for the MCP session, equivalent to the TUI
startup workspace selection.

Expected input:

```json
{
  "path": "/absolute/or/session-relative/path"
}
```

Expected behavior:

- resolve the path using the same workspace rules as the TUI;
- require the resolved path to exist and be a directory;
- store it as the session target directory;
- clear task-dependent transient state only if changing target directory would
  make prior state invalid;
- return a safe path label and machine-readable status.

### `sfe_set_task`

Store the current task, equivalent to `/task <text>`.

Expected input:

```json
{
  "task": "Change request or question for SFE"
}
```

Expected behavior:

- reject empty or whitespace-only tasks;
- store the task in the session;
- invalidate discovery, latest result, pending patch state, and previous run
  report state exactly as the TUI does for a new task;
- preserve the selected target directory.

### `sfe_run`

Run the current task, equivalent to `/run`.

Expected input:

```json
{}
```

Expected behavior:

- require a selected target directory;
- require a current task;
- call the same runtime path used by the TUI `/run` command;
- return concise structured status, execution mode, issue category and reason
  when failed, selected context metadata, changed files, promotion status, and
  safe progress metadata;
- include Real Loop summary fields when the shared runtime verifier/governor
  runs for an eligible `workspace_write` task;
- not expose raw provider payloads, secrets, absolute internal paths, full file
  contents, or full prompts.

### `sfe_run_report`

Return diagnostics for the previous `sfe_run`, equivalent to `/run-report`.

Expected input:

```json
{}
```

Expected behavior:

- never rerun execution;
- require a previous run result;
- return structured diagnostics derived from the stored latest run result;
- include the same runtime fields the TUI report renders, translated to safe
  structured output.

### `sfe_workspace_status`

Return current workspace/worktree state, equivalent to `/workspace-status`.

Expected input:

```json
{}
```

Expected behavior:

- report whether the MCP session is using the original target directory or an
  active SFE-created worktree;
- include SFE worktree session metadata when present;
- include Git status metadata when available;
- use safe path labels and avoid leaking unnecessary absolute paths.

## Target Directory Behavior

V1 is local-first and session-scoped. Only one target directory is needed for
the MCP server session, exactly like the TUI startup directory selection.

The selected target directory should be resolved once through the same rules
used by the TUI and then stored in MCP session state. Tool calls after
`sfe_set_target_directory` should operate on that selected directory unless
the user explicitly selects a different one through `sfe_set_target_directory`.

The MCP server must not accept per-call workspace overrides for `sfe_run` in
v1. Per-run target switching would make the MCP flow diverge from the TUI
startup model and increase the risk of accidental writes to the wrong
directory.

## Safety Constraints

The local MCP server is a write-capable local control surface once `/run`
selects `workspace_write`. It must therefore preserve the current SFE safety
boundaries:

- no Docker requirement for v1;
- no HTTP API for v1;
- no OpenAI-compatible API server for v1;
- no shell/tool execution added by MCP;
- no MCP-specific patch application path;
- no path writes outside the selected workspace/worktree;
- no absolute path, parent-directory escape, symlink, binary, or unsupported
  patch handling beyond the existing runtime guards;
- no raw provider request/response, prompt, file-content, API-key, `.env`, or
  secret rendering in MCP responses;
- no merge, push, remote creation, pull request creation, or source-branch
  mutation outside the current SFE runtime behavior;
- no attempt to clean or remove non-SFE worktrees.

Before enabling workspace writes through MCP, implementation tests must show
that `sfe_run` uses the same validation and patch/worktree machinery as TUI
`/run`.

Text-returning API providers, including OpenAI, Anthropic, Google, Alibaba,
Lemonade, Ollama, and similar endpoints, use the core `SFE_FILE` full-file block
transport for `workspace_write`. MCP does not implement its own parser or prompt
contract; it reaches the same `RuntimeSession` and `RunPipeline` path as the TUI.
Filesystem-capable local or CLI executors are a separate path when they actually
write files inside the controlled worktree.

Real Loop follows the same rule: MCP does not own verifier prompts, retry-task
generation, or loop stop logic. When enabled, those behaviors live in the shared
runtime layer and are reported through `sfe_run` / `sfe_run_report` as safe
structured metadata such as `real_loop_status`, `llm_verifier_verdict`,
`retry_worthwhile`, `stop_reason`, and `executor_retry_task`.

## Git Worktree And Promotion Expectations

When `/run` selects `workspace_write`, MCP should inherit the current Git and
promotion behavior from the shared SFE runtime:

- if the selected workspace is already inside a Git repository, SFE uses that
  repository for isolated worktree creation;
- if the selected workspace is not a Git repository and the runtime currently
  auto-initializes a local repository snapshot, MCP does the same;
- generated file changes are applied in an SFE-owned isolated worktree through
  the existing patch pipeline;
- promotion behavior must match the current runtime exactly, including which
  files are copied back to the target directory and which failures block
  promotion;
- MCP does not add merge, push, commit, PR, or cleanup behavior beyond the
  shared runtime.

The MCP `sfe_workspace_status` tool should report the active workspace mode and
SFE-owned worktree metadata so clients can understand whether the session is
operating on the original workspace or an isolated worktree.

## Explicitly Out Of Scope For V1

The following are intentionally out of scope for the first MCP milestone:

- Dockerized MCP execution;
- remote MCP hosting;
- HTTP API;
- OpenAI-compatible API server;
- multi-target sessions;
- per-run target directory override;
- separate MCP-only routing, discovery, execution, validation, or promotion
  logic;
- provider configuration UI;
- benchmark orchestration;
- test/lint/syntax command execution;
- automatic merge, push, pull request creation, or deployment;
- exposing advanced/debug TUI commands such as `/patch`, `/apply-patch`,
  `/isolate`, `/review-worktree`, `/cleanup-worktree`, or `/gc-worktrees` as
  MCP tools.

Those capabilities can be reconsidered later only after the canonical
`set_target_directory -> set_task -> run -> run_report -> workspace_status`
flow is ISO with the TUI runtime.

## Future Extension Points

Future MCP work can build on the v1 control surface after the shared runtime
boundary is proven:

- explicit read-only ask/report tools if they call shared runtime behavior;
- advanced diagnostic tools for discovery/context metadata;
- multi-session support with explicit session identifiers;
- structured progress streaming for clients that support it;
- policy controls for enabling or disabling workspace writes;
- optional test/lint execution as a separate, explicit, locally configured
  capability;
- GitHub or PR integration as an external-action milestone;
- remote/HTTP deployment once local behavior is stable and documented.

Future extensions must preserve the same principle: MCP adapts to SFE runtime
behavior; it does not become a second SFE implementation.

## Dogfooding V1 With A Real MCP Client

Use the local stdio entry point:

```bash
sfe-mcp
```

Configure the MCP client to launch that command as a stdio MCP server. The v1
dogfooding flow is:

```text
sfe_set_target_directory
sfe_set_task
sfe_run
sfe_run_report
sfe_workspace_status
```

Known v1 limitation: `sfe_run` is synchronous. Long runs may hit
client-specific tool-call or MCP request timeouts. The MCP server bridges SFE's
existing structured run progress events to MCP progress notifications when the
client sends a progress token for the tool call. If real dogfooding shows that
timeouts still block practical use, a later milestone can consider an async
start/poll shape. That should be driven by client evidence and should still
keep SFE as the owner of the run pipeline.
