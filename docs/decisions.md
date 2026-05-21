# Project Decisions

## Current Status Notes

This file is an architectural decision log. Older entries are preserved as
historical context and may describe work that was deferred or planned at the
time of writing. Current project navigation starts in `docs/INDEX.md`.

As of the current documentation set, provider paths include OpenAI, Lemonade,
Alibaba/Qwen, and Anthropic across benchmark surfaces. The SFE Proxy is an
implemented standby experimental prototype in `sfe_proxy/`, with historical
notes under `docs/history/proxy/`; it should not be read as production
infrastructure or the canonical user-facing path. Current benchmark summaries
include structural 50k+
observations, OpenAI and Anthropic protocol-aligned observations across all
four large/contextual tiers, and Alibaba/Qwen repeat-3 observations for
`standard`, `practical`, and `high_context` plus a single live structural
baseline-vs-spatial comparison.

These updates do not change the interpretation standard for this repository:
SFE remains an experimental, benchmark-specific architecture. The recorded
results are controlled observations, not statistical proof, production savings
commitments, or evidence that SFE generally improves model intelligence or
answer quality. For current benchmark interpretation, see
`docs/provider_comparison_summary.md`, `docs/token_cost_metrics.md`, and
`docs/large_contextual_benchmark_report.md`.

## Use SQLite First

Decision: Use SQLite first for structured logs, routing decisions, runs, providers, and configuration.

Do not introduce a vector database yet.

Rationale: The project is still defining contracts and observability. SQLite is simpler, deterministic, local, and enough for the first experimental protocol. Semantic memory can be added later behind a storage abstraction, using sqlite-vec, Chroma, or Qdrant when retrieval needs are clearer.

## Default Local Models

Decision: Use Qwen3-0.6B-GGUF as the default local routing model.

Use Qwen3.5-35B-A3B-GGUF as the default local execution model.

Rationale: The routing layer should be small, fast, and inexpensive. It only needs to classify tasks and produce strict routing JSON. The execution layer can use a larger local model for generation quality while remaining lightweight enough for local experimentation.

## Selective SFE Activation

Decision: Treat SFE routing and orchestration as conditional overhead, not as a default path for every task.

SFE should be activated selectively when the task shape gives it a plausible opportunity to amortize that overhead, especially through large context reduction or cognitive separation.

Rationale: The large/contextual Lemonade benchmark provides a positive signal for this policy. In the preserved expanded live run, baseline execution received all noisy context blocks while spatial execution received only the selected relevant block. Across 7 tasks and 14 runs, context reduction was verified, both modes succeeded on every run, and average input tokens fell from 2788.43 to 536.57, an 80.76% reduction.

This result is not final proof of general SFE effectiveness. The default benchmark path still preserves deterministic fixture selection as the oracle context-reduction comparison. Real-router selection is now an optional mode for testing whether Lemonade can identify the relevant block under semantic noise. In the latest 7-task real-router live run, the Lemonade selector produced valid fixture-matching selections for every router task after prompt hardening, with zero fallback-assisted executor runs. This is encouraging, but it remains a small deterministic synthetic benchmark rather than statistical proof.

OpenAI API reproduction remains deferred until we explicitly decide that the Lemonade real-router signal is worth reproducing. The next likely phase is repeated live runs for stability, a larger task set, or explicitly approved provider reproduction.

Status: Superseded for current documentation. OpenAI and Anthropic
protocol-aligned reproductions have since been run and documented, and
Alibaba/Qwen has narrower documented observations. The paragraph above is kept
as historical context for the Lemonade-first phase.

Routing is reliable, but routing has a fixed cost. SFE must be activated selectively on tasks where context reduction or cognitive separation can amortize that cost.

## High Context Requires Adequate Backend Context

Decision: Treat high_context benchmark runs as valid comparisons only when the backend context window is configured large enough for the full-context baseline.

Rationale: In high_context Lemonade testing, 16K context size produced empty baseline outputs, and 32K context size still left one baseline empty. With Lemonade configured at 64K context size, both high_context baseline runs completed successfully, while spatial_fixture and spatial_router also succeeded. The clean 64K run had 100% router valid selection, 100% router match, zero fallbacks, about 90.98% executor input token reduction, and about 72.8% router-inclusive end-to-end token reduction.

Interpretation: The earlier empty baseline outputs are backend/context-window execution limitations, not evidence that baseline reasoning failed. The 64K result is the cleanest high_context comparison so far, but it is still only two synthetic tasks and one live iteration. The next step should be a small repeated high_context Lemonade stability run before making broader claims, pursuing OpenAI API reproduction, or moving to the planned structural 50K+ tier.

Status: Superseded for current documentation. The structural 50k+ tier now
exists in the current large/contextual benchmark notes, including current
OpenAI and Anthropic observations and a narrower single-run Alibaba/Qwen
structural comparison. The paragraph above is retained to show the earlier
decision point before structural work was implemented.

Update: A first 3-iteration high_context stability run on the same 64K Lemonade setup stayed clean: 18 total runs, 100% success across baseline, spatial_fixture, and spatial_router, 100% router valid selection and match rates, zero fallbacks, and 90.98% average input token reduction. This strengthens the Lemonade engineering signal but remains limited to two synthetic tasks on a local backend.
