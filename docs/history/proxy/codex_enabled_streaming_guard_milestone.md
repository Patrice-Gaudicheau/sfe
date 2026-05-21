# Codex Enabled Streaming Guard Milestone

Status: standby/historical. The proxy is not the canonical user-facing path as
of TUI V0.1. This note is retained for compatibility research and audit
history.

This note records the first successful CodexCLI enabled-mode test after adding
the streaming guard.

## Context

`main` now contains both enabled-mode safety mechanisms:

- enabled fallback-to-original
- enabled streaming guard

A previous CodexCLI enabled-mode test failed because CodexCLI sent
`stream=true`, while enabled mode still built and sent a reduced candidate
request. For `/v1/responses`, that candidate request did not preserve Responses
streaming semantics, and CodexCLI ended with a stream completion error.

The streaming guard now bypasses enabled candidate replacement for `stream=true`
requests. When `SFE_PROXY_ENABLED_FALLBACK_TO_ORIGINAL=true`, streaming requests
are forwarded upstream unchanged.

## Result

The second CodexCLI enabled-mode test completed normally with exit code `0`.

The final sanitized `/v1/responses` log and shadow-event fields were:

```json
{
  "sfe_mode": "enabled",
  "fallback_used": true,
  "selection_applied": false,
  "selected_blocks_count": 1,
  "enabled_candidate_built": false,
  "enabled_replaces_upstream_request": false,
  "enabled_original_request_sent": true,
  "enabled_candidate_request_sent_to_upstream": false,
  "enabled_fallback_to_original": true,
  "enabled_streaming_bypass": true,
  "enabled_streaming_bypass_reason": "streaming_not_supported",
  "router_model": "gpt-5.4-nano",
  "executor_model": "gpt-5.5",
  "shadow_router_provider": "openai",
  "shadow_router_status": "skip",
  "status_code": 200,
  "stream": true
}
```

## Interpretation

This validates CodexCLI safety in enabled mode when CodexCLI sends streaming
Responses requests and fallback-to-original is enabled. The proxy keeps
`sfe_mode=enabled`, records the streaming bypass explicitly, and forwards the
original request unchanged instead of attempting unsafe context replacement.

This does not validate actual context replacement for CodexCLI streaming
requests. Direct non-streaming enabled mode remains the only validated path for
actual context replacement.

## Caveats

No CodexCLI token reduction is proven yet. Streaming context replacement is
intentionally not supported yet.

The safe default operating mode should remain shadow mode, or enabled mode with a
high threshold, unless intentionally testing.

No secrets, full prompts, request bodies, headers, private endpoint values, or
API keys are included in this note.
