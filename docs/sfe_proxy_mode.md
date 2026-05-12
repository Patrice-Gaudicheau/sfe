# SFE Proxy Mode

SFE remains Spatial Field Engine for Cognition. Proxy mode is an integration
mode, not a project rename.

The proxy implementation is deliberately boring: it is an OpenAI-compatible
HTTP proxy with pass-through behavior and optional shadow observability. It does
not perform SFE-enabled execution, it does not modify prompts, it does not
modify responses, it does not apply hidden repair, and it does not introduce
fallback or semantic routing behavior.

## Purpose

Proxy mode is intended as a zero-code integration path for OpenAI-compatible
clients. A client can point at the local SFE proxy endpoint while the proxy
forwards requests unchanged to an upstream OpenAI-compatible provider.

This version is useful for validating operational plumbing and request-shape
observability before adding future SFE-enabled behavior.

## Endpoints

The proxy supports:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`

For supported endpoints, the proxy preserves upstream status codes, JSON
responses, error responses, and OpenAI-compatible SSE streaming responses.
Unsupported endpoints, including `/` and `/favicon.ico`, return a small JSON
error response instead of a homepage.

## Configuration

Environment variables:

- `SFE_PROXY_HOST`, default `127.0.0.1`
- `SFE_PROXY_PORT`, default `17891`
- `SFE_PROXY_UPSTREAM_BASE_URL`, default `https://api.openai.com`
- `SFE_PROXY_UPSTREAM_API_KEY`, preferred upstream key for proxy mode
- `SFE_PROXY_MODE`, default `pass_through`
- `SFE_PROXY_SHADOW_MIN_INPUT_TOKENS`, default `50000`
- `SFE_PROXY_SHADOW_LOG_DIR`, default `logs/sfe_proxy_shadow`
- `SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS`, default `false`
- `SFE_PROXY_SHADOW_SELECTION_DRY_RUN`, default `false`
- `SFE_PROXY_SHADOW_ROUTER_DRY_RUN`, default `false`
- `SFE_PROXY_SHADOW_ROUTER_PROVIDER`, default `disabled`

Proxy mode uses the repository root `.env`. Do not create a separate proxy
environment file and do not duplicate secrets unless you need a proxy-specific
upstream key.

`SFE_PROXY_UPSTREAM_API_KEY` wins when set. For the default OpenAI upstream, or
when `SFE_PROXY_UPSTREAM_BASE_URL` points to `https://api.openai.com`,
`OPENAI_API_KEY` can be used as a fallback. If neither key is available, the
proxy fails clearly at startup. The OpenAI fallback is not applied to non-OpenAI
upstream URLs.

Supported modes:

- `pass_through`: forwards supported requests unchanged and returns upstream
  responses unchanged.
- `shadow`: forwards supported requests unchanged and returns upstream responses
  unchanged, while writing safe local JSONL observations for supported POST
  requests.

Any other mode fails clearly at startup.

The default bind address is `127.0.0.1`, not `0.0.0.0`. Do not expose the proxy
on the LAN unless you explicitly choose to change the bind address and understand
the operational risk.

## Running Directly

```bash
python -m sfe_proxy
```

The proxy listens on:

```text
http://127.0.0.1:17891
```

## Docker

The Docker compose path publishes the proxy on the host loopback address by
default:

```bash
make build
make start
make logs
make status
make stop
```

`make build` builds the image and does not require secrets. `make install`
currently means `make build` followed by `make start`, so runtime key validation
still applies there. Docker Compose reads the root `.env` for runtime variables
and does not bake API keys into the image.

The container listens internally on `0.0.0.0`, but the compose port mapping binds
to `${SFE_PROXY_HOST:-127.0.0.1}` on the host. Seeing
`http://0.0.0.0:17891` in the container log describes the container listener,
not a LAN exposure by itself; check `make status` or Docker port mappings to
confirm the host bind address.

## Safety And Observability

The proxy logs only minimal request metadata:

- timestamp
- method
- path
- upstream URL
- status code
- latency in milliseconds
- model, when present in the request JSON
- stream flag, when present in the request JSON

It does not log API keys, `Authorization` headers, full prompts, or full
responses by default.

## Shadow Mode

Shadow mode is enabled with:

```text
SFE_PROXY_MODE=shadow
```

Shadow mode must not affect client-visible behavior. It forwards the original
OpenAI-compatible request body to the upstream provider and returns the upstream
status code, response body, error payload, and SSE stream to the client using
the same pass-through path.

For supported POST endpoints, shadow mode writes one safe JSONL observation per
request to `SFE_PROXY_SHADOW_LOG_DIR`. The event includes metadata such as:

- timestamp
- endpoint
- model, when present
- stream flag, when present
- request body byte size
- rough estimated input tokens
- message count for `/v1/chat/completions`
- input item count for `/v1/responses`
- largest text field size
- future SFE routing eligibility
- eligibility reason

The first eligibility rule is conservative and deterministic: a request is
eligible only when the rough estimated input tokens are above
`SFE_PROXY_SHADOW_MIN_INPUT_TOKENS`, which defaults to `50000`.

The token estimate is intentionally labeled rough. It is based on local request
shape only and is not provider billing telemetry.

`SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS` defaults to `false`. Full payload logging is
not enabled in this first shadow implementation; prompts and responses are not
written to shadow logs by default. Treat any future full-payload logging option
as dangerous because it can capture prompts, documents, user data, or secrets.

### Shadow Selection Dry-Run

Shadow selection dry-run is disabled by default:

```text
SFE_PROXY_SHADOW_SELECTION_DRY_RUN=false
```

When set to `true`, shadow mode adds deterministic dry-run selection fields to
the JSONL observation for eligible supported POST requests. This does not call
an LLM router, does not alter the request sent upstream, does not alter the
response returned to the client, and does not perform SFE-enabled execution.

The first dry-run strategy is `largest_text_segment_baseline`. It extracts safe
text-shape metadata from OpenAI-compatible request bodies, identifies candidate
text segments, selects the largest segment as a conservative estimate, and
reports rough token-reduction metadata. It does not claim semantic correctness
and should not be read as real SFE routing.

Dry-run metadata includes fields such as:

- `shadow_selection_enabled`
- `would_activate_sfe`
- `would_activate_sfe_is_dry_run_only`
- `selection_strategy`
- `selection_status`
- `selection_reason`
- `estimated_full_input_tokens`
- `estimated_selected_input_tokens`
- `estimated_token_reduction_pct`
- `candidate_segment_count`
- `candidate_selected_segment_count`
- `candidate_segments_metadata`

Candidate segment metadata contains source labels and sizes only. It does not
include text content by default.

`would_activate_sfe` is a dry-run observation field only. It does not mean the
proxy actually activated SFE execution for that request.

### Shadow Router Dry-Run Contract

The proxy includes an internal, provider-neutral contract for future shadow
router dry-run analysis. It is disabled by default:

```text
SFE_PROXY_SHADOW_ROUTER_DRY_RUN=false
SFE_PROXY_SHADOW_ROUTER_PROVIDER=disabled
```

The supported router providers are:

- `disabled`: no network call and no router selection.
- `lemonade`: explicit opt-in metadata-only Lemonade dry-run.

When router dry-run is enabled with the disabled provider, the proxy can add
safe `shadow_router_*` metadata to the shadow JSONL event. The disabled provider
does not select segments, does not send request content anywhere, and cannot
affect the upstream request or downstream response.

The Lemonade provider is the first real shadow router dry-run provider. It is
enabled only when all of these are set:

```text
SFE_PROXY_MODE=shadow
SFE_PROXY_SHADOW_ROUTER_DRY_RUN=true
SFE_PROXY_SHADOW_ROUTER_PROVIDER=lemonade
```

Provider details come from the existing project-level Lemonade configuration,
not proxy-specific provider variables:

```text
SFE_LEMONADE_BASE_URL=http://127.0.0.1:13305
SFE_LEMONADE_API_KEY=<optional-local-provider-key>
SFE_LEMONADE_MODEL=<local-router-model>
```

If `SFE_LEMONADE_MODEL` is not set, the proxy falls back to the existing
project router model variable `SFE_ROUTER_MODEL`. If neither is set, Lemonade
router dry-run records a safe provider error and pass-through behavior remains
unchanged. The recommended fix is to set the standard project-level Lemonade
model variable, not a proxy-specific model variable.

The Lemonade router dry-run is local-provider oriented. When explicitly
enabled, it may send extracted text segments to the configured local Lemonade
router so that the router can perform a meaningful dry-run selection. The
router request also includes endpoint, model name, rough token counts,
eligibility metadata, request body size, stream flag, and candidate segment
size metadata.

The Lemonade router request does not include request headers, Authorization
values, API keys, raw payloads, upstream responses, or downstream response
content. The extracted text sent to Lemonade is not written to the shadow JSONL
log. The router prompt asks for strict JSON. The proxy also applies a small
deterministic JSON parsing normalization for common local model formatting,
including whole-output markdown fences and safely extractable prose-wrapped JSON
objects. This normalization is not LLM repair: the proxy does not retry, does
not ask another model to fix output, and does not fall back to deterministic
selection as if it were Lemonade output.

For Qwen-style local Lemonade router models, the proxy includes the same
non-thinking control used by the project Lemonade provider:
`chat_template_kwargs={"enable_thinking": false}`. The router prompt also starts
with `/no_think` and asks for one JSON object without prose, markdown, code
fences, explanation, or reasoning. Output is still parsed and schema-validated
strictly; malformed output remains an `invalid_output` shadow observation.

Lemonade router failures, timeouts, invalid JSON, or malformed results are
recorded in safe `shadow_router_*` metadata and must not affect the upstream
request or downstream response. Tests use mocked Lemonade HTTP responses; no
live provider is called by default.

This remains shadow-only observability, not SFE-enabled execution.

### Provider Limit Decision Contract

The proxy also includes a local provider limit decision contract for shadow
router providers. By default it is disabled and does not affect pass-through
behavior.

The defaults are non-restrictive:

```text
SFE_PROXY_PROVIDER_LIMITS_ENABLED=false
SFE_PROXY_PROVIDER_DEFAULT_MIN_INTERVAL_MS=0
SFE_PROXY_PROVIDER_DEFAULT_MAX_INPUT_TOKENS=0
SFE_PROXY_PROVIDER_DEFAULT_MAX_REQUESTS_PER_MINUTE=0
SFE_PROXY_PROVIDER_DEFAULT_QUEUE_MODE=reject
```

Provider-specific settings exist for `openai`, `anthropic`, and `lemonade`.
`disabled` is also a supported provider key and remains harmless.

For each numeric limit, `0` means unlimited or disabled for that limit. Queue
mode can be `reject` or `wait`. In this branch, both are decision modes only:
`reject` means a future provider call would be rejected by the decision layer,
while `wait` means a future provider call would require waiting. The proxy does
not sleep, queue, or retry based on this contract.

The Lemonade router dry-run consults the `lemonade` provider limit decision
before making a mocked or explicitly configured local Lemonade router call. If
the decision is `rejected` or `wait_required`, the proxy records the decision in
shadow metadata and skips the Lemonade call. `wait` remains decision-only: the
proxy does not actively queue or sleep.

Anthropic may need stricter future limits for large prompts and request pacing
because provider-side input-token-per-minute limits can affect large-context
workloads. Those constraints are represented here as local configuration and
decision metadata only.

## Future Modes

SFE-enabled mode is a future step. It is not implemented in this pass-through
and shadow-observability version.
