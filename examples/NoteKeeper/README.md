# NoteKeeper benchmark

NoteKeeper is a small-project benchmark for evaluating SFE behavior on a compact browser app. The app stores notes in `localStorage`, displays notes, and includes edit, pin, archive, delete, labels, search, checklist, and responsive polish tasks across a five-task sequence.

This benchmark is evidence for small-project reliability behavior. It is not evidence that SFE currently saves total tokens.

## Layout

- `00_project_brief/`: shared prompt, acceptance criteria, benchmark protocol, and task sequence.
- `10_baseline_full_context_gpt54/`: full-context baseline using `gpt-5.4`.
- `20_sfe_single_model_gpt54_nomultipass/`: SFE single-model run using `gpt-5.4`, without multipass.
- `30_sfe_split_gpt54_router_gpt54mini_executor/`: SFE split-model run using `gpt-5.4` for routing/discovery/planning and `gpt-5.4-mini` for execution.
- `40_sfe_single_model_gpt54_multipass/`: SFE single-model run using `gpt-5.4` with multipass.
- `90_comparison/`: comparison summary and token/cost table.

Generated apps are in each scenario's `app/` directory. Run reports, selected context, provider-call summaries, patch responses, and task results are in each scenario's `runs/` directory and top-level `report.md` / `token_usage.json` files.

## Results

| Scenario | Strict result | Practical result |
| --- | --- | --- |
| `10_baseline_full_context_gpt54` | Passed through `05_responsive_polish` | Complete app |
| `20_sfe_single_model_gpt54_nomultipass` | Failed at `05_responsive_polish` | Usable app after tasks 1-4 |
| `30_sfe_split_gpt54_router_gpt54mini_executor` | Failed at `05_responsive_polish` | Usable app after tasks 1-4 |
| `40_sfe_single_model_gpt54_multipass` | Passed through `05_responsive_polish` | Complete app |

The scenario 20 and 30 strict failures were late patch preimage mismatches during responsive polish. Manual inspection showed the apps produced after tasks 1-4 were usable: they could create notes, persist notes in `localStorage`, display notes, and expose expected edit, pin, archive, and delete controls.

Scenario 40 is the strongest reliability evidence in this set because it completed strict validation through the full five-task sequence.

## Rerunning

From the repository root:

```bash
python3 scripts/run_notekeeper_baseline_openai.py --model gpt-5.4
python3 scripts/run_notekeeper_sfe_single_model_nomultipass_openai.py --model gpt-5.4
python3 scripts/run_notekeeper_sfe_split_model_openai.py --router-model gpt-5.4 --executor-model gpt-5.4-mini
python3 scripts/run_notekeeper_sfe_single_model_multipass_openai.py --model gpt-5.4
```

These scripts write generated apps and run artifacts into the matching scenario directories.

## Token And Cost Interpretation

On this benchmark, SFE did not reduce total token usage:

- Scenario 20 used +28.5% total tokens versus baseline through tasks 1-4.
- Scenario 30 used +22.3% total tokens versus baseline through tasks 1-4.
- Scenario 40 completed strictly, but used +323.7% total tokens versus the full baseline.

Multipass improved reliability in this benchmark, not token efficiency.

The split-model scenario is better interpreted as cost-control evidence. Through tasks 1-4, the baseline used 54,581 tokens on `gpt-5.4`; scenario 30 used 10,784 tokens on `gpt-5.4` and 55,961 executor tokens on `gpt-5.4-mini`. Total token volume increased, but exposure to the expensive model dropped sharply.

NoteKeeper is small. Its baseline context is not large enough to amortize SFE orchestration overhead. A larger benchmark with much more irrelevant or weakly relevant context is needed before making strong token-saving claims.
