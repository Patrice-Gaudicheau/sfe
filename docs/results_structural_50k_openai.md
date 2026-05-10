# OpenAI Structural 50k+ Benchmark Result

## Purpose

This note records the OpenAI API result for the `structural` tier of the
large/contextual benchmark. The tier is a synthetic 50k+ token
structural-navigation stress test. It asks whether SFE can route a very large,
noisy context to the single authoritative record needed for execution, while
preserving exact answer fields and reporting route honesty explicitly.

This is not evidence of general intelligence, broad production readiness, or
universal context optimization. It is one controlled synthetic benchmark family
with one structural task.

## Task

The task is `large_contextual_structural_atlas_policy_mesh_gate`.

The baseline receives all 20 context blocks. The spatial-router path asks a
router to select one block, then sends only the selected block to the executor.
The expected authoritative block is `atlas-mesh-s9-final`.

The required answer values are:

- active version: `2026.08-s9`
- rollback threshold: `42.7` credits per thousand governed requests
- excluded replay dataset: `SableReplay-144`
- final approval owner: `ATLAS_OWNER_S9`
- mitigation label: `mesh_s9_epoch_pin`

## Publication Gate

The relevant publication gate is `honest_structural_pass`, not generic executor
success. The gate is true only when the spatial-router run satisfies all of the
following:

- router selection succeeded;
- no fixture fallback was used;
- selected-block verification was complete;
- output validation succeeded before repair;
- raw executor success was true.

The separate `honest_structural_pass_after_repair` field exists for repaired
outputs, but the headline result below did not require repair.

## Single Run

Source reports:

- `logs/large_contextual_benchmark_openai_api_structural_both_honest_gate.json`
- `logs/large_contextual_benchmark_openai_api_structural_both_honest_gate.md`

Configuration:

- provider: `openai-api`
- executor model: `gpt-5.5`
- router model: `gpt-5.4-nano`
- selection mode: `both`
- task tier: `structural`
- output repair limit: 1

Result:

- `honest_structural_pass`: true
- `honest_structural_pass_after_repair`: false
- router success: true
- selector fallback used: false
- verified selection complete: true
- raw executor success: true
- repaired success: true
- selected block: `atlas-mesh-s9-final`
- output repair required: false

Token comparison:

| Metric | Tokens |
| --- | ---: |
| Baseline total | 51,335 |
| Spatial-router executor | 3,077 |
| Spatial-router router | 5,087 |
| Spatial-router total | 8,164 |
| Output repair added | 0 |

The router-inclusive token reduction versus baseline was 84.10%.

## Repeat-5 Stability

Source reports:

- `logs/large_contextual_benchmark_openai_api_structural_both_honest_gate_repeat5.json`
- `logs/large_contextual_benchmark_openai_api_structural_both_honest_gate_repeat5.md`

The repeat-5 run used the benchmark runner's `--repeat 5` mode because the
dedicated stability runner is Lemonade-only and does not expose the OpenAI
executor or structural repair options.

Aggregate result:

- spatial-router runs: 5
- `honest_structural_pass`: 5/5
- `honest_structural_pass_after_repair`: 0/5
- router failures: 0
- selector fallbacks: 0
- wrong selected blocks: 0
- repairs required: 0
- selected block in every spatial-router run: `atlas-mesh-s9-final`

Average token comparison:

| Metric | Tokens |
| --- | ---: |
| Baseline total | 51,350.6 |
| Spatial-router executor | 3,077.0 |
| Spatial-router router | 5,091.0 |
| Spatial-router total | 8,168.0 |
| Output repair added | 0.0 |

The average router-inclusive token reduction versus baseline was 84.09%.

Per-run spatial-router summary:

| Run | Selected block | Honest pass | Repair needed | Router+executor tokens |
| ---: | --- | ---: | ---: | ---: |
| 1 | `atlas-mesh-s9-final` | true | false | 8,169 |
| 2 | `atlas-mesh-s9-final` | true | false | 8,172 |
| 3 | `atlas-mesh-s9-final` | true | false | 8,163 |
| 4 | `atlas-mesh-s9-final` | true | false | 8,166 |
| 5 | `atlas-mesh-s9-final` | true | false | 8,170 |

## Reliability Observation

The spatial-router path was stable across the five OpenAI runs: it selected the
authoritative block every time, used no fallback, passed selected-block
verification every time, and needed no output repair.

The baseline was less stable in this repeat set. It succeeded in 4/5 baseline
runs; one baseline run omitted `mesh_s9_epoch_pin`. This does not affect the
spatial-router publication gate, but it is a useful signal: flat full-context
execution can remain format-fragile even when the answer is present somewhere
in the prompt.

## Cost Note

The benchmark report records token usage, not billed dollar cost. Based on the
repeat-5 report, total recorded usage was:

- executor calls: 286,215 input tokens and 1,308 output tokens;
- router calls: 25,065 input tokens and 390 output tokens;
- combined total: 312,978 tokens.

Using standard OpenAI pricing available at the time of the run and assuming no
cached-input discount, the approximate total cost was about USD 1.48. This is
an estimate only; actual billing can vary with pricing, caching, account
configuration, or processing mode.

## Limitations

- The structural tier currently contains one synthetic task.
- The result depends on the configured OpenAI models and API behavior at run
  time.
- The fixtures are deterministic and controlled; they are not real production
  workloads.
- The validator uses exact target checks, which are appropriate for this task
  but do not cover broader answer quality.
- The repeat-5 result is a stability smoke test, not a statistical guarantee.
- The dedicated stability runner does not yet support OpenAI API execution, so
  the repeat result used the benchmark runner's repeat mode.

## Interpretation

This result is meaningful because the structural spatial-router path passed the
publication gate without fixture fallback and without output repair. The router
selected the only block containing all required values, selection verification
confirmed completeness, and the executor produced all required fields from the
selected block.

The result supports a narrow claim: on this synthetic structural-navigation
task, OpenAI-backed SFE routing reduced router-inclusive token use by about 84%
while preserving exact-field correctness across five repeated spatial-router
runs. It should not be generalized beyond this benchmark without more tasks,
providers, and repeated runs.

## Recommended Next Step

Add one or two additional structural tasks with the same honest-pass gate before
making broader publication claims. The next tasks should preserve the same
integrity constraints: no fixture fallback counted as success, no validation
relaxation, explicit selected-block verification, and separate reporting for
raw versus repaired outputs.
