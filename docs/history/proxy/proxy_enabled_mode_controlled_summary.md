# Proxy Enabled Mode Controlled Summary

This note summarizes the first controlled implementation of proxy `mode="enabled"`.

Enabled mode now sends a reduced SFE candidate request to the configured upstream and returns that upstream response to the client. The original full client request is not sent upstream in enabled mode.

## Current Scope

- Implemented at the proxy layer, not in Lemonade-specific code.
- Provider-agnostic candidate request construction.
- Uses selected segment IDs from existing proxy selection diagnostics.
- Preserves the user question in the reduced request.
- Excludes unselected distractor segment content when the selected segment set is testable.
- Records selected segment IDs, full request token estimate, reduced request token estimate, and estimated reduction percent.
- Records that the enabled request was sent and the original request was not sent.

## Fallback Behavior

If no usable selected segment is available, enabled mode returns a controlled routing error and does not send the original full request upstream. This avoids silently pretending SFE reduction occurred.

## Validation Boundary

Current validation uses mocked upstreams and provider-neutral mocked routing/selection only. No OpenAI, Anthropic, or live Lemonade validation is included in this phase.

This is not a production-readiness claim. Live provider behavior, answer quality under reduced context, broader fixture coverage, latency behavior, and operational fallback policy still need separate validation.
