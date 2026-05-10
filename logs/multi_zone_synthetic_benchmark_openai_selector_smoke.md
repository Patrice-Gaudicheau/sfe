# Multi-Zone Synthetic Benchmark

Benchmark type: `multi_zone/synthetic`
Provider: `openai-api`
Selector mode: `openai_selector_smoke`
Model: `gpt-5.4-nano`
API path: `/v1/responses`
Executor: `deterministic_fixture`
Runs: 4

## Summary

Honest multi-zone pass rate: 100.00%
Zone selection success rate: 100.00%
Selected-zone completeness rate: 100.00%
Distractor rejection rate: 100.00%
Fallback count: 0
Output validation complete rate: 100.00%
Average token reduction: 35.07%

## Estimated Token Accounting

| Metric | Estimated tokens |
| --- | ---: |
| Full-context baseline | 590.50 |
| Selected zones | 360.00 |
| Suppressed zones | 197.00 |
| Composed context | 381.00 |

## OpenAI Selector Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 1771 |
| Output | 375 |
| Total | 2146 |

## Fixtures

| Fixture ID | Selected zones | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `multi_zone_synthetic_aurora_release_gate` | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | True | True | False | 100.00% | 28.57% |
| `multi_zone_synthetic_quartz_relay_gate` | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final | True | True | False | 100.00% | 41.56% |

## Runs

| Task | Mode | Honest pass | Selected zones | Missing required | Distractors selected | Token reduction |
| --- | --- | ---: | --- | --- | --- | ---: |
| `multi_zone_synthetic_aurora_release_gate` | `baseline` | False | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final, distractor-aurora-mz1-draft, distractor-aurora-dashboard | none | distractor-aurora-mz1-draft, distractor-aurora-dashboard | 0.00% |
| `multi_zone_synthetic_aurora_release_gate` | `spatial_multi_zone` | True | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | none | none | 28.57% |
| `multi_zone_synthetic_quartz_relay_gate` | `baseline` | False | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final, distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | none | distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | 0.00% |
| `multi_zone_synthetic_quartz_relay_gate` | `spatial_multi_zone` | True | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final | none | none | 41.56% |
