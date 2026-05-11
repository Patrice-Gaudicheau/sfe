# Large Real-World OpenAI Selector + Executor Smoke

## Scope

This benchmark uses OpenAI for both source selection and final answer generation.
It uses the large real-world inspired multi-zone benchmark fixtures.

The executor receives only OpenAI-selected source context. It does not receive
the full 14-source context.

The benchmark does not use oracle source IDs as fallback, deterministic executor
output as fallback, or repair. Deterministic validation remains the final pass
gate.

## Benchmark setup

- Fixtures: 2.
- Candidate sources per fixture: 14.
- Required sources per fixture: 4.
- Distractors per fixture: 10.
- The OpenAI selector returns selected source IDs.
- The OpenAI executor receives only the selected source context and must output
  the existing machine-checkable answer contract.
- Output is parsed strictly as JSON.
- The final answer is accepted only if deterministic validation passes.

## Live repeat-3 result

- Router model: `gpt-5.4-nano`.
- Executor model: `gpt-5.5`.
- Repeat count: 3.
- Full honest end-to-end pass runs: 3/3.
- Fixture passes: 6/6.
- Selector exact match rate: 100.00% on all runs.
- Executor parse success rate: 100.00% on all runs.
- Executor validation rate: 100.00% on all runs.
- Honest end-to-end pass rate: 100.00% on all runs.
- Selector fallback count: 0 on all runs.
- Executor fallback count: 0 on all runs.
- Selector parse failure count: 0 on all runs.
- Executor parse failure count: 0 on all runs.
- Distractors selected: 0.
- Required sources missed: 0.
- Average selected-context token reduction: 79.67%.
- Total token usage across 3 runs: prompt 13929, completion 2972, total 16901.
- Selector total across 3 runs: prompt 10260, completion 1065, total 11325.
- Executor total across 3 runs: prompt 3669, completion 1907, total 5576.

## Interpretation

This is the first full OpenAI end-to-end smoke path for this benchmark family.

It is stronger than the selector-only and selector + deterministic executor
benchmarks because both selection and answer generation are performed by OpenAI
models.

The result shows that, within the limited scope of these two controlled
fixtures, the selected context was sufficient for an OpenAI executor to produce
outputs accepted by deterministic validation.

This supports the SFE idea that selected context can preserve required source
coverage while reducing prompt context.

## Limitations

- Only 2 fixtures.
- Two fixtures are not enough to estimate reliability.
- Controlled real-world inspired context, not arbitrary production data.
- Repeat-3 is a functional smoke check, not a stability benchmark or
  statistical validation.
- Model behavior may change.
- Prompt behavior may change.
- Future work should include noisier and more semantically overlapping
  distractors.
- No claim of broad real-world generalization.
- No claim of production readiness.
- No gateway/proxy behavior tested yet.

## Next steps

- Add more fixtures.
- Add repeat-N reporting only if useful.
- Compare router and executor model choices.
- Test larger fixture sets.
- Later test gateway/proxy behavior.
- Eventually compare full-context executor vs SFE-selected-context executor on
  cost, reliability, and validation quality.
