# High-Overlap New Fixture OpenAI Smoke Notes

This internal note records a limited local observation for the selected-context
OpenAI executor smoke runners added for the newer high-overlap authority-gap
fixtures. It is a methodology and observation note, not a public benchmark
claim.

## Scope

The local observation covered three fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

The executor model was `gpt-5.5`. The run scope was selected-context executor
smoke only: each executor received the deterministic authoritative source
context for the fixture.

This observation did not include:

- OpenAI selector testing for these fixtures.
- Full-context comparison with excluded sources visible.
- Repeat or stability testing.
- Cross-model testing.
- Statistical reliability measurement.

## Local Observation Summary

In this limited local run, all three selected-context executor smokes produced
strict passes under the existing validators.

The diagnostic reports showed:

- no copied excluded values;
- no excluded-source citations;
- no parse failures;
- no provider errors;
- no fallback usage;
- no repair usage.

These are local smoke observations only. They do not show that the fixtures
would pass under selector-driven context selection, full-context execution,
repeat runs, other models, or broader corpora.

## Interpretation

The selected-context executor behavior was clean in this limited local
observation. This is useful as a narrow check that, when the authoritative
context is supplied directly, the executor can produce validator-compatible
answers for the three new fixtures.

This does not prove general robustness, does not show that SFE prevents
contamination, and does not establish statistical reliability. It only supports
continuing the benchmark progression with additional controlled observations.

## Possible Next Steps

Reasonable next steps, if pursued later, are:

- add OpenAI selector smoke runners for the three fixtures;
- add selected-context vs full-context comparison runners;
- repeat observations to check small-run stability;
- later consider cross-model observations.

Any future result should keep the same cautious framing: controlled smoke
observation, strict validation unchanged, and no general safety or reliability
claim.
