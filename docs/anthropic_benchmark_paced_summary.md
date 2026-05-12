# Anthropic Benchmark Paced Summary

## Scope

This note summarizes a small rate-limit-aware live Anthropic campaign for the SFE
large/contextual benchmark stack. The goal was to validate the native Anthropic
provider integration and gather preliminary token-behavior evidence across the
standard, practical, high_context, and structural tiers.

This is not a full statistical reliability benchmark. It is a controlled local
campaign with small task counts and explicit pacing to avoid Anthropic provider
rate-limit failures.

## Provider Setup

- Provider: `anthropic`
- API style: native Anthropic Messages API
- Router model: `claude-haiku-4-5-20251001`
- Executor model: `claude-sonnet-4-6`
- Output repair: disabled
- Hidden retry mechanism: none
- Prompt caching, batching, or data-residency modifiers: not assumed in cost estimates
- Standard, practical, and high_context max output tokens: `240`
- Structural max output tokens: `360`
- Structural provider-call delay: `600` seconds between live provider calls

## Clean Results

The primary results below include tiers that completed without provider/API
failures.

| Tier | Calls completed | Provider failures | Baseline pass | Fixture pass | Router pass | Router valid / match | Selected reduction | Router-inclusive reduction | Estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 84/84 | 0 | 21/21 | 21/21 | 21/21 | 21/21 / 21/21 | 80.88% | 19.09% | ~$0.383665 |
| practical | 36/36 | 0 | 9/9 | 9/9 | 9/9 | 9/9 / 9/9 | 88.05% | 62.01% | ~$0.432765 |
| high_context | 24/24 | 0 | 6/6 | 6/6 | 6/6 | 6/6 / 6/6 | 91.02% | 72.02% | ~$0.498648 |
| structural | 12/12 | 0 | 3/3 | 3/3 | 3/3 | 3/3 / 3/3 | 93.94% | 83.63% | not recalculated |

## Token Totals

| Tier | Baseline | Fixture | Router executor | Router | Router + executor |
| --- | ---: | ---: | ---: | ---: | ---: |
| standard | 65,673 | 13,798 | 13,821 | 39,317 | 53,138 |
| practical | 99,921 | 12,564 | 12,617 | 25,347 | 37,964 |
| high_context | 125,399 | 11,924 | 11,886 | 23,205 | 35,091 |
| structural | 168,804 | 10,227 | 10,227 | 17,412 | 27,639 |

## Structural Pacing Note

The initial structural attempt hit Anthropic workspace input-token-per-minute
limits inside a single benchmark run. Baseline completed, but selected-context
executor calls were interrupted by provider/API rate-limit failures.

The clean structural repeat-3 result was obtained only after adding and using a
provider-call delay of `600` seconds between live provider calls. This pacing
changes execution timing only. It does not change fixtures, prompts, validation,
selection, scoring, fallback behavior, or output repair behavior.

The structural result should therefore be read as a clean ultra-paced Anthropic
structural observation, not as evidence that the same run shape is safe under
unpaced Anthropic workspace rate limits.

## Interpretation

The clean Anthropic tiers confirm the selected-context reduction pattern already
observed with other providers. Executor-visible context falls substantially when
the benchmark uses selected authoritative context instead of the full context.

Router overhead is visible at smaller context sizes. In the standard tier, the
executor input reduction is large, but router-inclusive reduction is much
smaller because the selector call has a fixed token cost. Router-inclusive
savings improve as the avoided context grows: practical, high_context, and
structural show materially stronger router-inclusive reductions.

These results support selective activation of SFE, not universal activation. In
the clean tiers, no selector failure, fallback, or repair was observed.

## Limitations

- Small sample size.
- No statistical reliability claim.
- Structural required explicit provider-call pacing because Anthropic rate
  limits affected the unpaced structural attempt.
- No explicit first-pass versus retry mechanism exists in this benchmark path.
- No output repair was used.
- Costs are estimates based on reported token accounting and public model pricing assumptions.
- Results should be compared only with equivalent protocol runs.

## Conclusion

This paced Anthropic campaign supports the provider-neutral SFE thesis at a
preliminary level. Across clean standard, practical, high_context, and
ultra-paced structural tiers, selected-context execution substantially reduced
executor context, while router-inclusive savings became meaningful only when the
avoided context was large enough to amortize routing cost. The structural tier
now has clean repeat-3 metrics, but only under explicit provider-call pacing.
