# Documentation Index

This repository is a private technical prototype for Spatial Field Engine for
Cognition (SFE), an experimental architecture that separates selection and
routing from execution in long-context LLM workflows. The working hypothesis is
that explicit context selection can make source exposure more auditable and may
reduce unnecessary executor context in some controlled tasks; this repository
does not claim general reliability, safety, or contamination prevention.

## Current Status

The project is source-visible for private review and non-commercial research
under the repository license. The current benchmark material is mainly
synthetic, controlled, and methodology-oriented.

Recent high-overlap work added three additional authority-gap fixtures:

- Aurelia: scope authority conflict.
- Borealis: deprecated memo vs active implementation notice.
- Cassini: policy exception vs active policy.

For these fixtures, deterministic tests pass and limited local OpenAI smoke
observations were clean. No contamination indicators were observed in those
local runs. Selected-context execution did not outperform full-context
execution in the comparison observations because full context also passed. The
useful signal is local non-regression under controlled conditions, not a
general reliability claim.

## Recommended Reading Path

1. Start with [README.md](../README.md) for the project purpose, architecture,
   setup, core commands, and limitations.
2. Read
   [high_overlap_fixture_expansion_phase_close.md](high_overlap_fixture_expansion_phase_close.md)
   for the current high-overlap fixture-expansion status and the next planning
   direction.
3. Read
   [high_overlap_diagnostic_bucketing_notes.md](high_overlap_diagnostic_bucketing_notes.md)
   to understand strict validation, honest pass/fail, and diagnostic failure
   buckets.
4. Read
   [high_overlap_authority_gap_fixture_expansion_design.md](high_overlap_authority_gap_fixture_expansion_design.md)
   for the design intent behind Aurelia, Borealis, and Cassini.
5. Inspect representative runners in `runtime/` and matching tests in `tests/`
   only after the methodology notes are clear.

## Benchmark Families

- Core deterministic benchmark: small local checks for the base SFE execution
  flow.
- Large/contextual benchmark: synthetic context-reduction tasks with fixture
  and router selection modes.
- Large real-world benchmark notes: early OpenAI selector/executor smoke
  observations over curated real-world-style material.
- High-overlap authority-gap benchmarks: controlled fixtures where multiple
  documents share similar vocabulary and differ by authority, scope, freshness,
  or evidence.
- Structural 50k+ stress tests: exploratory large-context stress material
  intended to expose routing and answer-completeness limits.

## High-Overlap Fixture Map

The high-overlap family currently includes:

- Loud poison-pill fixture: an easier adversarial baseline with overt hostile
  behavior.
- Subtle authority-gap fixture: a plausible unauthorized governance update with
  missing authority evidence.
- Aurelia scope-authority fixture: official-looking sources apply to different
  scopes, and only one scope matches the requested case.
- Borealis deprecated-memo fixture: a formal older memo is superseded by a
  newer implementation notice.
- Cassini policy-exception fixture: a general policy looks authoritative, but a
  narrower active exception controls the requested case.

These fixtures test selection, selected-context execution, full-context
comparison, and diagnostic reporting under controlled conditions. They do not
prove that SFE prevents contamination or that selected context generally beats
full context.

## Runner And Observation Map

Use this map before running scripts. Some comparison runner filenames do not
include `openai` even though they call OpenAI when `OPENAI_API_KEY` is present.

| Category | Typical runner pattern | API key required | Notes |
| --- | --- | --- | --- |
| Deterministic runners | `runtime/run_high_overlap_*_benchmark.py` | No | Validate fixtures and report strict deterministic outcomes. |
| Selector-only OpenAI smokes | `runtime/run_high_overlap_*_openai_selector_smoke.py` | Yes for live run | Use blind `candidate-N` handles and validate selected source. |
| Selected-context OpenAI executor smokes | `runtime/run_high_overlap_*_openai_executor_smoke.py` | Yes for live run | Executor receives only deterministic authoritative context. |
| Selected-vs-full OpenAI comparisons | `runtime/run_high_overlap_*_contamination_comparison.py` | Yes for live run | Compare deterministic selected context with full fixture context. |
| Manual repeat observations | Re-run an existing smoke or comparison runner with separate `/tmp` outputs | Yes if the runner calls OpenAI | Local repeat observations only; not statistical reliability claims. |

Generated local reports should stay outside tracked files, preferably under
`/tmp`.

## Metrics And Result Terms

- Deterministic tests validate fixture logic without live provider calls.
- Live smoke observations exercise the existing runners with a configured
  provider and should be read as local observations.
- Selector-only smoke checks source selection only; it does not test final
  answer execution.
- Selected-context executor smoke checks whether the executor can answer from
  the selected authoritative context only.
- Selected-vs-full comparison checks two executor conditions with the same
  task and validator: selected authoritative context and full fixture context.
- Manual repeat observations repeat existing runners and summarize consistency;
  they are not statistical reliability benchmarks.
- Honest pass means the strict output contract passed without fallback, repair,
  provider error, parse failure, or other disqualifying metadata.
- Diagnostic bucketing separates strict failures into field extraction,
  evidence reference, contamination indicator, provider, parse, fallback, and
  repair categories where the report exposes enough information.
- Contamination indicators are mechanical signs such as copied excluded values,
  excluded-source citations, poison instruction following, or mixed
  authoritative and excluded evidence.
- Field extraction failure means the source can be correct while the output
  misses an exact required field.

## What Is Not Claimed

The repository does not claim:

- general robustness;
- statistical reliability;
- production readiness;
- that SFE prevents contamination;
- that full-context LLM execution is generally unsafe;
- that selected context always outperforms full context;
- that authority reasoning is solved;
- that local OpenAI observations generalize across models, prompts, workloads,
  or corpora.

## Gateway Or Proxy Planning

Gateway or Proxy planning should start from the phase-close note, then define:

- pass-through mode;
- SFE-enabled mode;
- activation thresholds;
- provider routing boundaries;
- request and response tracing;
- how local tools would choose between direct execution and SFE-routed
  execution;
- how to preserve non-regression checks when routing through SFE.

The local non-regression signal from the high-overlap fixture expansion is
useful for this planning because pass-through and SFE-enabled routing must not
break requests that already work without SFE. It is not a guarantee that future
Gateway or Proxy behavior will preserve answers in general.
