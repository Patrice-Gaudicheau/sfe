<p align="center">
  <img src="assets/202606152310_github.jpg" alt="Spatial Field Engine">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="docs/30_USAGE.md"><img src="https://img.shields.io/badge/Interface-TUI%20%2B%20MCP-6f42c1.svg" alt="Interface: TUI + MCP"></a>
</p>

<p align="center">
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-OpenAI-412991?style=flat-square" alt="Provider: OpenAI"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-Anthropic-D97757?style=flat-square" alt="Provider: Anthropic"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-Google-4285F4?style=flat-square" alt="Provider: Google"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-Alibaba-FF6A00?style=flat-square" alt="Provider: Alibaba"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-Ollama-111111?style=flat-square" alt="Provider: Ollama"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-Lemonade-F59E0B?style=flat-square" alt="Provider: Lemonade"></a>
  <a href="docs/40_CONFIGURATION.md"><img src="https://img.shields.io/badge/Provider-CodexCLI-334155?style=flat-square" alt="Provider: CodexCLI"></a>
</p>

SFE is a context-routing layer for AI-assisted coding. It selects relevant project context, routes execution modes, and isolates filesystem changes in Git worktrees before promotion.

Instead of sending broad project context into every coding call, SFE narrows the
executor prompt to the files and constraints that matter for the current task.
On selected benchmark fixtures, SFE **reduced executor input tokens by up to 90%**
compared with full-context baselines.

Second, **output-token** cost can be lowered by delegating execution to a **cheaper model** or more specialized model once the context is already narrow. Savings depend on
task shape, provider behavior, and model choices.

## What SFE Does

- Builds a compact project map and selects task-relevant files.
- Routes a task to read-only answers, isolated code changes, or safe refusal when the request is outside the local workspace.
- Runs write tasks in isolated Git worktrees before promoting changes.
- Uses Aider as the default external writer for normal `workspace_write` runs.
- Exposes the same runtime through a local TUI and an MCP server.

## Why Not Just Run Aider Directly?

Aider is the writer. SFE is the routing and guard layer around it.

Aider already has its own repository map and token controls. SFE does not replace
that. It adds a pre-execution layer that selects task-specific context, chooses
the execution mode, and prepares an isolated Git worktree before Aider writes.

Run Aider directly when you already know the files, scope, and write mode. Use
SFE when you want context selection, model-role separation, read/write routing,
isolated filesystem changes, and a compact run report before deciding what to
keep.

## Quick Install

Requirements:

- Python 3.10+
- Git
- Aider for normal write runs: `pipx install aider-chat`

```bash
git clone https://github.com/Patrice-Gaudicheau/sfe.git
cd sfe
make install
make doctor
make sfe-tui
```

`make install` installs SFE locally in `.venv` with `pip install -e .`. It
reuses an existing `.venv`, creates `.env` from `.env.example` when needed, and
never overwrites an existing `.env`. If Aider is missing, the installer can
install it with `pipx install aider-chat` after confirmation, or you can run
that command manually. Makefile targets use the project virtualenv automatically.

Manual local install:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Activating `.venv` is optional when you use the Makefile targets. Use it only
when running Python commands directly.

## First Run

Configure a provider by editing `.env`, uncommenting one `SFE_PROVIDER`, and
filling the required key or local provider URL. `make doctor` reports whether a
provider appears configured.

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

- write tasks run through the isolated `workspace_write` path;
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

For Aider-backed writes, set `SFE_AIDER_PROVIDER` when SFE itself uses
`codexcli`; Aider cannot use CodexCLI as its LLM backend. Set
`SFE_AIDER_MODEL` when your executor model name is not already a valid
Aider/LiteLLM model name, for example `openai/Gemma-4-E4B-it-GGUF` for
Lemonade.

See [Configuration](docs/40_CONFIGURATION.md) for provider variables and local
provider notes.

## Benchmarks

Controlled benchmark observations show that selected executor context can be
smaller than full-context baselines on selected fixtures, especially as project
context grows. Router-inclusive savings are lower because routing has its own
fixed cost.

These results are not a production guarantee, not a universal token-savings
claim, and not evidence that SFE should wrap every prompt. See
[Benchmarks](docs/60_BENCHMARKS.md) for the cautious summary.

## Documentation

- [Install](docs/20_INSTALL.md)
- [Usage](docs/30_USAGE.md)
- [Configuration](docs/40_CONFIGURATION.md)
- [Architecture](docs/50_ARCHITECTURE.md)
- [Benchmarks](docs/60_BENCHMARKS.md)
- [FAQ](docs/70_FAQ.md)
- [Documentation index](docs/10_INDEX.md)

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
