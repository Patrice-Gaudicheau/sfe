# High-Overlap New Fixture Comparison Notes

This internal note records a limited local observation for the selected-context
vs full-context OpenAI comparison runners added for the newer high-overlap
authority-gap fixtures. It is a methodology and observation note, not a public
benchmark claim.

## Scope

The local observation covered three fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

The executor model was `gpt-5.5`. The run scope was selected-context vs
full-context comparison. The selected-context condition used deterministic
authoritative selection, and no selector call was involved in this comparison.
The same executor model was used for both selected and full conditions.

This observation did not include:

- repeat or stability testing;
- cross-model testing;
- selector plus executor integration;
- statistical reliability measurement.

## Local Observation Summary

In this limited local run, the selected-context condition passed for all three
fixtures, and the full-context condition passed for all three fixtures.

The comparison reports showed:

- no contamination delta observed;
- no copied excluded values;
- no excluded-source citations;
- no failed fields;
- no parse failures;
- no provider errors;
- no fallback usage;
- no repair usage.

These are local comparison observations only. They do not show that the same
results would hold across repeat runs, other models, broader corpora, or a
selector-plus-executor integrated path.

## Interpretation

This was a clean both-pass observation. It does not show a selected-vs-full
advantage on this run, and it also does not show full-context contamination on
this run.

The observation is useful as a narrow check that the comparison runners and
diagnostic fields function on the three new fixtures. It does not prove general
robustness, does not show that SFE prevents contamination, and does not show
that full-context execution is generally unsafe.

## Possible Next Steps

Reasonable next steps, if pursued later, are:

- run repeat-3 selected-vs-full comparison observations;
- make future fixtures more adversarial or higher-overlap;
- later consider cross-model observations;
- later add a selector plus executor integrated path.

Any future result should keep the same cautious framing: controlled comparison
observation, strict validation unchanged, and no general safety or reliability
claim.
