# NoteKeeper benchmark comparison

NoteKeeper is a small-project benchmark for comparing full-context generation with SFE-driven runs. The benchmark is useful as reliability evidence for a compact application, but it does not currently support a claim that SFE saves total tokens on this workload.

## Scenario outcomes

| Scenario | Strict result | Practical result | Interpretation |
| --- | --- | --- | --- |
| `10_baseline_full_context_gpt54` | Passed through `05_responsive_polish` | Complete app | Full-context baseline. |
| `20_sfe_single_model_gpt54_nomultipass` | Failed at `05_responsive_polish` with a patch preimage mismatch | Usable app after tasks 1-4 | Single-model SFE produced a manually testable app, but did not complete strict validation. |
| `30_sfe_split_gpt54_router_gpt54mini_executor` | Failed at `05_responsive_polish` with a patch preimage mismatch | Usable app after tasks 1-4 | Split-model SFE reduced expensive-model exposure, but did not complete strict validation. |
| `40_sfe_single_model_gpt54_multipass` | Passed through `05_responsive_polish` | Complete app | Strongest reliability evidence in this run; multipass improved completion reliability. |

## Token comparison

Scenarios 20 and 30 failed strict validation at task 5, so their successful comparison window is tasks 1-4 only.

| Scenario | Comparable scope | Total tokens | Baseline tokens | Delta | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| `20_sfe_single_model_gpt54_nomultipass` | Tasks 1-4 | 70,140 | 54,581 | +28.5% | SFE increased total token volume. |
| `30_sfe_split_gpt54_router_gpt54mini_executor` | Tasks 1-4 | 66,745 | 54,581 | +22.3% | SFE increased total token volume, while shifting execution to `gpt-5.4-mini`. |
| `40_sfe_single_model_gpt54_multipass` | Full run | 320,517 | 75,646 | +323.7% | Multipass completed strictly, but was much more expensive in token volume. |

Available run totals for scenarios 20 and 30 include the failed task-5 attempts and are not equivalent to the successful full baseline:

| Scenario | Available total tokens | Full baseline tokens | Delta | Note |
| --- | ---: | ---: | ---: | --- |
| `20_sfe_single_model_gpt54_nomultipass` | 95,017 | 75,646 | +25.6% | Includes failed `05_responsive_polish`. |
| `30_sfe_split_gpt54_router_gpt54mini_executor` | 86,885 | 75,646 | +14.9% | Includes failed `05_responsive_polish`. |

## Cost interpretation

The strongest supported claim from this benchmark is cost-control architecture, not raw token reduction.

For scenario 30 through tasks 1-4:

- Baseline used 54,581 tokens on `gpt-5.4`.
- Scenario 30 used 10,784 tokens on `gpt-5.4`.
- Scenario 30 used 55,961 executor tokens on `gpt-5.4-mini`.

This means token volume increased, but expensive `gpt-5.4` exposure dropped sharply. Depending on model pricing, a split-model SFE run can be cheaper in dollar cost even when it is not cheaper in token volume.

## Caveat

NoteKeeper is a small benchmark. Its baseline context is not large enough to amortize SFE orchestration overhead. A larger benchmark with much more irrelevant or weakly relevant context is needed before making strong token-saving claims.
