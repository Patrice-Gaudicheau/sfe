# High-Overlap New Fixture Selector Repeat-3 Notes

This internal note records a limited local repeat observation for the OpenAI
selector-only smoke runners added for the newer high-overlap authority-gap
fixtures. It is a methodology and observation note, not a public benchmark
claim.

## Scope

The local observation covered three fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

The selector model was `gpt-5.4-nano`. The run scope was selector-only manual
repeat-3 observation: each fixture's existing selector-only smoke runner was
run three times with separate local reports.

This observation did not include:

- executor behavior in this selector repeat observation;
- selected-context vs full-context comparison;
- a dedicated repeat-3 runner for these fixtures;
- cross-model testing;
- statistical reliability measurement.

Manual repeat-3 was used because the three new fixtures do not yet have
dedicated repeat-3 selector runners.

## Local Observation Summary

In this limited local run, all three fixtures selected the expected
authoritative source in each of the three selector observations:

- Aurelia: 3/3 authoritative selections.
- Borealis: 3/3 authoritative selections.
- Cassini: 3/3 authoritative selections.

Across the nine selector observations, the reports showed:

- 9/9 total selector passes;
- no fallback usage;
- no repair usage;
- no provider errors;
- no parse failures;
- no unknown candidate failures;
- no duplicate candidate failures;
- no observed inconsistency across runs.

These are local repeat observations only. They do not show that the selector
would behave the same way across larger repeats, other models, broader corpora,
or full-context executor conditions.

## Interpretation

The selector behavior was stable in this limited local repeat-3 observation.
This complements the previous selected-context executor smoke for the same
three fixtures by checking repeated selector-only behavior separately.

This does not prove general robustness, does not show that SFE prevents
contamination, and does not establish statistical reliability. It only supports
continuing the benchmark progression with additional controlled observations.

## Possible Next Steps

Reasonable next steps, if pursued later, are:

- add selected-context vs full-context comparison runners for the three
  fixtures;
- add dedicated repeat-3 selector runners if repeated selector observations
  become common;
- later consider cross-model observations.

Any future result should keep the same cautious framing: controlled smoke
observation, strict validation unchanged, and no general safety or reliability
claim.
