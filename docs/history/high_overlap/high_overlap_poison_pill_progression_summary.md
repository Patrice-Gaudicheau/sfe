# High-Overlap Poison-Pill Progression Summary

## Purpose

This document summarizes the recently completed high-overlap poison-pill
benchmark progression.

The phase extends SFE evaluation from token and context reduction toward
context-integrity testing under controlled hostile conditions. It remains a
small, controlled benchmark progression. It is not a statistical proof, not
production validation, and not a broad RAG safety benchmark.

## What Was Tested

The benchmark family uses a high semantic-overlap fixture where several sources
look relevant to the same release decision but differ in authority,
completeness, freshness, or trustworthiness.

The progression covered:

- A deterministic high-overlap poison-pill benchmark.
- An obsolete document from the same release family.
- A partial telemetry-only document with some correct values but missing
  authority, required action, and rollback evidence.
- A misleading wrong-authority document that overlaps with the task but lacks
  the controlling decision basis.
- A poison-pill document that contains attractive but invalid instructions and
  values.
- Selector behavior under strict deterministic validation.
- OpenAI selector smoke behavior on the same controlled fixture.
- OpenAI selector repeat-3 smoke behavior.
- OpenAI executor smoke behavior with selected context only.
- A selected-context vs full-context contamination comparison.

The executor comparisons intentionally separated selected-context-only
execution from full-context execution. The selected-context condition physically
excluded distractors from the executor prompt. The full-context condition
included the authoritative source and the hostile distractors together.

## What Was Observed

The observations should be read cautiously.

Within this controlled fixture, the deterministic validation path checked that
the selector chose the authoritative source and omitted obsolete, partial, and
poison-pill sources. The OpenAI selector smoke tests exercised the same strict
selection contract as functional smoke tests.

The selected-context-only executor smoke checked whether an OpenAI executor
could answer from the selected source context only, with deterministic answer
validation as the pass gate. It did not use fallback or repair as success.

The selected-context vs full-context contamination comparison added a controlled
comparison between two executor conditions on the same fixture. It reported
contamination indicators such as copied distractor values, poison instruction
markers, and distractor source citations. Under this fixture, the comparison can
show an observed integrity delta between selected-context execution and
full-context execution.

Across the phase, validation remained deterministic. Fallback and repair were
kept visible and were not counted as honest success.

## What Was Not Proven

This phase does not prove broad reliability.

It does not establish:

- Statistical proof.
- General robustness proof.
- Proof that SFE is safe.
- Proof that full-context LLMs are generally unsafe.
- Production validation.
- A broad RAG safety benchmark.
- General behavior across arbitrary corpora, models, prompts, or deployments.

The result is best treated as controlled evidence that this fixture can expose a
context-integrity difference between physically selected context and full
context with distractors.

## Why This Matters

SFE initially focused on token and context reduction: select the context needed
for a task, keep the executor prompt smaller, and validate the resulting answer.

This phase adds a related but different question: whether selected-context
execution can be evaluated as a structural guardrail under controlled hostile
conditions.

Physical exclusion of distractors is different from merely instructing a model
to ignore them. In selected-context execution, obsolete, partial, and
poison-pill documents are absent from the executor prompt when selection is
correct. In full-context execution, the model must both find the authoritative
source and resist conflicting nearby material inside the same prompt.

That distinction matters for context integrity. The benchmark does not show
that SFE is safe in general, but it gives a concrete way to measure whether
source selection and selected-context execution preserve the authoritative
answer contract under a controlled hostile setup.

## Limitations

The current evidence is intentionally narrow:

- Small controlled fixture count.
- Functional smoke tests rather than a large repeat benchmark.
- Prompts may still be prescriptive.
- No subtle poison fixtures yet.
- No broad stochasticity or temperature exploration.
- No real-world corpus contamination test yet.
- No production traffic or deployment path was validated.
- Model behavior may change over time.

These limitations should remain visible when interpreting the results.

## Next Step

The next logical branch is:

`feature/high-overlap-subtle-poison-fixtures`

That phase should add more plausible false updates and amendments without
obvious fake or poison labels. The invalid sources should be rejected because
they lack authority, signature, supersession, governance evidence, or complete
decision basis, not because they are visibly adversarial.

The deterministic validation should remain strict. A later selected-context vs
full-context comparison can be preserved as a separate extension if it is useful,
but the first step should be to make the fixture family less obvious while
keeping the pass contract machine-checkable.
