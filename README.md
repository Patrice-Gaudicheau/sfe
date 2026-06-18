# Spatial Field Engine

![Spatial Field Engine](assets/202606152310_github.jpg)

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](pyproject.toml)
[![Interface: TUI + MCP](https://img.shields.io/badge/Interface-TUI%20%2B%20MCP-6f42c1.svg)](docs/USAGE.md)

Spatial Field Engine is a context-routing layer for safer agentic coding
workflows. It selects relevant project context, routes execution modes, and
isolates filesystem changes in Git worktrees before promotion.

SFE is for developers who want an agentic coding workflow with clearer context
selection and stricter filesystem boundaries than a direct model call.

## What SFE Does

- Builds a compact project map and selects task-relevant files.
- Routes a task to answer-only, workspace-write, or unsupported-external-action
  modes.
- Runs write tasks in isolated Git worktrees before promoting changes.
- Uses Aider as the default external writer for normal `workspace_write` runs.
- Exposes the same runtime through a local TUI and an MCP server.

## Why Not Just Run Aider Directly?

Aider is the writer. SFE is the routing and guard layer around it.

Run Aider directly when you already know the files, scope, and write mode. Use
SFE when you want the tool to select context first, keep read-only answers away
from write paths, isolate filesystem changes, and produce a compact run report
before you decide what to keep.

## Quick Install

Requirements:

- Python 3.10+
- Git
- Aider for normal write runs: `pipx install aider-chat`

```bash
git clone git@github.com:Patrice-Gaudicheau/sfe.git
cd sfe
make install
source .venv/bin/activate
```

`make install` installs SFE locally in `.venv` with `pip install -e .`. It
reuses an existing `.venv`. If Python, `python3-venv`, `pipx`, or Aider are
missing, the script prints the needed commands and only runs external install
commands after clear confirmation or explicit opt-in environment variables.

Manual local install:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## First Run

Configure a provider:

```bash
cp .env.example .env
```

Edit `.env`, uncomment one `SFE_PROVIDER`, and fill the required key or local
provider URL.

Start the TUI:

```bash
make sfe-tui
```

Then run a task:

```text
Workspace: /path/to/your/project
/task Add a small README usage section
/run
```

## Basic TUI Commands

- `/task <text>` sets the current task.
- `/run` routes and executes the task.
- `/run-report` shows diagnostics for the previous run without running again.
- `/status` shows workspace and provider state.
- `/context` shows selected context summaries.
- `/quit` exits.

## How It Works

1. SFE reads the task and current workspace.
2. The router chooses an execution mode.
3. Discovery selects a bounded set of relevant files.
4. For write tasks, SFE creates or reuses an isolated Git worktree.
5. The configured writer runs inside that isolated workspace.
6. SFE promotes accepted changes back to the source repository.

## Safety Model

SFE is a local developer tool, not a sandbox boundary.

It does provide practical guardrails:

- write tasks run through the `workspace_write` path;
- source changes are prepared in `.sfe-worktrees/` before promotion;
- absolute paths, parent traversal, and internal repository paths are rejected;
- `.env` and common secret-like files are excluded from normal context loading;
- reports avoid raw provider payloads and secret values.

You should still review diffs before publishing code.

## Minimal Provider Configuration

Set one shared provider:

```env
SFE_PROVIDER=openai
OPENAI_API_KEY=...
```

Or split roles:

```env
SFE_PROVIDER_ROUTER=openai
SFE_PROVIDER_DISCOVERY=openai
SFE_PROVIDER_EXECUTOR=anthropic
```

For Aider-backed writes, set `SFE_AIDER_MODEL` if your executor model name is
not already a valid Aider/LiteLLM model name.

See [Configuration](docs/CONFIGURATION.md) for provider variables and local
provider notes.

## Benchmarks

Controlled benchmark observations show that selected executor context can be
smaller than full-context baselines on selected fixtures, especially as project
context grows. Router-inclusive savings are lower because routing has its own
fixed cost.

These results are not a production guarantee, not a universal token-savings
claim, and not evidence that SFE should wrap every prompt. See
[Benchmarks](docs/BENCHMARKS.md) for the cautious summary.

## Documentation

- [Install](docs/INSTALL.md)
- [Usage](docs/USAGE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarks](docs/BENCHMARKS.md)
- [FAQ](docs/FAQ.md)
- [Documentation index](docs/INDEX.md)

## Current Status And Limitations

SFE is a practical public edition of an evolving local developer tool. The
current workflow is strongest for local repositories, explicit coding tasks,
and provider configurations you control.

Known limits:

- Aider is external and required for normal write execution.
- Provider quality and model compatibility vary by role.
- The router can add overhead on small tasks.
- Worktree isolation helps with review and promotion, but it is not a security
  sandbox.
- Benchmark observations are limited to selected fixtures and local runs.
