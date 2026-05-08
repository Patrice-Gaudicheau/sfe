# Structural Benchmark Note

The `structural` tier is an exploratory 50k+ token stress-test tier for the
existing large/contextual benchmark protocol. It is intended to test whether
flat context injection becomes structurally brittle as context grows, not only
more expensive.

This tier reuses the same runner, prompt builders, selector contract,
validation checks, token reporting, and report writers as the existing
large/contextual benchmark. It is not a separate benchmark family.

## Why This Tier Exists

The existing tiers cover:

- `standard`: 2k-5k token mechanism validation
- `practical`: 10k-20k token router-cost amortization checks
- `high_context`: 20k-50k token strong SFE relevance zone

The `structural` tier pushes beyond those ranges. It uses many realistic
structured-document blocks with overlapping fields, schema-like distractors,
obsolete values, partial records, runbook language, catalogs, rosters,
checklists, and final-record references.

The goal is not simply to make a larger prompt. The task is designed so the
selector must prefer answer completeness over topical similarity. Exactly one
block contains all requested values. Several distractors contain the right
field names, adjacent values, or plausible operational context without being
sufficient to answer the question.

## Current Task Shape

The first structural task is:

`large_contextual_structural_atlas_policy_mesh_gate`

The expected block is:

`atlas-mesh-s9-final`

The validation targets are:

- `42.7`
- `SableReplay-144`
- `ATLAS_OWNER_S9`
- `mesh_s9_epoch_pin`
- `2026.08-s9`

The task currently has one relevant block and nineteen distractor blocks.

## Lemonade Findings

Initial Lemonade runs show that structural behavior is backend-sensitive:

- The fixture/oracle selected-context path succeeded.
- Later flat baseline runs around 74k input tokens produced empty output, even
  when Lemonade context size was increased to 256K.
- A local `Qwen3-0.6B-GGUF` router failed twice on the same task. It selected
  valid but wrong blocks: first `s9-audit-precheck`, then `sable-replay-catalog`.
- A local `Qwen3.5-35B-A3B-GGUF` router selected `atlas-mesh-s9-final`, and the
  `spatial_router` execution passed.

These results suggest that structural-tier routing depends on router model
capacity or a stronger verification step. They should not be read as proof that
a particular model family is generally sufficient or insufficient.

## OpenAI Findings

The OpenAI API path was also tested as an exploratory structural stress case.

In the fixture-only run:

- The baseline produced non-empty output, unlike the later Lemonade baseline
  runs, but missed `2026.08-s9`.
- The spatial fixture path passed all validation targets in that run.

In the router-inclusive run:

- The configured router selected `atlas-mesh-s9-final`.
- No fallback was used.
- Router-inclusive total token reduction was 84.30%.
- Estimated router-inclusive cost reduction versus baseline was about 93.10%.
- However, baseline, `spatial_fixture`, and `spatial_router` all missed
  `2026.08-s9` in that run.

This means the router handled the schema-versus-value selection, but executor
answer completeness was not stable across modes and runs.

## Interpretation

The structural tier should be treated as a stress test, not as part of the
clean OpenAI validation curve.

The clean OpenAI validation curve covers `standard`, `practical`, and
`high_context` runs where the fixture path succeeded before router-inclusive
results were interpreted. Structural does not currently meet that standard
because executor validation was not stable across modes.

The current structural evidence supports narrower observations:

- Selected-context execution can keep executor context small at structural
  scale when the correct block is selected.
- Single-pass routing becomes harder when distractors contain schemas,
  checklists, partial values, and related records.
- Stronger routers can improve structural selection on this task.
- Very long flat-context execution can be backend-sensitive.
- Routing correctness alone does not guarantee answer completeness.

It does not establish production readiness, broad real-world validity, or any
general improvement in model intelligence.

## Likely Next Steps

The next useful work is methodological rather than larger one-off runs:

- Add a value-verification pass after routing.
- Require executor answers to include all requested fields in a constrained
  format.
- Compare one-pass routing with route-then-verify selection.
- Repeat structural runs before interpreting stability.
- Add one or two more structural tasks only after the validation contract is
  tightened.
- Keep structural results separate from the main validation curve until baseline
  and selected-context executor validation are stable.

