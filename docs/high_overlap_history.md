# High-Overlap Benchmark History

Status note: This is a historical/methodology rollup for the High-Overlap
benchmark family. Current project entry points are `README.md` and
`docs/INDEX.md`. High-Overlap is a benchmark family and methodology area, not
the whole current project status. SFE remains experimental and
benchmark-specific.

## Current Visible High-Overlap Docs

These High-Overlap documents remain visible at the top level because they
describe methodology, fixture design, or phase-level interpretation:

- [high_overlap_diagnostic_bucketing_notes.md](high_overlap_diagnostic_bucketing_notes.md):
  diagnostic failure buckets and strict validation interpretation.
- [high_overlap_authority_gap_fixture_expansion_design.md](high_overlap_authority_gap_fixture_expansion_design.md):
  fixture expansion design for authority-gap scenarios.

## Historical Progression

The historical High-Overlap notes recorded controlled progression through
poison-pill, hostile distractor, subtle authority-conflict, and newer
authority-gap fixture checks. The newer fixture observations included selector,
selected-context executor, repeat-3, and selected-vs-full smoke runs.

Those records are local-only developer material. Current readers should use the
visible methodology docs above and the current project overview before
interpreting historical run notes.

## Caveats

- These are controlled benchmark notes, not statistical proof.
- Local observations should not be read as production validation.
- Selected-context vs full-context comparisons are benchmark observations, not
  general claims about model quality or safety.
- Some historical phase notes may include wording that reflects the project
  state at the time they were written.
