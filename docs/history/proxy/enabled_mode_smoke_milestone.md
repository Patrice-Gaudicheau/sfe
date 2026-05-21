# SFE Enabled-Mode Smoke Milestone

Status: standby/historical. The proxy is not the canonical user-facing path as
of TUI V0.1. This note is retained for compatibility research and audit
history.

This note records the first successful controlled SFE proxy enabled-mode smoke
test.

## Preconditions

`main` contains both prerequisites for this test:

- explicit proxy request logging for `sfe_mode`
- Docker Compose passthrough for `SFE_OPENAI_ROUTER_MODEL`

The test used a direct `/v1/responses` request through the local SFE proxy. It
did not use a full CodexCLI session.

## Local Test Configuration

The local ignored `.env` file was switched to:

```text
SFE_PROXY_MODE=enabled
SFE_PROXY_PROVIDER=openai
SFE_PROXY_SHADOW_ROUTER_DRY_RUN=true
SFE_PROXY_SHADOW_ROUTER_PROVIDER=openai
SFE_PROXY_SHADOW_MIN_INPUT_TOKENS=1
SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS=false
SFE_OPENAI_ROUTER_MODEL=gpt-5.4-nano
```

The `.env` file is local, ignored, and must not be committed.

## Result

The direct `/v1/responses` smoke test returned HTTP `200`.

Safe proxy and shadow-event fields showed:

```json
{
  "sfe_mode": "enabled",
  "selection_applied": true,
  "selected_blocks_count": 2,
  "router_model": "gpt-5.4-nano",
  "executor_model": "gpt-5.5",
  "enabled_candidate_built": true,
  "enabled_replaces_upstream_request": true,
  "enabled_original_request_sent": false,
  "enabled_candidate_request_sent_to_upstream": true,
  "enabled_estimated_token_reduction_pct": 51.5
}
```

The OpenAI router selected the authoritative block and the question block. The
upstream response included the expected current quota and current code from the
authoritative block, and did not include the obsolete quota or obsolete code.

## Interpretation

This validates enabled-mode candidate construction and upstream context
replacement for a direct, controlled `/v1/responses` smoke test.

It does not yet validate:

- enabled mode in a full CodexCLI session
- streaming behavior
- long-context stability
- production thresholds

No secrets, full prompts, request bodies, headers, private endpoint values, or
API keys are included in this note.
