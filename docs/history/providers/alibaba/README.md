# Alibaba Provider Historical Smoke Rollup

Status note: this is a historical rollup for Alibaba Model Studio, DashScope,
Qwen, and Alibaba-hosted DeepSeek smoke notes. It preserves provider-integration
observations for audit continuity. Current project entry points remain
`README.md`, `docs/INDEX.md`, and the current Alibaba/Qwen docs linked from
`docs/alibaba_provider_history.md`.

## Qwen Configuration Pattern

Most Qwen runs used:

- Router provider/model: `alibaba-api` / `qwen3.6-flash`.
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`.
- Qwen thinking disabled: `true`.

Thinking was disabled so token accounting remained usable and hidden reasoning
tokens did not inflate smoke results.

## Qwen Smoke Progression

| Area | Scope | Outcome | Limitation |
| --- | --- | --- | --- |
| Router smoke | High-overlap selector repeat-3 on `high_overlap_cassini_policy_exception_gate`. | `qwen3.6-flash` selected `cassini-v31` in 3/3 runs with valid JSON, no fallback, no parse failure, no provider error, total-token range 824 to 878, and latency range 1,720 ms to 2,102 ms. | Small router smoke only. A separate generic effectiveness smoke was useful as wiring evidence but not meaningful for provider-quality scoring because deterministic task wording corrected one route. |
| Progressive benchmark campaign | Effectiveness, high-overlap repeat-3, one multi-zone synthetic smoke, one limited large/contextual standard-tier smoke, and a structural dry-run estimate. | Alibaba calls produced valid router JSON in the covered stages; high-overlap selected `cassini-v31` in 3/3; the one multi-zone path passed; the limited large/contextual path selected `pay-ops`; no fallback or provider errors were observed in those narrow checks. | Not a full reliability campaign. The structural 50k stage was a dry-run estimate only, with no live structural call. |
| Structural 50k spatial-only smoke | One live reduced-context structural run on `large_contextual_structural_atlas_policy_mesh_gate`. | Router selected `atlas-mesh-s9-final`; executor output contained `42.7`, `SableReplay-144`, `ATLAS_OWNER_S9`, `mesh_s9_epoch_pin`, and `2026.08-s9`; fallback and repair were not used. Total spatial tokens were 8,454. | No live full-context baseline was run, so this was not a measured baseline-vs-spatial comparison. |

## Alibaba-Hosted DeepSeek Progression

The DeepSeek observations used:

- Provider: `alibaba-api`.
- Router model: `deepseek-v4-flash`.
- Executor model: `deepseek-v4-pro`.
- API style: OpenAI-compatible Chat Completions.
- Thinking disabled: `true`.

| Area | Scope | Outcome | Limitation |
| --- | --- | --- | --- |
| Connectivity and high-overlap smoke | Tiny exact-output prompts plus high-overlap selector repeat-3. | Both DeepSeek model IDs responded to connectivity prompts. The router selected `cassini-v31` in all 3 high-overlap runs, with 3/3 honest selector pass, 0 JSON parse failures, 0 fallback, and 0 provider errors. | Connectivity and selector smoke only. |
| Limited router plus executor smoke | One generic effectiveness benchmark run with DeepSeek router/executor. | Router success, JSON validity, and real routing accuracy were reported as 100%; fallback rate was 0. Provider errors were 0. | It was not an effectiveness win and should be treated as wiring/routing evidence, not quality or cost comparison. |
| Structural 50k spatial-only smoke | One reduced-context structural run on the Atlas fixture. | Router and executor selected `atlas-mesh-s9-final`; required targets were present; fallback and repair were not used; total spatial tokens were 8,414. | No live full-context baseline was included. |
| Structural 50k baseline-vs-spatial comparison | One live full-context baseline plus live router and reduced-context executor on the same Atlas fixture. | Baseline and spatial outputs both contained the required targets. Spatial end-to-end used 8,407 tokens versus 51,443 baseline tokens, saving 43,036 tokens for an 83.66% router-inclusive reduction. | Single synthetic structural task and one run only; not a repeat campaign, statistical result, or broad provider comparison. |

## Lessons

- Alibaba/Qwen and Alibaba-hosted DeepSeek should be documented as
  provider-specific historical observations unless a current summary promotes a
  narrower result.
- Thinking-disable configuration materially affects token-accounting
  interpretability and should remain explicit in historical interpretation.
- Structural spatial-only smokes are not equivalent to baseline-vs-spatial
  comparisons.
- Single live comparisons can close an integration loop, but they should not be
  framed as provider rankings or production-readiness evidence.
