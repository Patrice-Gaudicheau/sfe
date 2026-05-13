# Proxy Enabled Live OpenAI Router Multi-Fixture Summary

This note summarizes the controlled mini multi-fixture OpenAI router plus
OpenAI executor runner for proxy `mode="enabled"`. The runner is narrow and
cost-controlled: it uses three OpenAI-compatible multi-segment fixtures, asks
the configured OpenAI router model to select useful segments, sends each
reduced request to the configured OpenAI executor model, and returns the
reduced-path response to the client.

## What It Validates

- The proxy runs in `mode="enabled"`.
- The OpenAI router model is used for live segment selection.
- The OpenAI executor model receives the reduced request.
- The original full request is not sent upstream, as indicated by enabled-mode
  diagnostics.
- The client receives a response from the reduced enabled path.
- Diagnostics record selected segment IDs, full and reduced request token
  estimates, estimated reduction percent, router status, executor status, and
  client response status.

## Interpretation

Expected useful-segment inclusion is the safety-relevant routing metric for
this runner. Exact selection is tracked separately as a precision and reduction
metric. Over-selection is recorded but is not treated as a hard failure when
the expected useful segment is included, because over-selection preserves the
required context while reducing efficiency and potentially adding noise.

## Scope Limits

This is a controlled local validation only. It is not a broad benchmark, does
not test Anthropic, does not test Lemonade, does not compare models, does not
expose the proxy to external clients, and does not claim production readiness.
It also does not establish production latency, quota, retry, or statistical
routing behavior.

## Configuration

The runner uses existing environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `SFE_OPENAI_API_TIMEOUT`
- `SFE_OPENAI_ROUTER_MODEL`
- `SFE_OPENAI_EXECUTOR_MODEL`

Secret values must not be printed, and `.env` must remain ignored and
uncommitted.

## Next Step

The next step is to inspect the mini-run results before considering any larger
OpenAI enabled-mode benchmark or provider comparison.
