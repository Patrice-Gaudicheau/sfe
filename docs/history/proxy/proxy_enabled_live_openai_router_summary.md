# Proxy Enabled Live OpenAI Router Summary

This note summarizes the controlled single-fixture OpenAI router plus OpenAI
executor runner for proxy `mode="enabled"`. The runner is narrow and
cost-controlled: it uses one OpenAI-compatible multi-segment request, asks the
configured OpenAI router model to select useful segments, sends the reduced
request to the configured OpenAI executor model, and returns the reduced-path
response to the client.

## What It Validates

- The proxy runs in `mode="enabled"`.
- The OpenAI router provider is used for live segment selection.
- The expected useful segment is `segment-3`.
- The reduced candidate request is built from the router-selected segments.
- The reduced request is sent to OpenAI as the upstream executor path.
- The original full request is not sent upstream, as indicated by enabled-mode
  diagnostics.
- The client receives a response from the reduced enabled path.
- Diagnostics record selected segment IDs, full and reduced request token
  estimates, estimated reduction percent, router status, executor status, and
  client response status.

## Configuration

The runner uses existing environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `SFE_OPENAI_ROUTER_MODEL`
- `SFE_OPENAI_EXECUTOR_MODEL`

Secret values must not be printed, and `.env` must remain ignored and
uncommitted.

## Scope Limits

This is a controlled local validation only. It does not test Anthropic, does
not test Lemonade, does not run multiple OpenAI fixtures, does not expose the
proxy to external clients, and does not claim production readiness. It also
does not establish production latency, quota, retry, or statistical routing
behavior.

## Next Step

The next step is to inspect the single-fixture OpenAI router result before
considering any multi-fixture OpenAI enabled-mode runner.
