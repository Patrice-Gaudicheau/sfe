# Controlled Organic Multi-Zone Benchmark

Benchmark type: `multi_zone/controlled_organic`
Provider: `openai-api`
Selector mode: `openai_selector_smoke`
Selector provider: `openai-api`
Selector model: `gpt-5.4-nano`
Selector API path: `/v1/responses`
Executor mode: `openai_executor_smoke`
Executor provider: `openai-api`
Executor model: `gpt-5.5`
Executor API path: `/v1/responses`
Runs: 6

## Summary

Honest controlled-organic pass rate: 100.00%
Source selection success rate: 100.00%
Required source completeness rate: 100.00%
Distractor rejection rate: 100.00%
Fallback count: 0
Output validation complete rate: 100.00%
Executor output parse success rate: 100.00%
Output repair status: not_supported
Average token reduction: 41.64%
Stability repeat count: 3
Stability fixture executions: 3
Stability all repeats passed: True
Stability all fixtures passed: True

## Estimated Token Accounting

| Metric | Estimated tokens |
| --- | ---: |
| Full-context baseline | 610.00 |
| Selected sources | 352.00 |
| Suppressed sources | 251.00 |
| Composed context | 356.00 |

## OpenAI Selector Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 2973 |
| Output | 625 |
| Total | 3598 |

## OpenAI Executor Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 1992 |
| Output | 1017 |
| Total | 3009 |

## Fixtures

| Fixture ID | Selected sources | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `controlled_organic_release_readiness_gate` | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | True | True | False | 100.00% | 41.64% |

## Stability Runs

| Repeat | Fixture executions | Honest pass | Honest pass count | Fallback count | Required source complete count | Output validation complete count | Executor parse success count | Selector tokens | Executor tokens |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | True | 1 | 0 | 1 | 1 | 1 | 1188 | 986 |
| 2 | 1 | True | 1 | 0 | 1 | 1 | 1 | 1206 | 1038 |
| 3 | 1 | True | 1 | 0 | 1 | 1 | 1 | 1204 | 985 |

## Stability Fixtures

| Fixture ID | Repeats | Honest pass | Honest pass count | Required source completeness rate | Output validation rate | Fallback count | Executor parse success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `controlled_organic_release_readiness_gate` | 3 | True | 3 | 100.00% | 100.00% | 0 | 100.00% |

## Runs

| Fixture | Mode | Selector validation | Honest pass | Selected sources | Missing required | Distractors selected | Token reduction |
| --- | --- | --- | ---: | --- | --- | --- | ---: |
| `controlled_organic_release_readiness_gate` | `baseline` | incomplete | False | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778, doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | none | doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | 0.00% |
| `controlled_organic_release_readiness_gate` | `controlled_organic_multi_zone` | complete | True | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | none | none | 41.64% |
| `controlled_organic_release_readiness_gate` | `baseline` | incomplete | False | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778, doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | none | doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | 0.00% |
| `controlled_organic_release_readiness_gate` | `controlled_organic_multi_zone` | complete | True | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | none | none | 41.64% |
| `controlled_organic_release_readiness_gate` | `baseline` | incomplete | False | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778, doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | none | doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | 0.00% |
| `controlled_organic_release_readiness_gate` | `controlled_organic_multi_zone` | complete | True | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | none | none | 41.64% |
