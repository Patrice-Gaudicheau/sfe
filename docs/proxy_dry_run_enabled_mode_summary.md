# Proxy Dry-Run Enabled Mode Summary

`mode="dry_run_enabled"` is a provider-agnostic proxy safety mode. It simulates the request transformation that an SFE-enabled proxy could perform later, while preserving the normal upstream and client-visible behavior.

This is not real enabled execution. The proxy still sends the original full client request to the configured upstream, and the client-visible response still comes from that upstream unchanged.

## What It Does

- Observes supported OpenAI-compatible POST requests.
- Reuses the proxy candidate segment extraction and selection diagnostics.
- Builds a reduced SFE candidate request from selected segment IDs.
- Records diagnostics for the full request estimate, reduced candidate request estimate, selected segment IDs, and estimated token reduction.
- Keeps the reduced candidate request out of the real upstream request path.
- Marks diagnostics to show that the candidate request did not replace the upstream request and did not change the client response.

## Provider-Agnostic Scope

The mode is implemented at the proxy layer. It does not depend on Lemonade-specific behavior and can use provider-neutral selection diagnostics. Later router providers, including Lemonade, OpenAI, or Anthropic-compatible routing, can feed selected segment IDs into the same dry-run candidate request path.

## What It Does Not Validate

- Real `mode="enabled"` behavior
- Provider answer quality under reduced context
- Replacing the real upstream request
- Returning a reduced-context provider response to the client
- Production reliability or latency behavior
- OpenAI or Anthropic live proxy behavior

## Next Step

This mode is intended as the common pre-enabled validation layer before any Lemonade, OpenAI, or Anthropic activation. The next design decision should define explicit enabled-mode gates, fallback behavior, and latency constraints before implementing real client-visible SFE-enabled execution.
