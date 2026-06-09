# Large Real-World Benchmark Progression Summary

Status note: This is a historical benchmark progression record preserved for
audit/research continuity. Start with `README.md` and `docs/INDEX.md` for the
latest project overview.

## Purpose

This document summarizes the recent benchmark sequence that moved from
deterministic controlled multi-zone validation to live OpenAI selector and
executor smoke tests.

It is a synthesis document. It does not replace the individual benchmark notes,
and it is not a roadmap.

## Progression overview

The sequence advanced in five stages:

1. Minimal deterministic real-world inspired benchmark.
2. Large deterministic real-world inspired benchmark.
3. OpenAI selector-only smoke.
4. OpenAI selector + deterministic executor.
5. OpenAI selector + OpenAI executor.

Each stage kept deterministic validation as the source of truth. The later
OpenAI stages tested progressively more of the live selected-context path while
preserving strict pass gates and making fallback visible.

Stages 3-5 should be viewed as functional smoke tests rather than statistical
proofs of reliability.

## Results table

| Stage | Selection | Execution | Validation | Repeat | Honest pass | Fallbacks | Parse failures | Token reduction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Minimal real-world inspired multi-zone | Deterministic | Deterministic | Strict deterministic | Single deterministic run | 100.00% | 0 | n/a | about 39.46% |
| Large real-world inspired multi-zone | Deterministic | Deterministic | Strict deterministic | Single deterministic run | 100.00% | 0 | n/a | 79.67% |
| OpenAI selector-only smoke | OpenAI `gpt-5.4-nano` | None | Strict source selection validation | 3 live repeats | 3/3 full selector passes; 100.00% on all runs | 0 on all runs | 0 on all runs | 79.67% |
| OpenAI selector + deterministic executor | OpenAI `gpt-5.4-nano` | Deterministic | Strict deterministic answer validation | 3 live repeats | 3/3 full end-to-contract passes; 100.00% on all runs | 0 on all runs | 0 on all runs | 79.67% |
| OpenAI selector + OpenAI executor smoke | OpenAI `gpt-5.4-nano` | OpenAI `gpt-5.5` | Strict deterministic answer validation | 3 live repeats, 6 fixture executions | 3/3 full honest end-to-end runs; 6/6 fixture passes; 100.00% on all runs | selector 0; executor 0 on all runs | selector 0; executor 0 on all runs | 79.67% |

For the full OpenAI selector + executor smoke, total token usage across the
three live repeats was: prompt 13929, completion 2972, total 16901. Selector
usage was prompt 10260, completion 1065, total 11325. Executor usage was prompt
3669, completion 1907, total 5576.

## Interpretation

The minimal benchmark established the controlled contract on realistic
multi-zone fixtures. It showed that exact, machine-checkable validation can be
used for realistic project-like tasks without relying on soft semantic grading.

The large deterministic benchmark showed that token reduction becomes much
stronger as available context grows. With 2 fixtures, 14 candidate sources per
fixture, 4 required sources per fixture, and 10 distractors per fixture, the
selected-context token reduction estimate rose to 79.67% while preserving a
100.00% honest deterministic pass rate.

The OpenAI selector-only smoke showed that a real OpenAI router could recover
the same required source IDs as the deterministic selector on this controlled
large benchmark. Across three live repeats, it selected no distractors, missed
no required sources, used no fallback, and had no parse failures.

The OpenAI selector + deterministic executor benchmark showed that
OpenAI-selected context was sufficient for the existing deterministic answer
contract. This separated live routing from answer synthesis and confirmed that
the selected sources could support the validated output contract.

The OpenAI selector + OpenAI executor smoke showed that the full selected-context
path could pass strict deterministic validation end-to-end. Both source
selection and final answer generation were performed by OpenAI models, while the
executor still received only selected context rather than the full 14-source
context.

Taken together, the sequence supports the SFE hypothesis that selected context
can preserve required source coverage while reducing prompt context on
controlled large real-world inspired fixtures.

## What this does not prove

This benchmark sequence does not prove broad real-world generalization.

It does not prove production readiness, statistical robustness, or reliable
behavior on arbitrary repositories and arbitrary user data. It does not test
gateway behavior yet. It also does not prove that all model choices will behave
the same.

More fixtures, harder distractors, broader task types, and repeated stability
checks are still needed.

## Why the result matters

The progression separates routing, selected-context execution, and final
validation. That makes it easier to identify whether failures come from source
selection, answer generation, parsing, or deterministic validation.

The tests avoid counting fallback as success. The final OpenAI end-to-end smoke
used selected context only, and deterministic validation remained the final
source of truth.

This makes the result more meaningful than a single free-form LLM answer: the
output is machine-checkable, and success requires exact required facts and exact
evidence source IDs.

## Current evidence level

This is a controlled experimental signal, not a general proof.

The current evidence is strongest for the claim that SFE-style selected-context
composition can work on the controlled large real-world inspired benchmark
family under strict deterministic validation.

## Deterministic hardening fixture

The benchmark suite now also includes a deterministic high-overlap poison-pill
fixture. It tests exact source selection under hostile semantic overlap: one
source contains the active authority chain, current cycle date, valid owner,
current threshold, required control action, and rollback condition, while three
nearby sources are deliberately plausible but invalid.

The distractors cover an obsolete or replaced source, a partial telemetry-only
source, and an adversarial source that instructs the selector or executor to
prefer unsafe values. The fixture checks authority, freshness, completeness, and
resistance to adversarial instructions rather than semantic similarity alone.

This is a narrow deterministic fixture. It does not provide statistical proof of
general selector robustness, and it makes no provider or API call.

## High-overlap OpenAI selector repeat-3 smoke

SFE also includes a repeat-3 OpenAI selector-only smoke for the high-overlap
poison-pill fixture. It uses the same deterministic validator as the fixture
above and does not run an executor.

The observed repeat-3 run used OpenAI `gpt-5.4-nano`. Across three consecutive
selector calls, the selector passed all three runs: `run_count = 3`,
`honest_selector_pass_count = 3`, `honest_selector_pass_rate = 1.0`,
`fallback_count = 0`, `parse_failure_count = 0`, `poison_selection_count = 0`,
`obsolete_selection_count = 0`, `partial_selection_count = 0`, and
`mixed_selection_count = 0`. Total recorded usage was 2638 tokens, with total
recorded latency of 7724 ms.

This is a positive limited stability observation for this model on this fixture.
It is not statistical evidence of general selector robustness. The deterministic
validator remains the authority for pass/fail.

## Next sensible steps

- Add more fixtures.
- Add harder distractors.
- Add repeat-N reporting only if useful.
- Compare model choices and routing costs.
- Compare full-context executor vs selected-context executor.
- Later test gateway behavior.

## Closing summary

The current benchmark sequence shows that SFE can move from deterministic
multi-zone composition to a live OpenAI selected-context path while preserving
strict validation on controlled large real-world inspired fixtures.
