# Proxy Enabled Live Lemonade Multi-Fixture Summary

This note summarizes a controlled local live Lemonade runner for proxy
`mode="enabled"` across three fixtures. It uses a local Lemonade-compatible
endpoint as both the router and upstream path, with Qwen as the only configured
router/executor model for this phase.

## What It Validates

- The proxy runs in `mode="enabled"`.
- Live local Lemonade/Qwen routing is exercised across multiple controlled
  OpenAI-compatible multi-segment requests.
- The reduced candidate request is sent to the Lemonade-compatible upstream.
- The original full request is not sent upstream, as indicated by enabled-mode
  diagnostics.
- The client receives a successful response from the reduced enabled path.
- The reduced request includes the expected useful segment content.
- The reduced request excludes unselected distractor markers when observable.

## Interpretation

Expected useful-segment inclusion is the safety-relevant routing metric for this
runner. Exact selection is tracked separately as a precision and reduction
metric. Over-selection is also tracked separately and is not treated as a hard
failure when the expected useful segment is included and enabled-path checks
pass.

## Scope Limits

This is local validation only. It does not test OpenAI or Anthropic, does not
add Gemma or multi-model comparison, does not expose the proxy to external
clients, and does not claim production readiness. It also does not establish
statistical routing accuracy or production reliability.

An initial `incident_runbook` fixture was tried during development. It was
excluded from the committed runner after one live JSON run timed out on that
fixture. The timeout was treated as an incomplete live fixture result, not as a
successful enabled-mode validation and not as a hidden pass.

## Configuration

The runner uses existing environment variables:

- `SFE_LEMONADE_BASE_URL`
- `SFE_ROUTER_MODEL`
- `SFE_EXECUTOR_MODEL`
- `SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS`

No `.env` file is required by the runner.

## Next Step

The next step is to inspect live enabled-mode failures or over-selection
patterns before broadening fixture coverage or considering provider-specific
enabled-mode validation beyond local Lemonade/Qwen.
