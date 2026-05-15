# Proxy Shadow Live Qwen Multi-Fixture Summary

This phase tests live Lemonade Qwen shadow routing across multiple controlled fixtures. It remains shadow-only, uses a mocked upstream, and does not enable SFE execution.

## Configuration

- Router model: `Qwen3.5-35B-A3B-GGUF`
- Router model configured through `SFE_ROUTER_MODEL`
- Lemonade-compatible local endpoint configured through `SFE_LEMONADE_BASE_URL`
- Timeout configured through `SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS`
- Proxy mode: `mode="shadow"`
- Shadow router dry run: `shadow_router_dry_run=True`

## Result Summary

- Fixtures: 4
- Expected inclusion accuracy: 100.00%
- Exact selection accuracy: 50.00%
- Over-selection count: 2
- Average selected segment count: 1.5
- Average estimated token reduction pct: 73.53
- Upstream transparency all passed: True
- Client response transparency all passed: True
- Runner exit code: 0

## Interpretation

Expected segment inclusion is the safety-relevant routing metric for this shadow runner. Exact selection is a precision and reduction metric.

Over-selection is not treated as a hard failure here. It reduces efficiency and may add noise, but it is different from omitting the useful segment. In this run, Qwen included the expected useful segment in every fixture.

## Per-Fixture Summary

- `tariff_policy`: expected `segment-3`, selected `segment-3` plus `segment-6`
- `incident_runbook`: expected `segment-2`, selected `segment-2`
- `compatibility_matrix`: expected `segment-4`, selected `segment-4`
- `billing_terms`: expected `segment-1`, selected `segment-1` plus `segment-4`

## Not Validated Yet

- Statistical routing accuracy
- Production reliability
- Non-blocking shadow routing under slow routers
- OpenAI or Anthropic proxy behavior
- SFE-enabled execution
- Larger or noisier fixture sets

## Next Step

The next logical step is not SFE-enabled yet. The next step should be to decide whether to harden shadow routing behavior, such as better over-selection reporting, latency tracking, or non-blocking shadow execution semantics.
