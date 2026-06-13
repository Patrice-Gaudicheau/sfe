# SolarSystem3D comparison

This directory summarizes the first SolarSystem3D benchmark artifacts committed for comparison. The results should be treated as evidence for this benchmark run only, not as a general claim about SFE token or quality behavior.

## Scenario Results

| Scenario | Strict result | Completed tasks | First failure | Token usage |
| --- | --- | --- | --- | --- |
| `10_baseline_full_context_gpt54` | Success | 1-8 | None | 132,210 input, 30,464 cached input, 130,387 output |
| `20_sfe_single_model_gpt54_multipass` | Failed | 1-2 in the clean run | `03_bodies_scale_orbits`: `hunk_preimage_mismatch` on `app/app.js` | Clean run task evidence is under `runs/`; the later no-clean rerun top-level summary records 189,748 input and 56,271 output tokens for a task-1 restart failure |
| `30_sfe_split_gpt54_router_gpt54mini_executor_multipass` | Failed | 1-2 | `03_bodies_scale_orbits`: `hunk_location_mismatch` on `app/app.js` | 41,415 input, 0 cached input, 25,251 output |

## Interpretation

The full-context baseline completed successfully. It consumed many tokens, but it produced all expected static app files and the generated `app/app.js` passed `node --check` during validation.

Both SFE runner scenarios failed at task `03_bodies_scale_orbits` in the clean benchmark attempts. The failures were patch application mismatches against a large `app/app.js`, not truncated JSON or provider output-cap failures.

The split-model failure is not enough to blame only the `gpt-5.4-mini` executor, because the single-model `gpt-5.4` SFE scenario also failed on task 03. The current evidence points to patch fragility on larger generated files and is negative or inconclusive for SolarSystem3D under the current benchmark runner workflow.

The scenario 20 directory also preserves a later no-clean continuation experiment. That run detected the existing app files as context, but the runner restarted at task 1 and failed with another patch preimage mismatch. This makes it useful as evidence about benchmark-runner restart behavior, while the planned next experiment is manual `sfe-tui` against the existing target directory to test continuation on an existing app without modifying the runner.

## Included Evidence

- Scenario `app/` directories with generated static files.
- Scenario `report.md` and `token_usage.json` files.
- Task-level `runs/` artifacts, including selected context, provider calls, patch responses, run results, raw responses where applicable, parsed files, and multipass summaries.
- No screenshots or browser manual-review artifacts are included in this commit.
