# Alibaba/Qwen Provider History

Status note: This is a historical/provider-integration rollup for Alibaba
Model Studio, DashScope, Qwen, and related Alibaba-hosted model experiments.
Current project entry points are `README.md` and `docs/INDEX.md`. Current
multi-provider benchmark interpretation starts from
`docs/provider_comparison_summary.md` plus the current Alibaba/Qwen notes
linked below. SFE remains experimental and benchmark-specific.

## Current Supporting Alibaba/Qwen Docs

These notes remain the current Alibaba/Qwen supporting references:

- [alibaba_large_contextual_missing_tiers.md](alibaba_large_contextual_missing_tiers.md):
  repeat-3 Alibaba/Qwen `standard`, `practical`, and `high_context`
  large/contextual measurements using the same benchmark methodology as the
  existing provider comparison path.
- [alibaba_structural_50k_comparison_note.md](alibaba_structural_50k_comparison_note.md):
  single live Alibaba/Qwen structural 50k baseline-vs-spatial comparison.
- [alibaba_comparable_benchmark_runs.md](alibaba_comparable_benchmark_runs.md):
  limited Alibaba Model Studio replay across selected benchmark families.

The structural Alibaba/Qwen result is a single-run comparison unless a later
document says otherwise. It should not be read as a repeat campaign.

## Historical Integration Notes

Earlier Alibaba/Qwen work advanced through small provider checks before the
current large/contextual summaries existed. The local-only historical notes
cover early Qwen router checks, progressive benchmark stages, Qwen structural
spatial-only smoke, and Alibaba-hosted DeepSeek exploration.

Those notes are useful for audit continuity, but the current Alibaba/Qwen
benchmark status should be taken from the supporting docs above and from
`README.md`.

## Alibaba-Hosted DeepSeek Exploration

The DeepSeek-related observations are included in the consolidated Alibaba
history rollup. They should not be confused with the current Alibaba/Qwen
benchmark headline.

These are model/provider exploration records, not current Qwen summary rows and
not broad provider rankings.

## Caveats

- Alibaba/Qwen benchmark calls used Qwen thinking disabled where documented so
  token accounting remained usable and comparable.
- Some historical notes are smoke tests or environment-specific observations.
- Provider behavior, model names, API compatibility, rate limits, latency, and
  token accounting can change.
- Current Alibaba/Qwen observations are controlled benchmark observations, not
  statistical proof, production readiness evidence, or a claim of provider
  superiority.
