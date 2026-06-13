# SFE split-model gpt-5.4 router / gpt-5.4-mini executor report

Generated at: `2026-06-13T12:21:04+00:00`

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
| `01_initial_scaffold` | `true` | 4 | 8655 | 0 | 4011 | 23137 |  |
| `02_persistence_and_crud` | `true` | 3 | 8128 | 0 | 8066 | 31382 |  |
| `03_labels_search_archive` | `true` | 3 | 11896 | 0 | 6942 | 31995 |  |
| `04_checklists_and_pinning` | `true` | 3 | 11863 | 0 | 7184 | 27254 |  |
| `05_responsive_polish` | `false` | 3 | 11949 | 0 | 8191 | 30039 | hunk_preimage_mismatch |

## Model Routing

Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`, so planner calls use the router model unless the SFE internals change.

## Generated Files

- `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/index.html`
- `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/styles.css`
- `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/app.js`
- `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.
