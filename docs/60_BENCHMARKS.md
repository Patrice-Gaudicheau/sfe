# Benchmarks

SFE includes benchmark runners and fixtures used to observe context selection,
token exposure, and routing overhead.

## Benchmark Summary

Protocol-aligned controlled observations across four context-intensity tiers.

| Tier | OpenAI selected reduction | OpenAI router-inclusive reduction | Anthropic selected reduction | Anthropic router-inclusive reduction | Alibaba/Qwen selected reduction | Alibaba/Qwen router-inclusive reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `standard` [2k-5k tokens] | 81.06% | 21.71% | 80.88% | 19.09% | 80.72% | 19.77% |
| `practical` [10k-20k tokens] | 88.17% | 63.40% | 88.05% | 62.01% | 88.00% | 62.29% |
| `high_context` [20k-50k tokens] | 91.11% | 73.38% | 91.02% | 72.02% | 90.98% | 72.34% |
| `structural` [50k+ tokens] | 94.16% | 84.08% | 93.94% | 83.63% | 94.11% | 83.57% |

Selected reduction means executor-visible context reduction. Router-inclusive
reduction includes selector/router overhead. Standard context shows router
overhead more clearly, while larger tiers show better amortization. The
structural row is a single live baseline-vs-spatial comparison in the source
benchmark summary. These are controlled observations, not statistical proof and
not production commitments.

The public takeaway is modest:

- selected executor context can be much smaller than full context on selected
  fixtures;
- router-inclusive savings are lower because routing has a fixed cost;
- larger context windows tend to amortize that routing cost better than small
  prompts;
- provider behavior varies by model and role.

These are controlled benchmark observations, not production guarantees.

## How To Read The Numbers

- Observed token reduction means a measured reduction in a specific run or
  selected fixture.
- Executor-visible reduction excludes router overhead.
- Router-inclusive reduction includes selector/router overhead.
- A small prompt may not benefit from SFE because the router call can cost more
  than the avoided context.

## Running A Small Check

Dry-run a benchmark without live provider calls:

```bash
python runtime/run_large_contextual_benchmark.py --dry-run --limit 1
```

Live provider benchmarks require the relevant API keys or local provider
servers. Treat live results as local observations and record the provider,
model, task tier, and command used.

## Public Claim Boundary

SFE does not claim universal token savings, general robustness, or production
safety. Benchmark results are useful for comparing selected fixtures and for
understanding when routing overhead is worth paying.
