# High-Overlap New Fixture Smoke Runs, May 2026

Status note: this is a historical rollup for the newer High-Overlap
authority-gap fixture smoke notes. It preserves local benchmark observations
for audit continuity. It is not current project status, statistical reliability
evidence, or a production-readiness claim.

## Scope

The May 2026-era observations covered three newer authority-gap fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

The runs exercised three narrow paths:

- OpenAI selector-only smokes using `gpt-5.4-nano` and blind `candidate-N`
  handles.
- Selected-context OpenAI executor smokes using `gpt-5.5` with deterministic
  authoritative context.
- Selected-context vs full-context OpenAI executor comparisons using `gpt-5.5`.

## Results

| Observation | Model path | Outcome | Important limitation |
| --- | --- | --- | --- |
| Selector smoke | `gpt-5.4-nano` selector | All three fixtures selected the expected authoritative source. Reports showed no fallback, repair, provider errors, parse failures, unknown candidates, or duplicate candidates. | Single local selector-only smoke; no repeat, executor, comparison, cross-model, or statistical coverage. |
| Selector repeat-3 | `gpt-5.4-nano` selector | Aurelia, Borealis, and Cassini each selected the authoritative source in 3/3 runs, for 9/9 selector passes. No fallback, repair, provider errors, parse failures, unknown candidates, duplicate candidates, or observed inconsistency. | Manual repeat-3 because these fixtures did not yet have dedicated repeat runners. |
| Selected-context executor smoke | `gpt-5.5` executor | All three selected-context executor smokes passed strict validators. Reports showed no copied excluded values, excluded-source citations, parse failures, provider errors, fallback, or repair. | Deterministic authoritative context was supplied directly; this did not test selector-driven execution or full-context exposure. |
| Selected vs full comparison | `gpt-5.5` executor | Selected-context and full-context conditions both passed for all three fixtures. Reports showed no contamination delta, copied excluded values, excluded-source citations, failed fields, parse failures, provider errors, fallback, or repair. | Clean both-pass observation only; it does not show a selected-context advantage or prove full-context safety. |

## Interpretation

The newer fixtures behaved cleanly across the limited local observations. The
selector path chose the expected authoritative documents, the selected-context
executor could answer when given authoritative context, and the comparison
runners produced useful diagnostics.

The observations do not prove general robustness, contamination prevention, or
statistical reliability. They supported continuing the benchmark progression
with stricter repeat, integration, and cross-model checks.

## Lessons

- Keep High-Overlap results framed as controlled fixture observations.
- Report selected-context executor, full-context comparison, and selector-only
  observations separately.
- Preserve fallback, repair, provider-error, and parse-failure fields because
  they are part of the honest-pass boundary.
- Avoid claiming a selected-vs-full advantage when both conditions pass.
