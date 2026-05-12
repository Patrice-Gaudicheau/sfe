# OpenAI Paced-Equivalent Benchmark Summary

## Scope

This note summarizes a live OpenAI campaign aligned with the recent Anthropic
paced campaign protocol. The run used:

- selection mode `both`
- repeat `3`
- max output tokens `240` for standard, practical, and high_context
- max output tokens `360` for structural
- output repair disabled
- no hidden retry mechanism
- no observed provider/API failures

This is not a statistical reliability benchmark. It is a controlled local
campaign intended to make the OpenAI large/contextual results easier to compare
with protocol-aligned provider runs.

## Provider Setup

- Provider: `openai-api`
- API style: `openai_responses`
- Router model: `gpt-5.4-nano`
- Executor model: `gpt-5.5`
- Output repair: disabled with `--max-output-repairs 0`
- Benchmark-level first-pass versus retry mechanism: none
- Live Anthropic calls: none

## Results

| Tier | Calls | Provider failures | Baseline pass | Fixture pass | Router pass | Router valid / match | Fallback | Repair | Selected reduction | Router-inclusive reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 84 | 0 | 21/21 | 21/21 | 21/21 | 21/21 / 21/21 | 0 | 0 | 81.06% | 21.71% |
| practical | 36 | 0 | 7/9 | 6/9 | 6/9 | 9/9 / 9/9 | 0 | 0 | 88.17% | 63.40% |
| high_context | 24 | 0 | 6/6 | 6/6 | 6/6 | 6/6 / 6/6 | 0 | 0 | 91.11% | 73.38% |
| structural | 12 | 0 | 3/3 | 3/3 | 3/3 | 3/3 / 3/3 | 0 | 0 | 94.16% | 84.08% |

## Token Totals

| Tier | Baseline | Fixture | Router executor | Router | Router + executor |
| --- | ---: | ---: | ---: | ---: | ---: |
| standard | 59,159 | 12,200 | 12,236 | 34,077 | 46,313 |
| practical | 90,526 | 11,244 | 11,315 | 21,817 | 33,132 |
| high_context | 113,834 | 10,533 | 10,528 | 19,772 | 30,300 |
| structural | 154,005 | 9,231 | 9,231 | 15,279 | 24,510 |

## Practical-Tier Caveat

The practical tier had output omission failures on
`large_contextual_long_cobalt_dispatch_reconciliation`, missing the exact target
`oxygen-critical`.

The failures affected all executor conditions on that fixture:

- baseline: 2/3 failed
- fixture-selected: 3/3 failed
- router-selected: 3/3 failed

Router selection itself remained correct: 9/9 valid selections and 9/9 matches.
This should be treated as an executor output omission or validation issue on
that fixture, not as a selector failure or provider/API failure.

## Interpretation

The OpenAI campaign confirms the selected-context reduction pattern under this
large/contextual protocol. Executor-visible context is much smaller when the
executor receives only selected context instead of the full prompt context.

Router overhead remains visible at the standard tier. Router-inclusive reduction
becomes stronger as the avoided context grows, with practical, high_context, and
structural tiers showing stronger amortization than standard.

The structural tier completed cleanly with 84.08% router-inclusive reduction.
These results support selective SFE activation, not universal activation.

## Limitations

- Small repeat campaign, not statistical reliability proof.
- Practical tier has an output omission caveat.
- No explicit first-pass versus retry mechanism.
- Output repair was disabled.
- Dollar cost is not included because pricing was not recorded as a first-class runner metric.
- Results should be compared only against protocol-aligned runs.

## Conclusion

This OpenAI paced-equivalent campaign supports the core SFE pattern under a
protocol aligned with the Anthropic campaign: selected-context execution sharply
reduces executor context, while router-inclusive savings increase as the avoided
context grows. The structural tier completed cleanly, but practical-tier output
omissions should remain visible in any comparison.
