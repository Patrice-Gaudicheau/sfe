# Large Real-World OpenAI Selector + Deterministic Executor

Status note: This is a historical live-smoke record preserved for
audit/research continuity. Start with `README.md` and `docs/INDEX.md` for the
latest project overview.

## Scope

This benchmark uses OpenAI only for source selection. The executor remains
deterministic.

It uses the large real-world inspired multi-zone benchmark fixtures and tests
whether OpenAI-selected sources are sufficient for the existing deterministic
answer contract.

It does not test OpenAI answer generation, and it does not allow oracle fallback
as success.

## Benchmark setup

- Fixtures: 2.
- Candidate sources per fixture: 14.
- Required sources per fixture: 4.
- Distractors per fixture: 10.
- The OpenAI selector receives the candidate sources and returns selected source
  IDs.
- The deterministic executor composes the final benchmark output from selected
  sources only.
- Deterministic validation remains the source of truth.

## Live repeat-3 result

- Router model: `gpt-5.4-nano`.
- Repeat count: 3.
- Full end-to-contract passes: 3/3.
- Selector exact match rate: 100.00% on all runs.
- Deterministic executor validation rate: 100.00% on all runs.
- Honest end-to-contract pass rate: 100.00% on all runs.
- Fallback count: 0 on all runs.
- Parse failure count: 0 on all runs.
- Distractors selected: 0.
- Required sources missed: 0.
- Average selected-context token reduction: 79.67%.
- Total token usage across 3 runs: prompt 10260, completion 1152, total 11412.

## Interpretation

This is stronger than selector-only smoke because it validates the selected
context through the deterministic executor contract.

The selected sources were produced by a live OpenAI selector. The final
benchmark output was built and checked deterministically from the selected
context only.

This supports the idea that real selector output can preserve required source
coverage while reducing context on this controlled benchmark.

## Limitations

- Only 2 fixtures.
- Controlled real-world inspired context, not arbitrary production data.
- Deterministic executor, not OpenAI executor.
- Repeat-3 is a smoke check, not statistical validation.
- No claim of broad real-world generalization.
- No claim of production readiness.

## Next steps

- Add more fixtures.
- Test OpenAI selector + OpenAI executor.
- Compare router models and costs.
- Add repeat-N stability reporting only if needed.
- Later test gateway behavior.
