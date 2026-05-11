# High-Overlap Subtle-Poison Progression Summary

## Purpose

This document summarizes the completed high-overlap subtle-poison benchmark
phase.

The phase extends the earlier high-overlap poison-pill work from overt hostile
behavior toward subtler authority-gap failure modes. It remains a small,
controlled fixture progression. It is not statistical proof, not production
validation, and not a broad RAG safety benchmark.

## What Was Tested

The subtle-poison fixture uses high semantic overlap among sources that all look
relevant to the Helios Guard governance gate. The invalid source is plausible on
first reading: it is framed as a governance update for the same policy and uses
the same domain vocabulary as the authoritative source.

The progression covered:

- A deterministic high-overlap subtle-poison fixture.
- A plausible unauthorized governance update.
- Missing or pending authority evidence.
- Continuity Council signatures pending.
- A release operations desk note that cannot supersede a ratified council
  decision without the required signature chain.
- No obvious fake, poison, or adversarial labels in the source text.
- High semantic overlap between authoritative, obsolete, partial, and
  unauthorized update sources.
- Deterministic validation of selection and final answer integrity.
- An OpenAI selector-only smoke test.
- An OpenAI selector repeat-3 smoke test.
- An OpenAI executor smoke using selected authoritative context only.
- A selected-context vs full-context contamination comparison.

The executor work intentionally separated selected-context-only execution from
full-context execution. The selected-context condition physically excluded the
unauthorized update, obsolete source, and partial source from the executor
prompt. The full-context condition included all fixture sources together.

## What Was Observed

The observations should be read cautiously.

Within this controlled fixture, deterministic validation checked that the
authoritative source was selected and that the unauthorized update, obsolete
source, and partial source were rejected. The OpenAI selector smoke tests
exercised the same authority-gap reasoning contract as functional smoke tests.

The selected-context-only executor smoke checked whether an OpenAI executor
could answer from only the selected authoritative context, with deterministic
answer validation as the pass gate.

The selected-context vs full-context contamination comparison reported observed
contamination indicators, including copied unauthorized update values, obsolete
or partial values, excluded source citations, and mixed authoritative plus
unauthorized evidence. Under this fixture, the comparison can show an observed
integrity delta under controlled conditions.

Across the phase, results were reported as honest pass/fail observations. No
fallback or repair path was counted as success.

## What Was Not Proven

This phase does not prove broad reliability.

It does not establish:

- Statistical proof.
- General robustness proof.
- Proof that SFE is safe.
- Proof that full-context LLMs are generally unsafe.
- Production validation.
- A broad RAG safety benchmark.
- Cross-model validation.
- Proof that authority reasoning is solved.

The result is best treated as a smoke observation from a controlled fixture. It
does not generalize by itself to arbitrary corpora, models, prompts, or
deployments.

## Why This Matters

The earlier poison-pill fixture tested louder hostile behavior. This phase moves
toward subtle authority-gap failure modes, where the invalid source is plausible
rather than overtly hostile.

That distinction matters for context integrity. A model reading all sources must
resolve authority evidence, signature status, supersession authority, freshness,
and completeness while also ignoring a nearby unauthorized update with tempting
values. A selected-context executor only receives the source that selection has
accepted as authoritative.

Physical exclusion of unauthorized updates is different from asking the model to
ignore them. In this phase, selected-context execution can be evaluated as a
structural guardrail hypothesis under controlled conditions. This is still only
a hypothesis supported by fixture-level smoke observations, not a general safety
claim.

Full-context success remains a valid observation. Selected-context failure also
remains a valid observation. The comparison is useful because it records which
condition passed, which condition failed, and which contamination indicators
appeared under the same deterministic final validator.

## Limitations

The current evidence is intentionally narrow:

- Small controlled fixture count.
- No large repeat benchmark.
- No live API results committed.
- No temperature or stochasticity exploration.
- Prompts may still be task-specific.
- No real-world corpus contamination test.
- No cross-model comparison yet.
- No unified benchmark runner yet.

These limitations should remain visible when interpreting the phase.

## Next Steps

Useful next steps include:

- Optionally run the live OpenAI smoke or comparison paths if desired, with
  generated reports kept out of commits unless repository convention allows
  them.
- Harden documentation after any live observations are reviewed.
- Consider a unification branch for repeated prompt builders and summary
  helpers across loud and subtle comparison runners.
- Optionally explore temperature and cross-model behavior later.
- Eventually broaden the benchmark family with multiple subtle authority-gap
  fixtures.

Any follow-up should keep the same cautious framing: controlled fixture,
authority-gap reasoning, honest pass/fail, and integrity delta under controlled
conditions.
