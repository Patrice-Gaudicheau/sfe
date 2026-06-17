# Historical OpenAI Smoke Report Snapshots

This directory preserves a compact summary of previously tracked generated
Markdown reports from OpenAI selector, executor, and combined smoke runs.

These are historical snapshots, not the canonical current project status. Newly
generated logs and report streams should stay under ignored local paths such as
`logs/` unless they are intentionally summarized in `docs/` or `reports/`.

## Preserved Snapshot Summary

The original generated report files were removed after preserving their headline
results here. Each row is a narrow local smoke observation, not a statistical
reliability claim.

| Historical report | Benchmark family | Selector / executor shape | Runs | Honest pass rate | Avg token reduction | Caveat |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `controlled_organic_multi_zone_openai_selector_smoke.md` | controlled organic multi-zone | OpenAI selector, deterministic fixture executor | 2 | 100.00% | 41.64% | Selector-only smoke. |
| `controlled_organic_multi_zone_openai_executor_smoke.md` | controlled organic multi-zone | fixture selector, OpenAI executor | 2 | 100.00% | 41.64% | Executor-only smoke. |
| `controlled_organic_multi_zone_openai_both_smoke.md` | controlled organic multi-zone | OpenAI selector and executor | 2 | 100.00% | 41.64% | Single smoke run shape. |
| `controlled_organic_multi_zone_openai_both_repeat3.md` | controlled organic multi-zone | OpenAI selector and executor | 6 | 100.00% | 41.64% | Repeat-3 stability snapshot. |
| `multi_zone_synthetic_benchmark_openai_selector_smoke.md` | multi-zone synthetic | OpenAI selector, deterministic fixture executor | 4 | 100.00% | 35.07% | Selector-only smoke. |
| `multi_zone_synthetic_benchmark_openai_executor_smoke.md` | multi-zone synthetic | fixture selector, OpenAI executor | 4 | 100.00% | 35.07% | Executor-only smoke. |
| `multi_zone_synthetic_benchmark_openai_both_smoke.md` | multi-zone synthetic | OpenAI selector and executor | 4 | 100.00% | 35.07% | Single smoke run shape. |
| `multi_zone_synthetic_benchmark_openai_both_repeat3.md` | multi-zone synthetic | OpenAI selector and executor | 12 | 100.00% | 35.07% | Repeat-3 stability snapshot. |

## Cleanup Note

The full generated Markdown snapshots were intentionally deleted from
`docs/history` because they duplicated structured report tables and were not
linked individually from current docs. This summary keeps the audit trail small
while preserving the headline evidence and caveats.
