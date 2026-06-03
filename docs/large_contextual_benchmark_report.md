# Large Contextual Benchmark Report

This report records the large/contextual benchmark phases merged to `main`.
The fixture/oracle benchmark was merged in commit
`793e5e4f9d73f7e5fbc9d2ab6ce2139ac8708fe7`; the optional real-router selection
mode was merged in commit `5abf6ed1ecfde7cee6e6acc289e513f469699e99`.

The older detailed results below are Lemonade-first historical benchmark notes.
Current provider-comparison summaries now also cover OpenAI, Anthropic, and
Alibaba/Qwen. See:

- `docs/provider_comparison_summary.md`
- `docs/token_cost_metrics.md`
- `docs/openai_paced_equivalent_summary.md`
- `docs/anthropic_benchmark_paced_summary.md`
- `docs/alibaba_large_contextual_missing_tiers.md`
- `docs/alibaba_structural_50k_comparison_note.md`

## Purpose

The benchmark tests whether SFE can provide a practical advantage when the executor would otherwise receive a large, noisy context. Earlier experiments showed that routing can work, but routing and orchestration have fixed costs. This phase asks whether context reduction can amortize those costs.

Each task contains multiple context blocks. One block is clearly relevant to the user question; the remaining blocks are plausible distractors. The baseline receives all blocks. The spatial/SFE path receives the user question plus only the selected relevant block.

The benchmark began as Lemonade-first. The current runner also supports
provider-backed execution through `lemonade`, `openai-api`, `alibaba-api`,
`anthropic`, and `google` executors. These provider paths should still be
compared only when the run protocol is aligned.

## Benchmark Shape

- Benchmark type: `large/contextual`
- Executor choices: `lemonade`, `openai-api`, `alibaba-api`, `anthropic`, and
  `google`
- Default router: `fixture_relevance_router`
- Optional real router: `lemonade_block_selector`
- Current fixture task count: 7
- Default task tier: `standard`
- Practical task tier: `practical` with 10k-20k estimated baseline input tokens
- High-context task tier: `high_context` with 20k-50k estimated baseline input tokens
- Structural task tier: `structural` with 50k+ estimated baseline input tokens
- Preserved live result task count: 7
- Preserved live result run count: 14
- Dry run: false for the preserved live result
- Baseline prompt: all context blocks plus the question
- Spatial prompt: selected relevant block plus the question
- Default selection method: deterministic fixture marker
- Optional selection method: Lemonade block selector over compact block metadata

The deterministic selector remains intentional as the default fixture mode. It
isolates executor context reduction and avoids mixing that result with
router-quality measurement. Real-router mode is available as a separate opt-in
path for testing whether the configured provider can identify the relevant
block under semantic noise.

## Task Tiers

The default `standard` tier remains the reference benchmark and keeps the existing 7 tasks unchanged. It targets roughly 2k-5k estimated baseline input tokens per task and is the mechanism-validation tier.

The `practical` tier is selected with:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier practical --selection-mode both --limit 1
```

The practical tier is separate from the standard task set and currently contains 10k-20k estimated baseline input token tasks with one fixture-relevant block, strong semantic distractors, false-answer distractors, temporal/version distractors, and near-relevant blocks. It is the first economically meaningful long-context tier for testing whether SFE can amortize router cost. The older `long` name remains accepted as a backward-compatible alias for `practical`.

The `high_context` tier is selected with:

```bash
python runtime/run_large_contextual_benchmark.py --task-tier high_context --selection-mode both --limit 1
```

The high_context tier is separate from the standard and practical task sets and currently contains 20k-50k estimated baseline input token tasks. It is intended to test whether SFE becomes materially useful as prompt size, semantic noise, and distractor density grow.

The `structural` tier targets 50k+ token tasks where context structure becomes
closer to a necessity than a small optimization. It is implemented in the
current runner and is included in current OpenAI, Anthropic, and Alibaba/Qwen
documentation. Structural observations remain small controlled runs, not broad
reliability evidence.

## Current Multi-Provider Status

OpenAI and Anthropic have protocol-aligned `standard`, `practical`,
`high_context`, and `structural` observations. Alibaba/Qwen has repeat-3
`standard`, `practical`, and `high_context` observations, plus a single live
`structural` baseline-vs-spatial comparison. Lemonade remains useful as a local
provider and historical validation path.

Current README-level terminology distinguishes:

- selected reduction: executor-visible context reduction;
- router-inclusive reduction: reduction after selector/router overhead;
- `spatial_fixture`: oracle-style fixture selection;
- `spatial_router`: provider-backed router selection.

These are controlled benchmark observations, not statistical proof and not
production readiness evidence.

## High Context 64K Lemonade Result

The high_context tier is sensitive to Lemonade context-window configuration. Earlier high_context attempts at smaller context sizes exposed backend execution limits rather than benchmark reasoning failures:

- At 16K context size, high_context baseline execution produced empty outputs.
- At 32K context size, one baseline succeeded and one baseline still produced an empty output.
- At 64K context size, both high_context baseline runs completed successfully.

These earlier empty baseline outputs should be interpreted as full-context execution/context-window/backend limitations. They are not evidence that the baseline prompt lacked the answer or that the baseline reasoning task was impossible.

Clean comparison command, with Lemonade context size configured to 64K:

```bash
python runtime/run_large_contextual_stability.py --iterations 1 --selection-mode both --task-tier high_context --timeout-seconds 600
```

Aggregate result:

- Iterations: 1
- Task count: 2
- Total runs: 6
- Baseline success rate: 100.00%
- Spatial fixture success rate: 100.00%
- Spatial router success rate: 100.00%
- Router valid selection rate: 100.00%
- Router match rate: 100.00%
- Fallback count: 0
- Fallback rate: 0.00%
- Executor input token reduction: 90.98%
- Average router latency: 7064.50 ms
- Average router total tokens: 3416.00
- Average router+executor latency: 40748.50 ms
- Average router+executor total tokens: 5194.00

Baseline task details:

| Task | Baseline success | Input tokens | Total tokens | Latency ms | Validation targets |
| --- | ---: | ---: | ---: | ---: | --- |
| `large_contextual_high_context_orion_router_budget_gate` | true | 19043 | 19164 | 90836 | `31.4`, `NebulaReplay-88`, `Imani Vos`, `orb74_cost_epoch_lock` |
| `large_contextual_high_context_boreal_eval_release_gate` | true | 18958 | 19073 | 89286 | `0.783`, `0.86`, `QuasarBlend-52`, `Celia Okafor` |

Derived comparison:

- Baseline average latency was about 90.1 seconds.
- Spatial router end-to-end average latency was about 40.7 seconds.
- Baseline average total tokens were about 19118.
- Spatial router end-to-end average total tokens were about 5194.
- Router-inclusive end-to-end token reduction was about 72.8%.
- Executor input token reduction was about 90.98%.

This is the cleanest high_context comparison so far: baseline, spatial_fixture, and spatial_router all succeeded; the router selected the fixture-matching block on both tasks; fallback count was zero; and spatial_router preserved correctness while reducing both latency and router-inclusive token usage.

The result is still a small engineering signal, not statistical proof. It covers only two high_context tasks, one live iteration, local Lemonade execution, and synthetic deterministic fixtures. Current OpenAI, Anthropic, and Alibaba/Qwen notes now provide separate provider-comparison context; this historical Lemonade result depends on Lemonade being configured with enough context capacity; for this run, that was 64K.

The next recommended high_context step is a small stability run, for example:

```bash
python runtime/run_large_contextual_stability.py --iterations 3 --selection-mode both --task-tier high_context --timeout-seconds 600
```

This historical recommendation was appropriate before the later provider and
structural work. Current readers should use the provider-comparison summaries
listed above for the latest cross-provider status.

## High Context 3-Iteration Stability Result

The first high_context stability run repeated the clean 64K Lemonade setup across three iterations:

```bash
python runtime/run_large_contextual_stability.py --iterations 3 --selection-mode both --task-tier high_context --timeout-seconds 600
```

Aggregate result:

- Iterations: 3
- Task count: 2
- Total runs: 18
- Baseline success rate: 100.00%
- Spatial fixture success rate: 100.00%
- Spatial router success rate: 100.00%
- Router valid selection rate: 100.00%
- Router match rate: 100.00%
- Router match rate among valid selections: 100.00%
- Fallback count: 0
- Fallback rate: 0.00%
- Average router latency: 7286.00 ms
- Average router total tokens: 3416.00
- Average router+executor latency: 41313.67 ms
- Average router+executor total tokens: 5194.00
- Average input token reduction: 90.98%

Per-task router stability:

| Task | Router runs | Valid | Matches | Mismatches | Fallbacks | Selected block counts |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `large_contextual_high_context_boreal_eval_release_gate` | 3 | 3 | 3 | 0 | 0 | `ber122-hc4-final`: 3 |
| `large_contextual_high_context_orion_router_budget_gate` | 3 | 3 | 3 | 0 | 0 | `orb74-hc2-final`: 3 |

This is encouraging and stronger than the single smoke run: baseline, spatial_fixture, and spatial_router succeeded on all repeated runs; the router selected the fixture-matching block every time; and no fallback-assisted executor runs occurred.

The result is still not statistical proof. It covers two high_context tasks,
three live iterations, local Lemonade execution, and synthetic deterministic
fixtures. Later OpenAI, Anthropic, Alibaba/Qwen, and structural notes provide
additional context, but they remain controlled benchmark observations rather
than broad reliability claims.

## Selection Modes

The benchmark now supports three selection modes:

- `fixture`: the default compatibility mode. It runs `baseline` and `spatial`, where `spatial` receives the fixture-selected relevant block. This is the oracle upper bound for context reduction.
- `router`: runs `baseline` and `spatial_router`. The router receives the user question plus compact block IDs, titles, previews, and keywords, then returns a selected block ID. The executor receives only that selected block.
- `both`: runs `baseline`, `spatial_fixture`, and `spatial_router` for direct comparison.

Router output is validated as JSON with `selected_block_id`, `confidence`, and `reason`. Invalid JSON, invalid block IDs, or router failures are reported in the run data and safely fall back to fixture selection for execution. Fallback-assisted executor success is not counted as a valid router selection. Reports include valid router selection rate, match rate across all router tasks, match rate among valid selections, fallback count/rate, router latency, router token usage when available, and router-plus-executor end-to-end metrics.

Dry-run mode does not require Lemonade. In dry-run router modes, a deterministic simulated selector chooses the fixture-relevant block and marks the decision as simulated.

Repeated stability runs are available for the standard tier through:

```bash
python runtime/run_large_contextual_stability.py --iterations 5 --selection-mode both --timeout-seconds 240
```

The stability report preserves each iteration summary and aggregates router match counts, fallback counts, router cost, router-plus-executor cost, and per-task instability signals across repeated runs. It defaults to `--task-tier standard` so the scheduled stability run remains on the reference benchmark. It does not add tasks, change benchmark semantics, or include OpenAI API execution.

For cron, launch from the repository root so the local Python path and ignored `logs/` outputs are predictable:

```bash
cd /path/to/SpatialFieldEngineForCognition && TMPDIR=/tmp TMP=/tmp TEMP=/tmp python runtime/run_large_contextual_stability.py --iterations 5 --selection-mode both --timeout-seconds 240
```

The runner loads repository `.env` before resolving CLI defaults, matching `runtime/run_large_contextual_benchmark.py`; `SFE_LEMONADE_BASE_URL` can therefore point at a LAN Lemonade host without passing `--base-url`.

## Expanded Fixture Design

After the preserved live result below, the fixture set was expanded from 3 to 7 tasks before testing a real router. The added tasks keep the same benchmark semantics: each task still has exactly one relevant block, the baseline prompt receives every block, and the spatial prompt receives only the selected relevant block.

The expanded tasks add harder semantic distractors:

- Same-keyword distractors, where several blocks repeat terms such as failover, cache, rollback, latency, allocation, or evaluation.
- False-answer distractors, where an irrelevant block contains a plausible but superseded or rejected answer.
- Temporal distractors, where similar incidents or gates appear across different dates or versions.
- Near-relevant blocks, where a distractor contains part of the operational context but lacks the exact decision, mitigation, threshold, or owner.
- Selected-block cross-references, where the answer requires connecting two details inside the selected block.

The expanded 7-task fixture set has a full Lemonade fixture live run and a full
Lemonade real-router live run. The expansion makes the deterministic
context-reduction fixture harder. Real-router mode tests whether SFE can
identify the relevant block, not just benefit from a known block. Later OpenAI,
Anthropic, and Alibaba/Qwen runs are summarized in the provider-specific notes
linked above.

## Fixture Live Result

Command:

```bash
python runtime/run_large_contextual_benchmark.py --timeout-seconds 180
```

| Metric | Baseline | Spatial |
| --- | ---: | ---: |
| Runs | 7 | 7 |
| Average input tokens | 2788.43 | 536.57 |
| Average total tokens | 2843.29 | 586.14 |
| Average latency | 10532.29 ms | 4340.43 ms |
| Success rate | 100.00% | 100.00% |

Additional aggregate metrics:

- Context reduction verified: true
- Input token reduction: 80.76%

This fixture result showed that, when the relevant zone is known, reducing executor context can preserve success while reducing input tokens and latency. It is an oracle upper bound for context reduction, not a router-quality result.

## Per Task

| Task | Baseline input | Spatial input | Reduction | Selected block |
| --- | ---: | ---: | ---: | --- |
| `large_contextual_cache_failover_keyscope` | 2954.00 | 622.00 | 78.94% | `helio-cache-incident` |
| `large_contextual_eval_rollback` | 2352.00 | 477.00 | 79.72% | `eval-plan` |
| `large_contextual_inventory_allocation` | 2324.00 | 464.00 | 80.03% | `allocation` |
| `large_contextual_near_relevant_allocation_exception` | 3124.00 | 570.00 | 81.75% | `cobalt-dispatch-decision` |
| `large_contextual_payments_failover` | 2314.00 | 432.00 | 81.33% | `pay-ops` |
| `large_contextual_rollback_false_owner` | 3169.00 | 595.00 | 81.22% | `r42-gateway-decision` |
| `large_contextual_temporal_evaluation_gate` | 3282.00 | 596.00 | 81.84% | `boreal-2026-04` |

## Real-Router Live Result

Command:

```bash
python runtime/run_large_contextual_benchmark.py --selection-mode both --timeout-seconds 240
```

This run used the optional Lemonade block selector and compared `baseline`, `spatial_fixture`, and `spatial_router`.

Aggregate metrics:

- Runs: 21
- Context reduction verified: true
- Input token reduction: 80.72%
- Router valid selection rate: 100.00%
- Router match rate: 100.00%
- Fallback-assisted executor runs: 0

Earlier real-router testing exposed two concrete selector failures:

- `large_contextual_cache_failover_keyscope` selected `helio-ops-timeline`, a topically related timeline block, instead of answer-sufficient block `helio-cache-incident`.
- `large_contextual_temporal_evaluation_gate` produced invalid block ID `boral-2026-04` instead of exact ID `boreal-2026-04`.

The selector prompt was hardened without changing benchmark tasks, fixture labels, or benchmark semantics. It now emphasizes answer sufficiency over topical similarity, warns that distractors may share keywords, dates, people, and incident vocabulary, requires exact requested values to be present in the selected block, and requires exact block ID copying from the allowed ID list. Fallback remains explicit and is not counted as normal router success.

After this hardening, the latest live run selected `helio-cache-incident` for `large_contextual_cache_failover_keyscope`, selected `boreal-2026-04` for `large_contextual_temporal_evaluation_gate`, and had zero fallback-assisted executor runs.

## Interpretation

The fixture result is a stronger positive Lemonade signal than the earlier 3-task result, but it is still not final proof. On the expanded 7-task Lemonade-backed task set, the spatial path preserved success while substantially reducing executor input tokens and average latency.

The result supports selective SFE activation when the task has enough irrelevant or separable context for reduction to matter. It does not show that SFE should be applied to every task. The fixed cost of routing and orchestration still matters, especially for short prompts or tasks where context cannot be reduced safely.

The real-router result is encouraging because Lemonade selected the fixture-matching block on the current 7-task benchmark after prompt hardening. It is still not a statistical proof. The task set is small, deterministic, and synthetic; the result should be treated as a positive engineering signal rather than a general claim about router reliability.

End-to-end economics still matter. Router selection has its own token and
latency cost, so SFE should be activated where context reduction or cognitive
separation can plausibly amortize that cost. Current docs should report both
selected-context reduction and router-inclusive reduction.

## Limits

- The task set is still small, even after expanding to 7 fixtures.
- The task set is deterministic and synthetic.
- Validation is lightweight and task-specific.
- Results depend on the local Lemonade server and configured model.
- The fixture live result uses deterministic fixture selection and is an oracle upper bound.
- The real-router live result evaluates block selection only on the current 7-task fixture set.
- Later OpenAI, Anthropic, and Alibaba/Qwen observations exist, but the
  historical Lemonade results in this report remain small, synthetic, and
  controlled.

## Phase Conclusion

Routing is reliable, but routing has a fixed cost. SFE must be activated selectively on tasks where context reduction or cognitive separation can amortize that cost.
