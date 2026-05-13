# Proxy Enabled Mode Smoke Summary

This note summarizes a local controlled smoke runner for proxy `mode="enabled"`.
The runner validates enabled-mode mechanics with mocked upstream behavior and
provider-neutral mocked selection only. It does not call live providers and does
not claim production readiness.

## What It Validates

- `mode="enabled"` sends a reduced SFE candidate request to upstream.
- The original full request is not sent upstream in enabled mode.
- The client-visible response comes from the upstream response to the reduced
  request path.
- The reduced request preserves the user question.
- The reduced request includes the expected useful segment.
- The reduced request excludes unselected distractor segment content.
- Diagnostics include selected segment IDs, full request token estimate,
  reduced request token estimate, and estimated reduction percent.
- If no usable selected segment is available, enabled mode returns a controlled
  `422` response and does not silently send the original full request upstream.

## Current Fixture

The runner uses one controlled OpenAI-compatible multi-segment chat completion
request. The expected useful segment is `segment-3`, selected by local
provider-neutral selection. The upstream is mocked, and no OpenAI, Anthropic,
Lemonade, secrets, or `.env` configuration are required.

## Not Validated

- Live Lemonade, OpenAI, or Anthropic provider behavior.
- Answer quality under reduced context.
- Production latency, quota, retry, or reliability behavior.
- Statistical routing accuracy over larger fixture sets.

## Next Step

The next step is live provider validation for enabled mode, still with controlled
fixtures and explicit safety checks before considering broader production-like
proxy behavior.
