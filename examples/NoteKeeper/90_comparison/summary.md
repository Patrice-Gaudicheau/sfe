# NoteKeeper benchmark comparison

This summary is a placeholder for comparing the four NoteKeeper benchmark scenarios after all runs are complete.

## Scenarios to compare

- `10_baseline_full_context_gpt54`: baseline full context with `gpt-5.4` only, without SFE.
- `20_sfe_single_model_gpt54_nomultipass`: SFE single-model run with `gpt-5.4` and multipass disabled.
- `30_sfe_split_gpt54_router_gpt54mini_executor`: SFE split-model run with `gpt-5.4` for router/discovery/multipass planning, `gpt-5.4-mini` for execution, and multipass auto.
- `40_sfe_single_model_gpt54_multipass`: SFE single-model run with `gpt-5.4` for all roles and multipass auto.

## To fill after all runs

- Overall success and acceptance criteria comparison.
- Token and cost comparison.
- Latency or wall-clock duration comparison.
- Manual verification comparison.
- Code quality and maintainability observations.
- Notable workflow differences.
- Screenshots or visual notes, if captured.