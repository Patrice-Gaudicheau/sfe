# Proxy Enabled Live OpenAI Summary

This note summarizes the controlled single-fixture OpenAI runner for proxy
`mode="enabled"`. The runner is narrow and cost-controlled: it uses one
OpenAI-compatible multi-segment request, deterministic provider-neutral segment
selection, and OpenAI only as the live enabled upstream/executor path.

## What It Validates

- The proxy runs in `mode="enabled"`.
- The reduced candidate request is sent to OpenAI as the upstream path.
- The original full request is not sent upstream, as indicated by enabled-mode
  diagnostics.
- The client receives a response from the reduced enabled path.
- The reduced request includes the expected useful segment, `segment-3`.
- The reduced request excludes unselected distractor markers when observable.
- Diagnostics record selected segment IDs, full and reduced request token
  estimates, estimated reduction percent, routing status, and client response
  status.

## Routing Scope

This runner uses provider-neutral deterministic selection for routing and
records that explicitly. `SFE_OPENAI_ROUTER_MODEL` is reported when configured,
but it is not used as a live OpenAI router in this runner. Live OpenAI routing
is covered by the separate OpenAI router plus executor enabled-mode runner.

## Scope Limits

This is a controlled local validation only. It does not test Anthropic, does
not run multiple OpenAI fixtures, does not expose the proxy to external clients,
and does not claim production readiness. It also does not establish production
latency, quota, retry, or statistical routing behavior.

## Configuration

The runner uses existing environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `SFE_OPENAI_API_TIMEOUT`
- `SFE_OPENAI_ROUTER_MODEL`
- `SFE_OPENAI_EXECUTOR_MODEL`

No `.env` file is required by the runner, and secret values must not be printed.

## Next Step

The next step is to inspect the single-fixture OpenAI result alongside the
separate OpenAI router plus executor result before considering any multi-fixture
OpenAI enabled-mode runner.
