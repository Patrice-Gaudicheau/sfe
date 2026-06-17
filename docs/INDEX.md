# Documentation Index

This repository is a technical prototype for SFE (Spatial Field Engine for Cognition)
a routing/context engine for LLM workflows: it separates context
selection from execution, bounds execution modes, validates results where
possible, and records safe observability.

The documentation is organized so current architecture, TUI usage, benchmark
evidence, provider material, and historical notes are not confused.
The repository does not claim production readiness, statistical reliability, or
general model-safety guarantees.

## Start Here

1. [sfe_product_doctrine.md](sfe_product_doctrine.md): current doctrine and
   terminology. Read this first when interpreting the TUI, benchmarks,
   or filesystem/worktree mode.
2. [README.md](../README.md): project purpose, benchmark snapshot, setup,
   provider support, and limitations.
3. [current_architecture_status.md](current_architecture_status.md): current
   architecture status for the SFE core, TUI, `/run`, and `workspace_write`.
4. [real_loop.md](real_loop.md): bounded verifier/governor retry behavior for
   supported local `workspace_write` runs.
5. [tui_v0_1_user_guide.md](tui_v0_1_user_guide.md): local TUI workflow and
   command reference.
6. [sfe_mcp_local_control_surface.md](sfe_mcp_local_control_surface.md):
   design boundary for the current local STDIO MCP control surface over the same
   runtime path as the TUI.
7. [sfe_mcp_client_setup.md](sfe_mcp_client_setup.md): local MCP client setup
   for Antigravity and Codex App.
8. [execution_mode_router_contract.md](execution_mode_router_contract.md):
   current `/run` execution-mode router contract.
9. [workspace_write_multipass.md](workspace_write_multipass.md): current
   multi-pass behavior for large `workspace_write` scaffolds.
10. [aider_filesystem_executor_integration.md](aider_filesystem_executor_integration.md):
   current Aider-backed filesystem writer architecture for `workspace_write`.

## Current Architecture And Doctrine

- [sfe_product_doctrine.md](sfe_product_doctrine.md): SFE core, TUI,
  filesystem/worktree mode, benchmarks, and future API boundaries.
- [current_architecture_status.md](current_architecture_status.md): current
  architecture boundary and what remains unproven.
- [execution_mode_router_contract.md](execution_mode_router_contract.md):
  current `console_output`, `workspace_write`, and `external_action` contract.
- [workspace_write_multipass.md](workspace_write_multipass.md): how
  multi-pass `workspace_write` planning, batch validation, promotion, and
  reports work.
- [real_loop.md](real_loop.md): bounded verifier/governor retry behavior for
  supported local `workspace_write` runs.
- [aider_filesystem_executor_integration.md](aider_filesystem_executor_integration.md):
  current architecture for the external Aider-backed filesystem executor,
  worktree promotion, and legacy text fallback.
- [sfe_mcp_local_control_surface.md](sfe_mcp_local_control_surface.md):
  current local STDIO MCP control surface and TUI/MCP ISO runtime requirement.
- [sfe_mcp_client_setup.md](sfe_mcp_client_setup.md): current local STDIO MCP
  setup for Antigravity and Codex App.
- [decisions.md](decisions.md): project decision notes and historical context.

## TUI Usage

- [tui_v0_1_user_guide.md](tui_v0_1_user_guide.md): current local user-facing
  TUI guide. `/run` is the current primary action.
- [history/tui/tui_apply_patch_legacy_design.md](history/tui/tui_apply_patch_legacy_design.md):
  legacy `/patch` -> `/apply-patch` write-boundary design from before the
  current `/run`-first and Aider-backed workspace-writer flow.

Historical TUI milestone and backend-strategy notes are under
[`history/tui/`](history/tui/).

## Benchmark Evidence

Benchmarks are the practical exploratory implementation of the white paper
hypothesis. They are evidence and architectural feedback, not secondary
artifacts and not normal TUI output.

- [provider_comparison_summary.md](provider_comparison_summary.md): main
  cross-provider OpenAI/Anthropic summary for protocol-aligned large/contextual
  campaigns.
- [large_contextual_benchmark_report.md](large_contextual_benchmark_report.md):
  large/contextual benchmark methodology and report notes.
- [results_structural_50k_openai.md](results_structural_50k_openai.md):
  OpenAI structural 50k+ result note.
- [token_cost_metrics.md](token_cost_metrics.md): OpenAI token accounting and
  router-inclusive reduction details.
- [public_release_technical_report.md](public_release_technical_report.md):
  conservative public-release technical snapshot.
- [effectiveness.md](effectiveness.md): preserved strict Lemonade
  effectiveness result.
- [structural_benchmark_note.md](structural_benchmark_note.md): exploratory
  structural 50k+ stress-test notes.

## Provider Docs

- [openai_api_benchmark.md](openai_api_benchmark.md): optional direct OpenAI
  API benchmark path.
- [openai_validation_report.md](openai_validation_report.md): direct OpenAI API
  validation summary for large/contextual benchmark work.
- [openai_paced_equivalent_summary.md](openai_paced_equivalent_summary.md):
  OpenAI paced-equivalent campaign summary.
- [anthropic_benchmark_paced_summary.md](anthropic_benchmark_paced_summary.md):
  Anthropic paced campaign summary, including structural provider-call pacing.
- [alibaba_provider_history.md](alibaba_provider_history.md): starting point
  for Alibaba/Qwen historical provider integration notes.
- [alibaba_comparable_benchmark_runs.md](alibaba_comparable_benchmark_runs.md):
  limited Alibaba/Qwen replay across selected benchmark families.
- [alibaba_large_contextual_missing_tiers.md](alibaba_large_contextual_missing_tiers.md):
  Alibaba/Qwen repeat-3 `standard`, `practical`, and `high_context`
  large/contextual measurements.
- [alibaba_structural_50k_comparison_note.md](alibaba_structural_50k_comparison_note.md):
  Alibaba/Qwen single-run structural baseline-vs-spatial comparison.

## Benchmark Families

- Core deterministic benchmark: small local checks for the base SFE execution
  flow.
- Large/contextual benchmark: synthetic context-reduction tasks with fixture
  and router selection modes.
- High-overlap authority-gap benchmarks: controlled fixtures where similar
  documents differ by authority, scope, freshness, or evidence.
- Large real-world-style notes: historical OpenAI selector/executor smoke
  observations over curated material.
- Structural 50k+ stress tests: large-context stress material for routing,
  answer-completeness, and amortization behavior.

High-overlap remains an important benchmark family, but it should be read as
methodology and controlled fixture coverage rather than the whole-project
status. Start with [high_overlap_history.md](high_overlap_history.md),
[high_overlap_diagnostic_bucketing_notes.md](high_overlap_diagnostic_bucketing_notes.md),
and [high_overlap_authority_gap_fixture_expansion_design.md](high_overlap_authority_gap_fixture_expansion_design.md).

## Runner Map

Use this map before running scripts. Some comparison runner filenames do not
include `openai` even though they call OpenAI when `OPENAI_API_KEY` is present.

| Category | Typical runner pattern | API key required | Notes |
| --- | --- | --- | --- |
| Deterministic runners | `runtime/run_high_overlap_*_benchmark.py` | No | Validate fixtures and report strict deterministic outcomes. |
| Large/contextual runner | `runtime/run_large_contextual_benchmark.py` | No for `--dry-run`; yes for live providers | Supports `lemonade`, `openai-api`, `alibaba-api`, `anthropic`, and `google` executors. |
| Selector-only OpenAI smokes | `runtime/run_high_overlap_*_openai_selector_smoke.py` | Yes for live run | Use blind `candidate-N` handles and validate selected source. |
| Selected-context OpenAI executor smokes | `runtime/run_high_overlap_*_openai_executor_smoke.py` | Yes for live run | Executor receives deterministic authoritative context only. |
| Selected-vs-full OpenAI comparisons | `runtime/run_high_overlap_*_contamination_comparison.py` | Yes for live run | Compare selected authoritative context with full fixture context. |
| Alibaba/Qwen smoke | `runtime/run_alibaba_smoke.py` | Yes for live run | Tiny provider smoke path; not a benchmark campaign. |
| Google/Gemini smoke | `runtime/run_google_smoke.py` | Yes for live run | Tiny Gemini OpenAI-compatible smoke path; not a benchmark campaign. |

Generated local reports should stay outside tracked files, preferably under
`/tmp`, unless a summarized documentation note is intentionally added.

## History

Historical notes preserve experiments, smoke tests, milestones, and superseded
roadmaps. They are useful for audit trail and context, but they should not be
read as current top-level project status.

- [history/router/router_contract_legacy.md](history/router/router_contract_legacy.md):
  older broad router contract with task type, role, memory zones, and
  older direct/tool-assisted/multi-step execution patterns.
- [history/tui/tui_readonly_ask_milestone.md](history/tui/tui_readonly_ask_milestone.md)
- [history/tui/tui_direct_backend_strategy.md](history/tui/tui_direct_backend_strategy.md)
- [history/tui/tui_apply_patch_legacy_design.md](history/tui/tui_apply_patch_legacy_design.md)
- [history/mcp/mcp_antigravity_dogfooding_001.md](history/mcp/mcp_antigravity_dogfooding_001.md)
- [history/sfe_continuity_orientation_glossary.md](history/sfe_continuity_orientation_glossary.md)
- [history/high_overlap/high_overlap_fixture_expansion_phase_close.md](history/high_overlap/high_overlap_fixture_expansion_phase_close.md)
- [history/roadmaps/roadmap_after_structural_50k.md](history/roadmaps/roadmap_after_structural_50k.md)
- [high_overlap_history.md](high_overlap_history.md): rollup for historical
  high-overlap experiment notes.
- [large_real_world_history.md](large_real_world_history.md): rollup for
  historical large real-world-style benchmark notes.
- [history/openai_smoke_reports/](history/openai_smoke_reports/README.md):
  historical generated Markdown report snapshots moved out of tracked `logs/`.
- [alibaba_provider_history.md](alibaba_provider_history.md): rollup for
  Alibaba/Qwen historical integration notes.
- [history/providers/codexcli/](history/providers/codexcli/README.md):
  rollup for CodexCLI provider history and retained benchmark notes.

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
The repository does not claim general robustness, production readiness,
contamination prevention, or that selected context generally outperforms full
context.
