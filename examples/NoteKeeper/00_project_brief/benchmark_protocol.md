# NoteKeeper benchmark protocol

This benchmark uses the same project brief, acceptance criteria, and task sequence across three development scenarios. The goal is to compare workflow behavior on a small static web application while keeping the product request stable.

Do not change `00_project_brief/prompt.md`, `00_project_brief/acceptance_criteria.md`, or `00_project_brief/task_sequence.md` between scenarios. Each scenario should attempt the same five tasks in order.

## Scenarios

1. Baseline full context with `gpt-5.4` only, without SFE.
2. SFE single-model run with `gpt-5.4` used for routing, discovery, and execution.
3. SFE split-model run with `gpt-5.4` for router/discovery and `gpt-5.4-mini` for executor.

## Run capture requirements

After each scenario run, capture the following information when available:

- Provider and model per role, including router, discovery, executor, reviewer, or equivalent roles.
- Input tokens.
- Cached input tokens.
- Output tokens.
- Total estimated cost.
- Latency or wall-clock duration.
- Success or failure.
- Generated or modified files.
- Manual verification notes.

If a metric is not available, record it as `null` in `token_usage.json` and explain the gap briefly in `report.md`.

## Suggested run documentation

Each scenario folder contains a scenario-local `app/` directory for the final generated application produced by that scenario. The `runs/` directory is reserved for logs, prompts, transcripts, diffs, screenshots, and task-level notes captured during the corresponding task.

The scenario-level `report.md` should summarize:

- Scenario configuration.
- What was executed.
- Whether the final app met the acceptance criteria.
- Any deviations from the task sequence.
- Manual verification findings.
- Known defects or follow-up work.

The scenario-level `token_usage.json` should contain structured token and cost data without invented values. Use `null` for unavailable metrics.

## Comparison

Use `90_comparison/summary.md` to compare the three scenarios after all runs are complete. Use `90_comparison/cost_table.csv` for tabular cost and token data. Store any final comparison screenshots in `90_comparison/screenshots/`.
