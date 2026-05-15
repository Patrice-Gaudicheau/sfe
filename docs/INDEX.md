# Documentation Index

This repository is a technical prototype for Spatial Field Engine for Cognition
(`SFE`), an experimental architecture that separates context selection from
task execution in long-context LLM workflows. The documentation records
controlled benchmark methodology, provider-specific observations, and the
experimental SFE Proxy path. It does not claim production readiness,
statistical reliability, or general model-safety guarantees.

## Start Here

1. [README.md](../README.md): project purpose, architecture, setup, current
   provider support, Proxy usage, benchmark snapshot, and limitations.
2. [public_release_technical_report.md](public_release_technical_report.md):
   public-facing technical report for the current release-readiness snapshot.
3. [sfe_proxy_mode.md](sfe_proxy_mode.md): detailed SFE Proxy configuration,
   supported providers, modes, Docker usage, and operational caveats.
4. [router_contract.md](router_contract.md): router JSON contract and strict
   output expectations.

## Current Primary Docs

- [provider_comparison_summary.md](provider_comparison_summary.md): main
  cross-provider benchmark summary for protocol-aligned OpenAI and Anthropic
  campaigns.
- [token_cost_metrics.md](token_cost_metrics.md): OpenAI token accounting and
  router-inclusive reduction details.
- [large_contextual_benchmark_report.md](large_contextual_benchmark_report.md):
  large/contextual benchmark methodology and report notes.
- [effectiveness.md](effectiveness.md): preserved strict Lemonade
  effectiveness result.
- [decisions.md](decisions.md): project decision notes where applicable.

## Proxy And Provider Docs

- [sfe_proxy_mode.md](sfe_proxy_mode.md): canonical Proxy mode reference. It
  covers `pass_through`, `shadow`, `dry_run_enabled`, and `enabled` modes, plus
  OpenAI-compatible, OpenAI, Lemonade, Alibaba/Qwen, and Anthropic proxy
  providers.
- [proxy_milestone_history.md](proxy_milestone_history.md): preferred starting
  point for historical Proxy milestone notes before reading the individual
  smoke and controlled-run records.
- [openai_api_benchmark.md](openai_api_benchmark.md): optional direct OpenAI
  API benchmark path.
- [openai_validation_report.md](openai_validation_report.md): direct OpenAI API
  validation summary for large/contextual benchmark work.
- [openai_paced_equivalent_summary.md](openai_paced_equivalent_summary.md):
  OpenAI paced-equivalent campaign summary.
- [anthropic_benchmark_paced_summary.md](anthropic_benchmark_paced_summary.md):
  Anthropic paced campaign summary, including structural provider-call pacing.
- [alibaba_provider_history.md](alibaba_provider_history.md): preferred
  starting point for Alibaba/Qwen historical provider integration and related
  Alibaba-hosted model exploration notes.
- [alibaba_progressive_benchmark_note.md](history/providers/alibaba/alibaba_progressive_benchmark_note.md):
  progressive Alibaba/Qwen benchmark note.
- [alibaba_comparable_benchmark_runs.md](alibaba_comparable_benchmark_runs.md):
  limited Alibaba/Qwen replay across selected benchmark families.
- [alibaba_large_contextual_missing_tiers.md](alibaba_large_contextual_missing_tiers.md):
  Alibaba/Qwen repeat-3 `standard`, `practical`, and `high_context`
  large/contextual measurements.
- [alibaba_structural_50k_comparison_note.md](alibaba_structural_50k_comparison_note.md):
  Alibaba/Qwen single-run structural baseline-vs-spatial comparison.

## Benchmark Methodology

- [high_overlap_diagnostic_bucketing_notes.md](high_overlap_diagnostic_bucketing_notes.md):
  strict validation, honest pass/fail criteria, and diagnostic failure buckets.
- [high_overlap_authority_gap_fixture_expansion_design.md](high_overlap_authority_gap_fixture_expansion_design.md):
  design intent behind the Aurelia, Borealis, and Cassini authority-gap
  fixtures.
- [high_overlap_fixture_expansion_phase_close.md](high_overlap_fixture_expansion_phase_close.md):
  phase closeout for the high-overlap fixture expansion.
- [large_real_world_benchmark_progression_summary.md](large_real_world_benchmark_progression_summary.md):
  progression notes for large real-world-style benchmark work.
- [structural_benchmark_note.md](structural_benchmark_note.md): exploratory
  structural 50k+ stress-test notes.
- [results_structural_50k_openai.md](results_structural_50k_openai.md):
  OpenAI structural 50k+ result note.

## Benchmark Families

- Core deterministic benchmark: small local checks for the base SFE execution
  flow.
- Large/contextual benchmark: synthetic context-reduction tasks with fixture
  and router selection modes.
- High-overlap authority-gap benchmarks: controlled fixtures where multiple
  documents share similar vocabulary and differ by authority, scope, freshness,
  or evidence.
- Large real-world-style benchmark notes: early OpenAI selector/executor smoke
  observations over curated material.
- Structural 50k+ stress tests: exploratory large-context stress material
  intended to expose routing and answer-completeness limits.

High-overlap remains an important benchmark family, but it should be read as
methodology and controlled fixture coverage rather than the whole-project
status.

## Runner Map

Use this map before running scripts. Some comparison runner filenames do not
include `openai` even though they call OpenAI when `OPENAI_API_KEY` is present.

| Category | Typical runner pattern | API key required | Notes |
| --- | --- | --- | --- |
| Deterministic runners | `runtime/run_high_overlap_*_benchmark.py` | No | Validate fixtures and report strict deterministic outcomes. |
| Large/contextual runner | `runtime/run_large_contextual_benchmark.py` | No for `--dry-run`; yes for live providers | Supports `lemonade`, `openai-api`, `alibaba-api`, and `anthropic` executors. |
| Selector-only OpenAI smokes | `runtime/run_high_overlap_*_openai_selector_smoke.py` | Yes for live run | Use blind `candidate-N` handles and validate selected source. |
| Selected-context OpenAI executor smokes | `runtime/run_high_overlap_*_openai_executor_smoke.py` | Yes for live run | Executor receives deterministic authoritative context only. |
| Selected-vs-full OpenAI comparisons | `runtime/run_high_overlap_*_contamination_comparison.py` | Yes for live run | Compare selected authoritative context with full fixture context. |
| Alibaba/Qwen smoke | `runtime/run_alibaba_smoke.py` | Yes for live run | Tiny provider smoke path; not a benchmark campaign. |
| Proxy direct run | `python -m sfe_proxy` | Depends on configured upstream provider | Experimental local OpenAI-compatible proxy path. |
| Proxy Docker run | `make build`, `make start`, `make logs`, `make status`, `make stop` | `make build` no; `make start` depends on provider config | Uses `docker-compose.proxy.yml` and the root `.env` for runtime configuration. |

Generated local reports should stay outside tracked files, preferably under
`/tmp`, unless a summarized documentation note is intentionally added.

## Historical And Phase-Specific Notes

These notes preserve narrower experiments, smoke tests, and phase closeouts.
They are useful for audit trail and context, but they should not be read as the
current top-level project status.

- [proxy_milestone_history.md](proxy_milestone_history.md): rollup for the
  historical Proxy shadow, dry-run-enabled, enabled-mode, and live-provider
  milestone notes below.
- [high_overlap_poison_pill_progression_summary.md](high_overlap_poison_pill_progression_summary.md)
- [high_overlap_subtle_poison_progression_summary.md](high_overlap_subtle_poison_progression_summary.md)
- [high_overlap_new_fixtures_openai_smoke_notes.md](high_overlap_new_fixtures_openai_smoke_notes.md)
- [high_overlap_new_fixtures_selector_smoke_notes.md](high_overlap_new_fixtures_selector_smoke_notes.md)
- [high_overlap_new_fixtures_selector_repeat3_notes.md](high_overlap_new_fixtures_selector_repeat3_notes.md)
- [high_overlap_new_fixtures_comparison_notes.md](high_overlap_new_fixtures_comparison_notes.md)
- [large_real_world_openai_selector_smoke.md](large_real_world_openai_selector_smoke.md)
- [large_real_world_openai_selector_executor_smoke.md](large_real_world_openai_selector_executor_smoke.md)
- [large_real_world_openai_selector_deterministic_executor.md](large_real_world_openai_selector_deterministic_executor.md)
- [proxy_shadow_local_smoke_summary.md](history/proxy/proxy_shadow_local_smoke_summary.md)
- [proxy_shadow_candidate_context_summary.md](history/proxy/proxy_shadow_candidate_context_summary.md)
- [proxy_shadow_dry_run_enabled_comparison_summary.md](history/proxy/proxy_shadow_dry_run_enabled_comparison_summary.md)
- [proxy_shadow_live_lemonade_runner_summary.md](history/proxy/proxy_shadow_live_lemonade_runner_summary.md)
- [proxy_shadow_live_qwen_multifixture_summary.md](history/proxy/proxy_shadow_live_qwen_multifixture_summary.md)
- [proxy_dry_run_enabled_mode_summary.md](history/proxy/proxy_dry_run_enabled_mode_summary.md)
- [proxy_enabled_mode_smoke_summary.md](history/proxy/proxy_enabled_mode_smoke_summary.md)
- [proxy_enabled_mode_controlled_summary.md](history/proxy/proxy_enabled_mode_controlled_summary.md)
- [proxy_enabled_mode_milestone_summary.md](history/proxy/proxy_enabled_mode_milestone_summary.md)
- [proxy_enabled_live_lemonade_summary.md](history/proxy/proxy_enabled_live_lemonade_summary.md)
- [proxy_enabled_live_lemonade_multifixture_summary.md](history/proxy/proxy_enabled_live_lemonade_multifixture_summary.md)
- [proxy_enabled_live_openai_summary.md](history/proxy/proxy_enabled_live_openai_summary.md)
- [proxy_enabled_live_openai_router_summary.md](history/proxy/proxy_enabled_live_openai_router_summary.md)
- [proxy_enabled_live_openai_router_multifixture_summary.md](history/proxy/proxy_enabled_live_openai_router_multifixture_summary.md)
- [alibaba_provider_history.md](alibaba_provider_history.md): rollup for the
  Alibaba/Qwen historical integration notes and Alibaba-hosted DeepSeek
  exploration records below.
- [alibaba_router_smoke_note.md](history/providers/alibaba/alibaba_router_smoke_note.md)
- [alibaba_structural_50k_spatial_smoke_note.md](history/providers/alibaba/alibaba_structural_50k_spatial_smoke_note.md)
- [alibaba_deepseek_smoke_note.md](history/providers/alibaba/alibaba_deepseek_smoke_note.md)
- [alibaba_deepseek_structural_spatial_smoke_note.md](history/providers/alibaba/alibaba_deepseek_structural_spatial_smoke_note.md)
- [alibaba_deepseek_structural_50k_comparison_note.md](history/providers/alibaba/alibaba_deepseek_structural_50k_comparison_note.md)
- [roadmap_after_structural_50k.md](roadmap_after_structural_50k.md)

## Terms And Caveats

- Deterministic tests validate fixture logic without live provider calls.
- Live smoke observations exercise configured providers and should be read as
  local observations.
- Manual repeat observations are not statistical reliability benchmarks.
- Honest pass means the strict output contract passed without fallback, repair,
  provider error, parse failure, or other disqualifying metadata.
- Diagnostic bucketing separates strict failures into field extraction,
  evidence reference, contamination indicator, provider, parse, fallback, and
  repair categories where the report exposes enough information.
- Proxy mode is experimental integration infrastructure, not production
  deployment guidance.

The repository does not claim general robustness, production readiness,
contamination prevention, or that selected context generally outperforms full
context.
