# Structural Benchmark Note

The `structural` tier is an exploratory 50k+ token stress-test tier for the
existing large/contextual benchmark protocol. It is intended to test whether
flat context injection becomes structurally brittle as context grows, not only
more expensive.

This tier reuses the same runner, prompt builders, selector contract,
validation checks, token reporting, and report writers as the existing
large/contextual benchmark. It is not a separate benchmark family.

It is also not part of the clean amortization curve. The clean curve remains:

- `standard`: 2k-5k token mechanism validation
- `practical`: 10k-20k token realistic amortization test
- `high_context`: 20k-50k token strong SFE relevance zone

The `structural` tier is a separate 50k+ token structural necessity zone.

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

## Route-Then-Verify Behavior

The structural path now includes the first explicit route-then-verify
mechanism:

- Selection verification checks whether the selected context block contains all
  required target values.
- Output validation checks whether the visible executor answer contains all
  required target values.
- Optional output repair can ask the executor to produce a corrected visible
  answer from the same selected context.

The repair path is intentionally narrow. It is structural-only,
`spatial_router`-only, opt-in, and disabled by default with
`--max-output-repairs 0`. It runs only when selection verification is complete,
output validation is incomplete, and missing output targets are known.

This mechanism does not introduce hidden fallback, oracle substitution, a second
candidate retry, or context expansion. In particular, repair is not allowed to
fix a routing mistake. If the selected context is incomplete, repair is skipped.

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

After adding route-then-verify and opt-in output repair, two local Lemonade
structural runs illustrate the separation between routing failure and output
failure:

- With `Qwen3-0.6B-GGUF` as router and `Qwen3.5-35B-A3B-GGUF` as executor, the
  router selected `s9-audit-precheck`. Selection verification marked the block
  incomplete, and output repair was skipped even with `--max-output-repairs 1`.
  This is the desired safety behavior: SFE refused to repair from incomplete
  context.
- With `Qwen3.5-35B-A3B-GGUF` as both router and executor, the router selected
  `atlas-mesh-s9-final`. Selection verification was complete, output validation
  was complete, and repair was not required. No fallback or repair was used.

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

After adding route-then-verify and opt-in output repair, the same structural
task was rerun with `gpt-5.5` as executor and `gpt-5.4-nano` as router. In both
router-inclusive runs, the router selected `atlas-mesh-s9-final`; selection
verification confirmed that the selected context contained all required target
values; and no fallback was used.

With repair disabled (`--max-output-repairs 0`), baseline, `spatial_fixture`,
and `spatial_router` all produced non-empty outputs but omitted `2026.08-s9`.
The `spatial_router` run therefore kept `success=false` and
`success_after_output_repair=false`. The failure remained visible.

With repair enabled (`--max-output-repairs 1`), baseline still missed
`2026.08-s9`, while `spatial_fixture` passed. The `spatial_router` original
output again missed `2026.08-s9`, so output repair ran once from the same
selected context. The repair status was `attempted_complete`, the missing target
list became empty, `output_final_source` was `repaired`, and
`success_after_output_repair` became `true` while the original `success` field
remained `false`. The repair added 3,105 tokens and about 5.6 seconds of
latency in that run.

This is a positive check of the route-then-verify-repair design on one
structural stress case. It remains a small exploratory result, not production
readiness evidence, broad validation, or evidence of improved model
intelligence.

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
- The current route-then-verify path can distinguish routing failure from
  executor-output failure.
- Very long flat-context execution can be backend-sensitive.
- Routing correctness alone does not guarantee answer completeness.

It does not establish production readiness, broad real-world validity, or any
general improvement in model intelligence.

Structural should remain separate from the main publication story unless an
explicit later decision incorporates it. The current result is an exploratory
stress-test signal, not production readiness proof.

## Likely Next Steps

The next useful work is methodological rather than larger one-off runs:

- Add a value-verification pass after routing.
- Require executor answers to include all requested fields in a constrained
  format.
- Compare one-pass routing with route-then-verify selection across repeated
  local runs.
- Repeat structural runs before interpreting stability.
- Add one or two more structural tasks only after the validation contract is
  tightened.
- Keep structural results separate from the main validation curve until baseline
  and selected-context executor validation are stable.
