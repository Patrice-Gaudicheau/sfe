# Spatial Field Engine for Cognition

Spatial Field Engine for Cognition (`sfe`) is a Python prototype for experimenting with external workspace structure around LLM calls. It keeps task state in named zones, routes each task to a role/provider, and sends a bounded execution payload instead of always sending one large, flat prompt.

SFE does not claim to make a model more intelligent. The current project tests a narrower engineering hypothesis: for some tasks, explicit workspace structure and selective context activation can preserve measured task success while reducing executor context and improving traceability.

The evidence in this repository is early, mostly synthetic, and benchmark-specific. Treat the results as a research signal from a technical prototype, not as proof of general model capability or production readiness.

## Project Status

This repository is currently a technical prototype. It is source-available, not open source. Pull requests are not currently accepted. Forks are allowed for non-commercial research and experimentation under the PolyForm Noncommercial License 1.0.0.

SFE targets a practical infrastructure problem: long-context LLM calls can
become expensive when every request is sent as one flat prompt. SFE separates
source selection from execution so that, when activated selectively, the
executor can receive a smaller authoritative context. In the fresh local OpenAI
all-tier reproduction, router-inclusive token reduction increased from 21.82%
on the standard [2k-5k] tier to 84.08% on the structural [50k+] tier. These are
controlled observations, not guaranteed savings.

## Licensing

SFE is published as a source-visible project under the PolyForm Noncommercial License 1.0.0.

SFE encourages exploration, research, evaluation, learning, and small-scale experimentation by individuals, researchers, and small teams under its non-commercial terms.

Commercial deployment, hosted services, enterprise integration, API cost optimization at scale, token-saving infrastructure use, or incorporation into commercial products requires a separate commercial license.

For details, see `COMMERCIAL_LICENSE.md`.

## Contributions

Public feedback is welcome through issues or other public discussion channels.

Pull requests are not currently accepted.

Forks for non-commercial research and experimentation are allowed under the license.

## Where To Start

New technical reviewers should start with `docs/INDEX.md`. It gives a compact
map of the benchmark families, runner categories, current high-overlap status,
and the recommended reading path.

For the current high-overlap methodology, read
`docs/high_overlap_fixture_expansion_phase_close.md` and
`docs/high_overlap_diagnostic_bucketing_notes.md`.

## Current Private Benchmark Status

The high-overlap fixture-expansion phase is complete for three additional
authority-gap fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

Their deterministic tests pass. Limited local OpenAI selector, executor, and
selected-vs-full comparison observations were clean for these fixtures: no
contamination indicators were observed in those local runs, and full-context
execution also passed. Selected-context execution therefore did not outperform
full-context execution in those observations. The useful signal is local
non-regression under controlled conditions, not general reliability.

## Economic Fit

SFE is most relevant to long-context developer workflows, documentation and
knowledge-base analysis, policy or governance workflows with authority
conflicts, high-volume API usage where token budgets matter, and systems that
need auditable context selection before execution.

SFE is not a cost-saving silver bullet. It is most relevant when context is
large enough, or authority conflicts are dense enough, for routing overhead to
be amortized. This repository remains a private technical prototype, not a
production-ready product.

## Problem

Large prompts often mix user intent, constraints, background facts, distractors, prior decisions, and execution instructions in one context window. That can make runs harder to audit and can spend tokens on information that is irrelevant to the next model call.

SFE explores whether an external controller can:

- keep richer structured state outside the model prompt;
- activate only the zones needed for the current task;
- route work to a role/provider with an explicit contract;
- compare full-context baselines against reduced spatial execution payloads.

The tradeoff is that routing and orchestration have fixed costs. SFE only looks promising when context reduction or role separation can amortize that overhead.

## Architecture

At a high level, the current repository has four layers:

- `cognitive_map/`: deterministic workspace scaffolding with zones, fragments, activation levels, and handoff rules.
- `router/`: mock and LLM-backed routing contracts that classify tasks and choose execution roles.
- `providers/`: minimal provider adapters, including Lemonade and OpenAI-compatible paths.
- `runtime/`: benchmark runners, report generation, logging, and smoke-test entry points.

The main execution pattern is:

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

Lemonade is used here as a local OpenAI-compatible inference server. Configure it with:

```bash
SFE_LEMONADE_BASE_URL=http://127.0.0.1:13305
SFE_ROUTER_MODEL=<local-router-model-id>
SFE_EXECUTOR_MODEL=<local-executor-model-id>
```

OpenAI API benchmarks are optional and require `OPENAI_API_KEY` plus explicit `SFE_OPENAI_ROUTER_MODEL` and `SFE_OPENAI_EXECUTOR_MODEL` values that are available to your account.

## Live API Caution

Deterministic tests do not require an API key. Live OpenAI runners require
`OPENAI_API_KEY`; keep it in a local `.env` file and never commit it.

Generated benchmark reports should be written under `/tmp` or another
untracked local location. Some selected-vs-full comparison runner names do not
include `openai` even though they call OpenAI when the API key is present. Check
`docs/INDEX.md` before running live scripts.

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

An exploratory `structural` 50k+ stress-test tier is also available. It is
documented separately because it is intended to expose routing and answer
completeness limits rather than extend the main validation curve; see
`docs/structural_benchmark_note.md`.

Build prompts and reports without calling Lemonade:

```bash
python runtime/run_large_contextual_benchmark.py --dry-run --limit 1
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

The strongest current signal is context reduction on synthetic large/contextual tasks:

| Tier | Approximate baseline context | Observed executor input reduction | Notes |
| --- | ---: | ---: | --- |
| `standard` [2k-5k] | 2k-5k tokens | about 81% | 7 synthetic tasks; fixture and router modes available. |
| `practical` [10k-20k] | 10k-20k tokens | about 88% | Early long-context tier for router-cost amortization checks. |
| `high_context` [20k-50k] | 20k-50k tokens | about 91% | 2 synthetic tasks; clean 64K Lemonade runs only. |

Router-inclusive savings are lower because the router consumes tokens and latency. In the clean high_context Lemonade result, executor input reduction was about 90.98%, while router-plus-executor total token reduction was about 72.8%.

## Current OpenAI Token Reduction Signal

The strongest current OpenAI economic signal is router-inclusive token
reduction on larger context tiers. The standard tier still saves tokens, but
router overhead is much more visible. This supports selective activation rather
than always-on routing.

Fresh local OpenAI reproduction across four context-intensity tiers.
Router-inclusive reduction includes both selector and executor calls.

| Tier | Baseline scope | Executor input reduction | Router-inclusive token reduction | Note |
| --- | --- | ---: | ---: | --- |
| `standard` [2k-5k] | 2k-5k tokens | 81.06% | 21.82% | Router overhead remains visible at this size. |
| `practical` [10k-20k] | 10k-20k tokens | 88.17% | 63.54% | Stronger amortization signal. |
| `high_context` [20k-50k] | 20k-50k tokens | 91.11% | 73.35% | Larger avoided executor context. |
| `structural` [50k+] | 50k+ tokens | 94.16% | 84.08% | Stress-tier result; interpret separately from the clean curve. |

These are local OpenAI observations on controlled fixtures, not statistical
proof or guaranteed cost savings. See `docs/token_cost_metrics.md` for token
accounting, caveats, and the cost-relevant input/output breakdown.

A first direct OpenAI API validation reused the same large/contextual fixtures and reporting logic. In four small router-inclusive synthetic runs, executor input reduction ranged from 81.60% to 91.13%, router-inclusive total token reduction ranged from 15.06% on the standard task to about 73.6% on the two high_context tasks, and the router selected the expected block with zero fallbacks. See `docs/openai_validation_report.md`.

The strict mixed-task effectiveness benchmark in `docs/effectiveness.md` preserves an additional Lemonade result: 27.89% mean total token savings overall, 21.40% mean total token savings on successful pairs only, 100% router success, 100% JSON validity, and 100% routing accuracy on the current small task set.

In the large/contextual benchmark, `spatial_fixture` means oracle-style selection of the known relevant block and should be read as an upper bound on executor context reduction. `spatial_router` means the selector chose the block before execution. Executor context reduction excludes router cost; router-inclusive or end-to-end reduction includes selector overhead.

These numbers are useful for deciding what to test next. They should not be presented as general proof that SFE improves answer quality, reasoning, or model intelligence.

## Documentation

- `docs/INDEX.md`: recommended starting point and runner-category map for technical reviewers.
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

## Limitations

- The evidence is early and mostly synthetic.
- Task sets are small and deterministic.
- Several results depend on a local Lemonade server and specific local model availability.
- Fixture selection is an oracle upper bound for context reduction, not proof that a router can always find the right block.
- Real-router results are encouraging but still small.
- Scoring is mostly heuristic and task-specific.
- Router cost can erase gains on short or simple prompts.
- The project does not yet validate broad generalization across providers, model families, tool use, real user workloads, or adversarial retrieval settings.

## Development Checks

Run the test suite from the repository root:

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp pytest -q
```

Under WSL, using a Linux temp directory avoids pytest capture issues when `TMP` or `TEMP` point to `/mnt/c/...`.
