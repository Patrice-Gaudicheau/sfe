# SolarSystem3D comparison

This directory is reserved for comparison artifacts after the SolarSystem3D benchmark scenarios are run. No scenarios have been run yet.

## Planned scenarios

| Scenario | Purpose | Status |
| --- | --- | --- |
| `10_baseline_full_context_gpt54` | Full-context baseline using `gpt-5.4`. | Not run |
| `20_sfe_single_model_gpt54_multipass` | SFE single-model multipass using `gpt-5.4`. | Not run |
| `30_sfe_split_gpt54_router_gpt54mini_executor_multipass` | SFE split-model multipass using `gpt-5.4` router/planner/reviewer and `gpt-5.4-mini` executor. | Not run |

## Comparison Method

Use the shared brief, task sequence, and acceptance criteria for every scenario. Compare strict completion, practical usability, acceptance criteria coverage, manual browser findings, token volume, expensive-model exposure, estimated cost, latency, and scenario deviations.

Do not claim that SFE saves tokens unless the collected results support that conclusion. If a scenario fails before the full task sequence, compare only the largest common completed task window and label any failed-attempt totals separately.

## Suggested artifacts

- `summary.md` for final interpretation.
- `cost_table.csv` for token and cost data.
- `acceptance_matrix.csv` for criteria pass/fail notes.
- `screenshots/` for browser screenshots if captured.
- Scenario-specific manual review notes if needed.

