# Alibaba DeepSeek Structural 50k Spatial-Only Smoke Note

This note records one live Alibaba Model Studio DeepSeek spatial-only
structural 50k smoke test. It is not a full baseline-vs-spatial comparison, not
a repeat campaign, and not statistical reliability evidence. No live
full-context baseline was run.

No proxy files were modified. Alibaba thinking was disabled through the
benchmark provider configuration.

## Configuration

- Provider: `alibaba-api`
- Router model: `deepseek-v4-flash`
- Executor model: `deepseek-v4-pro`
- API style: OpenAI-compatible Chat Completions
- Task tier: `structural`
- Task: `large_contextual_structural_atlas_policy_mesh_gate`
- Mode: spatial router only
- Repair: disabled
- Raw report: `/tmp/sfe_alibaba_deepseek_structural_spatial_smoke.json`

## Result

- Expected authoritative block ID: `atlas-mesh-s9-final`
- Router selected block ID: `atlas-mesh-s9-final`
- Executor selected block ID: `atlas-mesh-s9-final`
- Router success: `true`
- Router valid selection: `true`
- Router matched fixture: `true`
- Fallback used: `false`
- Provider error: `false`
- Executor output validation status: `complete`
- Repair attempted: `false`
- Repair status: `disabled`

Required targets found in the executor output:

- `42.7`
- `SableReplay-144`
- `ATLAS_OWNER_S9`
- `mesh_s9_epoch_pin`
- `2026.08-s9`

Missing targets: none.

## Token And Latency Summary

- Router tokens: `5317`
- Executor tokens: `3097`
- Total spatial tokens: `8414`
- Router latency: `3224 ms`
- Executor latency: `4500 ms`
- Total spatial latency: `7724 ms`

## Interpretation

This single run shows that the Alibaba DeepSeek pair can complete the
structural spatial path for the Atlas fixture: `deepseek-v4-flash` selected the
expected structural block, and `deepseek-v4-pro` produced a complete answer from
the reduced context.

DeepSeek is therefore structurally validated for this spatial-only mode, but it
has not yet been compared against a live full-context baseline on the same
structural fixture.

This result should be read as a targeted smoke test only. It does not include a
live full-context baseline, does not measure baseline-vs-spatial savings for
DeepSeek, and does not establish statistical reliability.
