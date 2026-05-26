# Spatial Field Engine for Cognition

**Context-governance infrastructure for long-context LLM workflows.**

Spatial Field Engine for Cognition (`SFE`) is open source context-governance
infrastructure for long-context LLM workflows. It separates context selection
from task execution: instead of sending every request as one large flat prompt,
SFE routes the task through a selector, exposes selected authoritative context
to the executor, and records the decision path for audit.

The commercial relevance is strongest where teams run repeated API-heavy
long-context workflows and need token-budget control, authority governance, and
auditable context selection. SFE may be useful when avoided context is large
enough to amortize routing overhead.

In protocol-aligned controlled observations on 50k+ structural-tier tasks, SFE
measured 84.08% router-inclusive token reduction with OpenAI, 83.63% with
Anthropic, and 83.57% in a single-run Alibaba/Qwen structural comparison. These
are controlled benchmark observations, not production savings commitments.

SFE does not claim to make a model more intelligent. The current project tests a
narrower engineering hypothesis: for some tasks, explicit workspace structure
and selective context activation can preserve measured task success while
reducing executor context and improving traceability.

The evidence in this repository is early, mostly synthetic, and
benchmark-specific. Treat the results as a research signal from a technical
prototype, not as proof of general model capability or production readiness.

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
- Provider integration and proxy research.
- Token budget control and context exposure reduction.
- Auditable routing decisions.
- Authority conflicts between documents, versions, policies, or governance
  sources.
- Provider-routing and context-budget policies.
- Enterprise assistant workflows where full-context prompting is expensive or
  hard to audit.

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

For the current canonical user-facing workflow, read
`docs/tui_v0_1_user_guide.md` and `docs/current_architecture_status.md`.

For the current high-overlap methodology, read
`docs/high_overlap_fixture_expansion_phase_close.md` and
`docs/high_overlap_diagnostic_bucketing_notes.md`.

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

- `sfe/`: core SFE helpers, including provider selection, LLM-driven workspace
  discovery, shared router-review plumbing, and Git Worktree workspace
  isolation.
- `cognitive_map/`: deterministic workspace scaffolding with zones, fragments, activation levels, and handoff rules.
- `router/`: mock and LLM-backed routing contracts that classify tasks and choose execution roles.
- `providers/`: minimal benchmark provider adapters, including Lemonade,
  OpenAI API, Alibaba/Qwen, and native Anthropic Messages API paths.
- `runtime/`: benchmark runners, report generation, logging, and smoke-test entry points.
- `sfe_tui/`: current canonical user-facing TUI path using `DirectBackend`.
- `sfe_proxy/`: standby experimental OpenAI-compatible local proxy retained for
  compatibility research, observability, and historical stress tests.

The current canonical TUI path uses `DirectBackend` and follows:

```text
/task <question>
/run
```

`/run` first asks the core execution-mode router how to resolve the task.
`console_output` produces a natural-language answer in the TUI with no Git
preparation, worktree, patch, or workspace mutation. `workspace_write` uses the
existing discovery, context-routing, executor, patch, and isolated worktree
pipeline for creating, modifying, or deleting workspace files. If the selected
workspace is not yet a Git repository, `workspace_write` can initialize a local
snapshot first; it does not create a remote, push, run syntax checks, run tests
or lint, require diff inspection, require human approval, or require router
review. `external_action` is recognized as outside-workspace work, but is not
implemented yet and fails cleanly. Historical and debug commands such as
`/discover`, `/dry-run`, `/patch`, `/apply-patch`, `/isolate`, and
`/review-worktree` remain available through `/help-advanced`.

SFE's current product doctrine is intentionally narrow: it is a context routing
and token reduction layer. It is meant to send the executor less context, but
better selected context, and to bound writes mechanically with Git/worktree
isolation when a workspace write is selected. It is not meant to make the model
smarter, replace code review, control every executor response, or require
mandatory diff inspection, human approval, syntax checks, tests, or lint before
the worktree apply step.

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
only after routing selected context. No proxy is used in the canonical TUI path.

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
including the TUI and standby proxy compatibility path.

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

Proxy tests remain available for standby/historical compatibility work, but
they are not the current user-facing smoke path.

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
be reported safely if the configured provider is unavailable. No proxy is used.
This read-only smoke uses advanced diagnostics; the canonical task path is
`/task <question>` followed by `/run`.

The full test suite can also be run from the repository root:

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp pytest -q
```

Under WSL, using a Linux temp directory avoids pytest capture issues when `TMP`
or `TEMP` point to `/mnt/c/...`.

## Provider Support

The current prototype has provider paths for OpenAI, Lemonade, Alibaba/Qwen,
and Anthropic. They do not all have identical maturity or API shape.

| Provider | Benchmark path | Standby proxy notes | Notes |
| --- | --- | --- | --- |
| OpenAI | `--executor openai-api` in large/contextual benchmarks and related OpenAI runners | Historical proxy support exists, but the proxy is not the current user path. | Uses OpenAI-compatible or direct OpenAI API configuration. Set `OPENAI_API_KEY`, `SFE_OPENAI_ROUTER_MODEL`, and `SFE_OPENAI_EXECUTOR_MODEL` for live benchmark runs. |
| Lemonade | `--executor lemonade` and historical/local benchmark runners | Historical proxy support exists, but the proxy is not the current user path. | Local OpenAI-compatible inference server path. Configure `SFE_LEMONADE_BASE_URL`, `SFE_ROUTER_MODEL`, and `SFE_EXECUTOR_MODEL` for local live runs. |
| Alibaba/Qwen | `--executor alibaba-api` and `runtime/run_alibaba_smoke.py` | Historical proxy support exists, but the proxy is not the current user path. | Uses Alibaba Model Studio / DashScope OpenAI-compatible Chat Completions. Configure `ALIBABA_API_KEY`, `ALIBABA_BASE_URL`, `SFE_ALIBABA_ROUTER_MODEL`, and `SFE_ALIBABA_EXECUTOR_MODEL` for benchmarks. Qwen thinking is disabled by default for benchmark token-accounting comparability. |
| Anthropic | `--executor anthropic` in large/contextual benchmarks | Historical proxy support exists, but the proxy is not the current user path. | Uses the native Anthropic Messages API path. Configure `ANTHROPIC_API_KEY`, `SFE_ANTHROPIC_ROUTER_MODEL`, and `SFE_ANTHROPIC_EXECUTOR_MODEL` for benchmarks. Large-context structural runs may require provider-call pacing because of input-token-per-minute limits. |

Proxy-specific variables remain in `.env.example` for historical and standby
work, but the proxy is not the recommended active path for TUI V0.1. For the
standby proxy, `SFE_PROVIDER` is the current provider selector;
`SFE_PROXY_PROVIDER` is a legacy proxy-only fallback.

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

## Live API Caution

Deterministic tests do not require an API key. Live OpenAI runners require
`OPENAI_API_KEY`; live Anthropic runners require `ANTHROPIC_API_KEY`; live
Alibaba/Qwen runners require `ALIBABA_API_KEY`. Keep secrets in a local `.env`
file and never commit them.

Generated benchmark reports should be written under `/tmp` or another
untracked local location. Some selected-vs-full comparison runner names do not
include `openai` even though they call OpenAI when the API key is present. Check
`docs/INDEX.md` before running live scripts.

Anthropic structural runs may require `--provider-call-delay-seconds` because
provider input-token-per-minute limits can affect execution timing.

## Proxy Standby Status

The proxy and Dockerized proxy path are currently in standby. The canonical
user-facing path is the SFE-aware TUI with `DirectBackend`; start with
`docs/tui_v0_1_user_guide.md`.

The proxy source code remains in `sfe_proxy/`, and historical proxy notes are
kept under `docs/history/proxy/`. That material is retained for compatibility
research, observability work, OpenAI-compatible request-shape experiments, and
possible future development. It should not be read as the recommended active
user workflow, production deployment guidance, or the canonical SFE interface.

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
`alibaba-api`, and `anthropic`:

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

Run one tiny Alibaba/Qwen smoke test when local credentials are configured:

```bash
python runtime/run_alibaba_smoke.py --model qwen3.6-flash
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

- `docs/INDEX.md`: recommended starting point and runner-category map for technical reviewers.
- `docs/tui_v0_1_user_guide.md`: current canonical SFE-aware TUI workflow.
- `docs/tui_apply_patch_design.md`: advanced/debug `/patch` -> `/apply-patch`
  write boundary and router-reviewed full-file replacement design, retained for
  compatibility rather than the primary `/run` workflow.
- `docs/current_architecture_status.md`: current boundary between the TUI
  canonical path and standby/experimental proxy infrastructure.
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
- `docs/router_contract.md`: router JSON contract.
- `reports/technical_report_v0_1/`: earlier Cognitive Map technical report.
- `sfe_white_paper.md`: original architecture proposal; more speculative than the current public README.

## Proxy Standby Direction

Future proxy work may resume later, but it is not part of the current V0.1
user-facing path. Any future activation should stay narrow: better
observability, clearer activation criteria, and safer provider-operation
boundaries. The current proxy remains standby/experimental infrastructure for
local integration research and controlled routing experiments.

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
- Dollar savings depend on provider pricing, model choice, input/output mix,
  cache policy, batch policy, and deployment policy.
- Broad production workloads, tool-using agents, multi-tenant systems, and
  long-running real user traffic are not validated yet.
