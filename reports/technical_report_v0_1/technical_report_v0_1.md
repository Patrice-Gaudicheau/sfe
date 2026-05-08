# Spatial Field Engine for Cognition:
# Separating Audit, Workspace, and Payload for Efficient LLM Execution

Technical Report v0.1

Date: May 2026

## 1. Abstract

Spatial Field Engine for Cognition (SFE) is an experimental runtime architecture for structuring work around Large Language Models (LLMs). The project began from a spatial prompt and routing hypothesis, but the current implementation has been refined into a more concrete engineering claim: separating audit state, workspace state, and executor payload can reduce execution cost and latency while preserving deterministic verification success on a small exploratory benchmark.

This report describes the current Cognitive Map prototype, its benchmark methodology, and the latest observed results from a local Lemonade-backed run with symmetric deterministic verification. In that run, `cognitive_map` mode completed 30 provider calls with 30 provider successes and 30 deterministic verification passes. Compared with `explicit_metadata` mode, it used fewer total tokens and lower measured latency: 24.28% lower total token usage and 56.70% lower total latency observed in this exploratory benchmark.

These results are promising but limited. They do not prove that LLMs think spatially, do not reproduce a brain-like cognitive mechanism, and do not establish general scientific validity. They support a narrower engineering hypothesis: external workspace structure can preserve traceability while sending smaller, task-specific payloads to an executor model.

## Plain Language Summary

The project tests whether an LLM system can keep a rich internal record of what it is doing while sending the model only the compact information needed for the next answer. In the current benchmark, this Cognitive Map approach used fewer tokens and ran faster than sending explicit metadata directly in the execution prompt. The test is small, local, and not enough to prove answer quality or broad generality.

## 2. Motivation

LLM applications often face a tension between traceability and execution cost. A verbose prompt can explain intent, constraints, role, audit metadata, and expected behavior, but this increases token usage and can add latency. A compact prompt may run more cheaply, but may hide why the system made a decision or which constraints were active.

SFE explores whether those concerns can be separated:

- Audit: preserve a structured record of intent, constraints, state, and handoffs.
- Workspace: organize task state into explicit zones with bounded activation.
- Payload: send only the task-specific executor context needed for model execution.

The motivation is not to make an LLM more intelligent through spatial language. The motivation is to make an LLM runtime more controllable, inspectable, and efficient by moving some structure outside the model prompt.

## 3. Original Hypothesis and Refinement

The original SFE hypothesis used spatial organization as a conceptual lens for LLM orchestration. It suggested that context could be organized into zones, activated selectively, and routed through role-specific pathways instead of injected into one flat prompt.

The current prototype narrows that idea into a concrete runtime architecture. The active claim is not:

> Spatial prompting makes the model smarter.

The active claim is:

> Separating audit, workspace, and payload can make LLM execution more efficient and controllable while preserving a deterministic trace of task state.

This refinement matters. The current implementation does not claim that the model internally reasons spatially. It uses spatial terminology externally to organize state, constraints, handoffs, and executor payloads. The resulting architecture is testable as a software system, without requiring claims about cognition inside the model.

## 4. Background

### 4.1 LLM Orchestration

LLM orchestration systems commonly combine routing, prompt construction, tool calls, memory, and evaluation. Many such systems grow by adding more instructions and metadata to prompts. This can help control behavior, but it also increases execution payload size.

### 4.2 Prompt Verbosity

Prompt verbosity is often useful for auditability: a prompt can expose roles, constraints, examples, and safety requirements. However, a verbose prompt also consumes tokens and may increase latency. In local inference settings, both prompt and completion tokens can affect runtime cost.

### 4.3 Traceability Versus Execution Cost

Traceability asks the system to retain enough information to explain what happened. Execution efficiency asks the system to minimize what the model must process. These goals can conflict if the same prompt is used as both audit record and executor input.

SFE addresses this conflict by treating audit state and executor payload as separate artifacts.

### 4.4 Workspace-Style Architectures

Workspace-style architectures maintain intermediate task state outside a single prompt. SFE's Cognitive Map prototype follows this pattern with explicit zones, activation levels, and handoff traces. The current prototype is deterministic and small; it is not a general agent framework.

## 5. Architecture

### 5.1 Audit

The audit layer is the complete structured record of the task flow. In the Cognitive Map benchmark this includes a JSON snapshot of zones, fragments, activation levels, and handoff traces. It is larger than the executor payload and is intended for inspection rather than direct model execution.

### 5.2 Workspace

The workspace is the structured intermediate state used to prepare execution. The current implementation uses a deterministic `CognitiveWorkspace` with zones for intent, constraints, domain knowledge, execution, verification, and output.

### 5.3 Payload

The payload is the compact task-specific prompt sent to the executor model. It is derived from the workspace but does not include the full workspace JSON. This is the primary mechanism by which Cognitive Map mode reduces execution prompt size.

### 5.4 Cognitive Map

The Cognitive Map is a deterministic workspace scaffold. It separates task state into named zones and records handoffs between them. The map is external to the model; it does not imply that the model uses a spatial representation internally.

### 5.5 Zones

The current prototype defines six zones:

- `user_intent_zone`
- `task_constraints_zone`
- `domain_knowledge_zone`
- `execution_zone`
- `verification_zone`
- `output_zone`

Each zone tracks activation level, allowed operations, suppressed operations, input fragments, and output fragments.

### 5.6 Handoffs

Handoffs move fragments between zones and are recorded in a trace. The trace includes fragment hashes, which provide a compact audit trail for how information moved through the workspace.

### 5.7 Activation

Activation levels represent which zones are active during a flow. The current flow is deterministic and activates the expected zones. Dynamic activation remains future work.

### 5.8 Suppressed Operations

Suppressed operations encode what a zone should not do. This is an explicit control mechanism: for example, an analysis zone can suppress writing, coding, or planning operations. In the current prototype this is metadata rather than a full policy engine.

### 5.9 Verification

The benchmark uses a deterministic verifier applied symmetrically to `explicit_metadata` and `cognitive_map` outputs. It checks narrow constraints:

- generic outputs must not be empty, scaffold text, too short, or just a known task label;
- classification outputs must be exactly one allowed label;
- selected constraint-following tasks must match an exact bullet count;
- coding tasks that ask for a function must include a code-like function.

This is not semantic quality evaluation.

### 5.10 Reflection Loop

The Cognitive Map path includes a minimal bounded reflection loop. If deterministic verification fails and the retry budget allows it, the benchmark builds a compact retry payload containing the original task, previous output, and verification failure reason. Reflection is currently enabled only for `cognitive_map` mode; `explicit_metadata` is verified but not retried. The default retry budget is one attempt.

## 6. Implementation Overview

The main implementation components are:

- `cognitive_map/`: deterministic workspace, zones, and flow utilities.
- `runtime/run_cognitive_map_real_benchmark.py`: real Lemonade-backed benchmark comparing `explicit_metadata` and `cognitive_map` modes, with repeat support, symmetric deterministic verification, and Cognitive Map reflection.
- `runtime/report_cognitive_map_benchmark.py`: Markdown report generator for JSONL benchmark outputs.

The implementation intentionally avoids new runtime dependencies. The current Cognitive Map construction is deterministic and does not call an LLM.

## 7. Benchmark Methodology

The latest significant live run used the real Cognitive Map benchmark with a local Lemonade OpenAI-compatible server.

Setup:

- Modes: `explicit_metadata`, `cognitive_map`
- Task count: 10
- Repeat count: 3
- Total rows: 60
- Provider: local Lemonade server
- Reflection budget: 1 Cognitive Map retry
- Verification: deterministic and symmetric across both modes

### 7.1 Explicit Metadata Baseline

The baseline sends explicit spatial prompt metadata directly as the executor prompt. This preserves metadata in the execution payload but increases prompt size.

### 7.2 Cognitive Map Mode

Cognitive Map mode builds a structured workspace, records an audit snapshot, and derives a compact executor payload from task-relevant fragments. The full audit record is not sent to the executor model.

### 7.3 Symmetric Verification

Both modes are evaluated by the same deterministic verifier. Provider success and verification success are recorded separately. This avoids counting one mode under stricter output checks than the other.

### 7.4 Reflection

Reflection is enabled only for Cognitive Map mode. This makes the benchmark intentionally asymmetric with respect to retry behavior, but not with respect to deterministic output verification. Reflection events are reported separately.

## 8. Results

The following results are from the latest significant live run with symmetric verification.

### 8.1 Aggregate Metrics

| Mode | Runs | Prompt Tokens | Completion Tokens | Total Tokens | Mean Tokens / Run | Total Latency (ms) | Mean Latency (ms) | Provider Success | Verification Pass | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cognitive_map` | 30 | 4296 | 1098 | 5394 | 179.80 | 62455 | 2081.83 | 30 | 30 | 0 |
| `explicit_metadata` | 30 | 5034 | 2090 | 7124 | 237.47 | 144254 | 4808.47 | 30 | 30 | 0 |

### 8.2 Observed Ratios

| Metric | Observed Difference |
| --- | ---: |
| Total token reduction | 24.28% |
| Prompt token reduction | 14.66% |
| Completion token reduction | 47.46% |
| Latency reduction | 56.70% |
| Mean token difference | 57.67 tokens / run |
| Mean latency difference | 2726.63 ms / run |

### 8.3 Reflection

| Metric | Value |
| --- | ---: |
| Cognitive Map rows | 30 |
| Reflection-triggered rows | 3 |
| Labels that triggered reflection | `analysis` |
| Total reflection attempts used | 3 |
| Verification passed count | 30 |
| Verification failed count | 0 |

## 9. Interpretation

Observed in this exploratory benchmark, Cognitive Map mode reduced total token usage and latency relative to explicit metadata mode while preserving provider success and deterministic verification success.

The completion token reduction is particularly notable. The executor often produced shorter visible outputs under Cognitive Map payloads, while still passing deterministic checks. The latency reduction is also notable, though latency can be influenced by local runtime conditions, model server behavior, caching, and output length.

The result supports the architectural hypothesis that separating audit/workspace/payload can reduce execution cost. It does not prove superior answer quality. It also does not prove that the Cognitive Map itself contributes intelligence beyond deterministic preprocessing and compact prompt construction.

## 10. Limitations

- The benchmark size is small: 10 tasks repeated 3 times.
- The live benchmark uses a local Lemonade model/server configuration only.
- Cognitive Map creation is currently deterministic and effectively "free" in the benchmark accounting.
- There is no LLM-as-a-judge evaluation yet.
- Deterministic verification checks only narrow constraints.
- Tasks are micro-tasks rather than long-horizon workflows.
- The explicit metadata baseline may still be improvable.
- Quality is not fully semantically evaluated.
- Reflection is enabled for Cognitive Map mode only, so retry behavior is not symmetric.
- The current implementation does not isolate every causal factor behind token and latency reductions.

## 11. Threats to Validity

### 11.1 Baseline Design

The explicit metadata baseline may not be the strongest possible baseline. An optimized explicit prompt could reduce some of the observed gap.

### 11.2 Task Selection

The task set is small and may favor compact outputs. Larger tasks, tool-use tasks, or multi-step workflows could change the result.

### 11.3 Model-Specific Behavior

The observed effects may depend on the local Lemonade model and server behavior. Other models may respond differently to explicit metadata or Cognitive Map payloads.

### 11.4 Caching and Runtime Variability

Latency measurements can vary due to local server load, caching, hardware state, and output length. The latency result should be treated as observed runtime evidence, not a universal property.

### 11.5 Prompt Tuning Bias

The Cognitive Map executor payload has been tuned for compact task-specific execution. The baseline prompt may require further tuning for a fairer comparison.

### 11.6 Hardcoded Payload Builder

The current payload builder is task-specific and deterministic. A more general system would need to construct payloads robustly across broader task distributions.

## 12. Next Work

1. Intelligence Injection: populate at least one Cognitive Map zone using a small router model, such as Qwen 0.6B, instead of deterministic logic.
2. Add LLM-as-a-judge or human evaluation for semantic quality.
3. Expand the benchmark to a larger and more diverse task set.
4. Compare against an optimized explicit metadata baseline.
5. Compare across multiple models and local/runtime configurations.
6. Implement dynamic zone activation rather than fixed deterministic activation.
7. Measure Cognitive Map construction cost once LLM-assisted zone population is introduced.
8. Test longer workflows where auditability and state separation matter more than in micro-tasks.

## 13. Conclusion

SFE v0.1 is an empirically verified prototype, not a finished cognitive architecture. Its strongest current contribution is the separation of audit, workspace, and payload as distinct runtime artifacts.

In the latest symmetric-verification live benchmark, this separation was associated with lower token usage and lower latency while preserving provider success and deterministic verification success. The result supports further investigation of the architecture. It does not prove semantic quality improvement, cognitive equivalence, or broad generalization.

The next stage should move from deterministic workspace construction toward limited LLM-assisted zone construction, stronger evaluation, broader task coverage, and more competitive baselines.
