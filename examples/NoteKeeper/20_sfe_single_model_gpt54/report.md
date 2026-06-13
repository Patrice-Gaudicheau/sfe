# SFE single-model gpt-5.4 report

Generated at: `2026-06-13T09:52:27+00:00`

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
| `01_initial_scaffold` | `true` | 3 | 4844 | 0 | 3785 | 20528 |  |
| `02_persistence_and_crud` | `false` | 3 | 4972 | 0 | 5428 | 24639 | target_already_exists |

## Generated Files

- `examples/NoteKeeper/20_sfe_single_model_gpt54/app/index.html`
- `examples/NoteKeeper/20_sfe_single_model_gpt54/app/styles.css`
- `examples/NoteKeeper/20_sfe_single_model_gpt54/app/app.js`
- `examples/NoteKeeper/20_sfe_single_model_gpt54/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, and run metadata are stored under `runs/<task>/`.

## Post-run audit

The scenario was run exactly once with:

```bash
python3 scripts/run_notekeeper_sfe_single_model_openai.py --model gpt-5.4
```

The run used the real SFE `RunPipeline` / `RunRequest` path. Multipass was forced off intentionally for scenario 20 to isolate SFE routing, discovery, context selection, and executor behavior without testing the multi-pass scaffold workflow. A future scenario named `40_sfe_single_model_gpt54_multipass` will test the same model with multipass enabled.

The command exited with code `1`.

Task outcome:

- `01_initial_scaffold`: success
- `02_persistence_and_crud`: failed
- `03_labels_search_archive`: not run
- `04_checklists_and_pinning`: not run
- `05_responsive_polish`: not run

Failure details:

- Category: `physical_application_failure`
- Reason: `target_already_exists`
- Path: `app/index.html`

Interpretation: SFE successfully routed the task, discovered context, prepared executor prompts, and executed the patch/worktree flow, but native patch application failed because the task 2 patch attempted to create a file that already existed.

This failed result is committed as a raw benchmark artifact, without manual repair.

Token usage summary:

| Role | Calls | Input tokens | Cached input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Router | 2 | 1133 | 0 | 99 | 4023 |
| Discovery | 2 | 1742 | 0 | 143 | 2863 |
| Executor | 2 | 6941 | 0 | 8971 | 38281 |

Totals:

- `input_tokens`: 9816
- `cached_input_tokens`: 0
- `output_tokens`: 9213
- `latency_or_wall_clock_duration`: 45167
- `total_estimated_cost`: `null`

Caveats:

- The app visible in `app/` is only the task 1 scaffold.
- It is not a completed NoteKeeper implementation.
- The generated app should not be manually corrected.
- The failure is useful for documenting current SFE patch mechanics limitations.
