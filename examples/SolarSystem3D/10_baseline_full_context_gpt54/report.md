# Baseline full context gpt-5.4 report

Generated at: `2026-06-13T13:24:03+00:00`

## Scenario

- Workflow: full-context baseline without SFE.
- Provider: `openai-api`.
- Model: `gpt-5.4`.
- Routing: disabled.
- Discovery: disabled.
- Context reduction: disabled.
- Project brief: `../00_project_brief/prompt.md`.
- Task sequence: `../00_project_brief/task_sequence.md`.

## Result

- Success: `true`.
- Total estimated cost: `null`.
- Manual verification: not performed by this runner.

## Task Runs

| Task | Success | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `01_static_scaffold` | `true` | 4782 | 0 | 4938 | 25837 |  |
| `02_data_and_textures` | `true` | 9030 | 4352 | 12031 | 53359 |  |
| `03_bodies_scale_orbits` | `true` | 15217 | 4352 | 13749 | 55470 |  |
| `04_animation_time_scale` | `true` | 16740 | 4352 | 15574 | 61541 |  |
| `05_earth_seasons` | `true` | 18369 | 4352 | 17693 | 68575 |  |
| `06_camera_labels_focus` | `true` | 20232 | 4352 | 21529 | 85695 |  |
| `07_info_accessibility` | `true` | 23586 | 4352 | 22278 | 87657 |  |
| `08_responsive_performance_readme` | `true` | 24254 | 4352 | 22595 | 90432 |  |

## Generated Files

- `examples/SolarSystem3D/10_baseline_full_context_gpt54/app/index.html`
- `examples/SolarSystem3D/10_baseline_full_context_gpt54/app/styles.css`
- `examples/SolarSystem3D/10_baseline_full_context_gpt54/app/app.js`
- `examples/SolarSystem3D/10_baseline_full_context_gpt54/app/README.md`

## Notes

Task-level prompts, raw responses, parsed file snapshots, and run metadata are stored under `runs/<task>/`.
