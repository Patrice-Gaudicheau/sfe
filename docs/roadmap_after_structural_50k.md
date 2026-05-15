# Roadmap After Structural 50k

Status note: This is a historical roadmap from an earlier structural benchmark
phase, preserved for audit/research continuity. Some items below have since
been implemented or superseded by later provider, benchmark, and Proxy work.
Current terminology and implementation status use the experimental SFE Proxy.
Start with `README.md`, `docs/INDEX.md`, and the current benchmark/provider/proxy
docs for the latest project state.

## Current Status

Phase 1 established that SFE can pass an honest structural-routing benchmark on
a synthetic 50k+ token context using the OpenAI API path. The structural result
passed with `honest_structural_pass = true` across five repeated runs, selected
the expected block every time, used no selector fallback, required no output
repair, and preserved about 84% router-inclusive token reduction versus the
full-context baseline.

That result is meaningful because the pass condition is strict: generic executor
success is not enough, fallback is not hidden as success, selected context is
verified, and output repair is reported separately.

The current result is still narrow. It covers one deterministic synthetic task
where the answer lives in a single authoritative block. It does not prove that
SFE is a general cognitive engine, that the approach works on real workloads, or
that spatial composition has been demonstrated across multiple active zones.

## Why the Next Phase Matters

Single-block routing is a strong retrieval result, but it is not sufficient for
the larger SFE claim. Many realistic tasks require combining several kinds of
context: user intent, constraints, domain facts, current code or policy state,
prior decisions, and evidence. Selecting one block tests relevance selection;
assembling several zones tests composition.

Structured retrieval asks: which source contains the answer? Spatial composition
asks: which zones should be active together, what role does each zone play, and
can the executor combine them without losing constraints, evidence, or token
efficiency? Phase 2 should move from single-record selection toward auditable
multi-zone context assembly.

## Phase 2 Goal

Phase 2 should test multi-zone context composition. The router should be able to
select and assemble several relevant zones, not only choose one block. The
executor should receive a compact composed context with explicit zone roles, and
the report should show which zones were selected, how many tokens each zone
cost, which evidence supported the answer, and whether the final output passed
deterministic checks.

The target is not a broad autonomy claim. The target is a controlled engineering
claim: SFE can compose multiple context zones honestly, reduce unnecessary
context, and preserve correctness on tasks where one block is not enough.

## Candidate Next Benchmarks

### Real-World Repository Navigation Benchmark

Create small tasks over this repository or another fixed open-source repository.
Each task should require combining a user request, relevant source files, tests,
and documentation. Example questions could ask which files must change for a
feature, which tests cover a behavior, or why a reported failure occurs.

This benchmark is attractive because the corpus is concrete and auditable. It is
riskier than synthetic fixtures because expected answers may be harder to score
deterministically.

### Documentation / Policy Corpus Benchmark

Build tasks over a fixed documentation or policy corpus where answers require
combining definitions, exceptions, dates, and procedural constraints across
several documents. The benchmark can keep exact validation targets for fields
such as version, threshold, owner, date, exception, and required action.

This benchmark is closer to real knowledge-work retrieval while still allowing
deterministic scoring if tasks are carefully designed.

### Multi-Zone Synthetic Benchmark

Extend the large/contextual framework so each task has several necessary zones,
for example:

- task intent;
- hard constraints;
- domain context;
- evidence records;
- obsolete or conflicting distractors.

The answer should require combining at least two or three selected zones. No
single zone should contain the complete answer. Validation should check exact
fields and should also verify that selected zones contain the required evidence.

This is less realistic than repository or policy work, but it is the safest way
to isolate multi-zone composition mechanics before adding real-world ambiguity.

## Recommended First Benchmark

Start with a small multi-zone synthetic benchmark.

This is the safest next step because it is deterministic, inexpensive, and
directly tests the missing architecture without introducing too many uncontrolled
variables. It can reuse the existing large/contextual runner style, exact target
validation, selection verification, output validation, and structural honesty
reporting. It also allows failure modes to be diagnosed clearly: wrong zone
selection, incomplete zone set, output omission, evidence mismatch, or token
overhead.

The first version should be small: one or two tasks, three to five required
zones, and a repeat-3 or repeat-5 stability run only after the dry and unit-test
contracts are clear.

## Validation Strategy

Keep deterministic validation as the main gate where possible. For structural
fields, continue using exact checks for values such as versions, thresholds,
owners, labels, dates, and dataset names.

Avoid soft semantic validation as the primary pass condition for Phase 2. If a
semantic evaluator is introduced later, it should be reported separately from
deterministic gates. A semantic score can help review quality, but it should not
replace exact validation for benchmark-critical fields.

The Phase 2 report should separate:

- zone selection success;
- selected-zone completeness;
- output validation before repair;
- output validation after repair;
- fallback usage;
- token reduction;
- repeated-run stability.

## Engineering Tasks

- Define a multi-zone selector output schema with explicit zone IDs, zone roles,
  confidence, and short evidence rationale.
- Build a zone composition prompt builder that groups selected context by role
  rather than flattening all selected text.
- Add per-zone token accounting for selected and suppressed zones.
- Add an evidence ledger that records required fields, supporting zone IDs, and
  source snippets or spans.
- Add multi-zone selection verification that checks whether the selected zone
  set contains every required field and evidence source.
- Add a multi-zone validation report with honest pass, after-repair pass, repair
  status, fallback status, and selected-zone completeness.
- Add stability runs for the selected Phase 2 benchmark after single-run
  behavior is clean.
- Update documentation to distinguish single-block structural routing from
  multi-zone spatial composition.

## Future Phase: Tool-Aware Proxy Routing

A later proxy phase should extend SFE routing beyond passive memory/context
selection. The core idea is that SFE should route capability exposure as well
as context exposure.

In proxy mode, a client or agent may have many tools or MCP servers available.
The executor should not automatically receive every tool definition when only a
small subset is relevant to the current request. A future router should be able
to select relevant tool definitions for the current task, while the proxy keeps
deterministic control over which tool calls are allowed.

This should not treat tools as normal memory zones. The first contract should
keep two separate channels:

- `selected_zones` for passive context.
- `selected_tools` for active capabilities.

An early contract sketch could look like:

```json
{
  "task_type": "coding",
  "execution_mode": "tool_assisted",
  "selected_zones": ["src_core", "tests_proxy"],
  "selected_tools": ["github_search"],
  "tool_policy": {
    "allow_tool_calls": true,
    "max_tool_calls": 3,
    "requires_user_confirmation": false
  }
}
```

### Preferred First Architecture: Executor-Managed Tools

The minimal and safer first step is executor-managed tools:

- The router selects the relevant tools.
- The proxy injects only those selected tool definitions into the executor
  request.
- The executor may produce normal tool calls.
- The proxy intercepts and executes only allowed tool calls.
- Tool results are returned to the executor through the usual tool-result path.

This architecture keeps the router focused on selection rather than execution.
It also gives the proxy a deterministic enforcement point: non-selected tool
calls can be refused before anything external happens.

### Deferred Option: Router-Managed Tools

Router-managed tools should be deferred. In this option, the router calls tools
before selecting context, and tool outputs may become new context zones for the
executor.

That is more complex and riskier than executor-managed tools. It introduces
tool execution before context selection is complete, expands the audit surface,
and can blur the boundary between routing and acting. If it is explored later,
it should be treated as a possible external or on-demand module, not as part of
the initial Tool-Aware Proxy Routing phase. A safer framing is dynamic reduction
of the exposed capability surface, only if the tool-executing component is
robustly isolated and auditable.

### Security Framing

Tool-aware routing should not be described as strong security by itself. It can
reduce the exposed capability surface, but real safety still depends on
deterministic proxy controls such as:

- allowlists;
- read-only defaults;
- confirmation for destructive actions;
- maximum tool call limits;
- audit logs;
- explicit refusal of non-selected tool calls.

### Suggested Deterministic Benchmark

A future deterministic benchmark could use:

- 10 fake tools with long JSON schemas;
- one or two tools required by the task;
- a router that must select the correct tools;
- an executor request that receives only selected tool schemas.

Possible metrics:

- tools exposed;
- prompt tokens saved;
- required tool selected;
- irrelevant tool exposure;
- hallucinated tool call;
- missing required tool;
- refusal of non-allowed tool calls.

This phase should be framed as a roadmap idea, not a completed capability or a
production security claim.

## Long-Term Research Direction: Context Routing Unit

A more speculative long-term research direction is a Context Routing Unit
(CRU). SFE should remain software-first. CRU is not current functionality, not
real silicon, and not a near-term hardware implementation plan.

The CRU concept would be a software simulation of a possible future
context-routing co-processor inside the SFE runtime. Its purpose would be to
model hardware-like boundaries and responsibilities before any real hardware
consideration. The research question is whether deterministic, repetitive, and
auditable context-control operations can be separated cleanly from semantic
routing decisions.

In this framing, CRU would explore which parts of SFE could behave like a
hardware-assisted context-control layer. It would delegate deterministic control
work to a hardware-like software component, while keeping semantic routing,
policy decisions, model behavior, provider abstraction, and refusal logic in
evolvable software. Models, providers, and policies should be able to change
without redesigning a hardware boundary.

This is a research blueprint, not a committed implementation path. It should
not be described as a CPU, as a hardware product, or as a performance guarantee.

### Possible Deterministic CRU Responsibilities

The simulated CRU boundary could start with deterministic operations such as:

- fragment hashing;
- fragment identity verification;
- exact-match constraint checks;
- context size budget enforcement;
- cache lookup;
- deterministic zone eligibility checks;
- selected-zone validity checks;
- tool allowlist checks;
- quota enforcement;
- trace integrity;
- structured audit events.

These responsibilities are attractive because they are auditable and do not
require semantic interpretation by themselves.

### Possible Accelerated Responsibilities

Some operations could be accelerated by GPU, TPU, NPU, or similar hardware
while still being controlled by software:

- embeddings;
- reranking;
- semantic scoring;
- small router or classifier models.

These should remain software-governed. Acceleration would not by itself decide
policy, safety, provider behavior, or final context arbitration.

### Responsibilities Outside CRU

The following should remain outside CRU in the software semantic layer:

- intent interpretation;
- final zone arbitration;
- semantic validation;
- provider abstraction;
- policy decisions;
- tool exposure policy;
- safety and refusal logic.

Keeping these responsibilities outside the simulated CRU preserves flexibility.
It also avoids hard-coding model-specific or policy-specific behavior into a
hardware-like boundary.

### Research Framing

The CRU idea should be evaluated only as a long-term roadmap concept. A useful
first step, if this direction is ever explored, would be a software-only
simulation that records which operations are deterministic, which are semantic,
and which require provider or policy decisions. Any future report should keep
the distinction explicit and avoid claiming hardware performance or production
readiness.

## Risks

- Overclaiming from one benchmark family or one provider.
- Benchmark overfitting to synthetic fixture structure.
- Confusing SFE with ordinary RAG if the system only retrieves documents rather
  than composing role-specific zones.
- Synthetic-only success that does not transfer to repository, documentation, or
  operational tasks.
- Validator ambiguity when answers require synthesis rather than exact field
  extraction.
- Token savings disappearing when zone composition, evidence ledgers, verifier
  passes, or repair steps add too much overhead.
- Hidden fallback or repair being mistaken for raw routing success.

## Success Criteria

A meaningful Phase 2 result should satisfy all of the following:

- the honest pass gate remains strict;
- fallback is never hidden as success;
- selected zones are auditable and reported by ID and role;
- selected-zone completeness is verified;
- token reduction remains meaningful after router and composition overhead;
- reliability is equal to or better than baseline on the benchmark task set;
- results hold across repeated runs;
- repair, if used, is reported separately from raw success.

## Recommended Immediate Next Step

Design one small multi-zone synthetic benchmark task and its validation contract
before implementing new routing behavior. The task should require at least three
zones to answer, have exact deterministic targets, include partial and obsolete
distractors, and define upfront what counts as an honest multi-zone pass.
