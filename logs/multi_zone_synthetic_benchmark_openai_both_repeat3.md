# Multi-Zone Synthetic Benchmark

Benchmark type: `multi_zone/synthetic`
Provider: `openai-api`
Selector mode: `openai_selector_smoke`
Selector provider: `openai-api`
Selector model: `gpt-5.4-nano`
Selector API path: `/v1/responses`
Executor: `openai_executor_smoke`
Executor mode: `openai_executor_smoke`
Executor provider: `openai-api`
Executor model: `gpt-5.5`
Executor API path: `/v1/responses`
Runs: 12

## Summary

Honest multi-zone pass rate: 100.00%
Zone selection success rate: 100.00%
Selected-zone completeness rate: 100.00%
Distractor rejection rate: 100.00%
Fallback count: 0
Output validation complete rate: 100.00%
Executor output parse success rate: 100.00%
Output repair status: not_supported
Average token reduction: 35.07%
Stability repeat count: 3
Stability fixture executions: 6
Stability all repeats passed: True
Stability all fixtures passed: True

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
| Input | 5313 |
| Output | 1122 |
| Total | 6435 |

## OpenAI Executor Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 4368 |
| Output | 1322 |
| Total | 5690 |

## Fixtures

| Fixture ID | Selected zones | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `multi_zone_synthetic_aurora_release_gate` | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | True | True | False | 100.00% | 28.57% |
| `multi_zone_synthetic_quartz_relay_gate` | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final | True | True | False | 100.00% | 41.56% |

## Stability Runs

| Repeat | Fixture executions | Honest pass | Honest pass count | Fallback count | Executor parse success count | Output validation complete count | Selector tokens | Executor tokens |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2 | True | 2 | 0 | 2 | 2 | 2134 | 1884 |
| 2 | 2 | True | 2 | 0 | 2 | 2 | 2146 | 1897 |
| 3 | 2 | True | 2 | 0 | 2 | 2 | 2155 | 1909 |

## Stability Fixtures

| Fixture ID | Repeats | Honest pass | Honest pass count | Selected complete rate | Output validation rate | Fallback count | Executor parse success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `multi_zone_synthetic_aurora_release_gate` | 3 | True | 3 | 100.00% | 100.00% | 0 | 100.00% |
| `multi_zone_synthetic_quartz_relay_gate` | 3 | True | 3 | 100.00% | 100.00% | 0 | 100.00% |

## Runs

| Task | Mode | Honest pass | Selected zones | Missing required | Distractors selected | Token reduction |
| --- | --- | ---: | --- | --- | --- | ---: |
| `multi_zone_synthetic_aurora_release_gate` | `baseline` | False | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final, distractor-aurora-mz1-draft, distractor-aurora-dashboard | none | distractor-aurora-mz1-draft, distractor-aurora-dashboard | 0.00% |
| `multi_zone_synthetic_aurora_release_gate` | `spatial_multi_zone` | True | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | none | none | 28.57% |
| `multi_zone_synthetic_aurora_release_gate` | `baseline` | False | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final, distractor-aurora-mz1-draft, distractor-aurora-dashboard | none | distractor-aurora-mz1-draft, distractor-aurora-dashboard | 0.00% |
| `multi_zone_synthetic_aurora_release_gate` | `spatial_multi_zone` | True | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | none | none | 28.57% |
| `multi_zone_synthetic_aurora_release_gate` | `baseline` | False | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final, distractor-aurora-mz1-draft, distractor-aurora-dashboard | none | distractor-aurora-mz1-draft, distractor-aurora-dashboard | 0.00% |
| `multi_zone_synthetic_aurora_release_gate` | `spatial_multi_zone` | True | intent-aurora-gate, constraints-aurora-active, domain-aurora-governance, evidence-aurora-final | none | none | 28.57% |
| `multi_zone_synthetic_quartz_relay_gate` | `baseline` | False | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final, distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | none | distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | 0.00% |
| `multi_zone_synthetic_quartz_relay_gate` | `spatial_multi_zone` | True | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final | none | none | 41.56% |
| `multi_zone_synthetic_quartz_relay_gate` | `baseline` | False | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final, distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | none | distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | 0.00% |
| `multi_zone_synthetic_quartz_relay_gate` | `spatial_multi_zone` | True | constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final, intent-quartz-relay | none | none | 41.56% |
| `multi_zone_synthetic_quartz_relay_gate` | `baseline` | False | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final, distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | none | distractor-quartz-partial-threshold, distractor-quartz-previous-protocol, distractor-quartz-ops-note | 0.00% |
| `multi_zone_synthetic_quartz_relay_gate` | `spatial_multi_zone` | True | intent-quartz-relay, constraints-quartz-global, domain-quartz-threshold, evidence-quartz-final | none | none | 41.56% |
