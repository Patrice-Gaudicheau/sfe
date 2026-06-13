# SFE split-model gpt-5.4 router / gpt-5.4-mini executor report

Generated at: `2026-06-13T15:01:04+00:00`

## Scenario

- Workflow: SFE split-model run.
- Provider: `openai-api`.
- Router model: `gpt-5.4`.
- Discovery model: `gpt-5.4`.
- Multipass planner model: `gpt-5.4`.
- Executor model: `gpt-5.4-mini`.
- Multipass: `auto`.
- Workspace: temporary controlled workspace containing only benchmark brief, task metadata, and current scenario app files.
- Project brief: `../00_project_brief/prompt.md`.
- Task sequence: `../00_project_brief/task_sequence.md`.

## Result

- Success: `true`.
- Total estimated cost: `null`.
- Manual verification: not performed by this runner.

## Task Runs

| Task | Success | Provider calls | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `01_static_scaffold` | `true` | 4 | 12689 | 0 | 4504 | 30005 |  |
| `02_data_and_textures` | `true` | 3 | 10499 | 0 | 9565 | 43849 |  |
| `03_bodies_scale_orbits` | `true` | 3 | 15362 | 0 | 5983 | 24331 |  |
| `04_animation_time_scale` | `true` | 3 | 15365 | 0 | 6610 | 27211 |  |
| `05_earth_seasons` | `true` | 3 | 16096 | 0 | 8533 | 39807 |  |
| `06_camera_labels_focus` | `true` | 3 | 16883 | 0 | 5407 | 24254 |  |
| `07_info_accessibility` | `true` | 3 | 17122 | 0 | 5753 | 27405 |  |
| `08_responsive_performance_readme` | `true` | 3 | 17562 | 0 | 5230 | 24885 |  |

## Model Routing

Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`, so planner calls use the router model unless the SFE internals change.

## Generated Files

- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/index.html`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/styles.css`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/app.js`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.
