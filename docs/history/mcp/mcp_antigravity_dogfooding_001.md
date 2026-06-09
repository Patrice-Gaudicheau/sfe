# SFE MCP Antigravity Dogfooding 001

Status note: This is a historical dogfooding record. It records one local
successful SFE MCP run through Antigravity IDE and the operational fixes found
while reaching that run. It is not a production-readiness claim.

## Context

Antigravity IDE was opened in:

```text
/home/patrice/Projets/00_Tests/SFE-playground
```

The SFE MCP runtime was launched from:

```text
/home/patrice/Projets/SpatialFieldEngineForCognition
```

The effective local MCP launch command was the plain SFE entry point:

```bash
sfe-mcp
```

SFE provider configuration used CodexCLI for all runtime roles:

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=codexcli
SFE_PROVIDER_EXECUTOR=codexcli
```

The playground root contains independent test repositories as subdirectories.
Each test repository has its own `.git` directory and target files.

## Validated Successful Test

Test directory:

```text
/home/patrice/Projets/00_Tests/SFE-playground/test_002_basic_patch
```

Task:

```text
Modify hello.py so that hello() returns "hello from SFE MCP" instead of "hello".
```

Observed result:

| Field | Value |
| --- | --- |
| `status` | `completed` |
| `execution_mode` | `workspace_write` |
| `selected_source_refs` | `hello.py` |
| `changed_files` | `hello.py` |
| `patch_generated` | `true` |
| `patch_applied` | `true` |
| `executor_provider` | `codexcli` |

The run diagnostics showed a live CodexCLI execution-mode router call:

| Diagnostic field | Value |
| --- | --- |
| provider | `codexcli` |
| model | `gpt-5.5` |
| calls_made | `1` |
| confidence | `1.0` |

Final effective code change:

```diff
-    return "hello"
+    return "hello from SFE MCP"
```

This validated the local MCP macro-tool flow through:

```text
sfe_set_target_directory
sfe_set_task
sfe_run
sfe_run_report
sfe_workspace_status
```

The successful run used the shared SFE runtime path rather than a separate MCP
execution pipeline.

## Issues Found During Dogfooding

Several operational issues were discovered and fixed before the successful
Antigravity run.

### MCP Config Location

Antigravity was reading:

```text
C:\Users\patri\.gemini\config\mcp_config.json
```

This differed from the initially edited Antigravity IDE MCP config path. After
using the config path Antigravity actually read, the local SFE MCP server became
visible and registered the expected five tools.

### Installed Entry Point Imports

The installed `sfe-mcp` console entry point initially failed before tool
registration because the top-level `providers` package was not included in the
Python package configuration. This made imports such as `providers.alibaba`
fail when running the installed entry point without manually setting
`PYTHONPATH`.

The packaging configuration was fixed so the installed MCP entry point can
import the shared SFE runtime and provider modules normally.

### Original-Mode Git Status

`sfe_workspace_status` originally returned:

```json
{
  "git_status": {
    "available": false
  }
}
```

for a normal clean Git repository in original workspace mode. This did not mean
Windows Git was being used or that WSL Git was unavailable. It meant the shared
runtime did not yet probe Git status unless an isolated SFE worktree session was
active.

`RuntimeSession.workspace_status()` was updated to report useful original-mode
Git metadata for normal repositories, including clean/dirty state, changed-file
count, repository-root label, and branch metadata.

### MCP Environment Loading

The MCP client should not have to source `.env` or place secrets in
`mcp_config.json`. The `sfe-mcp` startup path needed to load the same local SFE
environment expected by the runtime before provider setup.

The shared SFE environment loader now checks the launch working directory `.env`
first and then falls back to the SFE project-root `.env`, without overriding
already-set environment variables and without printing secret values. The MCP
entry point loads that environment before importing and starting the MCP server.

### CodexCLI Executable Resolution

In an Antigravity-like WSL process environment, the CodexCLI provider could be
configured correctly while still failing `health()` because the `codex`
executable was not found on the MCP process `PATH`.

The failing condition was:

```text
execution_mode_router_not_configured
configured execution-mode router is not available
```

with provider `codexcli` and model `gpt-5.5`.

`CodexCLIProvider` was updated to resolve the executable from an explicit
configuration value, `PATH`, or known WSL Codex install locations. The same
resolved executable is used for provider health checks and for `codex exec`.
The unavailable diagnostic is now more actionable while still avoiding secrets,
raw provider payloads, or full environment dumps.

## Current V1 Limitation

SFE MCP v1 still uses synchronous `sfe_run`. This preserves the v1 macro-tool
shape and keeps SFE as the owner of the run pipeline.

SFE structured run progress events are bridged to MCP progress notifications
when the client supports them. The final `sfe_run` response also includes safe
progress metadata.

Async start/poll tools remain deferred. They should be considered only if real
client dogfooding shows that synchronous `sfe_run` regularly hits practical
client-specific timeout limits.

## Interpretation

This milestone validates that Antigravity can drive the local SFE MCP v1 server
through the intended five-tool control surface and complete a real
`workspace_write` patch against a dedicated Git repository.

The result supports the current architecture boundary: MCP is a local control
surface over `RuntimeSession`, not a second runtime implementation.
