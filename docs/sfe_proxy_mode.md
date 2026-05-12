# SFE Proxy Mode

SFE remains Spatial Field Engine for Cognition. Proxy mode is an integration
mode, not a project rename.

The first proxy implementation is deliberately boring: it is an
OpenAI-compatible HTTP pass-through proxy. It does not perform SFE selection, it
does not modify prompts, it does not modify responses, it does not apply hidden
repair, and it does not introduce fallback or semantic routing behavior.

## Purpose

Proxy mode is intended as a zero-code integration path for OpenAI-compatible
clients. A client can point at the local SFE proxy endpoint while the proxy
forwards requests unchanged to an upstream OpenAI-compatible provider.

This first version is useful for validating operational plumbing before adding
future shadow or SFE-enabled behavior.

## Endpoints

The initial pass-through proxy supports:

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
- `SFE_PROXY_UPSTREAM_API_KEY`, preferred upstream key for pass-through mode
- `SFE_PROXY_MODE`, default `pass_through`

Proxy mode uses the repository root `.env`. Do not create a separate proxy
environment file and do not duplicate secrets unless you need a proxy-specific
upstream key.

`SFE_PROXY_UPSTREAM_API_KEY` wins when set. For the default OpenAI upstream, or
when `SFE_PROXY_UPSTREAM_BASE_URL` points to `https://api.openai.com`,
`OPENAI_API_KEY` can be used as a fallback. If neither key is available, the
proxy fails clearly at startup. The OpenAI fallback is not applied to non-OpenAI
upstream URLs.

Only `SFE_PROXY_MODE=pass_through` is supported. Any other mode fails clearly at
startup.

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

## Future Modes

Shadow mode and SFE-enabled mode are future steps. They are not implemented in
this first pass-through version.
