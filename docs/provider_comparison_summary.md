# Provider Comparison Summary

## Scope

This document compares protocol-aligned OpenAI and Anthropic paced benchmark
campaigns for the SFE large/contextual benchmark stack. It focuses on the
provider-neutral SFE pattern: selected-context execution reduces executor-visible
context, while router-inclusive savings depend on whether the avoided context is
large enough to amortize routing.

OpenAI completed standard, practical, high_context, and structural tiers without
provider/API failures. Anthropic also completed standard, practical,
high_context, and structural tiers without provider/API failures in the clean
campaign results. Anthropic structural required `600` seconds of provider-call
pacing because of Anthropic workspace input-token-per-minute limits.

This is not a statistical reliability benchmark.

## Campaign Setup Comparison

| Field | OpenAI | Anthropic |
| --- | --- | --- |
| Provider | `openai-api` | `anthropic` |
| API style | `openai_responses` | native Anthropic Messages API |
| Router model | `gpt-5.4-nano` | `claude-haiku-4-5-20251001` |
| Executor model | `gpt-5.5` | `claude-sonnet-4-6` |
| Output repair | disabled | disabled |
| Hidden retries | none | none |
| Standard/practical/high_context max tokens | `240` | `240` |
| Structural max tokens | `360` | `360` |
| Provider-call pacing | not required | `600` seconds for structural |

## Comparable Tier Results

| Tier | OpenAI selected reduction | OpenAI router-inclusive reduction | OpenAI pass status | Anthropic selected reduction | Anthropic router-inclusive reduction | Anthropic pass status |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| standard | 81.06% | 21.71% | baseline 21/21, fixture 21/21, router 21/21 | 80.88% | 19.09% | baseline 21/21, fixture 21/21, router 21/21 |
| practical | 88.17% | 63.40% | baseline 7/9, fixture 6/9, router 6/9 | 88.05% | 62.01% | baseline 9/9, fixture 9/9, router 9/9 |
| high_context | 91.11% | 73.38% | baseline 6/6, fixture 6/6, router 6/6 | 91.02% | 72.02% | baseline 6/6, fixture 6/6, router 6/6 |
| structural | 94.16% | 84.08% | baseline 3/3, fixture 3/3, router 3/3 | 93.94% | 83.63% | baseline 3/3, fixture 3/3, router 3/3 |

## Provider-Specific Caveats

The OpenAI practical tier had output omission failures on
`large_contextual_long_cobalt_dispatch_reconciliation`, missing the exact target
`oxygen-critical`. The failures affected baseline, fixture-selected, and
router-selected outputs. Router selection remained valid and matched at `9/9`,
so this should be treated as an executor output omission or validation issue on
that fixture, not as a selector failure.

Anthropic structural initially hit provider/API input-token-per-minute limits.
The clean structural repeat-3 result required `600` seconds of provider-call
pacing. Pacing changes execution timing only and does not change fixtures,
prompts, validation, selection, scoring, fallback behavior, or output repair
behavior.

No fallback and no repair were used in the completed clean campaign results.

## Interpretation

Both providers show nearly identical selected-context reduction patterns across
tiers. Both providers also show router-inclusive savings increasing as the
avoided context grows.

The standard tier shows visible router overhead: executor input reduction is
large, but router-inclusive reduction is much smaller. Practical, high_context,
and structural tiers show increasingly meaningful router-inclusive savings as
the full-context prompt grows.

Structural results are now clean for both providers, with Anthropic requiring
provider-call pacing. These results support selective SFE activation, not
universal activation.

## Limitations

- Small repeat campaigns, not statistical proof.
- No explicit first-pass versus retry mechanism.
- Output repair was disabled.
- Provider-specific rate limits affect execution strategy.
- Cost comparison is not included because both summaries do not provide
  equivalent dollar-cost accounting.
- Results should be compared only against protocol-aligned runs.

## Conclusion

The provider comparison supports the preliminary provider-neutral SFE pattern:
reducing executor context is effective across OpenAI and Anthropic, while
router-inclusive savings become substantial only when the avoided context is
large enough to amortize routing. The clean structural results on both providers
strengthen the pattern, but the campaign remains a controlled engineering
benchmark rather than a statistical reliability proof.
