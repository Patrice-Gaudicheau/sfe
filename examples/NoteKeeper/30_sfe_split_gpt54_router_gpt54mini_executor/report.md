# SFE split-model gpt-5.4 router / gpt-5.4-mini executor report

Generated at: `2026-06-13T10:10:50+00:00`

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
| `01_initial_scaffold` | `false` | 6 | 15548 | 0 | 5774 | 32713 | Missing required app files in controlled workspace: app.js, README.md |

## Model Routing

Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`, so planner calls use the router model unless the SFE internals change.

## Generated Files


## Notes

Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.

## Post-run audit

The scenario was run exactly once with:

```bash
python3 scripts/run_notekeeper_sfe_split_model_openai.py --router-model gpt-5.4 --discovery-model gpt-5.4 --executor-model gpt-5.4-mini
```

The run used the real SFE `RunPipeline` / `RunRequest` path. Multipass was forced to `auto` intentionally for scenario 30.

Model configuration:

- Router: `gpt-5.4`
- Discovery: `gpt-5.4`
- Multipass planner: `gpt-5.4`
- Executor: `gpt-5.4-mini`

The command exited with code `1`.

Task outcome:

- `01_initial_scaffold`: failed
- `02_persistence_and_crud`: not run
- `03_labels_search_archive`: not run
- `04_checklists_and_pinning`: not run
- `05_responsive_polish`: not run

Failure summary:

- The scenario app directory still contains only `app/.gitkeep`.
- No final app files were copied into the scenario `app/` directory because task 1 failed validation.
- The temporary multipass workspace promoted `app/index.html` and `app/styles.css`, but the run failed before all required files were produced.
- Runner validation error: `Missing required app files in controlled workspace: app.js, README.md`
- SFE issue category: `multi_pass_patch_scope`
- SFE issue reason: `path_outside_batch_allowed_files`
- SFE issue path: `app/index.html`

Multipass details:

- `passes_total`: 4
- `passes_completed`: 2
- Failed pass: `scaffold-behavior-js`
- Failed pass allowed only `app/app.js`
- The patch also touched `app/index.html`

Interpretation:

SFE successfully routed, discovered context, selected context, planned multipass execution, and started multipass patch execution. The failure is not a completed-app quality failure. The failure documents a current multipass patch-scope limitation: the executor produced a patch touching a file outside the allowed file batch for that pass.

This failed result is committed as a raw benchmark artifact, without manual repair.

Provider calls by role:

| Role | Calls | Input tokens | Cached input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Router | 1 | 611 | 0 | 39 | 2334 |
| Discovery | 1 | 835 | 0 | 58 | 1444 |
| Multipass planner | 1 | 3430 | 0 | 639 | 7220 |
| Executor | 3 | 10672 | 0 | 5038 | 21715 |

Provider calls by model:

| Model | Calls | Input tokens | Cached input tokens | Output tokens | Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 3 | 4876 | 0 | 736 | 10998 |
| `gpt-5.4-mini` | 3 | 10672 | 0 | 5038 | 21715 |

Token totals:

- `input_tokens`: 15548
- `cached_input_tokens`: 0
- `output_tokens`: 5774
- `latency_or_wall_clock_duration`: 32713
- `total_estimated_cost`: `null`

Caveats:

- The app is empty by design after validation failure.
- The partial files promoted inside the temporary workspace should not be treated as the scenario output.
- The generated app should not be manually corrected.
- The failure is useful for documenting current SFE multipass patch mechanics limitations.
