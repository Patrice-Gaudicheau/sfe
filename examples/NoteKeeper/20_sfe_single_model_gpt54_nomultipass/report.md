# SFE single-model gpt-5.4 no-multipass report

Generated at: `2026-06-13T12:11:00+00:00`

## Scenario

- Workflow: SFE single-model run.
- Provider: `openai-api`.
- Router model: `gpt-5.4`.
- Discovery model: `gpt-5.4`.
- Executor model: `gpt-5.4`.
- Multipass: `false`.
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
| `01_initial_scaffold` | `true` | 3 | 5048 | 0 | 4716 | 25938 |  |
| `02_persistence_and_crud` | `true` | 3 | 9164 | 0 | 8196 | 36797 |  |
| `03_labels_search_archive` | `true` | 3 | 11044 | 0 | 9703 | 40292 |  |
| `04_checklists_and_pinning` | `true` | 3 | 14057 | 0 | 8212 | 32584 |  |
| `05_responsive_polish` | `false` | 3 | 14683 | 0 | 10194 | 42093 | hunk_preimage_mismatch |

## Generated Files

- `examples/NoteKeeper/20_sfe_single_model_gpt54_nomultipass/app/index.html`
- `examples/NoteKeeper/20_sfe_single_model_gpt54_nomultipass/app/styles.css`
- `examples/NoteKeeper/20_sfe_single_model_gpt54_nomultipass/app/app.js`
- `examples/NoteKeeper/20_sfe_single_model_gpt54_nomultipass/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, and run metadata are stored under `runs/<task>/`.
