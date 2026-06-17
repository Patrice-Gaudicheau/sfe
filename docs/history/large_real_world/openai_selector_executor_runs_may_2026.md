# Large Real-World OpenAI Selector/Executor Runs, May 2026

Status note: this is a historical rollup for earlier large real-world-style
OpenAI smoke notes. It preserves local benchmark observations for audit
continuity. It is not current benchmark guidance, production validation, or
statistical reliability evidence.

## Scope

The runs used controlled, project-like multi-zone fixtures:

- 2 fixtures.
- 14 candidate sources per fixture.
- 4 required sources per fixture.
- 10 distractors per fixture, including obsolete, partial, vocabulary-overlap,
  operational, announcement, checklist, and draft-style material.

Deterministic validation remained the source of truth. Oracle or deterministic
fallback was not counted as success.

## Progression

| Stage | Pipeline shape | Result | Token note |
| --- | --- | --- | --- |
| Selector-only smoke | OpenAI selector selected source IDs; no OpenAI answer generation. Router model: `gpt-5.4-nano`. Repeat count: 3. | Full selector passes 3/3. Selector exact match and honest selector pass rate were 100% on all runs. Fallback and parse failure counts were 0. | Average selected-context token reduction was 79.67%. Total usage across 3 runs: prompt 10,260, completion 1,112, total 11,372. |
| Selector plus deterministic executor | OpenAI selector selected source IDs; deterministic executor composed the benchmark output from selected sources only. Router model: `gpt-5.4-nano`. Repeat count: 3. | Full end-to-contract passes 3/3. Deterministic executor validation rate and honest end-to-contract pass rate were 100% on all runs. Fallback count, parse failure count, distractors selected, and required sources missed were all 0. | Average selected-context token reduction was 79.67%. Total usage across 3 runs: prompt 10,260, completion 1,152, total 11,412. |
| Selector plus OpenAI executor | OpenAI selector and OpenAI executor. Router model: `gpt-5.4-nano`; executor model: `gpt-5.5`. Repeat count: 3. Executor received only selected source context. | Full honest end-to-end pass runs 3/3. Fixture passes 6/6. Selector exact match, executor parse success, executor validation, and honest end-to-end pass rates were 100% on all runs. Selector/executor fallback and parse failure counts were 0. | Average selected-context token reduction was 79.67%. Total usage across 3 runs: prompt 13,929, completion 2,972, total 16,901. Selector total was 11,325; executor total was 5,576. |

## Interpretation

The sequence moved from selector-only evidence to selected-context validation
through a deterministic executor, then to a full OpenAI selector plus OpenAI
executor smoke. Within these two controlled fixtures, the selected context was
sufficient for the executor path and preserved required source coverage while
reducing selected context.

The full OpenAI path was the strongest of the three observations because both
selection and answer generation were live model calls. It remained a functional
smoke, not a broad real-world benchmark.

## Limitations

- Only 2 controlled fixtures were tested.
- Repeat-3 was a smoke check, not statistical validation.
- The contexts were real-world inspired, not arbitrary production data.
- Model and prompt behavior may change.
- These notes do not claim production readiness or broad generalization.

## Lessons

- Preserve the distinction between selector-only, selector plus deterministic
  executor, and live selector plus live executor evidence.
- Keep router-inclusive token accounting separate from executor-only selected
  context reduction.
- Treat clean local OpenAI smoke paths as evidence for further benchmark work,
  not as proof that SFE generally improves model quality or safety.
