# Alibaba/Qwen Large Contextual Missing-Tier Benchmark Note

This note records the Alibaba/Qwen measurements added for the large/contextual
`standard`, `practical`, and `high_context` tiers. These are controlled
benchmark observations, not statistical proof, production commitments, or a
claim of provider superiority.

## Run Approach

The existing large/contextual benchmark methodology was not changed. The run
used the same fixtures, tier definitions, selection modes, and token-reduction
formulas as the existing provider comparison path.

The original Alibaba/Qwen run used a direct Python invocation of
`run_benchmark(...)` with in-memory Alibaba provider injection before
`runtime/run_large_contextual_benchmark.py` exposed `alibaba-api` as a CLI
provider option. That avoided changing benchmark methodology while exercising
the same benchmark implementation.

Future Alibaba/Qwen large/contextual runs can use the CLI provider option:

```bash
python runtime/run_large_contextual_benchmark.py \
  --executor alibaba-api \
  --task-tier standard \
  --selection-mode both \
  --repeat 3 \
  --max-tokens 240 \
  --provider-call-delay-seconds 1.0
```

Configuration:

- Provider path: benchmark-only Alibaba API provider using DashScope
  OpenAI-compatible chat completions.
- Router model: `qwen3.6-flash`.
- Executor model: `qwen3.6-plus`.
- Qwen thinking: disabled by the existing provider default for usable token
  accounting.
- Tiers: `standard`, `practical`, and `high_context`.
- `repeat=3`.
- `selection_mode=both`.
- `max_tokens=240`.
- Provider pacing: `1.0` second between live provider calls.

The previously reported Alibaba/Qwen `structural` metric was not rerun. It
remains the single live baseline-vs-spatial comparison documented in
`docs/alibaba_structural_50k_comparison_note.md`.

## Token And Reduction Summary

| Tier | Baseline tokens | Selected-context tokens | Router tokens | Router-inclusive tokens | Selected reduction | Router-inclusive reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `standard` [2k-5k tokens] | 2,833.29 | 581.86 | 1,694.81 | 2,273.24 | 80.72% | 19.77% |
| `practical` [10k-20k tokens] | 10,118.22 | 1,265.78 | 2,550.00 | 3,815.33 | 88.00% | 62.29% |
| `high_context` [20k-50k tokens] | 19,111.67 | 1,779.00 | 3,506.83 | 5,285.33 | 90.98% | 72.34% |

Selected reduction means executor-visible context reduction. Router-inclusive
reduction includes selector/router overhead.

## Latency Summary

| Tier | Baseline latency | Selected-context latency | Router-inclusive latency |
| --- | ---: | ---: | ---: |
| `standard` [2k-5k tokens] | 3,444.29 ms | 3,161.29 ms | 5,610.67 ms |
| `practical` [10k-20k tokens] | 4,156.22 ms | 3,415.22 ms | 6,186.44 ms |
| `high_context` [20k-50k tokens] | 5,804.00 ms | 3,761.17 ms | 6,498.50 ms |

Latency is reported as observed benchmark timing and should not be read as a
provider-level latency guarantee.

## Router Status

| Tier | Task count | Repeat | Router success | Fallback count |
| --- | ---: | ---: | ---: | ---: |
| `standard` [2k-5k tokens] | 7 | 3 | 100% | 0 |
| `practical` [10k-20k tokens] | 3 | 3 | 100% | 0 |
| `high_context` [20k-50k tokens] | 2 | 3 | 100% | 0 |

## Local Artifacts

The run generated local benchmark artifacts under `/tmp`. They are listed here
for traceability and are not committed repository artifacts:

- `/tmp/sfe_alibaba_large_contextual_standard_repeat3.json`
- `/tmp/sfe_alibaba_large_contextual_standard_repeat3.md`
- `/tmp/sfe_alibaba_large_contextual_practical_repeat3.json`
- `/tmp/sfe_alibaba_large_contextual_practical_repeat3.md`
- `/tmp/sfe_alibaba_large_contextual_high_context_repeat3.json`
- `/tmp/sfe_alibaba_large_contextual_high_context_repeat3.md`
- `/tmp/sfe_alibaba_large_contextual_missing_tiers_summary.json`

## Interpretation Limits

The measurements are consistent with the expected amortization pattern: router
overhead is more visible in the standard tier and is amortized better as
context size grows. They do not establish statistical significance, production
readiness, or broad provider ranking.

Alibaba/Qwen still differs from the OpenAI and Anthropic summaries in one
important respect: the `structural` Alibaba/Qwen row remains a single
baseline-vs-spatial live comparison, while the missing-tier rows above are
repeat-3 observations.
