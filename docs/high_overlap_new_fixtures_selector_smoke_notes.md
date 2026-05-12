# High-Overlap New Fixture Selector Smoke Notes

This internal note records a limited local observation for the OpenAI
selector-only smoke runners added for the newer high-overlap authority-gap
fixtures. It is a methodology and observation note, not a public benchmark
claim.

## Scope

The local observation covered three fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

The selector model was `gpt-5.4-nano`. The run scope was selector-only smoke:
the selector was asked to choose the authoritative candidate for each fixture
using blind `candidate-N` handles.

This observation did not include:

- executor behavior in this selector smoke;
- selected-context vs full-context comparison;
- repeat or stability testing;
- cross-model testing;
- statistical reliability measurement.

## Local Observation Summary

In this limited local run, all three selector smokes selected the expected
authoritative source under the existing selector validators.

The reports showed:

- no fallback usage;
- no repair usage;
- no provider errors;
- no parse failures;
- no unknown candidate failures;
- no duplicate candidate failures.

These are local smoke observations only. They do not show that the selector
would behave the same way across repeat runs, other models, broader corpora, or
full-context executor conditions.

## Interpretation

The selector behavior was clean in this limited local observation. This
complements the previous selected-context executor smoke for the same three
fixtures by checking the selector-only path separately.

This does not prove general robustness, does not show that SFE prevents
contamination, and does not establish statistical reliability. It only supports
continuing the benchmark progression with additional controlled observations.

## Possible Next Steps

Reasonable next steps, if pursued later, are:

- run repeat-3 selector observations for the three fixtures;
- add selected-context vs full-context comparison runners;
- later consider cross-model observations.

Any future result should keep the same cautious framing: controlled smoke
observation, strict validation unchanged, and no general safety or reliability
claim.
