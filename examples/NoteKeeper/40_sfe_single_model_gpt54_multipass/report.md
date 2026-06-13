# SFE single-model gpt-5.4 multipass report

Generated at: `2026-06-13T10:37:17+00:00`

## Scenario

- Workflow: SFE single-model run with multipass auto.
- Provider: `openai-api`.
- Router model: `gpt-5.4`.
- Discovery model: `gpt-5.4`.
- Multipass planner model: `gpt-5.4`.
- Executor model: `gpt-5.4`.
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
| `01_initial_scaffold` | `true` | 7 | 19426 | 0 | 6720 | 37957 |  |
| `02_persistence_and_crud` | `false` | 3 | 5134 | 0 | 4516 | 20323 | target_already_exists |

## Model Routing

Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`. This runner sets that model to the same value as router, discovery, and executor.

## Generated Files

- `examples/NoteKeeper/40_sfe_single_model_gpt54_multipass/app/index.html`
- `examples/NoteKeeper/40_sfe_single_model_gpt54_multipass/app/styles.css`
- `examples/NoteKeeper/40_sfe_single_model_gpt54_multipass/app/app.js`
- `examples/NoteKeeper/40_sfe_single_model_gpt54_multipass/app/README.md`

## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.

## Post-run audit

The scenario was run exactly once with:

```bash
python3 scripts/run_notekeeper_sfe_single_model_multipass_openai.py --model gpt-5.4
```

The run used the real SFE `RunPipeline` / `RunRequest` path. Multipass was forced to `auto` intentionally for scenario 40.

Model configuration:

- Router: `gpt-5.4`
- Discovery: `gpt-5.4`
- Multipass planner: `gpt-5.4`
- Executor: `gpt-5.4`

The command exited with code `1`.

Task outcome:

- `01_initial_scaffold`: success, multipass completed 4/4 passes
- `02_persistence_and_crud`: failed
- `03_labels_search_archive`: not run
- `04_checklists_and_pinning`: not run
- `05_responsive_polish`: not run

Generated app state:

- The scenario app directory contains the four app files: `index.html`, `styles.css`, `app.js`, and `README.md`.
- These files come only from the successful task 1 scaffold.
- The app is partially generated and is not a completed NoteKeeper implementation.

Failure summary:

- Category: `physical_application_failure`
- Reason: `target_already_exists`
- Path: `app/index.html`

Interpretation:

SFE successfully routed, discovered context, selected context, planned multipass execution, completed the task 1 multipass scaffold, and promoted the four scaffold files. The run failed on task 2 because the generated patch attempted to create `app/index.html` even though the file already existed.

This failure mode resembles scenario 20 more than scenario 30. Scenario 30 failed earlier during task 1 with a multipass patch-scope violation. Scenario 40 shows that using `gpt-5.4` for all roles does not eliminate the `target_already_exists` patch-application issue.

This failed result is committed as a raw benchmark artifact, without manual repair.

Provider calls by role:

| Role | Calls | Input tokens | Cached input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Router | 2 | 1211 | 0 | 82 | 2967 |
| Discovery | 2 | 1819 | 0 | 135 | 3113 |
| Multipass planner | 1 | 3480 | 0 | 661 | 5798 |
| Executor | 5 | 18050 | 0 | 10358 | 46402 |

Provider calls by model:

| Model | Calls | Input tokens | Cached input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 10 | 24560 | 0 | 11236 | 58280 |

Token totals:

- `input_tokens`: 24560
- `cached_input_tokens`: 0
- `output_tokens`: 11236
- `latency_or_wall_clock_duration`: 58280
- `total_estimated_cost`: `null`

Caveats:

- The generated app should not be manually corrected.
- The app files are only the task 1 scaffold.
- The failure is useful for documenting current SFE patch mechanics limitations.
- In particular, SFE needs better handling when a later task should modify existing files instead of creating them again.
