# Benchmarks

SFE includes benchmark runners and fixtures used to observe context selection,
token exposure, and routing overhead.

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
