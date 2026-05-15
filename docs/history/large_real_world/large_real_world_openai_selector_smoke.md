# Large Real-World OpenAI Selector Smoke

## Scope

This is a selector-only smoke test using the large real-world inspired multi-zone benchmark fixtures.

The benchmark tests whether an OpenAI router can recover the exact required source IDs from a larger controlled project-like context. It does not test OpenAI answer generation, end-to-end answer quality, or production behavior.

Oracle or deterministic fallback is not counted as success.

## Benchmark Setup

- 2 fixtures
- 14 candidate sources per fixture
- 4 required sources per fixture
- 10 distractors per fixture
- Distractors include obsolete, partial, vocabulary-overlap, operational, announcement, checklist, and draft-style material.
- Deterministic validation remains the source of truth.

## Live Repeat-3 Result

- Router model: `gpt-5.4-nano`
- Repeat count: 3
- Full selector passes: 3/3
- Selector exact match rate: 100.00% on all runs
- Honest selector pass rate: 100.00% on all runs
- Fallback count: 0 on all runs
- Parse failure count: 0 on all runs
- Average selected-context token reduction: 79.67%
- Total token usage across 3 runs: prompt 10260, completion 1112, total 11372

## Interpretation

This is the first live signal that a real OpenAI selector can recover the same required sources as the deterministic selector on this controlled large benchmark.

The result supports the idea that SFE-style routing can preserve required source coverage while reducing selected context. It is encouraging, but limited.

## Limitations

- Only 2 fixtures were tested.
- The context is controlled and real-world inspired, not arbitrary production data.
- This is selector-only; it does not include an OpenAI executor.
- Repeat-3 is a smoke check, not statistical validation.
- This result is not a claim of broad real-world generalization.

## Next Steps

- Repeat with more fixtures.
- Test OpenAI selector with deterministic executor.
- Then test OpenAI selector with OpenAI executor.
- Later compare model sizes and routing costs.
