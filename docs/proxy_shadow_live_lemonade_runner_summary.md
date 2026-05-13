# Proxy Shadow Live Lemonade Runner Summary

This phase validates a single controlled live Lemonade shadow-routing scenario
while preserving proxy transparency. It does not validate production
reliability, statistical routing accuracy, or SFE-enabled execution.

## Validated Mechanics

- Mocked upstream behavior.
- Real local Lemonade-compatible router endpoint.
- Proxy `mode="shadow"`.
- `shadow_router_dry_run=True`.
- OpenAI-compatible multi-segment request.
- Expected useful segment: `segment-3`.
- Unchanged upstream request.
- Unchanged client-visible response.
- Structured timeout and request-error diagnostics.
- Configurable timeout via `SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS`.

## Live Validation Results

`Qwen3.5-35B-A3B-GGUF`:

- Selected `segment-3`.
- Selection matched.
- Estimated token reduction pct: 80.4.
- Upstream request unchanged.
- Client response unchanged.

`Gemma-4-E4B-it-GGUF`:

- Selected `segment-3`.
- Selection matched.
- Estimated token reduction pct: 80.5.
- Upstream request unchanged.
- Client response unchanged.

## Not Validated Yet

- Multiple live fixtures.
- Live statistical routing accuracy.
- Latency comparison between models.
- Production proxy reliability.
- OpenAI or Anthropic proxy behavior.
- SFE-enabled execution.
- Non-blocking shadow routing behavior under slow router conditions.

## Next Step

The next logical step is a small live multi-fixture runner or model comparison
runner, still in shadow mode, before considering SFE-enabled proxy behavior.
