# Roadmap After Structural 50k

## Current Status

Phase 1 established that SFE can pass an honest structural-routing benchmark on
a synthetic 50k+ token context using the OpenAI API path. The structural result
passed with `honest_structural_pass = true` across five repeated runs, selected
the expected block every time, used no selector fallback, required no output
repair, and preserved about 84% router-inclusive token reduction versus the
full-context baseline.

That result is meaningful because the pass condition is strict: generic executor
success is not enough, fallback is not hidden as success, selected context is
verified, and output repair is reported separately.

The current result is still narrow. It covers one deterministic synthetic task
where the answer lives in a single authoritative block. It does not prove that
SFE is a general cognitive engine, that the approach works on real workloads, or
that spatial composition has been demonstrated across multiple active zones.

## Why the Next Phase Matters

Single-block routing is a strong retrieval result, but it is not sufficient for
the larger SFE claim. Many realistic tasks require combining several kinds of
context: user intent, constraints, domain facts, current code or policy state,
prior decisions, and evidence. Selecting one block tests relevance selection;
assembling several zones tests composition.

Structured retrieval asks: which source contains the answer? Spatial composition
asks: which zones should be active together, what role does each zone play, and
can the executor combine them without losing constraints, evidence, or token
efficiency? Phase 2 should move from single-record selection toward auditable
multi-zone context assembly.

## Phase 2 Goal

Phase 2 should test multi-zone context composition. The router should be able to
select and assemble several relevant zones, not only choose one block. The
executor should receive a compact composed context with explicit zone roles, and
the report should show which zones were selected, how many tokens each zone
cost, which evidence supported the answer, and whether the final output passed
deterministic checks.

The target is not a broad autonomy claim. The target is a controlled engineering
claim: SFE can compose multiple context zones honestly, reduce unnecessary
context, and preserve correctness on tasks where one block is not enough.

## Candidate Next Benchmarks

### Real-World Repository Navigation Benchmark

Create small tasks over this repository or another fixed open-source repository.
Each task should require combining a user request, relevant source files, tests,
and documentation. Example questions could ask which files must change for a
feature, which tests cover a behavior, or why a reported failure occurs.

This benchmark is attractive because the corpus is concrete and auditable. It is
riskier than synthetic fixtures because expected answers may be harder to score
deterministically.

### Documentation / Policy Corpus Benchmark

Build tasks over a fixed documentation or policy corpus where answers require
combining definitions, exceptions, dates, and procedural constraints across
several documents. The benchmark can keep exact validation targets for fields
such as version, threshold, owner, date, exception, and required action.

This benchmark is closer to real knowledge-work retrieval while still allowing
deterministic scoring if tasks are carefully designed.

### Multi-Zone Synthetic Benchmark

Extend the large/contextual framework so each task has several necessary zones,
for example:

- task intent;
- hard constraints;
- domain context;
- evidence records;
- obsolete or conflicting distractors.

The answer should require combining at least two or three selected zones. No
single zone should contain the complete answer. Validation should check exact
fields and should also verify that selected zones contain the required evidence.

This is less realistic than repository or policy work, but it is the safest way
to isolate multi-zone composition mechanics before adding real-world ambiguity.

## Recommended First Benchmark

Start with a small multi-zone synthetic benchmark.

This is the safest next step because it is deterministic, inexpensive, and
directly tests the missing architecture without introducing too many uncontrolled
variables. It can reuse the existing large/contextual runner style, exact target
validation, selection verification, output validation, and structural honesty
reporting. It also allows failure modes to be diagnosed clearly: wrong zone
selection, incomplete zone set, output omission, evidence mismatch, or token
overhead.

The first version should be small: one or two tasks, three to five required
zones, and a repeat-3 or repeat-5 stability run only after the dry and unit-test
contracts are clear.

## Validation Strategy

Keep deterministic validation as the main gate where possible. For structural
fields, continue using exact checks for values such as versions, thresholds,
owners, labels, dates, and dataset names.

Avoid soft semantic validation as the primary pass condition for Phase 2. If a
semantic evaluator is introduced later, it should be reported separately from
deterministic gates. A semantic score can help review quality, but it should not
replace exact validation for benchmark-critical fields.

The Phase 2 report should separate:

- zone selection success;
- selected-zone completeness;
- output validation before repair;
- output validation after repair;
- fallback usage;
- token reduction;
- repeated-run stability.

## Engineering Tasks

- Define a multi-zone selector output schema with explicit zone IDs, zone roles,
  confidence, and short evidence rationale.
- Build a zone composition prompt builder that groups selected context by role
  rather than flattening all selected text.
- Add per-zone token accounting for selected and suppressed zones.
- Add an evidence ledger that records required fields, supporting zone IDs, and
  source snippets or spans.
- Add multi-zone selection verification that checks whether the selected zone
  set contains every required field and evidence source.
- Add a multi-zone validation report with honest pass, after-repair pass, repair
  status, fallback status, and selected-zone completeness.
- Add stability runs for the selected Phase 2 benchmark after single-run
  behavior is clean.
- Update documentation to distinguish single-block structural routing from
  multi-zone spatial composition.

## Risks

- Overclaiming from one benchmark family or one provider.
- Benchmark overfitting to synthetic fixture structure.
- Confusing SFE with ordinary RAG if the system only retrieves documents rather
  than composing role-specific zones.
- Synthetic-only success that does not transfer to repository, documentation, or
  operational tasks.
- Validator ambiguity when answers require synthesis rather than exact field
  extraction.
- Token savings disappearing when zone composition, evidence ledgers, verifier
  passes, or repair steps add too much overhead.
- Hidden fallback or repair being mistaken for raw routing success.

## Success Criteria

A meaningful Phase 2 result should satisfy all of the following:

- the honest pass gate remains strict;
- fallback is never hidden as success;
- selected zones are auditable and reported by ID and role;
- selected-zone completeness is verified;
- token reduction remains meaningful after router and composition overhead;
- reliability is equal to or better than baseline on the benchmark task set;
- results hold across repeated runs;
- repair, if used, is reported separately from raw success.

## Recommended Immediate Next Step

Design one small multi-zone synthetic benchmark task and its validation contract
before implementing new routing behavior. The task should require at least three
zones to answer, have exact deterministic targets, include partial and obsolete
distractors, and define upfront what counts as an honest multi-zone pass.
