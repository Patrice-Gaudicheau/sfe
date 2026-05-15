# Proxy Shadow Dry-Run Enabled Comparison Summary

This note summarizes the first controlled dry-run enabled comparison runner for SFE proxy shadow mode. Dry-run enabled comparison means the runner builds the reduced request that SFE-enabled behavior might send later, but sends it only to a separate mocked experimental upstream for inspection.

This is still not real SFE-enabled client behavior. The original full request still goes to the normal mocked upstream, the client-visible response still comes from that normal upstream, and the reduced candidate request is never returned to the client.

## What Was Validated

- A controlled OpenAI-compatible proxy shadow request runs with mocked router behavior.
- The proxy remains in `mode="shadow"` with `shadow_router_dry_run=True`.
- The normal mocked upstream receives the original full request unchanged.
- The client-visible response comes from the normal mocked upstream unchanged.
- A reduced candidate request is built from selected segment IDs.
- The reduced candidate request is sent only to a second mocked experimental upstream.
- The experimental upstream response is not exposed to the client.
- The reduced candidate request contains the expected useful segment content.
- The reduced candidate request excludes unselected distractor segment content.
- Full request and reduced candidate request token estimates are reported.

## Current Controlled Result

- Fixture: `tariff_policy_dry_run_enabled_comparison`
- Expected useful segment: `segment-3`
- Selected segment IDs: `segment-3`
- Expected segment included: True
- Exact selection match: True
- Over-selected: False
- Full request estimated tokens: 1022
- Reduced candidate request estimated tokens: 268
- Estimated reduction percent: 73.78
- Normal upstream received original request: True
- Experimental upstream received reduced request: True
- Client response came from normal upstream: True
- Experimental response hidden from client: True
- Reduced request contains expected segment: True
- Reduced request excludes unselected segments: True

## What Remains Unvalidated

- Real SFE-enabled proxy behavior
- Replacing the upstream request in client-visible operation
- Answer quality under reduced context
- Production proxy behavior
- OpenAI or Anthropic proxy behavior
- Live Lemonade routing behavior for this comparison path
- Larger fixture sets and statistical routing accuracy
- Non-blocking shadow execution under slow router or experimental upstream conditions

## Next Step

This is the last safe comparison layer before considering actual SFE-enabled behavior. The next step should be an explicit design decision about activation semantics, including how reduced requests would be gated, how failures would fall back to the original request, and how latency or non-blocking behavior would be enforced.
