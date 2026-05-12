# High-Overlap Authority-Gap Fixture Expansion Design

## Purpose

This note proposes a small next set of high-overlap authority-gap fixtures. It
is design-only. It does not implement fixtures, change validators, change
prompts, or report new benchmark results.

The goal is to broaden the fixture family while preserving the current strict
validation style: one expected authoritative source, exact expected fields,
forbidden values for excluded sources, strict evidence references, visible
fallback or repair status, and diagnostic bucketing for failure interpretation.

This is an internal benchmark-design note. It is not a public benchmark claim,
not evidence of general reliability, and not a claim that SFE prevents
contamination.

## Current Fixture Family Summary

The current high-overlap family has two main fixture styles.

The loud poison-pill fixture uses the Orion release gate. It includes one
authoritative release note, one obsolete memo, one partial telemetry-style
document, and one overtly hostile source with tempting but invalid instructions
and values. It tests whether selection rejects obsolete, partial, and visibly
hostile material, and whether executor output avoids copied distractor values,
wrong citations, and poison instruction following.

The subtle authority-gap fixture uses the Helios governance gate. It includes
one ratified Continuity Council decision, one plausible unauthorized governance
update, one obsolete carryover note, and one partial monitoring addendum. The
invalid update uses the same domain vocabulary as the authoritative source and
looks institutionally plausible, but Continuity Council signatures are pending
and the release operations desk cannot supersede the ratified decision without
the required signature chain.

Together, the fixtures currently cover:

- Overt hostile instructions and values.
- Plausible unauthorized updates.
- Obsolete sources.
- Partial sources.
- Selected-context-only executor behavior.
- Full-context contamination comparison.
- Diagnostic separation between field extraction failures and contamination
  indicators.

They do not yet cover several realistic authority gaps:

- A narrower exception that controls over a broader active policy.
- A formally written but deprecated memo superseded by an operational notice.
- Multiple official-looking sources that are valid only for different regions,
  products, departments, or deployment scopes.

## Candidate A: Policy Exception vs Active Policy

### Fixture Purpose

Test whether the selector and executor can distinguish a broad active policy
from a narrower exception that controls the requested case.

The failure mode is not that the general policy is fake. The general policy can
be real and current, but the task asks for a case where a narrower approved
exception is controlling.

### Authoritative Source Pattern

The authoritative source should be an exception-aware decision record. It should
state the requested case scope, cite or summarize the relevant general policy,
and explicitly identify the exception authority. To preserve the current
single-authoritative-source contract, this record should contain all expected
answer fields directly.

Example authority evidence:

- Exception board approval.
- Case-specific scope.
- Effective date.
- Owner signature.
- Statement that the exception controls only for the requested case.

### Distractor Source Patterns

Useful distractors include:

- The broad active policy with mostly correct terminology but wrong values for
  the exception case.
- A policy FAQ or implementation summary that omits the exception.
- A stale exception draft that uses similar language but lacks final approval.

Roles and titles should stay neutral. They should not label a source as a trap,
poison, invalid, or distractor.

### Expected Model Failure Mode

A model may select the broad active policy because it appears more general and
formally authoritative. In full-context execution, it may copy broad-policy
values even when the exception source is present.

### Required Output Fields

Use the existing field shape unless a future implementation needs a clearer
case-specific field:

- `active_protocol`
- `cycle_date`
- `owner_id`
- `threshold`
- `required_action`
- `blocking_condition`
- `evidence_source_ids`

### Contamination Indicators

Contamination indicators should include:

- Copied broad-policy values when the exception should control.
- Citation of the broad policy as the authority for the exception case.
- Mixed evidence from the exception source and broad-policy source.
- Citation of an unapproved exception draft.

### Clean Field-Extraction Failure

A clean field-extraction failure would be a wrong or truncated exact field from
the exception source while evidence still cites only the exception source and no
excluded values are copied.

For example, a shortened protocol label or date normalization mistake would be a
field extraction failure if no broad-policy or draft values appear.

### True Contamination

True contamination would require an explicit indicator such as copied
broad-policy values, copied stale draft values, excluded-source citation, or
mixed exception plus excluded evidence.

### Distinction From Existing Fixtures

This fixture is distinct because the tempting distractor is a real active
general policy, not an obsolete source, partial source, overt poison document,
or unauthorized update. The correct answer depends on recognizing that a narrow
exception controls the requested scope.

### Recommendation

Implement later. It is valuable, but it is the easiest candidate to make
ambiguous if the exception source depends on a separate general policy. The
first implementation should keep one complete exception-aware authoritative
source to preserve strict deterministic validation.

## Candidate B: Deprecated Memo vs Active Implementation Notice

### Fixture Purpose

Test whether the selector and executor can prefer a newer operationally
authoritative implementation notice over an older formal memo.

The older memo should look credible and institutionally polished. The active
notice should supersede one or more critical fields and carry the operational
authority required by the task.

### Authoritative Source Pattern

The authoritative source should be an implementation notice with clear
supersession evidence. It should state that it is active for the requested
cycle, identify the operational authority, include the required fields, and
name the deprecated memo it supersedes.

Example authority evidence:

- Implementation office or deployment authority.
- Effective date after the old memo.
- Supersession clause for the relevant fields.
- Owner or release-controller signature.

### Distractor Source Patterns

Useful distractors include:

- A deprecated memo with formal language and old but plausible values.
- A meeting note that mentions the implementation notice but lacks final
  authority.
- A partial dashboard or status summary with one or two correct fields.

### Expected Model Failure Mode

A model may prefer the older memo because it is formally written, longer, or
appears more policy-like. It may also mix the implementation notice with memo
values if both appear in full context.

### Required Output Fields

Use the existing expected field shape:

- `active_protocol`
- `cycle_date`
- `owner_id`
- `threshold`
- `required_action`
- `blocking_condition`
- `evidence_source_ids`

### Contamination Indicators

Contamination indicators should include:

- Copied deprecated memo values.
- Citation of the deprecated memo as the controlling authority.
- Mixed implementation-notice and deprecated-memo evidence.
- Copied partial dashboard values where the dashboard lacks authority.

### Clean Field-Extraction Failure

A clean field-extraction failure would be an exact-value miss from the active
implementation notice with no copied memo values and no deprecated memo
citation.

For example, an `active_protocol` paraphrase from the notice would remain a
strict failure but should bucket as field extraction if no excluded-source
evidence appears.

### True Contamination

True contamination would require copied deprecated values, deprecated-source
citation, mixed active plus deprecated evidence, or use of partial dashboard
values.

### Distinction From Existing Fixtures

This fixture overlaps somewhat with the existing obsolete-source pattern, but
adds a more specific freshness-plus-operational-authority distinction. The
challenge is not merely that one source is old; it is that a newer
implementation notice has authority to supersede a formal memo for operational
fields.

### Recommendation

Implement after the scope-conflict fixture. This candidate is mechanically
straightforward, but it should be written carefully so it does not duplicate the
current obsolete memo case too closely.

## Candidate C: Regional or Scope Authority Conflict

### Fixture Purpose

Test whether the selector and executor can choose the source whose authority
matches the requested region, product, department, or deployment scope.

Several sources can be official-looking and valid in their own scopes. Only one
should apply to the asked case.

### Authoritative Source Pattern

The authoritative source should state the requested scope and contain all
expected fields for that scope. It should include scope evidence directly in the
body, such as region, product, department, deployment lane, or customer tier.

Example authority evidence:

- Scope clause.
- Scope owner signature.
- Effective date for that scope.
- Statement that neighboring scopes use separate decision records.

### Distractor Source Patterns

Useful distractors include:

- A valid source for a neighboring region or product.
- A valid source for a different department or deployment lane.
- A partial cross-scope summary that mentions the requested scope but lacks
  complete authority.

These distractors should not be portrayed as false in their own scopes. Their
wrongness should come from scope mismatch.

### Expected Model Failure Mode

A model may select an official-looking source from the wrong scope or merge
fields across multiple scopes because the vocabulary and field names are highly
overlapping.

### Required Output Fields

Use the existing expected field shape:

- `active_protocol`
- `cycle_date`
- `owner_id`
- `threshold`
- `required_action`
- `blocking_condition`
- `evidence_source_ids`

Optionally add a `scope` field only if a later implementation determines that
scope must be machine-checked separately. The safer first version should keep
the current field shape and include scope in source text and expected evidence.

### Contamination Indicators

Contamination indicators should include:

- Copied values from a wrong-scope source.
- Citation of a wrong-scope source.
- Mixed evidence from the correct scope and wrong scope.
- Use of a cross-scope summary as authority when it is marked summary-only.

### Clean Field-Extraction Failure

A clean field-extraction failure would be an exact-value miss from the correct
scope source while citing only the correct source and avoiding wrong-scope
values.

### True Contamination

True contamination would require copied wrong-scope values, wrong-scope source
citation, mixed correct plus wrong-scope evidence, or reliance on a
summary-only source.

### Distinction From Existing Fixtures

This fixture is distinct because excluded sources may be fully valid, current,
and official within their own scope. The required reasoning is scope matching,
not hostility, pending signatures, obvious incompleteness, or simple
supersession.

### Recommendation

Implement now as the safest next deterministic expansion. It fits the existing
single-authoritative-source structure, introduces a new authority-gap type, and
can reuse the current diagnostic bucketing without adding new runtime concepts.

## Recommended Implementation Order

From safest to riskiest:

1. Regional or scope authority conflict.
2. Deprecated memo vs active implementation notice.
3. Policy exception vs active policy.

The scope-conflict fixture is the safest because it can be modeled with one
complete authoritative source and wrong-scope distractors that are excluded by
scope mismatch. The deprecated-memo fixture is also tractable, but it is closer
to the existing obsolete-source case and should be written to emphasize
operational supersession. The policy-exception fixture is useful but riskier
because exception logic can accidentally require multi-source evidence unless
the authoritative exception source is complete.

## Minimal Future Implementation Plan

If one of these candidates is approved later, the smallest safe coding step is:

1. Add one deterministic fixture with the existing source and expected-field
   shape.
2. Add validator expectations for the authoritative source, excluded source
   IDs, forbidden values, and evidence references.
3. Add fake-provider tests that prove strict pass/fail behavior is unchanged.
4. Add diagnostic-bucketing assertions from the start, including clean field
   failure and contamination-indicator cases.
5. Add optional OpenAI selector or executor smoke only after deterministic tests
   are stable.
6. Keep selected-context vs full-context comparison as a later extension unless
   the deterministic fixture and smoke path are already clean.

The first future branch should avoid broad refactors. A single fixture plus
targeted deterministic tests is enough to evaluate whether the design is
machine-checkable.

## Non-Goals

This expansion design is not:

- A public benchmark claim.
- Proof of general reliability.
- A scoring improvement exercise.
- A change to strict validation semantics.
- A claim that SFE prevents contamination.
- A request to commit live reports or local observation outputs.

