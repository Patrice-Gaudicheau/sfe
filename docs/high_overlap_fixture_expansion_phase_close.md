# High-Overlap Fixture Expansion Phase Close

Status note: This is a historical phase-close record preserved for
audit/research continuity. High-overlap remains a useful benchmark family and
methodology area, but it is not the whole current project status. Future-looking
Gateway/Proxy wording below reflects the project state at the time; current
terminology treats the SFE Proxy as standby experimental infrastructure. Start
with `README.md` and `docs/INDEX.md` for the latest project overview.

This internal note closes the high-overlap fixture-expansion phase for the
three newer authority-gap fixtures. It records local methodology observations
and a planning decision. It is not a public benchmark claim.

## Fixtures Covered

The phase covered three additional high-overlap authority-gap fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

## Phase Summary

For these three fixtures, the current local state is:

- deterministic tests pass;
- selector-only OpenAI smoke passed locally;
- selector manual repeat-3 observation passed locally;
- selected-context OpenAI executor smoke passed locally;
- selected-context vs full-context comparison passed locally;
- selected-context vs full-context manual repeat-3 observation passed locally.

These observations were local, limited, and non-statistical.

## Current Interpretation

No contamination indicators were observed in these local runs. No
selected-context vs full-context advantage was observed, because the
full-context condition also passed in the comparison observations.

The same local observations provide a limited non-regression signal: in these
tested cases, routing through SFE with a small selector did not degrade answers
that full-context execution also handled correctly. This is not a general
non-regression guarantee and not a statistical claim. It is useful for Gateway
or Proxy planning because pass-through and SFE-enabled routing need to avoid
breaking requests that already work without SFE.

The useful result of this phase is that the fixture plumbing, strict validators,
diagnostic bucketing, selector smokes, executor smokes, and comparison runners
all exercised the new fixtures cleanly in local smoke observations.

This is not a statistical reliability claim, not proof of general robustness,
and not evidence that SFE prevents contamination in general.

## Decision

Do not make these three fixtures more adversarial for now. Close the
high-overlap fixture-expansion phase at the current level of coverage and move
next toward Gateway or Proxy planning, where the work can be easier to integrate
with request flows and local tooling.

## Suggested Next Phase

The next phase should focus on Gateway or Proxy design. Topics to cover include:

- activation threshold;
- pass-through mode;
- SFE-enabled mode;
- provider routing;
- request/response tracing;
- later integration with AgorAi or other local tools.

Any future benchmark result should keep the same cautious framing: local smoke
observation, strict validation unchanged, and no general safety or reliability
claim.
