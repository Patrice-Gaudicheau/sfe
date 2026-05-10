# Multi-Zone Synthetic Benchmark

Benchmark type: `multi_zone/synthetic`
Provider: `openai-api`
Selector mode: `openai_selector_smoke`
Model: `gpt-5.4-nano`
API path: `/v1/responses`
Executor: `deterministic_fixture`
Runs: 2

## Summary

Honest multi-zone pass rate: 100.00%
Zone selection success rate: 100.00%
Selected-zone completeness rate: 100.00%
Distractor rejection rate: 100.00%
Fallback count: 0
Output validation complete rate: 100.00%
Average token reduction: 28.57%

## Estimated Token Accounting

| Metric | Estimated tokens |
| --- | ---: |
| Full-context baseline | 553.00 |
| Selected zones | 374.00 |
| Suppressed zones | 148.00 |
| Composed context | 395.00 |

## OpenAI Selector Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 862 |
| Output | 221 |
| Total | 1083 |

## Runs

| Task | Mode | Honest pass | Selected zones | Missing required | Distractors selected | Token reduction |
| --- | --- | ---: | --- | --- | --- | ---: |
| `multi_zone_synthetic_aurora_release_gate` | `baseline` | False | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final, distractor-aurora-mz1-draft, distractor-aurora-dashboard | none | distractor-aurora-mz1-draft, distractor-aurora-dashboard | 0.00% |
| `multi_zone_synthetic_aurora_release_gate` | `spatial_multi_zone` | True | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | none | none | 28.57% |
