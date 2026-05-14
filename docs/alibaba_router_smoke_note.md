# Alibaba Router Smoke Note

This note records a limited single-run Alibaba Model Studio router smoke test.
It is not a reliability benchmark, not a statistical routing result, and not a
production validation.

## Configuration

- Router provider/model: `alibaba-api` / `qwen3.6-flash`
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`
- Qwen thinking disabled: `true`

Thinking was disabled for Alibaba Qwen calls because prior connectivity checks
showed that leaving thinking enabled can add hidden reasoning tokens even for
trivial smoke prompts. Disabling thinking keeps this smoke more useful for token
accounting and cost sanity checks.

## High-Overlap Selector Smoke

The meaningful smoke result used the controlled high-overlap selector fixture:

- Fixture: `high_overlap_cassini_policy_exception_gate`
- Selected ID: `cassini-v31`
- Expected authoritative ID: `cassini-v31`
- Exact authoritative selection: `true`
- Honest selector pass: `true`
- Parse success: `true`
- Fallback used: `false`
- Provider error: `false`
- Router tokens: `745` input, `121` output, `866` total
- Latency: `2251 ms`

In this single run, `qwen3.6-flash` produced valid JSON and selected the
authoritative high-overlap document without fallback.

## Generic Effectiveness Smoke

A tiny generic effectiveness smoke also ran with Alibaba as both router and
executor. It produced valid router JSON and valid executor outputs. Its routing
correctness result is not meaningful for provider evaluation because the
deterministic task wording guard corrected the route from `writing` to
`planning`.

That run is useful only as a wiring check for Alibaba router/executor calls, not
as evidence of routing quality.
