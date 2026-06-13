# SFE split-model gpt-5.4 router / gpt-5.4-mini executor report

Generated at: `2026-06-13T13:30:46+00:00`

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

- Success: `false`.
- Total estimated cost: `null`.
- Manual verification: not performed by this runner.

## Task Runs

| Task | Success | Provider calls | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `01_static_scaffold` | `true` | 4 | 13002 | 0 | 5466 | 26718 |  |
| `02_data_and_textures` | `true` | 3 | 11723 | 0 | 11126 | 47864 |  |
| `03_bodies_scale_orbits` | `false` | 3 | 16690 | 0 | 8659 | 36801 | hunk_location_mismatch |

## Model Routing

Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`, so planner calls use the router model unless the SFE internals change.

## Generated Files

- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/index.html`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/styles.css`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/app.js`
- `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.
