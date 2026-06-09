# Alibaba DeepSeek Structural 50k Baseline-vs-Spatial Comparison Note

This note records one live Alibaba Model Studio DeepSeek structural 50k
baseline-vs-spatial comparison. It is a single-run comparison, not a repeat
campaign, not statistical reliability evidence, and not production validation.

Alibaba thinking was disabled through the
benchmark provider configuration. Output repair was disabled.

## Configuration

- Provider: `alibaba-api`
- Router model: `deepseek-v4-flash`
- Executor model: `deepseek-v4-pro`
- API style: OpenAI-compatible Chat Completions
- Task tier: `structural`
- Task: `large_contextual_structural_atlas_policy_mesh_gate`
- Selection mode: `router`
- Baseline path: live full-context executor
- Spatial path: live router plus live reduced-context executor
- Output validation: enabled for structural tier
- Selection verification: enabled for structural tier
- Repair: disabled with `max_output_repairs=0`
- Raw report: `/tmp/sfe_alibaba_deepseek_structural_50k_comparison.json`

The run used the existing large/contextual benchmark provider hook for Alibaba.
It did not add a new architecture path.

## Result

- Expected authoritative block ID: `atlas-mesh-s9-final`
- Router selected block ID: `atlas-mesh-s9-final`
- Spatial executor selected block ID: `atlas-mesh-s9-final`
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

Required targets found in both baseline and spatial outputs:

- `42.7`
- `SableReplay-144`
- `ATLAS_OWNER_S9`
- `mesh_s9_epoch_pin`
- `2026.08-s9`

Missing targets: none.

## Token And Latency Summary

| Path | Input Tokens | Output Tokens | Total Tokens | Latency |
| --- | ---: | ---: | ---: | ---: |
| Baseline full-context executor | 51,356 | 87 | 51,443 | 48,287 ms |
| Spatial router | 5,242 | 75 | 5,317 | 1,576 ms |
| Spatial reduced-context executor | 3,010 | 80 | 3,090 | 3,411 ms |
| Spatial end-to-end | 8,252 | 155 | 8,407 | 4,987 ms |

Router-inclusive spatial reduction versus baseline:

- Tokens saved: `43,036`
- Reduction: `83.66%`

The report also records selected-context input reduction of `94.14%` when
comparing executor input size only.

## Interpretation

This single run closes the first DeepSeek structural loop for Alibaba: the live
full-context baseline produced a complete answer, the live router selected the
expected structural block, and the live reduced-context executor produced a
complete answer from the selected block.

Unlike the earlier DeepSeek spatial-only structural smoke, this note includes a
complete live baseline-vs-spatial structural comparison for the same fixture.
It is still only one synthetic structural task and one run, so it should not be
treated as statistical reliability evidence or a broad provider comparison.
