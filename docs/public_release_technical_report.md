# Spatial Field Engine Public-Release Technical Report

This report summarizes the current public-release readiness snapshot for Spatial Field Engine for Cognition (`sfe`). It is intentionally conservative: the project is a technical prototype with early benchmark signals, not a validated scientific claim.

## Hypothesis

SFE tests whether an external workspace controller can reduce the amount of context sent to an executor model while preserving measured task success on selected workloads.

The current hypothesis is engineering-focused:

> External workspace structure, role routing, and selective context activation can make some LLM workflows more inspectable and token-efficient when the task contains enough irrelevant or noisy context to amortize routing overhead.

This is not a claim that SFE improves model intelligence. The model still performs the generation. SFE changes the runtime structure around the model call: what state is kept externally, what context is activated, and what payload is sent to the executor.

## Architecture Summary

The prototype separates four concerns:

- Workspace state: named zones and fragments track intent, constraints, domain context, execution state, verification state, and output state.
- Routing: a mock router or LLM router selects task type, role, provider, model, memory zones, and execution mode through a JSON contract.
- Provider execution: local Lemonade and OpenAI-compatible paths execute prompts through configurable model ids.
- Reporting: benchmark runners record success checks, token estimates, latency, router validity, fallbacks, and generated reports.

Lemonade is treated as a local OpenAI-compatible inference server. The repository does not require Lemonade for deterministic dry runs, but live Lemonade benchmarks require a running local server and installed local models.

## Benchmark Tiers

The large/contextual benchmark is the main context-reduction benchmark. Each task contains a relevant context block plus distractor blocks. The baseline receives all blocks. The spatial path receives only the selected relevant block.

| Tier | Baseline context range | Purpose | Current signal |
| --- | ---: | --- | ---: |
| `standard` | approximately 2k-5k tokens | Mechanism validation on smaller synthetic tasks. | about 81% executor input reduction |
| `practical` | approximately 10k-20k tokens | First economically meaningful tier for router-cost amortization. | about 88% executor input reduction |
| `high_context` | approximately 20k-50k tokens | Stronger relevance tests with higher prompt size and distractor density. | about 91% executor input reduction |

The planned `structural` tier for 50k+ token tasks is not implemented.

## Observed Reductions

The current observed reductions are best interpreted as executor-context reductions under controlled synthetic benchmark conditions:

- `standard`: average input tokens dropped from about 2.8k to about 0.5k in the preserved 7-task live Lemonade fixture run, an 80.76% reduction.
- `practical`: observed reduction is approximately 88% on the current 10k-20k synthetic tier.
- `high_context`: observed executor input reduction is approximately 90.98% on the current 20k-50k tier in a clean 64K Lemonade setup.

The high_context signal is the cleanest large-context router-inclusive comparison so far, but it remains small: two synthetic tasks, three repeated live iterations, local Lemonade execution, 100% baseline/spatial success, 100% router valid selection and match rates, and zero fallbacks.

## Router-Inclusive Cost

Executor input reduction is not the same as end-to-end savings. SFE pays for routing, selection, prompt construction, and sometimes additional verification.

Router-inclusive reporting therefore matters:

- On short prompts, router cost can erase or reverse token savings.
- On large prompts, routing can be amortized if the selected executor payload is much smaller than the full baseline prompt.
- In the clean high_context Lemonade result, executor input reduction was about 90.98%, while router-plus-executor total token reduction was about 72.8%.

Any public claim should distinguish executor-only reduction from router-inclusive end-to-end reduction.

## Methodological Limitations

- The current evidence is early and mostly synthetic.
- The benchmark tasks are small in count and deterministic in structure.
- Fixture selection is an oracle upper bound for context reduction, not a real-router result.
- Real-router selection is available and promising in the current runs, but it has not been tested broadly.
- Scoring is mostly heuristic, with task-specific checks rather than independent human or robust model-graded evaluation.
- Local Lemonade results depend on server configuration, context-window settings, model availability, and runtime conditions.
- The OpenAI API path exists but the large/contextual signals have not been systematically reproduced through it.
- Results do not isolate all causal factors; routing, role framing, prompt compaction, and context filtering can interact.
- The repository does not yet evaluate adversarial retrieval, real user workloads, long multi-step tool use, or provider/model-family generalization.

## Publication Guidance

For a future public GitHub release, the project can be framed as:

- a high-quality technical prototype;
- an early benchmark signal for selective context activation;
- an implementation scaffold for more rigorous experiments.

Avoid claims that:

- SFE improves model intelligence;
- SFE proves spatial cognition in LLMs;
- SFE generally improves answer quality;
- SFE is production-ready;
- the current synthetic benchmark results establish broad scientific validity.

## Next Validation Steps Before Any arXiv Submission

Before any arXiv submission or stronger public research claim, the project should add:

- Larger benchmark sets per tier, with preregistered task definitions.
- Clear separation of fixture/oracle selection from real-router selection.
- Router-inclusive cost reporting as the default headline metric.
- Stronger answer-quality evaluation, including exact-match tasks where possible and independently reviewed samples.
- Provider and model-family replication, including explicitly approved OpenAI API runs.
- Ablations that isolate routing, prompt compaction, role framing, and context filtering.
- Repeated-run stability reporting with confidence intervals or at least variance summaries.
- Tests for failure cases where the relevant context is ambiguous, split across blocks, or adversarially similar to distractors.
- A frozen artifact policy that keeps canonical reports in `docs/` or `reports/` while excluding generated `logs/` output from version control.

Until those steps are complete, the appropriate public framing is: early, synthetic evidence that selective external context activation can reduce executor context on some controlled tasks, with promising but limited router-inclusive savings at larger context sizes.
