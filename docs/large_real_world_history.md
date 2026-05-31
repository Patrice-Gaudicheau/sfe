# Large Real-World Benchmark History

Status note: This is a historical benchmark rollup. Current project entry
points are `README.md` and `docs/INDEX.md`. The current large/contextual
benchmark reference is `docs/large_contextual_benchmark_report.md`. SFE remains
experimental and benchmark-specific.

## Current Visible Benchmark Docs

Use these documents for the current benchmark picture:

- [large_contextual_benchmark_report.md](large_contextual_benchmark_report.md):
  current large/contextual benchmark methodology and report notes.
- [provider_comparison_summary.md](provider_comparison_summary.md): current
  cross-provider summary for protocol-aligned OpenAI and Anthropic campaigns.
- [token_cost_metrics.md](token_cost_metrics.md): token accounting and
  router-inclusive reduction details.

## Historical Progression

The Large Real-World notes record an earlier benchmark progression over
controlled, project-like multi-zone fixtures:

- [large_real_world_benchmark_progression_summary.md](history/large_real_world/large_real_world_benchmark_progression_summary.md):
  synthesis of the progression from deterministic validation through live
  OpenAI selector and executor smoke tests.
- [large_real_world_openai_selector_smoke.md](history/large_real_world/large_real_world_openai_selector_smoke.md):
  OpenAI selector-only smoke observations.
- [large_real_world_openai_selector_deterministic_executor.md](history/large_real_world/large_real_world_openai_selector_deterministic_executor.md):
  OpenAI selector plus deterministic executor observations.
- [large_real_world_openai_selector_executor_smoke.md](history/large_real_world/large_real_world_openai_selector_executor_smoke.md):
  OpenAI selector plus OpenAI executor smoke observations.

These notes are useful for audit continuity, but they are not the current
headline benchmark documentation.

## Caveats

- These are historical progression notes over controlled fixtures.
- Local observations are not statistical proof or production validation.
- Some historical integration terminology reflects the project state at the
  time the notes were written; current terminology uses Proxy for the standby
  compatibility path.
- These notes should not be read as current provider or Proxy documentation.
