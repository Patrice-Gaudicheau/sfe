# Alibaba Structural 50k Spatial-Only Smoke Note

This note records one live Alibaba Model Studio spatial-only structural 50k
smoke test. It is not a full baseline-vs-spatial comparison, not a reliability
benchmark, and not production validation. No live full-context baseline was run.

## Configuration

- Router provider/model: `alibaba-api` / `qwen3.6-flash`
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`
- Qwen thinking disabled: `true`
- Task tier: `structural`
- Fixture: `large_contextual_structural_atlas_policy_mesh_gate`
- Repair: disabled

Thinking remained disabled for Alibaba Qwen calls to keep token accounting
usable and to avoid hidden reasoning token inflation in this smoke.

## Result

- Expected authoritative block ID: `atlas-mesh-s9-final`
- Router selected block ID: `atlas-mesh-s9-final`
- Router success: `true`
- Router valid selection: `true`
- Router matched fixture: `true`
- Fallback used: `false`
- Provider error: `false`
- Selection verification status: `complete`
- Selection missing targets: none
- Executor output validation status: `complete`
- Executor output contained all required targets: `true`
- Executor missing targets: none
- Repair attempted: `false`
- Repair required: `false`
- Repair status: `disabled`

Required targets found in the executor output:

- `42.7`
- `SableReplay-144`
- `ATLAS_OWNER_S9`
- `mesh_s9_epoch_pin`
- `2026.08-s9`

## Token And Latency Summary

- Router tokens: `5261` input, `80` output, `5341` total
- Executor tokens: `3027` input, `86` output, `3113` total
- Total spatial tokens: `8454`
- Router latency: `2215 ms`
- Executor latency: `3343 ms`
- Total spatial latency: `5558 ms`

## Interpretation

This single run validates the reduced-context structural path for one Alibaba
fixture: the router selected the expected structural block, and the executor
answered correctly from that reduced context. It does not validate the live
full-context baseline, so it does not provide a measured live baseline-vs-spatial
token or cost comparison.

A prior dry-run estimate for the same structural tier estimated a full-context
baseline around `74248` total tokens and a spatial router path around `10022`
tokens. This live spatial-only smoke used `8454` total spatial tokens. The
baseline estimate is included only as context; no live baseline call was made.
