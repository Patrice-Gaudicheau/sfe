# Codex Enabled Streaming Replacement Smoke

Status: standby/historical. The proxy is not the canonical user-facing path as
of TUI V0.1. This note is retained for compatibility research and audit
history.

This note records the first successful CodexCLI smoke test for opt-in enabled
streaming replacement on branch `feature/enabled-streaming-replacement`, commit
`9da72dc2aa9fcde3c3e9c664ec9b43842520a512`.

## Prior Direct Smoke

A direct live `/v1/responses` streaming smoke test had already validated the
proxy path before the CodexCLI run:

```json
{
  "stream": true,
  "sfe_mode": "enabled",
  "fallback_used": false,
  "selection_applied": true,
  "enabled_candidate_built": true,
  "enabled_replaces_upstream_request": true,
  "enabled_original_request_sent": false,
  "enabled_candidate_request_sent_to_upstream": true,
  "response_completed_observed": true,
  "status_code": 200
}
```

## CodexCLI Smoke

Patrice ran the CodexCLI test manually in a normal terminal because
Codex-managed shells could not see the local `sfe` profile. The command path was:

```text
codex --profile sfe
```

The fixed test prompt was:

```text
Réponds uniquement par: STREAMING_ENABLED_TEST_OK
```

The user-facing response completed normally:

```text
STREAMING_ENABLED_TEST_OK
```

The final sanitized Docker request log fields for the CodexCLI `/v1/responses`
request were:

```json
{
  "path": "/v1/responses",
  "model": "gpt-5.5",
  "executor_model": "gpt-5.5",
  "router_model": "gpt-5.4-nano",
  "provider": "openai",
  "sfe_mode": "enabled",
  "stream": true,
  "selection_applied": true,
  "selected_blocks_count": 1,
  "fallback_used": false,
  "status_code": 200,
  "latency_ms": 4358
}
```

## Interpretation

This validates a minimal CodexCLI path where `stream=true`, enabled mode, and the
opt-in streaming replacement path were active together, and the client-facing
response completed normally.

## Caveats

This is a minimal CodexCLI smoke test, not a complex agentic development task.
The compact request log proves enabled mode and streaming were active, but it
does not include all shadow event detail fields. No broad reliability or token
savings claim should be made from this result. Richer CodexCLI tasks are still
needed before treating enabled streaming replacement as generally usable.

No secrets, request bodies, headers, API keys, hidden reasoning, private endpoint
values, or full SSE payloads are included in this note.
