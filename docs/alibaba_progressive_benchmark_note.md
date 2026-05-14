# Alibaba Progressive Benchmark Note

This note records a limited progressive Alibaba Model Studio benchmark campaign.
It is not a reliability benchmark, not a statistical provider comparison, and
not production validation. Alibaba Qwen thinking was disabled for all live
calls to keep token accounting usable.

## Configuration

- Router provider/model: `alibaba-api` / `qwen3.6-flash`
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`
- Qwen thinking disabled: `true`
- Raw reports were written under `/tmp` and were not committed.

## Stage A: Effectiveness Benchmark

Command shape:

```bash
python runtime/run_effectiveness_benchmark.py \
  --router alibaba-api \
  --router-model qwen3.6-flash \
  --executor alibaba-api \
  --executor-model qwen3.6-plus \
  --repeat 1 \
  --max-tokens 96 \
  --strict
```

Result summary:

- Paired runs: `10`
- Router success rate: `100.00%`
- JSON valid rate: `100.00%`
- Fallback count: `0`
- Parse failure count: `0`
- Provider error count: `0`
- Real routing accuracy: `100.00%`
- Router token total: `13421`
- Router token range: `1334` to `1360`
- Executor token total: `5027`
- Executor latency range: `1554 ms` to `5170 ms`
- Effective by target metric: `false`

Interpretation: Stage A validated Alibaba benchmark wiring and router JSON
behavior on the existing effectiveness benchmark. It did not show benchmark
effectiveness under the current metric, and one spatial run was excluded from
strict scoring.

## Stage B: High-Overlap Selector Repeat-3

Fixture: `high_overlap_cassini_policy_exception_gate`

- Expected authoritative ID: `cassini-v31`
- Pass count: `3/3`
- Fallback count: `0`
- Parse failure count: `0`
- Provider error count: `0`
- Router token total: `2519`
- Token range: `824` to `866`
- Latency range: `1679 ms` to `1851 ms`

Per-run selected IDs:

- Run 1: `cassini-v31`
- Run 2: `cassini-v31`
- Run 3: `cassini-v31`

Interpretation: In this limited repeat-3 smoke, Alibaba selected the
authoritative high-overlap document every time without fallback.

## Stage C: Multi-Zone Synthetic Smoke

Stage C used the existing multi-zone synthetic benchmark functions with a small
Alibaba selector/executor adapter, limited to one fixture and one repeat.

- Fixture: `multi_zone_synthetic_aurora_release_gate`
- Honest multi-zone pass count: `1/1`
- Selected zone completeness rate: `100.00%`
- Distractor rejection rate: `100.00%`
- Fallback count: `0`
- Executor parse success rate: `100.00%`
- Selector tokens: `1156`
- Executor tokens: `977`
- Average selected-zone token reduction: `28.57%`

Interpretation: Stage C validated one Alibaba multi-zone selection/execution
path without fallback. This remains a small smoke, not a broad multi-zone
benchmark.

## Stage D: Large/Contextual Limited Smoke

Stage D used the large/contextual benchmark provider hook with Alibaba, limited
to one standard-tier task and one repeat. This was a compatibility smoke rather
than a committed Alibaba mode for that runner.

- Run count: `2`
- Router run count: `1`
- Successful runs: `2`
- Router success count: `1`
- Router valid selection count: `1`
- Router matched fixture count: `1`
- Fallback count: `0`
- Provider error count: `0`
- Router tokens: `1619`
- Executor tokens: `2848`
- Router latency: `1793 ms`
- Executor latency range: `2223 ms` to `4123 ms`
- Router selected block: `pay-ops`
- Fixture block: `pay-ops`

Interpretation: Stage D validated a limited large/contextual Alibaba path on
one standard-tier task. It does not validate the full large/contextual suite.

## Stage E: Structural 50k Dry-Run Estimate

No live structural 50k Alibaba run was executed. A dry-run estimate for one
structural task showed:

- Baseline total tokens estimate: `74248`
- Spatial router executor tokens estimate: `4280`
- Spatial router router tokens estimate: `5742`
- Spatial router end-to-end tokens estimate: `10022`
- Estimated reduction vs baseline: `86.50%`

Interpretation: the estimated full-context baseline cost is high enough that a
live structural Alibaba run should require an explicit decision before running.
