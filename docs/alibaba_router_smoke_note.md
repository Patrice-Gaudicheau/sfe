# Alibaba Router Smoke Note

This note records a limited Alibaba Model Studio router smoke test. It is not a
reliability benchmark, not a statistical routing result, and not a production
validation.

## Configuration

- Router provider/model: `alibaba-api` / `qwen3.6-flash`
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`
- Qwen thinking disabled: `true`

Thinking was disabled for Alibaba Qwen calls because prior connectivity checks
showed that leaving thinking enabled can add hidden reasoning tokens even for
trivial smoke prompts. Disabling thinking keeps this smoke more useful for token
accounting and cost sanity checks.

## High-Overlap Selector Smoke

The meaningful smoke result used the controlled high-overlap selector fixture
with three repeated selector-only calls:

- Fixture: `high_overlap_cassini_policy_exception_gate`
- Expected authoritative ID: `cassini-v31`
- Run count: `3`
- Honest selector pass count: `3/3`
- Parse failure count: `0`
- Fallback count: `0`
- Provider error count: `0`
- Total token range: `824` to `878`
- Latency range: `1720 ms` to `2102 ms`

Per-run results:

| Run | Selected ID | Exact authoritative | Honest pass | Input tokens | Output tokens | Total tokens | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `cassini-v31` | `true` | `true` | `745` | `79` | `824` | `1721` |
| 2 | `cassini-v31` | `true` | `true` | `745` | `79` | `824` | `1720` |
| 3 | `cassini-v31` | `true` | `true` | `745` | `133` | `878` | `2102` |

Across these three limited calls, `qwen3.6-flash` produced valid JSON and
selected the authoritative high-overlap document without fallback. This is still
only a small smoke signal; it should not be treated as a reliability estimate.

## Generic Effectiveness Smoke

A tiny generic effectiveness smoke also ran with Alibaba as both router and
executor. It produced valid router JSON and valid executor outputs. Its routing
correctness result is not meaningful for provider evaluation because the
deterministic task wording guard corrected the route from `writing` to
`planning`.

That run is useful only as a wiring check for Alibaba router/executor calls, not
as evidence of routing quality.
