# Codex SFE Shadow-Routing Milestone

Status: standby/historical. The proxy is not the canonical user-facing path as
of TUI V0.1. This note is retained for compatibility research and audit
history.

This note records the current local Codex-to-SFE proxy milestone.

## Configuration

Codex was launched with `--profile sfe`. The Codex profile points to the local
SFE Responses-compatible proxy through:

```toml
model_provider = "sfe"
model = "gpt-5.5"
```

The SFE proxy receives Codex `/v1/responses` traffic. Proxy request logs now
include an explicit `sfe_mode` field, which makes pass-through, shadow, enabled,
and rejected paths visible in the normal request log.

The current local non-destructive shadow-routing configuration is:

```text
SFE_PROXY_MODE=shadow
SFE_PROXY_SHADOW_ROUTER_DRY_RUN=true
SFE_PROXY_SHADOW_ROUTER_PROVIDER=lemonade
SFE_PROXY_SHADOW_MIN_INPUT_TOKENS=1
```

With `SFE_PROXY_MODE=shadow`, `/v1/responses` request logs report
`sfe_mode=shadow`. With the router dry-run flags above, shadow routing is active
but remains non-destructive: the original upstream OpenAI request is forwarded
unchanged.

## Live Observation

A live CodexCLI test through the SFE profile produced the following safe proxy
log fields:

```json
{
  "sfe_mode": "shadow",
  "selection_applied": true,
  "selected_blocks_count": 3,
  "router_model": "Qwen3.5-35B-A3B-GGUF",
  "executor_model": "gpt-5.5",
  "status_code": 200
}
```

No prompts, request bodies, authorization headers, API keys, hidden reasoning, or
secrets are included in this note.

## Interpretation

This proves that Codex traffic can reach the SFE proxy through the `sfe` profile,
that `/v1/responses` traffic is observed in shadow mode, and that the Lemonade
shadow router dry-run can produce candidate block selection metadata without
changing the upstream OpenAI request.

This does not yet prove enabled-mode context replacement. It also does not yet
prove token savings in Codex sessions.

## Follow-Up

A previous smoke test recorded `lemonade_router_timeout`, so Lemonade router
latency and stability need follow-up before considering enabled mode.

The local `.env` file is ignored and must remain uncommitted.
