# Proxy Shadow Candidate Context Summary

This note summarizes the first controlled candidate-context runner for SFE proxy shadow mode. Candidate context means the reduced request/context that could be assembled from the shadow router selected segments if SFE activation were enabled later.

This is still not SFE-enabled execution. The reduced candidate context is built and inspected locally only. It is not sent to the upstream provider, and it does not change the client-visible response.

## What Was Validated

- A controlled OpenAI-compatible proxy shadow request runs with a mocked upstream.
- The default runner uses mocked Lemonade-compatible router behavior.
- The proxy remains in `mode="shadow"` with `shadow_router_dry_run=True`.
- The upstream receives the original full request unchanged.
- The client-visible response remains the mocked upstream response unchanged.
- The runner builds a reduced candidate context from selected segment IDs.
- The candidate context preserves the original user question.
- The candidate context contains the expected useful segment content.
- The candidate context excludes unselected distractor segment content.
- The runner reports full request and candidate context token estimates.

## Current Controlled Result

- Fixture: `tariff_policy_candidate_context`
- Expected useful segment: `segment-3`
- Selected segment IDs: `segment-3`
- Expected segment included: True
- Exact selection match: True
- Over-selected: False
- Full request estimated tokens: 1022
- Candidate context estimated tokens: 197
- Estimated reduction percent: 80.72
- Upstream request unchanged: True
- Client response unchanged: True

## What Remains Unvalidated

- SFE-enabled execution
- Sending reduced candidate requests to an upstream provider
- Answer quality under reduced context
- Production proxy behavior
- Statistical routing accuracy
- OpenAI or Anthropic proxy behavior
- Larger or noisier fixture sets
- Non-blocking shadow routing under slow router conditions

## Next Step

The next logical step is still not SFE-enabled execution. The next step should be to decide how candidate-context reporting should be hardened, including over-selection reporting, latency tracking, and non-blocking shadow execution semantics.
