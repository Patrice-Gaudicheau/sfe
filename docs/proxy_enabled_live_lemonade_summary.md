# Proxy Enabled Live Lemonade Summary

This note summarizes the controlled local live Lemonade runner for proxy
`mode="enabled"`. The runner is narrow by design: it uses a local
Lemonade-compatible endpoint as both the router path and the enabled upstream
path, then verifies that the proxy sends the reduced request to Lemonade and
returns the reduced-path response to the client.

## What It Validates

- The proxy runs in `mode="enabled"`.
- A live local Lemonade-compatible router can select segments for a controlled
  multi-segment OpenAI-compatible request.
- The reduced candidate request is built from selected segment IDs.
- The reduced candidate request is sent to the Lemonade-compatible upstream.
- The original full request is not sent upstream, as indicated by enabled-mode
  diagnostics.
- The client receives a response from the reduced enabled path.
- The reduced request includes the expected useful segment, `segment-3`.
- The reduced request excludes unselected distractor markers when observable.
- Diagnostics record selected segment IDs, token estimates, reduction percent,
  routing status, and client response status.

## Scope Limits

This is still a controlled local validation. It does not test OpenAI or
Anthropic, does not expose the proxy to external clients, does not require
secrets, and does not claim production readiness. It also does not establish
statistical routing quality or production reliability.

## Configuration

The runner uses existing environment variables:

- `SFE_LEMONADE_BASE_URL`
- `SFE_ROUTER_MODEL`
- `SFE_EXECUTOR_MODEL`
- `SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS`

No `.env` file is required by the runner.

## Next Step

The next step is to repeat enabled-mode validation across a small controlled
fixture set, while keeping the same explicit safety checks before considering
broader provider or production-like proxy behavior.
