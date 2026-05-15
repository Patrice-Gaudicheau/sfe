# Proxy Enabled Mode Milestone Summary

SFE proxy now has a complete staged mode progression: `shadow`,
`dry_run_enabled`, and `enabled`. In `enabled` mode, the proxy now sends the
reduced SFE candidate request upstream and returns the upstream response from
that reduced path to the client.

## Mode Semantics

- `shadow`: observes routing and selection metadata while preserving the
  original upstream request and client-visible response.
- `dry_run_enabled`: builds a reduced candidate request for inspection, but
  keeps the original upstream request and original client-visible response path.
- `enabled`: sends the reduced candidate request upstream and returns the
  reduced-path upstream response to the client.
- `enabled` returns a controlled `422` when routing is unusable. It does not
  silently fall back to sending the original full request.

## Lemonade Live Validation

Local Lemonade enabled validation passed using `Qwen3.5-35B-A3B-GGUF` as the
router/executor model. The committed multi-fixture live run passed 3 of 3
fixtures:

- Expected inclusion accuracy: 100.00%
- Exact selection accuracy: 33.33%
- Over-selection count: 2
- Average estimated reduction percent: 56.45
- Original request not sent upstream: 3/3
- Reduced request sent upstream: 3/3
- Client success count: 3/3

The `incident_runbook` fixture was excluded after a live timeout and documented
as a limitation, not treated as a hidden pass.

## OpenAI Live Validation

OpenAI enabled validation passed with a live OpenAI executor. OpenAI router plus
executor validation also passed, using:

- Router model: `gpt-5.4-nano`
- Executor model: `gpt-5.5`

The latest OpenAI router plus executor multi-fixture rerun passed 3 of 3
fixtures:

- Expected inclusion accuracy: 100.00%
- Exact selection accuracy: 0.00%
- Over-selection count: 3
- Average estimated reduction percent: 40.47
- Original request not sent upstream: 3/3
- Reduced request sent upstream: 3/3
- Client success count: 3/3

## Interpretation

Expected segment inclusion is the safety-relevant routing metric at this stage.
Exact selection is a precision and reduction metric. Over-selection is tracked
but is not a hard failure when the expected useful segment is included.
Over-selection reduces efficiency and may add context noise, but it is different
from omitting the useful segment.

The current results validate the enabled proxy path under controlled runner
conditions. They do not validate production reliability.

## What Is Validated

- Provider-agnostic proxy mode progression.
- Live enabled path with Lemonade.
- Live enabled path with OpenAI.
- Reduced request is actually sent upstream in `enabled` mode.
- Original full request is not sent upstream in `enabled` mode.
- Client response comes from the reduced path.
- No silent fallback on routing failure.
- Secrets and `.env` were not committed.

## Not Validated Yet

- Production reliability.
- Large statistical routing accuracy.
- Broader noisy fixture sets.
- Anthropic enabled path.
- Real application integration.
- Latency and timeout hardening.
- Long-running operational behavior.
- Quality comparison against full-context answers at scale.

## Next Possible Steps

Possible next steps include Anthropic enabled validation, a larger OpenAI
fixture set, latency and cost reporting, answer-quality comparison between full
and reduced paths, and application-level integration tests.
