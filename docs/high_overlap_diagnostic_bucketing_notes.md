# High-Overlap Diagnostic Bucketing Notes

## Purpose

Diagnostic bucketing exists to make high-overlap executor and comparison
reports easier to audit.

The high-overlap benchmark paths still use strict validation as the pass gate.
The diagnostic fields do not change the validator, expected values, prompts, or
fixtures. They only separate why a strict failure happened when the existing
validation and provider metadata already expose enough information to do so.

This note is an internal methodology note. It is not a public performance
claim, not a score improvement mechanism, and not evidence that SFE prevents
contamination in general.

## Strict Validation Remains Unchanged

Strict pass/fail outcomes remain the controlling result:

- `honest_executor_pass`
- `selected_honest_pass`
- `full_context_honest_pass`
- Existing deterministic validation pass/fail behavior

Diagnostic fields do not make a failed run pass. A run with the wrong field
value, wrong evidence reference, copied excluded value, provider error, parse
failure, fallback usage, or repair usage still fails under the same strict
rules.

## Failure Buckets

A strict failure can come from more than one cause. The diagnostic fields keep
those causes visible without treating them as mutually exclusive.

The current buckets include:

- Field extraction failure.
- Evidence reference failure.
- Contamination indicator.
- Provider error.
- Parse failure.
- Fallback usage.
- Repair usage.

The `failure_flags` list can contain multiple flags when a run has multiple
observable issues. For example, a response can both miss an exact field value
and cite an excluded source. The strict outcome remains a failure either way.

## Interpreting Contamination Indicators

Contamination diagnostics are mechanical indicators, not a broad claim about a
model or system.

The current reports distinguish contamination-like evidence such as:

- Copied excluded values.
- Excluded-source citations.
- Poison instruction following.
- Mixed authoritative and excluded evidence when the validator exposes it.

If these indicators are absent, a strict failure should not automatically be
described as contamination. It may instead be an exact-field extraction failure,
an evidence-reference failure, a parse failure, or another output-contract
issue.

## Loud `active_protocol` Observation

Recent limited local OpenAI verification after diagnostic bucketing showed the
loud poison-pill executor and comparison paths failing strictly on
`active_protocol`.

The strict failure remained a failure. The diagnostic fields classified it as a
`field_extraction_failure` because:

- `active_protocol` was listed in `failed_field_names`.
- No copied excluded values were reported.
- No excluded-source citation was reported.
- No poison instruction following was reported.

Under that local observation, the failure is better read as an exact-field
extraction failure than as contamination. This does not weaken strict
validation; it only makes the reason for the strict failure easier to inspect.

## Why This Matters

Without diagnostics, a single strict fail can hide different phenomena:

- The model selected or used the wrong authority.
- The model copied an excluded value.
- The model cited excluded evidence.
- The model produced the right general answer but missed an exact required
  field.
- The provider failed or returned unparsable output.
- Fallback or repair appeared in the path.

With diagnostics, future high-overlap reports are easier to audit without
manually inspecting every JSON payload. The strict pass/fail outcome still
answers whether the run satisfied the benchmark contract. The buckets help
explain what kind of failure was observed under that contract.

## Current Status

The current status should be read cautiously:

- Source selection has been stable in the tested local OpenAI observations.
- No contamination indicators were observed in the latest limited diagnostic
  verification.
- The loud fixture still exposes an exact-field extraction weakness on
  `active_protocol`.
- The subtle fixture passed the latest limited diagnostic verification.

These are local observations only. They are not statistical reliability claims,
not cross-model proof, not production validation, and not evidence that
authority reasoning is solved.

## Non-Goals

Diagnostic bucketing is not:

- A score improvement mechanism.
- A validation weakening.
- A public claim.
- A replacement for future fixture expansion.
- A replacement for larger repeat, temperature, cross-model, or real-world
  corpus testing.

