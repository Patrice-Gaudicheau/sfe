# Controlled Organic Multi-Zone Benchmark

Benchmark type: `multi_zone/controlled_organic`
Provider: `deterministic_mock`
Selector mode: `fixture`
Selector provider: `deterministic_mock`
Selector model: `n/a`
Selector API path: `n/a`
Executor mode: `openai_executor_smoke`
Executor provider: `openai-api`
Executor model: `gpt-5.5`
Executor API path: `/v1/responses`
Runs: 2

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
| Input | n/a |
| Output | n/a |
| Total | n/a |

## OpenAI Executor Usage

| Metric | Actual tokens |
| --- | ---: |
| Input | 664 |
| Output | 311 |
| Total | 975 |

## Fixtures

| Fixture ID | Selected sources | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `controlled_organic_release_readiness_gate` | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | True | True | False | 100.00% | 41.64% |

## Runs

| Fixture | Mode | Selector validation | Honest pass | Selected sources | Missing required | Distractors selected | Token reduction |
| --- | --- | --- | ---: | --- | --- | --- | ---: |
| `controlled_organic_release_readiness_gate` | `baseline` | incomplete | False | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778, doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | none | doc-policy-thresholds-previous, doc-ops-note-local-override, doc-release-notes-draft | 0.00% |
| `controlled_organic_release_readiness_gate` | `controlled_organic_multi_zone` | complete | True | doc-release-notes-helix-2026-11, doc-policy-thresholds-current, doc-service-ownership-map, doc-incident-followup-778 | none | none | 41.64% |
