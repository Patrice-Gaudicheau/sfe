# SFE MCP Client Setup

This guide documents the local SFE MCP server setup for two desktop clients:

- Antigravity
- Codex App

It is operational setup documentation for the current local STDIO MCP server.
For the MCP design boundary, see
[sfe_mcp_local_control_surface.md](sfe_mcp_local_control_surface.md).

## Current MCP Tools

The SFE MCP server is expected to expose exactly these tools:

- `sfe_set_target_directory`
- `sfe_set_task`
- `sfe_run`
- `sfe_run_report`
- `sfe_workspace_status`

If the client does not show these tools, treat the MCP server as not correctly
started or not correctly discovered.

## Prerequisites

This setup assumes:

- SFE is checked out at
  `/home/patrice/Projets/SpatialFieldEngineForCognition`.
- The MCP client runs on Windows and starts SFE through WSL.
- The local `sfe` Python package is installed in editable mode from the SFE
  checkout.
- The `sfe-mcp` launcher exists at `/home/patrice/.local/bin/sfe-mcp`.
- Provider credentials, if needed by the runtime, are supplied by the existing
  local SFE environment. They are not configured in the MCP client by default.

Do not add `PYTHONPATH` by default. The editable install is the intended way to
load the local checkout, and adding `PYTHONPATH` can hide configuration errors
or accidentally load a different copy.

## STDIO MCP Principle

The SFE MCP server is a local STDIO server. The client starts one process and
communicates with it over standard input and standard output.

On Windows clients, the recommended process chain is:

```text
Windows MCP client
  -> wsl.exe
    -> bash -lc
      -> cd /home/patrice/Projets/SpatialFieldEngineForCognition
      -> /home/patrice/.local/bin/sfe-mcp
```

The `cd` inside the Bash command is important. It guarantees the Linux working
directory used by the SFE MCP server. A Windows-side working-directory field
only controls where `wsl.exe` itself is launched.

Use the absolute launcher path:

```bash
/home/patrice/.local/bin/sfe-mcp
```

This avoids depending on the WSL `PATH` for MCP startup.

## Editable Local Install

The expected installation shape is:

```text
sfe package location: /home/patrice/.local/lib/python3.12/site-packages
editable project:     /home/patrice/Projets/SpatialFieldEngineForCognition
```

The server should import code from the checkout, for example:

```text
sfe_mcp.server -> /home/patrice/Projets/SpatialFieldEngineForCognition/sfe_mcp/server.py
sfe.patching   -> /home/patrice/Projets/SpatialFieldEngineForCognition/sfe/patching.py
```

After Python source changes, restart the MCP server from the client. A running
STDIO MCP server does not hot reload Python modules.

## Codex App Setup With The Form

Use these values in the Codex App MCP server form.

```text
Name
sfe_mcp

Type
STDIO

Command
wsl.exe

Arguments
-e
bash
-lc
cd /home/patrice/Projets/SpatialFieldEngineForCognition && /home/patrice/.local/bin/sfe-mcp

Environment variables
none by default

Environment variables to transfer
none by default

Working directory
C:\Users\patri
```

Notes:

- The Windows working directory starts `wsl.exe`.
- The real Linux working directory is set by the `cd` in the Bash command.
- Do not add `PYTHONPATH` by default.
- Prefer the absolute `/home/patrice/.local/bin/sfe-mcp` path over relying on
  `PATH`.

## Codex App Setup With TOML

The equivalent Codex App configuration is:

```toml
[mcp_servers.sfe_mcp]
enabled = true
command = "wsl.exe"
args = ["-e", "bash", "-lc", "cd /home/patrice/Projets/SpatialFieldEngineForCognition && /home/patrice/.local/bin/sfe-mcp"]
cwd = 'C:\Users\patri'
```

On the validated local machine, this file was inspected at:

```text
/mnt/c/Users/patri/.codex/config.toml
```

Do not edit that file unless you are intentionally changing the local Codex App
configuration.

## Antigravity Setup

In Antigravity, open the custom MCP server configuration UI:

```text
Manage MCP servers
```

Create or inspect a server named:

```text
sfe
```

The server should be enabled, and the five expected tools should be detected
and enabled:

- `sfe_set_target_directory`
- `sfe_set_task`
- `sfe_run`
- `sfe_run_report`
- `sfe_workspace_status`

Configure the server as a STDIO MCP server with the same process shape used by
Codex App:

```text
Command
wsl.exe

Arguments
-e
bash
-lc
cd /home/patrice/Projets/SpatialFieldEngineForCognition && /home/patrice/.local/bin/sfe-mcp
```

If Antigravity has fields for environment variables, leave them empty by
default. If it has a working-directory field, a Windows directory such as
`C:\Users\patri` is acceptable because the Bash command performs the required
Linux-side `cd`.

## Target Directory Paths

Pass WSL-internal Linux paths to `sfe_set_target_directory`.

Good:

```text
/home/patrice/Projets/00_Tests/SFE-playground/test_13_miniblog
```

Avoid:

```text
C:\Users\patri\...
\\wsl.localhost\Ubuntu\home\patrice\...
/Ubuntu/home/patrice/...
```

Windows paths, UNC paths, and client-specific URI-like paths are not the target
paths SFE expects. The SFE MCP server runs inside WSL, so workspace targets
should be normal WSL filesystem paths.

## Useful Verification Commands

Run these inside WSL:

```bash
which sfe-mcp
readlink -f "$(command -v sfe-mcp)"
head -n 5 "$(command -v sfe-mcp)"
python -m pip show sfe
python - <<'PY'
import inspect, sfe_mcp.server, sfe.patching
print(inspect.getfile(sfe_mcp.server))
print(inspect.getfile(sfe.patching))
PY
```

Expected results:

- `sfe-mcp` resolves to `/home/patrice/.local/bin/sfe-mcp`.
- `pip show sfe` reports an editable project location at
  `/home/patrice/Projets/SpatialFieldEngineForCognition`.
- `inspect.getfile(...)` reports files under the local SFE checkout.

## Minimal Smoke Test

Use this smoke test after adding or changing an MCP client configuration.

Target directory:

```text
/home/patrice/Projets/00_Tests/SFE-playground/test_mcp_smoke
```

Task:

```text
Create a single file named hello.txt containing exactly: SFE MCP smoke test
```

Recommended MCP flow:

1. Call `sfe_set_target_directory` with the target directory.
2. Call `sfe_set_task` with the task text.
3. Call `sfe_run`.
4. Call `sfe_run_report`.
5. Verify that the report has `ok true`, `status completed`, and `issue null`.
6. Verify that `hello.txt` exists in the target directory and contains the
   requested text.

The target directory must already exist. The smoke test should create the file
through SFE MCP, not through manual shell writes.

## Troubleshooting

### Tools Are Missing

If the client does not show all five SFE tools, the MCP server was not started
or was not discovered correctly.

Check:

- the command is `wsl.exe`;
- the arguments are in the correct order;
- the Bash command uses the SFE checkout path;
- `/home/patrice/.local/bin/sfe-mcp` exists;
- the server is enabled in the client UI;
- each tool is enabled in the client UI.

### Server Was Not Restarted

If Python code changed but the MCP behavior is still old, restart the MCP
server from the client. STDIO MCP servers load Python modules at process start.
There is no hot reload while the server is already running.

### Modified Code Is Not Loaded

Use the verification commands above. The important checks are:

- `python -m pip show sfe` shows the local checkout as the editable project;
- `inspect.getfile(sfe_mcp.server)` points into the checkout;
- `inspect.getfile(sfe.patching)` points into the checkout.

If these point elsewhere, the MCP server can use a different SFE installation
than the repository you are editing.

### `PATH` Does Not Find `sfe-mcp`

Use the absolute launcher path in the MCP command:

```bash
/home/patrice/.local/bin/sfe-mcp
```

This is preferred for client configuration because MCP clients may launch a
shell with a different environment than an interactive terminal.

### Wrong Target Path

Use WSL paths in `sfe_set_target_directory`, for example:

```text
/home/patrice/Projets/00_Tests/SFE-playground/test_13_miniblog
```

Do not pass Windows paths, UNC paths, or Antigravity URI-style paths. Path
confusion is a common cause of workspace selection failures.

### `workspace_not_found`

The selected target directory must already exist and must be a directory. Create
or choose the directory before calling `sfe_set_target_directory`.

Also verify that the path is a WSL path visible inside the WSL distribution
where `sfe-mcp` is running.

### Run Fails After Server Starts

Call `sfe_run_report` after every failed `sfe_run`. It reports the stored run
diagnostics without rerunning the task.

For patch-proposal failures, inspect the patch diagnostics fields exposed by
the MCP report, especially strict parse status, fenced extraction status, raw
segment extraction status, and final parse issue reason.
