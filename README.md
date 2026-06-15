![SFE - Spatial Field Engine for Cognition](assets/202606152310_github.jpg)

# Spatial Field Engine for Cognition

[![AI-Coded: 95%+](https://img.shields.io/badge/AI--Coded-95%25%2B-111111?style=flat-square)](docs/ai-coded.md)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](pyproject.toml)
[![Status: experimental research](https://img.shields.io/badge/Status-experimental%20research-orange.svg)](#project-status)
[![Interface: TUI + MCP](https://img.shields.io/badge/Interface-TUI%20%2B%20MCP-6f42c1.svg)](#quick-start-tui-or-mcp)
[![Providers: multi--provider](https://img.shields.io/badge/Providers-multi--provider-0f766e.svg)](#provider-support)

**Context-routing and governance infrastructure for long-context LLM workflows.**

Spatial Field Engine for Cognition (`SFE`) is open-source infrastructure that separates context selection from task execution. Instead of sending every request as one large flat prompt, SFE routes the task, selects authoritative context, and exposes only that bounded context to the executor.

For technical founders, AI infrastructure teams, and research engineers running repeated API-heavy workflows, SFE provides:

- **Bounded Context Exposure:** Reduces repeated input-token exposure by selecting smaller, authoritative executor contexts.
- **Architectural Role Separation:** Splits Discoverer, Router, and Executor into independent roles, allowing distinct models for each.
- **Multi-Provider Workflows:** Mix and match OpenAI, Anthropic, Qwen, DeepSeek-compatible endpoints, Ollama, or Lemonade within a single workflow.
- **Dollar-Cost Optimization:** Treat cost as a model-allocation problem. Route with a strong reasoning model and execute with a smaller, cheaper, or specialized model.
- **Controlled Execution Surfaces:** Support local iterative workspace-write **loops** through a local TUI or integrate via the built-in MCP server.

*Note: SFE is an experimental research prototype. It does not claim to make models more intelligent, nor does it guarantee universal token savings. The evidence here is early, mostly synthetic, and benchmark-specific. Treat results as a technical prototype signal, not production readiness. See [Limitations](#limitations) for details.*

## Quick Start: TUI or MCP

Configure at least one provider before using the TUI or MCP server:

```bash
cp .env.example .env
```

Fill in at least one provider configuration in `.env`. `SFE_PROVIDER` is the
simplest starting point for local use. Advanced users can split runtime roles
with `SFE_PROVIDER_ROUTER`, `SFE_PROVIDER_DISCOVERY`, and
`SFE_PROVIDER_EXECUTOR`. See [Setup](#setup) and [Provider Support](#provider-support)
below for the provider-specific variables.

To start the local TUI:

```bash
make sfe-tui
```

Use this minimal workflow:

```text
Workspace: <enter the target workspace directory>
/task <describe what SFE should do>
/run
```

`Workspace` selects the target directory. `/task` defines the current task.
`/run` lets SFE route the task, select context, and execute the appropriate
mode. For write tasks, SFE uses its workspace-write path and mechanical
boundaries. For read-only or answer tasks, SFE can answer without mutating the
workspace.

For MCP clients, use the local SFE MCP server instead of the TUI. The current
client setup notes cover both
[Antigravity](docs/sfe_mcp_client_setup.md#antigravity-setup) and
[Codex App](docs/sfe_mcp_client_setup.md#codex-app-setup-with-the-form);
they also show the expected MCP tool flow and local STDIO process shape.

For the current product doctrine, start with `docs/sfe_product_doctrine.md`. In short: SFE core is the routing/context engine; the TUI is the current local user-facing control surface; patch/worktree is the developer execution mode inside `workspace_write`; benchmarks are the experimental evidence and architectural feedback loop.

## Core Engineering Signal

Across protocol-aligned OpenAI and Anthropic campaigns, selected-context
reduction patterns were nearly identical. A narrower Alibaba/Qwen replay also
completed selected benchmark families, including one live structural
baseline-vs-spatial comparison. Router-inclusive gains were modest on standard
context, then increased sharply as context grew.

The useful signal is the amortization pattern, not a claim of universal
activation. Structural 50k+ observations reached 84.08% OpenAI and 83.63%
Anthropic router-inclusive reduction, with a single-run Alibaba/Qwen structural
observation at 83.57%. These remain controlled benchmark observations.

## Why This Matters

Long-context LLM calls can waste budget by repeatedly sending irrelevant,
obsolete, partial, or non-authoritative context. SFE explores whether context
exposure can be reduced before execution while keeping source selection
auditable.

The same architecture can spend reasoning budget where it is most strategic:
on routing and context selection. Once the executor context is clean and
bounded, execution can often be delegated to a smaller, cheaper, or more
code-specialized model, subject to task difficulty and provider support. SFE
therefore attacks cost on two axes: input-token exposure reduction through
selected context, and output-token dollar-cost reduction through executor
model/provider choice.

The repository preserves full-context baseline comparisons, selected-context
executor runs, selector-only checks, and selected-vs-full comparisons. The
intended activation model is selective, not always-on: SFE is most relevant
when context size, authority conflicts, or audit requirements can justify the
routing overhead.

## Multi-Provider Performance Snapshot

Protocol-aligned controlled OpenAI, Anthropic, and Alibaba/Qwen observations
across four context-intensity tiers. Alibaba/Qwen `standard`, `practical`, and
`high_context` rows use `repeat=3`, `selection_mode=both`, and
`max_tokens=240`; the `structural` row remains a single live
baseline-vs-spatial comparison.

| Tier | OpenAI selected reduction | OpenAI router-inclusive reduction | Anthropic selected reduction | Anthropic router-inclusive reduction | Alibaba/Qwen selected reduction | Alibaba/Qwen router-inclusive reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `standard` [2k-5k tokens] | 81.06% | 21.71% | 80.88% | 19.09% | 80.72% | 19.77% |
| `practical` [10k-20k tokens] | 88.17% | 63.40% | 88.05% | 62.01% | 88.00% | 62.29% |
| `high_context` [20k-50k tokens] | 91.11% | 73.38% | 91.02% | 72.02% | 90.98% | 72.34% |
| `structural` [50k+ tokens] | 94.16% | 84.08% | 93.94% | 83.63% | 94.11% | 83.57% |

Selected reduction means executor-visible context reduction. Router-inclusive
reduction includes selector/router overhead. The standard tier shows router
overhead clearly; larger tiers show better amortization. Anthropic structural
required `600` seconds of provider-call pacing because of provider
input-token-per-minute limits. Alibaba/Qwen calls used the benchmark-only
Alibaba provider path with Qwen thinking disabled for usable token accounting;
the `standard`, `practical`, and `high_context` rows are repeat-3 observations,
while the `structural` row is a single live baseline-vs-spatial comparison, not
a repeat campaign.

These are controlled observations, not statistical proof and not production
commitments. See `docs/provider_comparison_summary.md` for the cross-provider
OpenAI/Anthropic summary, `docs/token_cost_metrics.md` for OpenAI token
accounting details, and `docs/alibaba_structural_50k_comparison_note.md` plus
`docs/alibaba_large_contextual_missing_tiers.md` and
`docs/alibaba_comparable_benchmark_runs.md` for the current Alibaba/Qwen
observations.

## Operational Relevance

SFE may be commercially relevant when avoided context is large enough to
amortize routing cost. Current areas of interest include:

- API-heavy long-context workflows.
- Provider integration research.
- Token budget control and context exposure reduction.
- Auditable routing decisions.
- Authority conflicts between documents, versions, policies, or governance
  sources.
- Provider-routing and context-budget policies.
- Enterprise assistant workflows where full-context prompting is expensive or
  hard to audit.

## Router/Executor Model Separation

SFE treats Discoverer, Router, and Executor as separate runtime roles rather
than assuming that every step must use one provider or one model. The Router is
the role where strong reasoning is usually most valuable, because a bad routing
or context-selection decision can dominate the rest of the run. The Discoverer
may not need to be as strong as the Router, depending on workspace structure,
metadata quality, and task type. The Executor can often be smaller, cheaper, or
more code-specialized when SFE has already narrowed the context to the files or
sources most likely to matter.

Router and Executor therefore do not need to share a provider. For example,
OpenAI can be configured for routing while Qwen, Ollama, Lemonade or
another supported specialized provider is configured for execution.
OpenAI-compatible providers such as DeepSeek may also fit this role when
supported by the local configuration. This cross-provider role split is a
distinctive architectural advantage relative to many LLM workflow tools that
bind selection and execution to one model path. It remains a design capability,
not a guarantee that every smaller executor model will preserve task quality.

## The Amortization Hypothesis

Routing has a fixed cost. SFE is not intended to activate on every prompt, and
short or simple prompts may not benefit. The project is most relevant when
avoided context is large enough, or when authority and audit requirements
justify routing.

Selective activation is therefore central to the design: context size,
authority-conflict density, token budget, and audit requirements should decide
when SFE is used.

## Who This Is For

- AI platform teams.
- LLM infrastructure architects.
- Teams building proxies or provider-routing systems.
- Teams operating API-heavy long-context workloads.
- Teams handling authority conflicts, policy documents, governance,
  compliance, or audit-sensitive assistant workflows.
- Technical investors evaluating context-governance infrastructure.

## Project Status

This repository is a technical prototype and experimental research-grade
infrastructure. It is open source under the Apache License 2.0. Forks,
benchmarks, integrations, issues, and pull requests are welcome when they follow
the project rules and keep claims grounded in the current evidence.

## License

SFE is open source under the Apache License 2.0. You may use, copy, modify,
distribute, fork, and build on the project under the terms of that license.

Commercial use is permitted under Apache-2.0. Paid support, consulting,
integration help, hosted deployments, or private enterprise work may be offered
separately, but they are not required for using, forking, modifying, or
distributing the project under the license.

This project is experimental research-grade infrastructure. It is provided
without warranties or production, safety, security, reliability, or fitness
claims. See `LICENSE` for the full license text.

## Contributions

Contributions are welcome. Please open issues or pull requests for bug fixes,
documentation improvements, benchmark additions, provider integrations, and
focused design changes.

By contributing, you agree that your contribution will be provided under the
Apache License 2.0. Contributions should include clear rationale, tests or
reproduction steps where practical, and must not add unsupported production,
safety, security, reliability, or fitness claims.

## Where To Start

New technical reviewers should start with `docs/INDEX.md`. It gives a compact
map of the benchmark families, runner categories, current high-overlap status,
and the recommended reading path.

For the current local user-facing workflow, read
`docs/sfe_product_doctrine.md`, `docs/tui_v0_1_user_guide.md`, and
`docs/current_architecture_status.md`.

For the current high-overlap methodology, read
`docs/high_overlap_diagnostic_bucketing_notes.md` and
`docs/high_overlap_history.md`.

## High-Overlap Fixture Status

The high-overlap fixture-expansion phase is complete for three authority-gap
fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

Their deterministic tests pass. Limited local OpenAI selector, executor, and
selected-vs-full comparison observations were clean for these fixtures, but
full-context execution also passed. The useful signal is controlled local
non-regression, not general reliability or a broad quality claim.

## Problem

Large prompts often mix user intent, constraints, background facts, distractors, prior decisions, and execution instructions in one context window. That can make runs harder to audit and can spend tokens on information that is irrelevant to the next model call.

SFE explores whether an external controller can:

- keep richer structured state outside the model prompt;
- activate only the zones needed for the current task;
- route work to a role/provider with an explicit contract;
- compare full-context baselines against reduced spatial execution payloads.

The tradeoff is that routing and orchestration have fixed costs. SFE only looks promising when context reduction or role separation can amortize that overhead.

## Architecture

At a high level, the current repository has these layers:

- `sfe/`: core SFE routing/context engine helpers, including provider
  selection, execution-mode routing, LLM-driven workspace discovery, bounded
  execution plumbing, validation support, and Git Worktree workspace isolation.
- `cognitive_map/`: deterministic workspace scaffolding with zones, fragments, activation levels, and handoff rules.
- `router/`: mock and LLM-backed routing contracts that classify tasks and choose execution roles.
- `providers/`: minimal benchmark provider adapters, including Lemonade,
  OpenAI API, Alibaba/Qwen, and native Anthropic Messages API paths.
- `runtime/`: benchmark runners, report generation, logging, and smoke-test entry points.
- `sfe_tui/`: current local user-facing TUI surface using `DirectBackend`.

SFE is not primarily a Git patch assistant. The current local TUI surface uses
`DirectBackend` and follows:

```text
/task <question>
/run
```

`/run` first asks the core execution-mode router how to resolve the task.
`console_output` produces a natural-language answer in the TUI with no Git
preparation, worktree, patch, or workspace mutation. `workspace_write` uses the
existing discovery, context-routing, Aider-backed filesystem executor, and
isolated worktree pipeline for creating, modifying, or deleting workspace
files. Aider is required for normal `workspace_write` execution and is not
vendored into SFE; install it externally and keep it on `PATH`. In all cases,
SFE enforces one safety boundary: every created, modified, or deleted path must
be inside the selected destination directory before changes are promoted. Aider
may create commits inside the SFE-controlled worktree, but SFE promotes only
the final validated file state back to the selected source destination; the
user source history does not receive Aider's micro-commits directly. If the
selected workspace is not yet a Git repository, `workspace_write` can
initialize a local snapshot first; it does not create a remote, push, run
syntax checks, run tests or lint, require diff inspection, require human
approval, or require router review. `external_action` is recognized as
outside-workspace work, but is not implemented yet and fails cleanly.
Historical and debug commands such as
`/discover`, `/dry-run`, `/patch`, `/apply-patch`, `/isolate`, and
`/review-worktree` remain available, but are hidden from the default help.

SFE's current product doctrine is intentionally narrow: it is a context routing
and token reduction layer. It is meant to send the executor less context, but
better selected context, and to bound writes mechanically with Git/worktree
isolation when a workspace write is selected. It is not meant to make the model
smarter, replace code review, control every executor response, or require
mandatory diff inspection, human approval, syntax checks, tests, or lint before
the worktree apply step.

### Aider Workspace Writer

Normal `workspace_write` execution uses Aider by default for both single-pass
and multi-pass runs. `SFE_WORKSPACE_WRITE_EXECUTOR` does not need to be set for
normal use. Set `SFE_WORKSPACE_WRITE_EXECUTOR=text` only for legacy/debug
rollback to the older `SFE_FILE` or strict Git-diff text transport.

Recommended Ubuntu, Debian, and WSL installation:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
exec $SHELL -l
pipx install aider-chat
aider --version
which aider
```

An executable such as `~/.local/bin/aider` is valid as long as it is on `PATH`.
The older `aider-install` bootstrap can still work as an alternative, but
`pipx install aider-chat` avoids common externally-managed Python environment
problems on Debian-family systems.

`SFE_AIDER_MODEL` is the explicit model override for Aider. When it is unset,
SFE resolves the executor provider from `SFE_PROVIDER_EXECUTOR`, then
`SFE_PROVIDER`, then the default `openai`, and uses the known-safe executor
model for that provider, such as `SFE_OPENAI_EXECUTOR_MODEL`,
`SFE_ANTHROPIC_EXECUTOR_MODEL`, or the current Google `SFE_GOOGLE_MODEL`. SFE
never falls back to router model settings for Aider; if no safe
Aider-compatible executor model can be selected, `workspace_write` fails closed
with a `missing_aider_model` diagnostic.

The architecture boundary is:

```text
Discoverer -> Router -> Executor
```

For TUI workspace-write context selection today, the Discoverer is core
workspace discovery in `sfe/discovery.py`, backed by the dedicated discovery
router in `sfe/discovery_router.py`. `/discover` scans the selected workspace,
builds a metadata-only workspace map, asks the configured discovery router which
files to inspect, and then locally revalidates selected paths before loading
them. The `/dry-run` context preview is still a provider-free local lexical
preview, and the Executor is the configured executor behind `DirectBackend`.
Separate router-review calls are used by the advanced `/apply-patch` and
`/review-worktree` flows; these are semantic LLM reviews, not formal security
proofs and are not mandatory for `/run`. `/discover` does not write files, run
shell commands, initialize Git, or expose raw file contents in diagnostics.
`/dry-run` still makes zero provider calls. `/ask` calls the configured executor
only after routing selected context.

Manual `/files` context loading remains available for debug/design work, but it
is not the normal human-facing TUI workflow.

The benchmark execution pattern remains:

1. Load a task and available context.
2. Route or select the relevant role/context block.
3. Build either a full baseline prompt or a reduced spatial prompt.
4. Execute through the configured provider.
5. Record token estimates, latency, routing validity, fallbacks, and task-specific success checks.

## Glossary

- Selector: the routing or selection step that chooses which source or context
  block should be exposed to execution.
- Executor: the model call that produces the final task answer from the
  selected or full context.
- Selected context: the bounded context exposed after selection, usually one
  authoritative source in the high-overlap fixtures.
- Full context: the complete fixture context, including authoritative and
  excluded or competing sources.
- Honest pass: a strict pass with no fallback, repair, provider error, parse
  failure, or disqualifying metadata.
- Diagnostic bucketing: mechanical failure categorization that keeps strict
  pass/fail unchanged while separating field extraction, evidence reference,
  contamination indicator, provider, parse, fallback, and repair failures.
- Contamination indicator: a mechanical signal such as copied excluded values,
  excluded-source citation, poison instruction following, or mixed
  authoritative and excluded evidence.
- Field extraction failure: a strict failure where the selected source may be
  correct but an exact required field is missing or wrong.
- Selection-induced error: a failure caused by selecting too little context, the
  wrong context, or a context block that omits information needed for the task.
- Local observation: a result from a local run in a specific environment; it is
  not a statistical or general reliability claim.

## Setup

This project is dependency-light and targets Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Copy `.env.example` to `.env` for local provider configuration. `.env` is ignored and must not be committed.
Use `SFE_PROVIDER` as the canonical provider selector for SFE surfaces,
including the TUI.
For SFE runtime roles, `SFE_PROVIDER_ROUTER` and `SFE_PROVIDER_EXECUTOR`
optionally override `SFE_PROVIDER`; when either is absent or blank, SFE falls
back to `SFE_PROVIDER` and then the surface default. Discovery routing can be
overridden separately with `SFE_PROVIDER_DISCOVERY`; blank or absent discovery
provider falls back to `SFE_PROVIDER_ROUTER`, then `SFE_PROVIDER`, then the
surface default. Discovery model variables are provider-specific, for example
`SFE_OPENAI_DISCOVERY_MODEL`, `SFE_LEMONADE_DISCOVERY_MODEL`, and
`SFE_CODEXCLI_DISCOVERY_MODEL`, and fall back to the existing router/shared
model variables when absent. Google discovery uses `SFE_GOOGLE_DISCOVERY_MODEL`
with `SFE_GOOGLE_MODEL` as its fallback. Ollama discovery uses
`SFE_OLLAMA_DISCOVERY_MODEL` with `SFE_OLLAMA_ROUTER_MODEL` and
`SFE_OLLAMA_MODEL` as fallbacks.

This role-level provider configuration is what enables Router/Executor model
separation: a strong router can be paired with a cheaper or more specialized
executor when the selected context is narrow enough and the configured provider
supports the required task.

## Minimal Verification

These commands do not require provider API keys:

```bash
python -m py_compile runtime/run_large_contextual_benchmark.py sfe/discovery.py sfe_tui/*.py
pytest tests/test_env_config.py -q
pytest tests/test_sfe_discovery.py -q
pytest tests/test_sfe_tui.py -q
pytest tests/test_large_contextual_benchmark.py -q
python runtime/run_large_contextual_benchmark.py --dry-run --limit 1
```

For the current repository-root read-only TUI smoke path:

```bash
make sfe-tui
```

Then accept the current workspace and run:

```text
/status
/task Explique en quelques phrases comment SFE_PROVIDER est résolu.
/discover
/dry-run
/context
/ask
/status
/quit
```

Expected observations are modest: `/discover` reports safe candidate metadata
and remains read-only, `/dry-run` reports `provider calls made: 0`, and `/ask`
requires a configured provider. With `SFE_PROVIDER=lemonade` and Lemonade
reachable, `/ask` can complete through `DirectBackend`. Provider errors should
be reported safely if the configured provider is unavailable. This read-only
smoke uses advanced diagnostics; the canonical task path is
`/task <question>` followed by `/run`.

For a local Ollama read-only smoke, start Ollama, pull the configured model,
and use the local provider:

```bash
ollama pull qwen3.5:4b
SFE_PROVIDER=ollama SFE_OLLAMA_MODEL=qwen3.5:4b make sfe-tui
```

The full test suite can also be run from the repository root:

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp pytest -q
```

Under WSL, using a Linux temp directory avoids pytest capture issues when `TMP`
or `TEMP` point to `/mnt/c/...`.

## Provider Support

The current prototype has provider paths for OpenAI, Lemonade, Alibaba/Qwen,
Anthropic, Google/Gemini, Ollama, and CodexCLI. They do not all have identical
maturity or API shape.

| Provider | Benchmark path | Notes |
| --- | --- | --- |
| OpenAI | `--executor openai-api` in large/contextual benchmarks and related OpenAI runners | Uses OpenAI-compatible or direct OpenAI API configuration. Set `OPENAI_API_KEY`, `SFE_OPENAI_ROUTER_MODEL`, and `SFE_OPENAI_EXECUTOR_MODEL` for live benchmark runs. |
| Lemonade | `--executor lemonade` and historical/local benchmark runners | Local OpenAI-compatible inference server path. Configure `SFE_LEMONADE_BASE_URL`, `SFE_ROUTER_MODEL`, and `SFE_EXECUTOR_MODEL` for local live runs. |
| Alibaba/Qwen | `--executor alibaba-api` and `runtime/run_alibaba_smoke.py` | Uses Alibaba Model Studio / DashScope OpenAI-compatible Chat Completions. Configure `ALIBABA_API_KEY`, `ALIBABA_BASE_URL`, `SFE_ALIBABA_ROUTER_MODEL`, and `SFE_ALIBABA_EXECUTOR_MODEL` for benchmarks. Qwen thinking is disabled by default for benchmark token-accounting comparability. |
| Anthropic | `--executor anthropic` in large/contextual benchmarks | Uses the native Anthropic Messages API path. Configure `ANTHROPIC_API_KEY`, `SFE_ANTHROPIC_ROUTER_MODEL`, and `SFE_ANTHROPIC_EXECUTOR_MODEL` for benchmarks. Large-context structural runs may require provider-call pacing because of input-token-per-minute limits. |
| Google/Gemini | `--executor google` in large/contextual and effectiveness-style benchmark runners, plus `runtime/run_google_smoke.py` | Uses Gemini's OpenAI-compatible Chat Completions endpoint. Configure `GOOGLE_API_KEY`, `SFE_GOOGLE_MODEL`, `SFE_GOOGLE_DISCOVERY_MODEL`, and `SFE_GOOGLE_BASE_URL` for live runs. Default model is `gemini-2.5-flash-lite`; absent or blank discovery model falls back to `SFE_GOOGLE_MODEL`, then the Google default. |
| Ollama | TUI/core provider roles and `runtime/run_ollama_smoke.py` | Local Ollama HTTP API provider for capable local machines and experimentation. Configure `SFE_PROVIDER=ollama`, `SFE_OLLAMA_BASE_URL`, and `SFE_OLLAMA_MODEL`. Default local endpoint is `http://localhost:11434`; the smoke-test model is `qwen3.5:4b`. Pull the model before use. This is a compatibility feature, not a performance claim. |
| CodexCLI | Benchmark internals may use `openai-codexcli` through `providers.codexcli.PROVIDER_NAME`. | Public SFE surfaces can use `SFE_PROVIDER=codexcli` or split roles with `SFE_PROVIDER_ROUTER`, `SFE_PROVIDER_DISCOVERY`, and `SFE_PROVIDER_EXECUTOR`. Model selection uses `SFE_CODEXCLI_ROUTER_MODEL`, `SFE_CODEXCLI_DISCOVERY_MODEL`, and `SFE_CODEXCLI_EXECUTOR_MODEL`; absent or blank discovery model falls back to the router model, then the CodexCLI router default. `SFE_CODEXCLI_ROUTER_EFFORT`, `SFE_CODEXCLI_DISCOVERY_EFFORT`, and `SFE_CODEXCLI_EXECUTOR_EFFORT` override `SFE_CODEXCLI_REASONING_EFFORT` for their respective roles; absent or blank discovery effort falls back to router effort, then the legacy shared value. CodexCLI can route `/run`, select discovery files from the workspace map, answer TUI console/read-only requests, and propose DEV patches as text only. SFE remains responsible for discovery path validation, patch parsing, validation, worktree isolation, application, and rejection. |

Full CodexCLI `/run` routing can be configured explicitly:

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=codexcli
SFE_PROVIDER_EXECUTOR=codexcli
SFE_CODEXCLI_DISCOVERY_MODEL="gpt-5.5"
SFE_CODEXCLI_DISCOVERY_EFFORT="high"
```

For long text-generation tasks, especially scaffold-style workspace writes,
the executor can use a longer idle supervision window without changing router or
discovery behavior:

```env
SFE_CODEXCLI_EXECUTOR_IDLE_TIMEOUT_SECONDS=900
```

This falls back to `SFE_PROVIDER_EXECUTOR_IDLE_TIMEOUT_SECONDS`, then
`SFE_PROVIDER_IDLE_TIMEOUT_SECONDS`, then the built-in provider idle default.
The setting only keeps a silent provider call alive longer. Normal
`workspace_write` uses the Aider-backed filesystem writer; the legacy text
transport is available only when `SFE_WORKSPACE_WRITE_EXECUTOR=text` is set for
debugging or rollback.

Large `workspace_write` scaffold tasks can use core multi-pass execution.
`SFE_WORKSPACE_WRITE_MULTIPASS=auto` enables a cautious heuristic for large
project/scaffold requests, `true` forces multi-pass for validation or testing,
and `false` preserves single-pass behavior. Multi-pass asks the Router for a
strict JSON batch plan, validates that plan before execution, then asks the
filesystem executor to make one batch of workspace changes with an explicit
`allowed_files` list. The default guardrails reject invalid plans, batches that
exceed a numeric `SFE_MULTIPASS_MAX_PASSES` cap when configured (`auto` by
default) or
`SFE_MULTIPASS_MAX_FILES_PER_PASS` (default `10`). `allowed_files` is planning
guidance and report metadata by default; actual changes that touch additional
files inside the destination directory are reported as warnings rather than
rejected. Any actual changed path outside the destination directory rejects the
run with a diagnostic listing the offending paths. This improves large scaffold
reliability but does not implement automatic resume after a failed pass; the
run report indicates whether a manual resume is plausible.

`SFE_MULTIPASS_PLANNER_MODEL` is deprecated and ignored. Multi-pass planning now
uses the configured Router provider/model, such as `SFE_PROVIDER_ROUTER`,
`SFE_OPENAI_ROUTER_MODEL`, `SFE_CODEXCLI_ROUTER_MODEL`, or another supported
Router model variable.

Google/Gemini discovery can be selected with `SFE_PROVIDER_DISCOVERY=google`
and optionally `SFE_GOOGLE_DISCOVERY_MODEL=<model-id>`.

Ollama can be selected for all TUI/core provider roles:

```bash
SFE_PROVIDER=ollama
SFE_OLLAMA_BASE_URL=http://localhost:11434
SFE_OLLAMA_MODEL=qwen3.5:4b
SFE_OLLAMA_THINK=false
```

Optional role model overrides are `SFE_OLLAMA_ROUTER_MODEL`,
`SFE_OLLAMA_DISCOVERY_MODEL`, and `SFE_OLLAMA_EXECUTOR_MODEL`. The selected
model must already be available locally, for example with
`ollama pull qwen3.5:4b`. `SFE_OLLAMA_THINK=false` is the default for SFE
Ollama calls so reasoning-capable local models spend their output budget on the
requested router or executor response. The optional live smoke is:

```bash
SFE_OLLAMA_LIVE_SMOKE=1 SFE_OLLAMA_MODEL=qwen3.5:4b pytest tests/test_ollama_smoke.py -q
python runtime/run_ollama_smoke.py --model qwen3.5:4b
```

Ollama troubleshooting:

- Server not running: start Ollama and verify `curl http://localhost:11434/api/tags`.
- Model not found: run `ollama pull <model>`, then retry with the same `SFE_OLLAMA_MODEL`.
- Slow responses: local models can be slow on CPU-only machines or small GPUs; increase `SFE_OLLAMA_TIMEOUT_SECONDS` if needed.
- WSL networking: when Ollama is installed inside WSL, `http://localhost:11434` is normally correct from the same WSL environment. If Ollama runs on Windows instead, ensure the Windows Ollama server is reachable from WSL and set `SFE_OLLAMA_BASE_URL` explicitly if localhost forwarding is not working.

Lemonade is used here as a local OpenAI-compatible inference server. Configure it with:

```bash
SFE_LEMONADE_BASE_URL=http://127.0.0.1:13305
SFE_ROUTER_MODEL=<local-router-model-id>
SFE_EXECUTOR_MODEL=<local-executor-model-id>
```

OpenAI API benchmarks are optional and require `OPENAI_API_KEY` plus explicit
`SFE_OPENAI_ROUTER_MODEL` and `SFE_OPENAI_EXECUTOR_MODEL` values that are
available to your account.

Anthropic API benchmarks are optional and require:

```bash
ANTHROPIC_API_KEY=<local-key>
ANTHROPIC_BASE_URL=https://api.anthropic.com
SFE_ANTHROPIC_ROUTER_MODEL=<anthropic-router-model-id>
SFE_ANTHROPIC_EXECUTOR_MODEL=<anthropic-executor-model-id>
```

Alibaba/Qwen benchmark runs are optional and require:

```bash
ALIBABA_API_KEY=<local-key>
ALIBABA_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
SFE_ALIBABA_ROUTER_MODEL=qwen3.6-flash
SFE_ALIBABA_EXECUTOR_MODEL=qwen3.6-plus
SFE_ALIBABA_DISABLE_THINKING=true
```

Google/Gemini benchmark runs are optional and require:

```bash
GOOGLE_API_KEY=
SFE_GOOGLE_MODEL=gemini-2.5-flash-lite
SFE_GOOGLE_DISCOVERY_MODEL=<google-discovery-model-id>
SFE_GOOGLE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

## Live API Caution

Deterministic tests do not require an API key. Live OpenAI runners require
`OPENAI_API_KEY`; live Anthropic runners require `ANTHROPIC_API_KEY`; live
Alibaba/Qwen runners require `ALIBABA_API_KEY`; live Google/Gemini runners
require `GOOGLE_API_KEY`; live Ollama smokes require a running local Ollama
server and a pulled local model. Keep secrets in a local `.env` file and never
commit them.

Generated benchmark reports should be written under `/tmp` or another
untracked local location. Some selected-vs-full comparison runner names do not
include `openai` even though they call OpenAI when the API key is present. Check
`docs/INDEX.md` before running live scripts.

Anthropic structural runs may require `--provider-call-delay-seconds` because
provider input-token-per-minute limits can affect execution timing.

## Benchmarks

Run the deterministic local benchmark:

```bash
python runtime/run_benchmark.py --router mock
```

Run the strict Lemonade effectiveness benchmark:

```bash
python runtime/run_effectiveness_benchmark.py \
  --executor lemonade \
  --router llm \
  --repeat 3 \
  --strict
```

Run the large/contextual fixture benchmark:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier standard --selection-mode fixture
```

Provider-backed large/contextual runs use the same runner with an explicit
executor. Current executor choices are `lemonade`, `openai-api`,
`alibaba-api`, `anthropic`, and `google`:

```bash
python runtime/run_large_contextual_benchmark.py \
  --executor alibaba-api \
  --task-tier standard \
  --selection-mode both \
  --repeat 3 \
  --max-tokens 240 \
  --provider-call-delay-seconds 1.0
```

Compare fixture and real-router selection:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier standard --selection-mode both
```

Run the practical 10k-20k tier:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier practical --selection-mode both --limit 1
```

Run the high_context 20k-50k tier:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier high_context --selection-mode both --limit 1
```

The `structural` 50k+ stress-test tier is also available. It remains a
stress-tier observation, but it is now included in the protocol-aligned OpenAI
and Anthropic multi-provider benchmark summaries. Use it to examine router
amortization, answer completeness, and provider execution constraints at larger
context sizes.

Build prompts and reports without provider calls:

```bash
python runtime/run_large_contextual_benchmark.py --dry-run --limit 1
```

Run the CodexCLI-only DEV/Patch output-token protocol without live provider
calls:

```bash
python runtime/run_codexcli_output_token_benchmark.py --dry-run --max-tasks 1
```

For the protocol, fixture reset command, safe one-task live commands, and
Campaign A/B model setup, see
`docs/history/providers/codexcli/codexcli_output_token_dev_patch_benchmark_protocol.md`.

Run one tiny Alibaba/Qwen smoke test when local credentials are configured:

```bash
python runtime/run_alibaba_smoke.py --model qwen3.6-flash
```

Run one tiny Google/Gemini smoke test when local credentials are configured:

```bash
python runtime/run_google_smoke.py --model gemini-2.5-flash-lite
```

Run the Cognitive Map deterministic micro-benchmark:

```bash
python runtime/run_cognitive_map_benchmark.py
```

Run the exploratory Lemonade-backed Cognitive Map comparison:

```bash
python runtime/run_cognitive_map_real_benchmark.py --model "$SFE_EXECUTOR_MODEL"
```

Generated logs, JSONL streams, SQLite files, and benchmark outputs are written under `logs/` by default and are ignored.

## Current Benchmark Signal

The strongest current cross-provider signal comes from protocol-aligned OpenAI
and Anthropic large/contextual campaigns. Both show nearly identical
selected-context reduction patterns, and both show router-inclusive savings
increasing with context size. Alibaba/Qwen now has repeat-3 `standard`,
`practical`, and `high_context` observations using the same large/contextual
fixtures, plus a separate single-run structural baseline-vs-spatial comparison.

Structural 50k+ observations are clean in the current controlled runs:

- OpenAI: 94.16% selected reduction and 84.08% router-inclusive reduction.
- Anthropic: 93.94% selected reduction and 83.63% router-inclusive reduction,
  with `600` seconds provider-call pacing for structural because of Anthropic
  input-token-per-minute limits.
- Alibaba/Qwen: 94.11% selected reduction and 83.57% router-inclusive
  reduction in one live structural baseline-vs-spatial comparison, with Qwen
  thinking disabled for token accounting.

Lemonade remains useful as a local-provider result and historical benchmark
path. It is no longer the only current headline for token-reduction behavior.

In the large/contextual benchmark, `spatial_fixture` means oracle-style
selection of the known relevant block and should be read as an upper bound on
executor context reduction. `spatial_router` means the selector chose the block
before execution. Executor context reduction excludes router cost;
router-inclusive or end-to-end reduction includes selector overhead.

These numbers are useful for deciding what to test next. They should not be
presented as general proof that SFE improves answer quality, reasoning, or
model intelligence.

## Documentation

- `docs/INDEX.md`: recommended starting point and documentation map for technical reviewers.
- `docs/sfe_product_doctrine.md`: current product doctrine and terminology.
- `docs/tui_v0_1_user_guide.md`: current local SFE-aware TUI workflow.
- `docs/tui_apply_patch_design.md`: advanced/debug `/patch` -> `/apply-patch`
  write boundary and router-reviewed full-file replacement design, retained for
  compatibility rather than the primary `/run` workflow.
- `docs/current_architecture_status.md`: current boundary between the SFE core,
  local TUI surface, patch/worktree mode, and provider integration.
- `docs/workspace_write_multipass.md`: multi-pass `workspace_write` mode for
  large scaffold generation, including configuration and report fields.
- `docs/aider_filesystem_executor_integration.md`: current Aider-backed
  `workspace_write` architecture, worktree promotion behavior, and legacy text
  fallback.
- `docs/aider_env_bridge.md`: secret-safe SFE-to-Aider environment bridge and
  model selection policy.
- `docs/provider_comparison_summary.md`: main cross-provider benchmark summary for protocol-aligned OpenAI and Anthropic campaigns.
- `docs/openai_paced_equivalent_summary.md`: OpenAI paced-equivalent campaign summary.
- `docs/anthropic_benchmark_paced_summary.md`: Anthropic paced campaign summary, including structural provider-call pacing.
- `docs/alibaba_structural_50k_comparison_note.md`: Alibaba/Qwen single-run structural baseline-vs-spatial comparison.
- `docs/alibaba_large_contextual_missing_tiers.md`: Alibaba/Qwen repeat-3 standard, practical, and high_context measurements.
- `docs/alibaba_comparable_benchmark_runs.md`: limited Alibaba/Qwen replay across selected benchmark families.
- `docs/public_release_technical_report.md`: public-facing technical report for the current release-readiness snapshot.
- `docs/large_contextual_benchmark_report.md`: detailed large/contextual benchmark notes.
- `docs/effectiveness.md`: preserved strict Lemonade effectiveness result.
- `docs/openai_validation_report.md`: direct OpenAI API validation summary for the large/contextual benchmark.
- `docs/token_cost_metrics.md`: fresh OpenAI all-tier token accounting and router-inclusive reduction summary.
- `docs/structural_benchmark_note.md`: exploratory structural 50k+ stress-test notes.
- `docs/openai_api_benchmark.md`: optional OpenAI API benchmark path.
- `docs/execution_mode_router_contract.md`: current `/run` execution-mode
  router contract.
- `reports/technical_report_v0_1/`: earlier Cognitive Map technical report.
- `sfe_white_paper.md`: original architecture proposal; more speculative than the current public README.

## Limitations

- The evidence remains benchmark-specific and controlled, not a production
  commitment.
- Repeat campaign sizes are still small relative to production workloads; these
  are not statistical proof.
- OpenAI and Anthropic token-reduction reproductions cover all four benchmark
  tiers, but task counts per tier remain limited. Alibaba/Qwen now has repeat-3
  `standard`, `practical`, and `high_context` metrics, but its `structural`
  figure remains a single-run comparison rather than a repeat campaign.
- Provider-specific rate limits can affect execution strategy.
- Anthropic structural required `600` seconds provider-call pacing because of
  Anthropic input-token-per-minute limits.
- High-overlap authority-gap fixtures validate routing, diagnostics, and local
  non-regression behavior, not broad real-world reliability.
- Selected-context execution did not outperform full-context execution in the
  latest new-fixture comparisons because full context also passed.
- SFE can introduce selection-induced errors if the selector chooses the wrong
  source or filters out required context.
- Router overhead can erase gains on short or simple prompts.
- Output-token savings are dollar-cost savings from executor model/provider
  choice, not guaranteed output-token count reduction.
- Dollar savings depend on provider pricing, selected models, output size,
  input/output mix, cache policy, batch policy, workload shape, and deployment
  policy.
- Broad production workloads, tool-using agents, multi-tenant systems, and
  long-running real user traffic are not validated yet.
