# OpenAI API Validation Report

This report summarizes the first direct OpenAI API validation of the existing
large/contextual benchmark protocol. It uses the same fixtures, prompt builders,
selection modes, validation checks, token reporting, and JSON/Markdown reporting
logic used for the Lemonade large/contextual benchmark.

The OpenAI API was used as the provider path for executor calls and, in
router-inclusive runs, for selector calls. The executor model was a configured
frontier OpenAI model. The router model was a configured lower-cost OpenAI model.
Model identifiers are environment-dependent and should be set with
`SFE_OPENAI_EXECUTOR_MODEL` and `SFE_OPENAI_ROUTER_MODEL`. No API keys or local
credential values are included in this report.

## Benchmark Shape

- Protocol: `runtime/run_large_contextual_benchmark.py`
- Provider path: `--executor openai-api`
- Tiers tested: `standard`, `practical`, and `high_context`
- Selection modes tested: fixture/oracle and router-inclusive `both`
- Fixture selection: known relevant block selected directly
- Router selection: model selects one block from compact block metadata
- Validation: existing task-specific string checks

Fixture/oracle runs verified that the baseline and selected-context executor
paths both succeeded before router-inclusive runs were interpreted. The main
result below focuses on router-inclusive runs, where router cost is included in
the `spatial_router` end-to-end token and cost comparison.

## Router-Inclusive Results

Estimated costs use the configured model pricing at the time of testing and are
approximate. They are intended for scale comparison, not billing reconciliation.

| Tier / task | Baseline total tokens | Router + executor total tokens | Executor input reduction | Router-inclusive total token reduction | Router match | Fallback used | Estimated baseline cost | Estimated router + executor cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `standard` / payments | 2,358 | 2,003 | 81.60% | 15.06% | true | false | about $0.0133 | about $0.0045 |
| `practical` / aquila | 10,112 | 3,642 | 88.19% | 63.98% | true | false | about $0.0520 | about $0.0084 |
| `high_context` / Orion | 19,020 | 5,023 | 91.09% | 73.59% | true | false | about $0.0972 | about $0.0115 |
| `high_context` / Boreal | 18,936 | 4,989 | 91.13% | 73.65% | true | false | about $0.0968 | about $0.0117 |

## Interpretation

These runs support the amortization hypothesis in this small synthetic setting:
as baseline context grows, the router overhead becomes smaller relative to the
avoided executor context. The standard task shows limited router-inclusive token
reduction because the router cost is large relative to the short baseline. The
practical and high_context tasks show substantially larger router-inclusive
total token reductions because the baseline prompt is much larger while the
selected executor payload remains comparatively small.

This is a token and cost signal, not a claim that SFE improves model
intelligence. The model still performs the task. SFE changes how context is
selected and bounded before the executor call.

## Caveats

- The sample is small: one standard task, one practical task, and two
  high_context tasks.
- The tasks are synthetic and deterministic.
- Router selection succeeded on these runs, but broader router reliability has
  not been established.
- Validation is task-specific and heuristic.
- These results do not prove broad real-world validity, production readiness, or
  general answer-quality improvement.
- Cost estimates are approximate and depend on model pricing, routing model
  choice, account configuration, and provider-side token accounting.

## Next Validation Steps

- Repeat the OpenAI runs across more tasks and seeds before making stronger
  claims.
- Add real or semi-real workloads with independently reviewed success criteria.
- Stress-test router selection with harder distractors and adversarially similar
  blocks.
- Compare lower-cost executor models to test whether routing enables cheaper
  execution without losing the benchmark's measured success checks.
- Keep reporting executor-only and router-inclusive metrics separately.
