# Proxy Milestone History

Status note: This is a historical rollup for Proxy development milestones. The
current Proxy reference is `docs/sfe_proxy_mode.md`; current project entry
points are `README.md` and `docs/INDEX.md`. The Proxy remains experimental
integration infrastructure, not production deployment guidance.

## Overview

Proxy work progressed through a narrow sequence of modes:

- `pass_through`: forward supported OpenAI-compatible requests unchanged.
- `shadow`: preserve upstream and client-visible behavior while recording safe
  observations.
- `dry_run_enabled`: build reduced candidate requests for diagnostics while
  keeping the original upstream path.
- `enabled`: send a reduced request upstream and return the reduced-path
  response, with controlled rejection instead of silent fallback when routing
  is unusable.

The milestone notes below are smoke and controlled-run records. They are useful
for audit continuity and for understanding how the Proxy path was de-risked,
but they are not statistical reliability evidence and do not establish
production readiness.

## Shadow Mode

The earliest Proxy milestones focused on transparency: the original request
went upstream, the client-visible response stayed unchanged, and shadow
metadata captured routing or candidate-context diagnostics.

- [proxy_shadow_local_smoke_summary.md](history/proxy/proxy_shadow_local_smoke_summary.md):
  local mocked-upstream validation of pass-through transparency, shadow router
  metadata, and deterministic useful-segment checks.
- [proxy_shadow_candidate_context_summary.md](history/proxy/proxy_shadow_candidate_context_summary.md):
  candidate-context construction and local diagnostic coverage.
- [proxy_shadow_dry_run_enabled_comparison_summary.md](history/proxy/proxy_shadow_dry_run_enabled_comparison_summary.md):
  comparison between shadow observations and dry-run-enabled candidate request
  construction.
- [proxy_shadow_live_lemonade_runner_summary.md](history/proxy/proxy_shadow_live_lemonade_runner_summary.md):
  live Lemonade router dry-run validation while preserving shadow-only client
  behavior.
- [proxy_shadow_live_qwen_multifixture_summary.md](history/proxy/proxy_shadow_live_qwen_multifixture_summary.md):
  multi-fixture live Qwen/Lemonade shadow routing observations.

## Dry-Run-Enabled Mode

Dry-run-enabled mode introduced reduced request construction as a diagnostic
artifact, but it still preserved the original upstream request and response
path.

- [proxy_dry_run_enabled_mode_summary.md](history/proxy/proxy_dry_run_enabled_mode_summary.md):
  provider-agnostic dry-run-enabled mode summary and validation boundary.

## Enabled Mode

Enabled mode changed the execution path: the reduced request became the
upstream request. These notes record the controlled validation sequence and the
explicit no-silent-fallback behavior.

- [proxy_enabled_mode_smoke_summary.md](history/proxy/proxy_enabled_mode_smoke_summary.md):
  first enabled-mode smoke validation.
- [proxy_enabled_mode_controlled_summary.md](history/proxy/proxy_enabled_mode_controlled_summary.md):
  controlled enabled-mode behavior and fallback boundary.
- [proxy_enabled_mode_milestone_summary.md](history/proxy/proxy_enabled_mode_milestone_summary.md):
  rollup of mode semantics plus Lemonade and OpenAI enabled-mode validation.
- [proxy_structured_responses_builder_diagnostics_note.md](history/proxy/proxy_structured_responses_builder_diagnostics_note.md):
  controlled structured `/v1/responses` builder validation, the current
  `unsafe_task_envelope` fallback boundary for realistic CodexCLI envelopes,
  and the sanitized topology-diagnostics next step.

## Live Provider Observations

Later notes exercised live providers in narrow, controlled conditions. They
should be read as environment-specific observations, not broad provider claims.

- [proxy_enabled_live_lemonade_summary.md](history/proxy/proxy_enabled_live_lemonade_summary.md):
  live Lemonade enabled-mode validation.
- [proxy_enabled_live_lemonade_multifixture_summary.md](history/proxy/proxy_enabled_live_lemonade_multifixture_summary.md):
  multi-fixture Lemonade enabled-mode observations.
- [proxy_enabled_live_openai_summary.md](history/proxy/proxy_enabled_live_openai_summary.md):
  live OpenAI executor enabled-mode validation.
- [proxy_enabled_live_openai_router_summary.md](history/proxy/proxy_enabled_live_openai_router_summary.md):
  live OpenAI router plus executor validation.
- [proxy_enabled_live_openai_router_multifixture_summary.md](history/proxy/proxy_enabled_live_openai_router_multifixture_summary.md):
  multi-fixture OpenAI router plus executor enabled-mode observations.

## Caveats

- These notes are historical milestone records, not current operating
  instructions. Use `docs/sfe_proxy_mode.md` for current Proxy configuration,
  providers, modes, Docker usage, and safety notes.
- Live runs were environment-specific. Provider behavior, model behavior, rate
  limits, latency, and quota constraints can change.
- Smoke tests and controlled mini-runs are not production validation.
- The Proxy remains experimental and should not be exposed beyond deliberate
  local development or explicitly controlled test environments.
