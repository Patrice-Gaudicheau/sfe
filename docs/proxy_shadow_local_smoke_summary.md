# Proxy Shadow Local Smoke Summary

This phase validates local proxy shadow mechanics only. It does not validate
live router quality, SFE-enabled execution, or production reliability.

## Validated

- OpenAI-compatible proxy request passthrough.
- Unchanged upstream request in the tested shadow scenarios.
- Unchanged client-visible response in the tested shadow scenarios.
- Shadow router metadata capture.
- Deterministic useful-segment selection checks.
- One local smoke runner: `runtime/run_sfe_proxy_shadow_smoke.py`.
- One deterministic mini benchmark runner with 4 controlled fixtures:
  `runtime/run_sfe_proxy_shadow_mini_benchmark.py`.
- Local-only mocked upstream behavior and mocked Lemonade-compatible router
  behavior.
- No OpenAI, Anthropic, live Lemonade, secrets, or external API calls.

## Results

- Smoke runner selected `segment-3`.
- Mini benchmark fixtures: 4.
- Mini benchmark result: 4 passed, 0 failed.
- Selection accuracy: 100.00%.
- Average estimated token reduction pct: 75.38.
- Upstream transparency: all passed.
- Client response transparency: all passed.
- Pytest proxy suite: 70 passed.

## Not Validated Yet

- Live Lemonade router quality.
- OpenAI proxy behavior.
- Anthropic proxy behavior.
- SFE-enabled execution.
- Production reliability.
- Statistical routing accuracy.
- Real-world provider latency and quota behavior.

## Next Step

The next logical step is a live Lemonade shadow runner, still without
SFE-enabled execution and still with no client-visible impact.
