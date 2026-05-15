# Token And Cost Metrics

## Purpose

This page summarizes the current token-reduction evidence for the
large/contextual benchmark family, with emphasis on router-inclusive token
reduction. Router-inclusive reduction is the relevant metric for cost-sensitive
use because it includes both the selector call and the selected-context executor
call.

These are local OpenAI observations on controlled benchmark fixtures. They are
not statistical proof, not a guarantee of dollar cost savings, and not evidence
that SFE always improves results. Dollar cost is derivable from token counts and
explicit pricing assumptions, but the current runner does not report dollar cost
as a first-class metric.

## Business Impact

Router-inclusive token reduction is the most relevant metric for
cost-sensitive deployments because it includes both the selector call and the
selected-context executor call. In the fresh local OpenAI all-tier
reproduction, the signal strengthens as context size grows: standard-tier
reduction is smaller because router overhead is more visible, while practical,
high_context, and structural tiers show stronger amortization.

This is useful for infrastructure planning, but it is not a guaranteed savings
claim. SFE is economically relevant only when context size, authority conflict
density, or audit requirements justify the extra routing step.

## Fresh OpenAI All-Tier Reproduction

Run context:

- Runner: `runtime/run_large_contextual_benchmark.py`
- Executor path: `--executor openai-api`
- Selection mode: `--selection-mode both`
- Router model: `gpt-5.4-nano`
- Executor model: `gpt-5.5`

| Tier | Baseline scope | Tasks | Baseline success | Fixture success | Router success | Executor input reduction | Router-inclusive token reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 2k-5k tokens | 7 | 6/7 | 7/7 | 7/7 | 81.06% | 21.82% |
| practical | 10k-20k tokens | 3 | 2/3 | 2/3 | 2/3 | 88.17% | 63.54% |
| high_context | 20k-50k tokens | 2 | 2/2 | 2/2 | 2/2 | 91.11% | 73.35% |
| structural | 50k+ tokens | 1 | 1/1 | 1/1 | 1/1 | 94.16% | 84.08% |

This table is a fresh local OpenAI all-tier reproduction. The cross-provider
summary in `docs/provider_comparison_summary.md` uses a separate
protocol-aligned OpenAI/Anthropic campaign snapshot, where the standard-tier
OpenAI router-inclusive reduction is `21.71%`. Treat the small standard-tier
difference as run-snapshot drift rather than a new headline claim.

## Token Accounting

| Tier | Baseline total tokens | Router tokens | Selected executor tokens | Router+executor total tokens |
| --- | ---: | ---: | ---: | ---: |
| standard | 19,733 | 11,368 | 4,060 | 15,428 |
| practical | 30,168 | 7,276 | 3,724 | 11,000 |
| high_context | 37,918 | 6,598 | 3,505 | 10,103 |
| structural | 51,335 | 5,093 | 3,077 | 8,170 |

## Cost-Relevant Breakdown

| Tier | Baseline input/output | Router input/output | Selected executor input/output |
| --- | ---: | ---: | ---: |
| standard | 19,258 / 475 | 10,955 / 413 | 3,648 / 412 |
| practical | 29,977 / 191 | 7,080 / 196 | 3,547 / 177 |
| high_context | 37,789 / 129 | 6,444 / 154 | 3,360 / 145 |
| structural | 51,253 / 82 | 5,013 / 80 | 2,995 / 82 |

## Interpretation

The token-reduction signal grows with context size. The standard tier still
shows router-inclusive token reduction, but router overhead is much more visible
because the baseline context is relatively small. Practical, high_context, and
structural tiers show stronger router-inclusive reductions because the avoided
executor context is larger relative to selector overhead.

This supports selective activation rather than always-on routing. SFE should be
activated when context reduction or role separation can plausibly amortize the
selector call. Short or simple prompts may not justify routing overhead.

Dollar cost should be computed from the input/output token counts above and
explicit pricing assumptions for the specific router and executor models used
at the time of analysis. Pricing changes over time, and provider-side billing
can differ because of caching, account configuration, or processing mode.

## How To Estimate Dollar Cost

This repository records token counts, not guaranteed dollar savings. To estimate
cost for a specific provider, model, date, and contract, apply explicit pricing
assumptions to the token counts.

Estimated baseline cost:

```text
baseline_input_tokens * baseline_input_price
+ baseline_output_tokens * baseline_output_price
```

Estimated SFE cost:

```text
router_input_tokens * router_input_price
+ router_output_tokens * router_output_price
+ selected_executor_input_tokens * executor_input_price
+ selected_executor_output_tokens * executor_output_price
```

Estimated savings:

```text
estimated_baseline_cost - estimated_SFE_cost
```

Prices vary by provider, model, date, account configuration, caching behavior,
and commercial contract. Avoid hardcoded dollar claims unless those pricing
assumptions are explicit and current for the intended reader.

## Anomalies And Caveats

- No provider errors, parse errors, router failures, fallbacks, or repairs
  occurred in this fresh OpenAI all-tier run.
- In the standard tier, the baseline missed `Mira Chen`, while fixture and
  router paths passed.
- In the practical tier, baseline, fixture, and router paths all missed exact
  target `oxygen-critical`. This is not an SFE-vs-baseline regression, but it
  should be treated as a validation or task anomaly before stronger
  interpretation.
- Task counts are small: 7 standard, 3 practical, 2 high_context, and 1
  structural task.
- These are local OpenAI observations, not statistical proof or production
  validation.
- The results do not prove general reliability, guaranteed cost savings, or
  broad answer-quality improvement.

## Relationship To Lemonade Metrics

The Lemonade benchmark metrics remain useful historical and local evidence,
especially for the original large/contextual validation curve and the
high_context stability run. The fresh OpenAI metrics now provide comparable
token accounting across all four large/contextual tiers using the direct
OpenAI API path.

README summaries should distinguish these fresh OpenAI token observations from
the older Lemonade-local benchmark history. In both cases, executor input
reduction and router-inclusive token reduction should be reported separately.
