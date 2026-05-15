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
current large/contextual summaries existed:

- [alibaba_router_smoke_note.md](alibaba_router_smoke_note.md): early router
  smoke checks for Alibaba/Qwen provider wiring.
- [alibaba_progressive_benchmark_note.md](alibaba_progressive_benchmark_note.md):
  progressive setup across effectiveness, high-overlap selector,
  multi-zone, limited large/contextual, and structural dry-run stages.
- [alibaba_structural_50k_spatial_smoke_note.md](alibaba_structural_50k_spatial_smoke_note.md):
  earlier structural spatial-only smoke that preceded the current
  baseline-vs-spatial structural comparison.

These notes are useful for audit continuity, but the current Alibaba/Qwen
benchmark status should be taken from the supporting docs above and from
`README.md`.

## Alibaba-Hosted DeepSeek Exploration

The DeepSeek-related notes are Alibaba-hosted provider exploration records.
They should not be confused with the current Alibaba/Qwen benchmark headline:

- [alibaba_deepseek_smoke_note.md](alibaba_deepseek_smoke_note.md): DeepSeek
  connectivity and limited benchmark smoke observations through Alibaba-hosted
  paths.
- [alibaba_deepseek_structural_spatial_smoke_note.md](alibaba_deepseek_structural_spatial_smoke_note.md):
  DeepSeek structural spatial-only smoke.
- [alibaba_deepseek_structural_50k_comparison_note.md](alibaba_deepseek_structural_50k_comparison_note.md):
  DeepSeek structural 50k baseline-vs-spatial comparison note.

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
