# SFE Product Doctrine

This note defines the current product doctrine for Spatial Field Engine for
Cognition (`SFE`). It is the short alignment document to read before
interpreting the TUI, benchmarks, or historical router concepts.

## What SFE Is

SFE is a general routing and context engine for LLM workflows. Its core product
model is:

```text
SFE core = routing + context selection + bounded execution + validation + observability
TUI = local user-facing control surface
patch/worktree = developer execution mode
benchmarks = evidence and architectural feedback loop
```

SFE is not the model itself. It is the layer around model calls that decides
what task shape is being handled, which context should be exposed, how execution
should be bounded, and what evidence should be recorded afterward.

## What SFE Is Not

SFE is not primarily a Git patch assistant. Patch/worktree is one execution
mode, not the identity of the project.

SFE is not a benchmark dashboard. Benchmarks remain separate from normal TUI
usage.

SFE does not claim to make models smarter. The current claim is narrower:
selected context and explicit routing may reduce executor context and improve
traceability on tasks where routing overhead can be justified.

## White Paper And Benchmarks

The white paper is the founding architectural hypothesis: external structure,
spatial memory, bounded activation, cognitive routing, role-aware execution,
and token observability may improve how LLM workflows are organized.

The benchmarks are the practical exploratory implementation of that hypothesis.
They are not secondary artifacts. They test routing, selected context, baseline
versus spatial execution, token reduction, fallback honesty, repair masking, and
provider behavior under controlled conditions.

Benchmark lessons should influence future SFE architecture, but benchmark
runners should stay separate from normal TUI usage. A future benchmark launcher
may be a Makefile target or dedicated CLI command, not a permanent TUI
dashboard.

## White Paper To Current Implementation Mapping

The white-paper concepts remain conceptually important, but the current
implementation is pragmatic and narrower:

- Spatial memory and zones map today to workspace context discovery, explicit
  context segments, and selected context boundaries.
- Field activation maps to passing selected context into execution instead of
  injecting the full available context.
- Cognitive routing maps to current execution-mode routing and context
  selection, with room for stronger routers later.
- Role-based processing is not yet a general TUI role system. Today it is
  expressed mostly through execution modes such as `console_output` and
  `workspace_write`.
- Token observability is expressed through benchmark reports, lightweight
  `SFE:` progress lines, and `/run-report` diagnostics.

Older concepts such as zones, roles, and broad router contracts are not
automatically dead legacy. They remain useful design vocabulary and historical
context. The current canonical `/run` contract, however, is the execution-mode
pipeline documented in `execution_mode_router_contract.md`, not the historical
router contract.

## TUI And Execution Modes

The TUI is the current local user-facing surface for SFE. It lets a user choose
a workspace, set a task, and run the SFE pipeline locally without depending on a
future API surface.

`/run` is the current canonical TUI action. It first routes the task to an
execution mode. It may produce `console_output`, enter `workspace_write`, or
reject an unsupported `external_action`.

`workspace_write` is the developer-oriented patch/worktree mode. Once SFE routes
into `workspace_write`, the workflow intentionally becomes practical software
development infrastructure: Git preparation, worktree isolation, patch
generation, validation, and promotion. That is not conceptual drift. It is the
first serious developer application of the SFE engine.

The future API should be treated as another access surface for the same SFE
core, not as a replacement doctrine.

## Lightweight Observability

The TUI should make the routing/context layer visible without becoming heavy.
The `SFE:` progress lines during `/run` are lightweight observability of
pipeline boundaries such as execution-mode routing, context discovery, selected
context, prompt preparation, patch validation, promotion, and console answer
generation.

Those lines are not benchmark output. They do not perform a live
baseline-versus-spatial comparison, do not run benchmark runners, and do not
turn `/run` into a dashboard.
