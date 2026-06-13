# SFE single-model gpt-5.4 multipass report

Generated at: `2026-06-13T13:51:17+00:00`

## Scenario

- Workflow: SFE single-model run with multipass forced on.
- Provider: `openai-api`.
- Router model: `gpt-5.4`.
- Discovery model: `gpt-5.4`.
- Multipass planner model: `gpt-5.4`.
- Executor model: `gpt-5.4`.
- Multipass: `true`.
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
| `01_static_scaffold` | `false` | 9 | 189748 | 0 | 56271 | 255692 | hunk_preimage_mismatch |

## Generated Files

- `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass/app/index.html`
- `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass/app/styles.css`
- `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass/app/app.js`
- `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, and run metadata are stored under `runs/<task>/`.
