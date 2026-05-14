# Alibaba Structural 50k Baseline-vs-Spatial Comparison Note

This note records one live Alibaba Model Studio structural 50k comparison. It
is a single-run baseline-vs-spatial comparison, not a repeat campaign, not a
statistical reliability result, and not production validation.

No proxy files were modified. Alibaba Qwen thinking was disabled for the live
calls to keep token accounting usable and to avoid hidden reasoning-token
inflation.

## Configuration

- Provider: `alibaba-api`
- Router model: `qwen3.6-flash`
- Executor model: `qwen3.6-plus`
- API style: OpenAI-compatible Chat Completions
- Task tier: `structural`
- Task: `large_contextual_structural_atlas_policy_mesh_gate`
- Selection mode: `router`
- Output validation: enabled for structural tier
- Selection verification: enabled for structural tier
- Repair: disabled with `max_output_repairs=0`
- Raw report: `/tmp/sfe_alibaba_structural_50k_comparison.json`

The run used the existing large/contextual benchmark provider hook for Alibaba.
It did not add a new architecture path.

## Result

- Expected authoritative block ID: `atlas-mesh-s9-final`
- Router selected block ID: `atlas-mesh-s9-final`
- Router success: `true`
- Router valid selection: `true`
- Router matched fixture: `true`
- Fallback used: `false`
- Provider errors: none reported
- Baseline output validation: `complete`
- Spatial output validation: `complete`
- Selection verification status: `complete`
- Repair attempted: `false`
- Repair required: `false`

Required targets found in the spatial output:

- `42.7`
- `SableReplay-144`
- `ATLAS_OWNER_S9`
- `mesh_s9_epoch_pin`
- `2026.08-s9`

Missing targets: none.

## Token And Latency Summary

| Path | Input Tokens | Output Tokens | Total Tokens | Latency |
| --- | ---: | ---: | ---: | ---: |
| Baseline full-context executor | 51,379 | 87 | 51,466 | 9408 ms |
| Spatial router | 5,261 | 80 | 5,341 | 2151 ms |
| Spatial reduced-context executor | 3,027 | 86 | 3,113 | 3873 ms |
| Spatial end-to-end | 8,288 | 166 | 8,454 | 6024 ms |

Router-inclusive spatial reduction versus baseline:

- Tokens saved: `43,012`
- Reduction: `83.57%`

The report also records selected-context input reduction of `94.11%` when
comparing executor input size only.

## Interpretation

This single run validates that the Alibaba benchmark path can complete the
structural fixture in both modes:

- the live full-context baseline executor produced a complete answer;
- the live router selected the expected structural block;
- the live reduced-context executor produced a complete answer;
- no fallback was used;
- no repair was attempted or required.

This is stronger than the earlier Alibaba spatial-only structural smoke because
it includes a live full-context baseline. It is still only one synthetic
structural task and one run, so it should not be treated as statistical
reliability evidence or a broad provider comparison.
