# Spatial Field Engine for Cognition

Spatial Field Engine for Cognition (`sfe`) is a Python prototype for experimenting with external workspace structure around LLM calls. It keeps task state in named zones, routes each task to a role/provider, and sends a bounded execution payload instead of always sending one large, flat prompt.

SFE does not claim to make a model more intelligent. The current project tests a narrower engineering hypothesis: for some tasks, explicit workspace structure and selective context activation can preserve measured task success while reducing executor context and improving traceability.

The evidence in this repository is early, mostly synthetic, and benchmark-specific. Treat the results as a research signal from a technical prototype, not as proof of general model capability or production readiness.

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
| `standard` | 2k-5k tokens | about 81% | 7 synthetic tasks; fixture and router modes available. |
| `practical` | 10k-20k tokens | about 88% | Early long-context tier for router-cost amortization checks. |
| `high_context` | 20k-50k tokens | about 91% | 2 synthetic tasks; clean 64K Lemonade runs only. |

Router-inclusive savings are lower because the router consumes tokens and latency. In the clean high_context Lemonade result, executor input reduction was about 90.98%, while router-plus-executor total token reduction was about 72.8%.

The strict mixed-task effectiveness benchmark in `docs/effectiveness.md` preserves an additional Lemonade result: 27.89% mean total token savings overall, 21.40% mean total token savings on successful pairs only, 100% router success, 100% JSON validity, and 100% routing accuracy on the current small task set.

These numbers are useful for deciding what to test next. They should not be presented as general proof that SFE improves answer quality, reasoning, or model intelligence.

## Documentation

- `docs/public_release_technical_report.md`: public-facing technical report for the current release-readiness snapshot.
- `docs/large_contextual_benchmark_report.md`: detailed large/contextual benchmark notes.
- `docs/effectiveness.md`: preserved strict Lemonade effectiveness result.
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

## Release Status

This repository is being prepared for a future public GitHub release. Do not treat the current branch as publication approval, and do not push or make the repository public without an explicit release decision.
